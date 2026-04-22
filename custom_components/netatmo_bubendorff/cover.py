"""Support for Netatmo/Bubendorff covers (open/close/stop/tilt).

## Hardware truth
Bubendorff shutters honour only four target_position values:

  * 100  — fully open
  *   0  — fully closed
  *  -1  — stop current movement
  *  -2  — preferred position = jalousie (slats tilted)

Intermediate 0-100 values are rejected by firmware.

## State readback gotcha
Netatmo's cloud only reports current_position as 0 or 100. The tilt state
(-2) is never returned by the API — even after a successful tilt command.
To show the correct "tilted" state and survive HA restarts, we persist
target_position in StateStore (backed by HA's Store helper in .storage/).
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from .pyatmo import modules as NaModules

from homeassistant.components.cover import (
    CoverDeviceClass,
    CoverEntity,
    CoverEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_URL_CONTROL,
    DOMAIN,
    NETATMO_CREATE_COVER,
    SHUTTER_POSITION_CLOSED,
    SHUTTER_POSITION_OPEN,
    SHUTTER_POSITION_PREFERRED,
    SHUTTER_POSITION_STOP,
)
from .data_handler import HOME, SIGNAL_NAME, NetatmoDevice
from .netatmo_entity_base import NetatmoBase
from .position_store import StateStore

_LOGGER = logging.getLogger(__name__)

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
    store = StateStore(hass, entry.entry_id)
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
        | CoverEntityFeature.OPEN_TILT
        | CoverEntityFeature.CLOSE_TILT
    )
    _attr_device_class = CoverDeviceClass.SHUTTER

    def __init__(
        self,
        netatmo_device: NetatmoDevice,
        entry: ConfigEntry,
        store: StateStore,
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

        # Restore target_position from the persistent store. Netatmo cloud
        # never returns -2 after a tilt command, so this is the only way to
        # remember tilt state across HA restarts.
        persisted = self._store.get(self.entity_id_stub)
        if persisted is not None:
            self._cover.target_position = persisted

        self._sync_state()

    @property
    def entity_id_stub(self) -> str:
        """Entity key used in the state store (pre-registry name)."""
        return self.entity_id or self._attr_unique_id

    # ---- cover commands ----

    async def _leave_tilt_if_needed(self) -> None:
        """Flatten slats before an UP movement.

        Bubendorff firmware rejects OPEN from jalousie (-2) state — must
        close_tilt first to flatten slats, then chain the original command.
        """
        if self._cover.target_position == SHUTTER_POSITION_PREFERRED:
            _LOGGER.debug("Leaving jalousie before next move: flattening slats")
            await self._cover.async_close_tilt()
            await asyncio.sleep(2)

    async def async_open_cover(self, **kwargs: Any) -> None:
        """Open the shutter fully."""
        await self._leave_tilt_if_needed()
        await self._cover.async_open()
        await self._commit(SHUTTER_POSITION_OPEN)

    async def async_close_cover(self, **kwargs: Any) -> None:
        """Close the shutter fully."""
        await self._cover.async_close()
        await self._commit(SHUTTER_POSITION_CLOSED)

    async def async_stop_cover(self, **kwargs: Any) -> None:
        """Stop any current shutter movement."""
        await self._cover.async_stop()
        await self._commit(SHUTTER_POSITION_STOP)

    async def async_open_cover_tilt(self, **kwargs: Any) -> None:
        """Tilt slats to jalousie (preferred) position."""
        await self._cover.async_open_tilt()
        await self._commit(SHUTTER_POSITION_PREFERRED)

    async def async_close_cover_tilt(self, **kwargs: Any) -> None:
        """Flatten slats — returns shutter to closed position."""
        await self._cover.async_close_tilt()
        await self._commit(SHUTTER_POSITION_CLOSED)

    @callback
    def async_update_callback(self) -> None:
        """Update entity state from a webhook push or poll cycle."""
        api_pos = self._cover.current_position
        if api_pos in (SHUTTER_POSITION_CLOSED, SHUTTER_POSITION_OPEN):
            # Shutter physically hit a hard limit — clear any stale tilt state.
            self._cover.target_position = int(api_pos)
            self.hass.async_create_task(
                self._store.async_update(self.entity_id_stub, int(api_pos))
            )
        self._sync_state()

    # ---- helpers ----

    async def _commit(self, target_position: int) -> None:
        """Optimistically update state, persist, and notify HA."""
        self._cover.target_position = target_position
        if target_position in (SHUTTER_POSITION_OPEN, SHUTTER_POSITION_CLOSED):
            self._cover.current_position = target_position
        await self._store.async_update(self.entity_id_stub, target_position)
        self._sync_state()
        self.async_write_ha_state()

    def _sync_state(self) -> None:
        """Rebuild HA-visible attributes from pyatmo fields."""
        target = getattr(self._cover, "target_position", None)
        api_pos = getattr(self._cover, "current_position", None)
        in_tilt = target == SHUTTER_POSITION_PREFERRED

        self._attr_current_cover_position = (
            int(api_pos) if api_pos in (SHUTTER_POSITION_CLOSED, SHUTTER_POSITION_OPEN)
            else None
        )
        self._attr_current_cover_tilt_position = 100 if in_tilt else 0
        # Keep state unknown so HA never disables any button — Netatmo API
        # reports only 0/100 and never tilt, so any state-based disabling
        # would be based on stale/wrong data. Matches manufacturer app behaviour.
        self._attr_is_closed = None

        self._attr_extra_state_attributes = {
            "intended_state": _describe_state(api_pos, target),
            "netatmo_current_position": api_pos,
            "netatmo_target_position": target,
        }

        self._attr_available = bool(getattr(self._cover, "reachable", True))


def _describe_state(current_pos: int | None, target: int | None) -> str:
    """Map current_position + target_position to a human label."""
    if target == SHUTTER_POSITION_PREFERRED:
        return STATE_TILTED
    if target == SHUTTER_POSITION_STOP:
        return STATE_STOPPED
    if target == SHUTTER_POSITION_OPEN or current_pos == SHUTTER_POSITION_OPEN:
        return STATE_OPEN
    if target == SHUTTER_POSITION_CLOSED or current_pos == SHUTTER_POSITION_CLOSED:
        return STATE_CLOSED
    return STATE_UNKNOWN
