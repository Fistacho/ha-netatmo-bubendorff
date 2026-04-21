"""Support for Netatmo/Bubendorff covers (with jalousie/slats support).

Bubendorff shutters do NOT support continuous 0-100 positioning.
They accept only 4 discrete target_position values:
  * 100  -> fully open
  *   0  -> fully closed
  *  -1  -> stop current movement
  *  -2  -> preferred position = jalousie/slats mode (visible through)

HA cover feature mapping:
  OPEN       -> 100
  CLOSE      ->   0
  STOP       ->  -1
  OPEN_TILT  ->  -2  (put slats in jalousie position)
  CLOSE_TILT ->   0  (return slats flat = shutter closed)

SET_POSITION is intentionally NOT exposed because the hardware does not
honor intermediate values — exposing a 0-100 slider would be misleading.

State readback caveat
---------------------
Netatmo's cloud does NOT report -2 in `current_position` after a tilt.
It stays at 0/100 even though the slats are physically tilted. To give
HA a useful state we:

  1. Read `target_position` from the pyatmo Shutter object — that reflects
     the last command (persisted server-side) and IS `-2` after a tilt.
  2. After every command we issue, eagerly overwrite the in-memory
     `target_position` and rebuild HA attributes (optimistic update).
     A later webhook / poll can still correct this if the real state
     diverges (e.g. someone pressed the physical wall switch after us).

The logical state is exposed in the `intended_state` extra attribute,
readable from Lovelace/automations as cover.*.attributes.intended_state.
"""
from __future__ import annotations

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
    NETATMO_CREATE_COVER,
    SHUTTER_POSITION_CLOSED,
    SHUTTER_POSITION_OPEN,
    SHUTTER_POSITION_PREFERRED,
    SHUTTER_POSITION_STOP,
)
from .data_handler import HOME, SIGNAL_NAME, NetatmoDevice
from .netatmo_entity_base import NetatmoBase

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

    @callback
    def _create_entity(netatmo_device: NetatmoDevice) -> None:
        async_add_entities([NetatmoCover(netatmo_device)])

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

    def __init__(self, netatmo_device: NetatmoDevice) -> None:
        """Initialize the Netatmo device."""
        super().__init__(netatmo_device.data_handler)

        self._cover: NaModules.Shutter = netatmo_device.device

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
        self._sync_state()

    async def async_open_cover(self, **kwargs: Any) -> None:
        """Open the shutter fully."""
        await self._cover.async_open()
        self._optimistic_set(SHUTTER_POSITION_OPEN)
        self.async_write_ha_state()

    async def async_close_cover(self, **kwargs: Any) -> None:
        """Close the shutter fully."""
        await self._cover.async_close()
        self._optimistic_set(SHUTTER_POSITION_CLOSED)
        self.async_write_ha_state()

    async def async_stop_cover(self, **kwargs: Any) -> None:
        """Stop any current shutter movement."""
        await self._cover.async_stop()
        # Don't touch current_position — we have no idea where it physically
        # stopped. Just mark target_position so intended_state shows 'stopped'.
        self._cover.target_position = SHUTTER_POSITION_STOP
        self._sync_state()
        self.async_write_ha_state()

    async def async_open_cover_tilt(self, **kwargs: Any) -> None:
        """Tilt slats to jalousie (preferred) position."""
        await self._cover.async_open_tilt()
        self._optimistic_set(SHUTTER_POSITION_PREFERRED)
        self.async_write_ha_state()

    async def async_close_cover_tilt(self, **kwargs: Any) -> None:
        """Flatten slats — returns shutter to closed position."""
        await self._cover.async_close_tilt()
        self._optimistic_set(SHUTTER_POSITION_CLOSED)
        self.async_write_ha_state()

    @callback
    def async_update_callback(self) -> None:
        """Update the entity state from the device after a webhook push."""
        self._sync_state()

    # ---- helpers ----

    def _optimistic_set(self, target: int) -> None:
        """Record our last command into the pyatmo module's target_position.

        Netatmo's cloud only reflects open (100) / closed (0) in the
        `current_position` read-back — a tilt (-2) or an in-flight move
        stays invisible. Setting `target_position` locally lets HA surface
        the logical state (`intended_state`) immediately after a command
        instead of waiting for the cloud round-trip.
        """
        self._cover.target_position = target
        if target in (SHUTTER_POSITION_OPEN, SHUTTER_POSITION_CLOSED):
            # For discrete positions Netatmo will eventually confirm this
            # same value, so we can also advance current_position optimistically.
            self._cover.current_position = target
        self._sync_state()

    def _sync_state(self) -> None:
        """Rebuild HA-visible attributes from the pyatmo module's fields.

        Source of truth priority:
          1. `target_position` — last command (reliable for tilt state).
          2. `current_position` — physical reading (0/100 only, tilt invisible).
        """
        pos = self._cover.current_position
        target = getattr(self._cover, "target_position", None)

        self._attr_current_cover_position = pos

        # Shutter is in tilt / jalousie when the last command was -2.
        # `current_position` stays 0 in that case, so we rely on target.
        in_tilt = target == SHUTTER_POSITION_PREFERRED

        self._attr_current_cover_tilt_position = 100 if in_tilt else 0

        # is_closed: physically flat at 0 AND not in tilt.
        self._attr_is_closed = pos == SHUTTER_POSITION_CLOSED and not in_tilt

        # Expose a human-readable logical state + the raw Netatmo fields for
        # debugging automations.
        self._attr_extra_state_attributes = {
            "intended_state": _describe_state(pos, target),
            "netatmo_current_position": pos,
            "netatmo_target_position": target,
        }

        # Mark entity unavailable when the bridge reports the shutter offline.
        # HA will grey out the tile and block service calls — better than a
        # silent NOP on a dead device.
        self._attr_available = bool(getattr(self._cover, "reachable", True))


def _describe_state(pos: int | None, target: int | None) -> str:
    """Map (current_position, target_position) to a human label."""
    if target == SHUTTER_POSITION_PREFERRED:
        return STATE_TILTED
    if target == SHUTTER_POSITION_STOP:
        return STATE_STOPPED
    if pos == SHUTTER_POSITION_CLOSED:
        return STATE_CLOSED
    if pos == SHUTTER_POSITION_OPEN:
        return STATE_OPEN
    return STATE_UNKNOWN
