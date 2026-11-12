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
    # The cloud never reports tilt and only reports 0 / 100, so the state is
    # partly optimistic. assumed_state also keeps every cover button enabled
    # in the frontend (open, close and tilt are always allowed, as in the
    # manufacturer app) -- which is_closed=None did not achieve, because the
    # frontend disables buttons from current_position / current_tilt_position.
    _attr_assumed_state = True

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

        # Last target commanded from HA (0, 100, -1, -2), persisted in the
        # store. Kept here, not only in pyatmo: every /homestatus poll
        # overwrites the module's target_position with the cloud's value,
        # and the cloud never reports -2.
        self._target: int | None = self._cover.target_position
        # current_position seen in the previous poll (None until the first
        # poll after start); a change of it tells an outside move.
        self._last_api_pos: int | None = None

        self._sync_state()

    async def async_added_to_hass(self) -> None:
        """Restore the persisted target, then subscribe and refresh."""
        # Restored here because the store is keyed by entity_id, which is
        # only known once the entity is registered (in __init__ the key fell
        # back to unique_id and never matched, so tilt was never restored).
        persisted = self._store.get(self.entity_id_stub)
        if persisted is not None:
            self._target = persisted
            self._cover.target_position = persisted
        await super().async_added_to_hass()

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
        if self._target == SHUTTER_POSITION_PREFERRED:
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
        """Update entity state from a poll of /homestatus.

        The cloud reports an NBO shutter only as 0 or 100 and a tilted one
        as 0 (or a stale 100), never -2. So while HA's target is the tilt it
        is kept, unless the API shows the shutter moving to fully open
        (remote, app, schedule). A close from outside cannot be told apart
        from the tilt (both report 0) and keeps showing "tilted".
        """
        api_pos = self._cover.current_position
        if api_pos in (SHUTTER_POSITION_CLOSED, SHUTTER_POSITION_OPEN):
            api_pos = int(api_pos)
            if self._target == SHUTTER_POSITION_PREFERRED:
                if api_pos == SHUTTER_POSITION_OPEN and self._last_api_pos not in (
                    None,
                    SHUTTER_POSITION_OPEN,
                ):
                    self._set_target(api_pos)
            elif self._target != api_pos:
                # Open / closed / stopped follow the reported end position.
                self._set_target(api_pos)
            self._last_api_pos = api_pos
        # pyatmo just overwrote it with the cloud's target_position.
        self._cover.target_position = self._target
        self._sync_state()
        self.async_write_ha_state()

    # ---- helpers ----

    @callback
    def _set_target(self, target_position: int) -> None:
        """Take a target reported by the API and persist it."""
        self._target = target_position
        self.hass.async_create_task(
            self._store.async_update(self.entity_id_stub, target_position)
        )

    async def _commit(self, target_position: int) -> None:
        """Optimistically update state, persist, and notify HA."""
        self._target = target_position
        self._cover.target_position = target_position
        if target_position in (SHUTTER_POSITION_OPEN, SHUTTER_POSITION_CLOSED):
            self._cover.current_position = target_position
        await self._store.async_update(self.entity_id_stub, target_position)
        self._sync_state()
        self.async_write_ha_state()

    def _sync_state(self) -> None:
        """Rebuild HA-visible attributes from pyatmo fields."""
        target = self._target
        api_pos = getattr(self._cover, "current_position", None)
        in_tilt = target == SHUTTER_POSITION_PREFERRED

        self._attr_current_cover_position = (
            int(api_pos) if api_pos in (SHUTTER_POSITION_CLOSED, SHUTTER_POSITION_OPEN)
            else None
        )
        self._attr_current_cover_tilt_position = 100 if in_tilt else 0
        intended_state = _describe_state(api_pos, target)
        # HA semantics: "closed" means fully closed. Tilted slats and a
        # stopped (partly open) shutter are "open"; no data means unknown.
        self._attr_is_closed = (
            None if intended_state == STATE_UNKNOWN
            else intended_state == STATE_CLOSED
        )

        self._attr_extra_state_attributes = {
            "intended_state": intended_state,
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
