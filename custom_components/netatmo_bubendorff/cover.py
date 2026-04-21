"""Support for Netatmo/Bubendorff covers (with jalousie + time-based positions).

## Hardware truth
Bubendorff shutters honour only four `target_position` values:

  * 100  — fully open
  *   0  — fully closed
  *  -1  — stop current movement
  *  -2  — preferred position = jalousie (slats tilted)

Intermediate 0-100 values are rejected by firmware. However, **we emulate**
arbitrary positions by sending an OPEN or CLOSE and scheduling a STOP after
`travel_time × (distance / 100)` seconds. Accuracy is roughly ±15 % due to
Netatmo API / RF bridge latency — good enough for "open to 30 %" automations,
not good enough for precise alignment.

## State readback gotcha
Netatmo's cloud only reports `current_position` as 0 or 100. Even when the
shutter sits at jalousie (-2) or at an intermediate stopped position, the
API keeps returning one of those two values. To give HA a truthful estimate
we maintain our own `PositionStore` (`.storage/…`) that survives restarts.

## Confidence model
See `position_store.py`. Briefly: KNOWN when we just hit 0 or 100,
ESTIMATED after an intermediate drive, UNKNOWN after HA restart if we've
never observed the shutter, or after we suspect out-of-band movement
(e.g. physical wall switch).
"""
from __future__ import annotations

import asyncio
from datetime import datetime
import logging
from typing import Any

from .pyatmo import modules as NaModules

