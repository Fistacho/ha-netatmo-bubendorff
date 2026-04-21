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

from .const import CONF_URL_CONTROL, NETATMO_CREATE_COVER, SHUTTER_POSITION_PREFERRED
from .data_handler import HOME, SIGNAL_NAME, NetatmoDevice
from .netatmo_entity_base import NetatmoBase

_LOGGER = logging.getLogger(__name__)


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
        self._sync_state()
        self.async_write_ha_state()

    async def async_close_cover(self, **kwargs: Any) -> None:
        """Close the shutter fully."""
        await self._cover.async_close()
        self._sync_state()
        self.async_write_ha_state()

    async def async_stop_cover(self, **kwargs: Any) -> None:
        """Stop any current shutter movement."""
        await self._cover.async_stop()

    async def async_open_cover_tilt(self, **kwargs: Any) -> None:
        """Tilt slats to jalousie (preferred) position."""
        await self._cover.async_open_tilt()
        self._sync_state()
        self.async_write_ha_state()

    async def async_close_cover_tilt(self, **kwargs: Any) -> None:
        """Flatten slats — returns shutter to closed position."""
        await self._cover.async_close_tilt()
        self._sync_state()
        self.async_write_ha_state()

    @callback
    def async_update_callback(self) -> None:
        """Update the entity state from the device after a webhook push."""
        self._sync_state()

    def _sync_state(self) -> None:
        """Recompute derived HA attributes from the device's current position.

        Bubendorff reports one of: 0 (closed), 100 (open), -2 (jalousie).
        -1 (stop) is a write-only command and never appears as a read-back state.
        """
        pos = self._cover.current_position
        self._attr_current_cover_position = pos

        # is_closed is True only when shutter is physically flat at 0.
        # In jalousie mode (-2) slats let light through, so it's NOT closed.
        self._attr_is_closed = pos == 0

        # Tilt position: binary flag exposed via current_cover_tilt_position
        # so card UIs can show "slats tilted" state.
        self._attr_current_cover_tilt_position = (
            100 if pos == SHUTTER_POSITION_PREFERRED else 0
        )