from homeassistant.components.cover import (
    ATTR_POSITION,
    CoverDeviceClass,
    CoverEntity,
    CoverEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import (
    CONF_DEFAULT_TRAVEL_TIME,
    CONF_TRAVEL_TIMES,
    CONF_URL_CONTROL,
    DEFAULT_TRAVEL_TIME_SECONDS,
    DOMAIN,
    NETATMO_CREATE_COVER,
    POSITION_CONFIDENCE_ESTIMATED,
    POSITION_CONFIDENCE_KNOWN,
    POSITION_CONFIDENCE_UNKNOWN,
    SHUTTER_POSITION_CLOSED,
    SHUTTER_POSITION_OPEN,
    SHUTTER_POSITION_PREFERRED,
    SHUTTER_POSITION_STOP,
)
from .data_handler import HOME, SIGNAL_NAME, NetatmoDevice
from .netatmo_entity_base import NetatmoBase
from .position_store import PositionStore

_LOGGER = logging.getLogger(__name__)

# Logical state labels exposed via the `intended_state` attribute.
STATE_OPEN = "open"
STATE_CLOSED = "closed"
STATE_TILTED = "tilted"
STATE_STOPPED = "stopped"
STATE_UNKNOWN = "unknown"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Netatmo cover platform."""
    store = PositionStore(hass, entry.entry_id)
    await store.async_load()

    @callback
    def _create_entity(netatmo_device: NetatmoDevice) -> None:
        async_add_entities([NetatmoCover(netatmo_device, entry, store)])

    entry.async_on_unload(
        async_dispatcher_connect(hass, NETATMO_CREATE_COVER, _create_entity)
    )


class NetatmoCover(NetatmoBase, CoverEntity):
    """Representation of a Netatmo/Bubendorff cover device."""

    _attr_supported_features = (
        CoverEntityFeature.OPEN
        | CoverEntityFeature.CLOSE
        | CoverEntityFeature.STOP
        | CoverEntityFeature.SET_POSITION     # emulated via timed STOP
        | CoverEntityFeature.OPEN_TILT
        | CoverEntityFeature.CLOSE_TILT
    )
    _attr_device_class = CoverDeviceClass.SHUTTER

    def __init__(
        self,
        netatmo_device: NetatmoDevice,
        entry: ConfigEntry,
        store: PositionStore,
    ) -> None:
        """Initialize the Netatmo device."""
        super().__init__(netatmo_device.data_handler)

        self._cover: NaModules.Shutter = netatmo_device.device
        self._entry = entry
        self._store = store

        self._id = self._cover.entity_id
        self._attr_name = self._device_name = self._cover.name
        self._model = self._cover.device_type
        self._config_url = CONF_URL_CONTROL

        self._home_id = self._cover.home.entity_id
        self._signal_name = f"{HOME}-{self._home_id}"
        self._publishers.extend(
            [
                {
                    "name": HOME,
                    "home_id": self._home_id,
                    SIGNAL_NAME: self._signal_name,
                },
            ]
        )
        self._attr_unique_id = f"{self._id}-{self._model}"

        # In-flight STOP timer for intermediate positions.
        self._stop_task: asyncio.Task[None] | None = None
        self._movement_started_at: datetime | None = None
        self._movement_from: float | None = None
        self._movement_to: float | None = None

        # Seed local state from the persistent store.
        persisted = self._store.get(self.entity_id_stub)
        self._position: float = persisted.position
        self._confidence: str = persisted.confidence

        self._sync_state()

    # ---- HA lifecycle helpers ----

    @property
    def entity_id_stub(self) -> str:
        """Entity key used in the position store (pre-registry name)."""
        # At construction time self.entity_id is None; fall back to unique_id.
        return self.entity_id or self._attr_unique_id

    def _travel_time(self) -> float:
        """Resolve this cover's travel time (options > default)."""
        times: dict[str, float] = self._entry.options.get(CONF_TRAVEL_TIMES, {})
        per_cover = times.get(self.entity_id_stub)
        if isinstance(per_cover, (int, float)) and per_cover > 0:
            return float(per_cover)
        fallback = self._entry.options.get(
            CONF_DEFAULT_TRAVEL_TIME, DEFAULT_TRAVEL_TIME_SECONDS
        )
        try:
            return float(fallback)
        except (TypeError, ValueError):
            return DEFAULT_TRAVEL_TIME_SECONDS

    # ---- cover commands ----

    async def _leave_tilt_if_needed(self) -> None:
        """Flatten slats before an UP movement.

        Bubendorff firmware rejects an OPEN from the jalousie (-2) state —
        users reported that from tilted you must first `close_tilt` (slats
        flat = physical 0) and only THEN `open`. Called from any command
        that targets a non-tilt position.
        """
        if self._cover.target_position == SHUTTER_POSITION_PREFERRED:
            _LOGGER.debug("Leaving jalousie before next move: flattening slats")
            await self._cover.async_close_tilt()
            # Give the motor a moment to settle the slats back to flat before
            # we chain the next command. Slats move much faster than the full
            # shutter (~2 s empirically), so this short wait is plenty.
            await asyncio.sleep(2)

    async def async_open_cover(self, **kwargs: Any) -> None:
        """Open the shutter fully."""
        self._cancel_stop_task()
        await self._leave_tilt_if_needed()
        await self._cover.async_open()
        await self._commit(SHUTTER_POSITION_OPEN, POSITION_CONFIDENCE_KNOWN)

    async def async_close_cover(self, **kwargs: Any) -> None:
        """Close the shutter fully."""
        self._cancel_stop_task()
        # close from tilt = just flatten slats; both resolve to physical 0,
        # no need to chain commands explicitly.
        await self._cover.async_close()
        await self._commit(SHUTTER_POSITION_CLOSED, POSITION_CONFIDENCE_KNOWN)

    async def async_stop_cover(self, **kwargs: Any) -> None:
        """Stop any current shutter movement."""
        self._cancel_stop_task()
        await self._cover.async_stop()
        # Best effort: estimate where we ended up based on elapsed time.
        self._position = self._estimate_position_now()
        self._confidence = POSITION_CONFIDENCE_ESTIMATED
        self._cover.target_position = SHUTTER_POSITION_STOP
        await self._persist()
        self._sync_state()
        self.async_write_ha_state()

    async def async_set_cover_position(self, **kwargs: Any) -> None:
        """Drive the shutter to an arbitrary percentage (emulated via timed STOP).

        Algorithm:
          1. Compute direction (up / down) from current estimate to target.
          2. If target is 0 or 100, delegate to the full-travel command.
          3. Else: fire OPEN or CLOSE, then schedule a STOP after
             `travel_time × distance/100` seconds. Confidence ends as
             ESTIMATED because mid-travel position can't be verified.
        """
        target = int(kwargs[ATTR_POSITION])
        target = max(0, min(100, target))

        if target == SHUTTER_POSITION_OPEN:
            await self.async_open_cover()
            return
        if target == SHUTTER_POSITION_CLOSED:
            await self.async_close_cover()
            return

        current = self._position
        if abs(target - current) < 1:
            return  # already there

        self._cancel_stop_task()
        travel_time = self._travel_time()
        distance = abs(target - current)
        duration = travel_time * (distance / 100.0)

        # Going up from a tilted state requires close_tilt first.
        if target > current:
            await self._leave_tilt_if_needed()

        # CRITICAL: do NOT await the OPEN/CLOSE call. Netatmo's HTTP response
        # takes ~10 s (and appears to be a fixed timeout, not tied to physical
        # completion). If we awaited it, our STOP timer would start counting
        # AFTER the motor has already been running for ~10 s — the shutter
        # would overshoot the target by a huge margin. We dispatch the
        # command as a background task and start counting immediately.
        if target > current:
            cmd_coro = self._cover.async_open()
        else:
            cmd_coro = self._cover.async_close()
        self.hass.async_create_task(cmd_coro)

        self._movement_started_at = dt_util.utcnow()
        self._movement_from = current
        self._movement_to = float(target)
        self._confidence = POSITION_CONFIDENCE_ESTIMATED

        # Schedule the STOP to interrupt the full-travel command.
        self._stop_task = self._entry.async_create_background_task(
            self.hass,
            self._stop_after(duration, target),
            name=f"{DOMAIN}_stop_{self.entity_id_stub}",
        )

        self._sync_state()
        self.async_write_ha_state()

    async def _stop_after(self, delay: float, target_position: float) -> None:
        """Sleep for `delay` seconds then send STOP and commit position."""
        try:
            await asyncio.sleep(delay)
        except asyncio.CancelledError:
            return

        try:
            await self._cover.async_stop()
        except Exception as err:  # noqa: BLE001 — surface any Netatmo failure
            _LOGGER.warning("STOP after intermediate drive failed: %s", err)

        self._position = float(target_position)
        self._confidence = POSITION_CONFIDENCE_ESTIMATED
        self._movement_started_at = None
        self._movement_from = None
        self._movement_to = None
        await self._persist()
        self._sync_state()
        self.async_write_ha_state()

    async def async_open_cover_tilt(self, **kwargs: Any) -> None:
        """Tilt slats to jalousie (preferred) position."""
        self._cancel_stop_task()
        await self._cover.async_open_tilt()
        # Jalousie behaves like "closed with tilted slats" — position 0 in our
        # model, but we also mark target_position=-2 for UI clarity.
        self._cover.target_position = SHUTTER_POSITION_PREFERRED
        self._position = 0.0
        self._confidence = POSITION_CONFIDENCE_KNOWN
        await self._persist()
        self._sync_state()
        self.async_write_ha_state()

    async def async_close_cover_tilt(self, **kwargs: Any) -> None:
        """Flatten slats — returns shutter to closed position."""
        self._cancel_stop_task()
        await self._cover.async_close_tilt()
        await self._commit(SHUTTER_POSITION_CLOSED, POSITION_CONFIDENCE_KNOWN)

    @callback
    def async_update_callback(self) -> None:
        """Update the entity state from the device after a webhook push."""
        # Netatmo only reports 0 or 100 here. If we see either, trust it —
        # it means the shutter physically reached a limit.
        api_pos = self._cover.current_position
        if api_pos in (SHUTTER_POSITION_CLOSED, SHUTTER_POSITION_OPEN):
            self._position = float(api_pos)
            self._confidence = POSITION_CONFIDENCE_KNOWN
            self._cancel_stop_task()
            self.hass.async_create_task(self._persist())
        self._sync_state()

    # ---- helpers ----

    def _cancel_stop_task(self) -> None:
        if self._stop_task is not None and not self._stop_task.done():
            self._stop_task.cancel()
        self._stop_task = None
        self._movement_started_at = None

    def _estimate_position_now(self) -> float:
        """Interpolate where we are mid-travel, in case STOP arrives mid-flight."""
        if (
            self._movement_started_at is None
            or self._movement_from is None
            or self._movement_to is None
        ):
            return self._position
        travel_time = self._travel_time()
        elapsed = (dt_util.utcnow() - self._movement_started_at).total_seconds()
        frac = min(1.0, max(0.0, elapsed / max(travel_time, 0.1)))
        return self._movement_from + (self._movement_to - self._movement_from) * frac

    async def _commit(self, position: float, confidence: str) -> None:
        """Post-command bookkeeping: update state, persist, push to HA."""
        self._cover.target_position = int(position)
        self._cover.current_position = int(position)
        self._position = float(position)
        self._confidence = confidence
        self._movement_started_at = None
        self._movement_from = None
        self._movement_to = None
        await self._persist()
        self._sync_state()
        self.async_write_ha_state()

    async def _persist(self) -> None:
        await self._store.async_update(
            self.entity_id_stub, self._position, self._confidence
        )

    def _sync_state(self) -> None:
        """Rebuild HA-visible attributes from local state + pyatmo fields."""
        target = getattr(self._cover, "target_position", None)
        in_tilt = target == SHUTTER_POSITION_PREFERRED

        self._attr_current_cover_position = int(round(self._position))
        self._attr_current_cover_tilt_position = 100 if in_tilt else 0
        # HA's "closed" semantic: position at 0 AND not in tilt.
        self._attr_is_closed = (self._position <= 0) and not in_tilt

        self._attr_extra_state_attributes = {
            "intended_state": _describe_state(self._position, target, self._confidence),
            "position_confidence": self._confidence,
            "travel_time_seconds": self._travel_time(),
            "netatmo_current_position": self._cover.current_position,
            "netatmo_target_position": target,
        }

        self._attr_available = bool(getattr(self._cover, "reachable", True))


def _describe_state(position: float, target: int | None, confidence: str) -> str:
    """Map position + target_position + confidence to a human label."""
    if confidence == POSITION_CONFIDENCE_UNKNOWN:
        return STATE_UNKNOWN
    if target == SHUTTER_POSITION_PREFERRED:
        return STATE_TILTED
    if target == SHUTTER_POSITION_STOP:
        return STATE_STOPPED
    if position <= 0:
        return STATE_CLOSED
    if position >= 100:
        return STATE_OPEN
    return STATE_STOPPED  # intermediate after timed STOP
