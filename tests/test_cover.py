"""Cover state and device naming (1.6.3).

Live symptoms on HA 2026.11.1 (2026-11-11), all four Bubendorff shutters:

* state ``unknown`` although ``current_position`` is 0 / 100 and
  ``intended_state`` is known -- ``is_closed`` was hard-coded to ``None``;
* shutters 2-4 have no friendly name and every shutter device has
  ``name == ""`` -- the disabled "Radio" / "Reachability" sensors share the
  shutter's device and sent ``DeviceInfo(name="")``, overwriting the device
  name set by the cover on every start.
"""
from __future__ import annotations

# The package import registers the vendored pyatmo in sys.modules; it MUST
# precede `import pyatmo` below.
from custom_components import netatmo_bubendorff  # noqa: F401  # isort: skip
from custom_components.netatmo_bubendorff.const import (  # isort: skip
    DATA_DEVICE_IDS,
    DOMAIN,
)
from custom_components.netatmo_bubendorff.cover import NetatmoCover  # isort: skip
from custom_components.netatmo_bubendorff.data_handler import (  # isort: skip
    NetatmoDevice,
)
from custom_components.netatmo_bubendorff.position_store import (  # isort: skip
    StateStore,
)
from custom_components.netatmo_bubendorff.sensor import (  # isort: skip
    SENSOR_TYPES,
    NetatmoSensor,
)

from collections import defaultdict
from datetime import timedelta
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pyatmo
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.const import ATTR_ASSUMED_STATE, ATTR_FRIENDLY_NAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_platform

NO_SLEEP = patch(
    "custom_components.netatmo_bubendorff.cover.asyncio.sleep", AsyncMock()
)

HOME_ID = "home-1"
GATEWAY_ID = "70:ee:50:00:00:01"
SHUTTER_ID = "0000890993"

HOMESDATA = {
    "id": HOME_ID,
    "name": "Dom",
    "modules": [
        {"id": GATEWAY_ID, "type": "NBG", "name": "Bramka"},
        {
            "id": SHUTTER_ID,
            "type": "NBO",
            "name": "Roleta 2",
            "room_id": "room-1",
            "bridge": GATEWAY_ID,
        },
    ],
    "rooms": [
        {"id": "room-1", "name": "Salon", "type": "livingroom",
         "module_ids": [SHUTTER_ID]},
    ],
}


def _homestatus(current_position: int, reachable: bool = True) -> dict:
    return {
        "id": SHUTTER_ID,
        "type": "NBO",
        "reachable": reachable,
        "current_position": current_position,
        "target_position": current_position,
        "rf_strength": 70,
        "firmware_revision": 16,
    }


def _data_handler() -> MagicMock:
    handler = MagicMock()
    handler.subscribe = AsyncMock()
    handler.unsubscribe = AsyncMock()
    handler.publisher = defaultdict(lambda: MagicMock(subscriptions=[]))
    return handler


async def _shutter(current_position: int, reachable: bool = True):
    home = pyatmo.Home(MagicMock(), HOMESDATA)
    module = home.modules[SHUTTER_ID]
    await module.update(_homestatus(current_position, reachable))
    module.async_set_target_position = AsyncMock(return_value=True)
    return module


def _platform(hass: HomeAssistant, entry: MockConfigEntry, domain: str):
    platform = entity_platform.EntityPlatform(
        hass=hass,
        logger=logging.getLogger(__name__),
        domain=domain,
        platform_name=DOMAIN,
        platform=None,
        scan_interval=timedelta(seconds=30),
        entity_namespace=None,
    )
    platform.config_entry = entry
    return platform


@pytest.fixture
async def setup_shutter(hass: HomeAssistant):
    """Add the cover and the shutter's diagnostic sensors like a real start."""
    platforms: list[entity_platform.EntityPlatform] = []

    async def _setup(
        current_position: int = 0,
        reachable: bool = True,
        entry: MockConfigEntry | None = None,
    ):
        if entry is None:  # a given entry simulates a restart of the same one
            entry = MockConfigEntry(domain=DOMAIN, unique_id=DOMAIN, data={})
            entry.add_to_hass(hass)
        hass.data.setdefault(DOMAIN, {})[DATA_DEVICE_IDS] = {}

        module = await _shutter(current_position, reachable)
        device = NetatmoDevice(_data_handler(), module, HOME_ID, f"home-{HOME_ID}")
        store = StateStore(hass, entry.entry_id)
        await store.async_load()

        cover = NetatmoCover(device, entry, store)
        cover.test_entry = entry
        cover.test_platform = _platform(hass, entry, "cover")
        platforms.append(cover.test_platform)
        await platforms[-1].async_add_entities([cover])

        # Same order as data_handler.setup_modules: NETATMO_CREATE_COVER first,
        # then NETATMO_CREATE_SENSOR for the same module (sensor.py filter).
        sensors = [
            NetatmoSensor(device, description)
            for description in SENSOR_TYPES
            if (description.netatmo_name or description.key) in module.features
        ]
        assert sensors, "shutter must create its diagnostic sensors"
        platforms.append(_platform(hass, entry, "sensor"))
        await platforms[-1].async_add_entities(sensors)
        await hass.async_block_till_done()
        return cover

    yield _setup

    for platform in platforms:
        await platform.async_reset()


async def test_device_keeps_shutter_name_after_sensors_are_added(
    hass: HomeAssistant, setup_shutter
) -> None:
    """The shutter's sensors must not blank the shared device name."""
    cover = await setup_shutter()

    assert cover.device_entry is not None
    device = dr.async_get(hass).async_get(cover.device_entry.id)
    assert device is not None
    assert (DOMAIN, SHUTTER_ID) in device.identifiers
    assert device.name == "Roleta 2"

    state = hass.states.get(cover.entity_id)
    assert state is not None
    assert state.attributes.get(ATTR_FRIENDLY_NAME) == "Roleta 2"


@pytest.mark.parametrize(
    ("current_position", "expected"), [(0, "closed"), (100, "open")]
)
async def test_state_follows_reported_position(
    hass: HomeAssistant, setup_shutter, current_position: int, expected: str
) -> None:
    """A position of 0 / 100 from the API is a known state, not unknown."""
    cover = await setup_shutter(current_position)

    state = hass.states.get(cover.entity_id)
    assert state.state == expected
    assert state.attributes["intended_state"] == expected
    # Buttons stay active (the reason is_closed used to be None): the
    # frontend keeps every cover button enabled for an assumed state.
    assert state.attributes.get(ATTR_ASSUMED_STATE) is True


async def test_state_after_commands(hass: HomeAssistant, setup_shutter) -> None:
    """Optimistic state after open / tilt / close commands."""
    cover = await setup_shutter(0)

    await cover.async_open_cover()
    assert hass.states.get(cover.entity_id).state == "open"

    await cover.async_open_cover_tilt()
    state = hass.states.get(cover.entity_id)
    assert state.attributes["intended_state"] == "tilted"
    assert state.state == "open"  # slats let light in: not fully closed

    await cover.async_close_cover()
    assert hass.states.get(cover.entity_id).state == "closed"


async def test_unreachable_shutter_is_unavailable(
    hass: HomeAssistant, setup_shutter
) -> None:
    """reachable=false from homestatus makes the cover unavailable."""
    cover = await setup_shutter(0, reachable=False)

    assert hass.states.get(cover.entity_id).state == "unavailable"


# --- tilt (jalousie, target_position -2) ------------------------------------
#
# The cloud reports only current_position 0 / 100 for NBO and never -2; the
# HOME publisher polls /homestatus every 30 s. A poll must not wipe the tilt
# that HA commanded.


async def _poll(hass: HomeAssistant, cover: NetatmoCover, position: int) -> None:
    """One /homestatus round trip: pyatmo update + publisher callback."""
    await cover._cover.update(_homestatus(position))
    cover.async_update_callback()
    await hass.async_block_till_done()


def _assert_tilted(hass: HomeAssistant, cover: NetatmoCover) -> None:
    # What the entity holds and persists for the next restart ...
    assert cover.extra_state_attributes["intended_state"] == "tilted"
    assert cover.current_cover_tilt_position == 100
    assert cover.is_closed is False
    assert cover._store.get(cover.entity_id_stub) == -2
    # ... and what HA shows.
    state = hass.states.get(cover.entity_id)
    assert state.attributes["intended_state"] == "tilted"
    assert state.attributes["current_tilt_position"] == 100
    assert state.state == "open"  # slats let light in: not fully closed


async def test_tilt_survives_poll_reporting_closed(
    hass: HomeAssistant, setup_shutter
) -> None:
    """(a) After open_cover_tilt the next polls report 0: still tilted."""
    cover = await setup_shutter(0)

    await cover.async_open_cover_tilt()
    _assert_tilted(hass, cover)

    await _poll(hass, cover, 0)
    await _poll(hass, cover, 0)
    _assert_tilted(hass, cover)
    assert hass.states.get(cover.entity_id).attributes["current_position"] == 0


async def test_tilt_from_open_survives_stale_open_report(
    hass: HomeAssistant, setup_shutter
) -> None:
    """(a) Tilt from fully open: a stale 100, then 0, keep the tilt."""
    cover = await setup_shutter(100)

    await cover.async_open_cover_tilt()
    await _poll(hass, cover, 100)
    _assert_tilted(hass, cover)
    await _poll(hass, cover, 0)
    _assert_tilted(hass, cover)


async def test_tilt_cleared_by_close_and_open_from_ha(
    hass: HomeAssistant, setup_shutter
) -> None:
    """(b) Plain close / open from HA leave the tilt and stay left."""
    cover = await setup_shutter(0)

    await cover.async_open_cover_tilt()
    await cover.async_close_cover()
    await _poll(hass, cover, 0)
    state = hass.states.get(cover.entity_id)
    assert state.attributes["intended_state"] == "closed"
    assert state.attributes["current_tilt_position"] == 0
    assert state.state == "closed"

    await cover.async_open_cover_tilt()
    with NO_SLEEP:
        await cover.async_open_cover()
    await _poll(hass, cover, 100)
    state = hass.states.get(cover.entity_id)
    assert state.attributes["intended_state"] == "open"
    assert state.attributes["current_tilt_position"] == 0
    assert state.state == "open"


async def test_tilt_cleared_when_opened_from_outside(
    hass: HomeAssistant, setup_shutter
) -> None:
    """(c) Remote / app opens the tilted shutter: the API goes 0 -> 100."""
    cover = await setup_shutter(0)

    await cover.async_open_cover_tilt()
    await _poll(hass, cover, 0)
    await _poll(hass, cover, 100)

    state = hass.states.get(cover.entity_id)
    assert state.attributes["intended_state"] == "open"
    assert state.attributes["current_tilt_position"] == 0
    assert state.state == "open"


async def test_tilt_survives_restart(hass: HomeAssistant, setup_shutter) -> None:
    """(d) Tilt is persisted and still shown after a restart and a poll."""
    cover = await setup_shutter(0)
    await cover.async_open_cover_tilt()
    entry = cover.test_entry
    await cover.test_platform.async_reset()  # HA stops

    cover = await setup_shutter(0, entry=entry)  # HA starts, API reports 0
    _assert_tilted(hass, cover)
    await _poll(hass, cover, 0)
    _assert_tilted(hass, cover)


async def test_radio_sensor_reads_rf_strength(hass: HomeAssistant) -> None:
    """The "Radio" sensor (key rf_status) reads the module's rf_strength."""
    module = await _shutter(0)
    device = NetatmoDevice(_data_handler(), module, HOME_ID, f"home-{HOME_ID}")
    description = next(d for d in SENSOR_TYPES if d.key == "rf_status")
    sensor = NetatmoSensor(device, description)
    sensor.async_write_ha_state = MagicMock()

    sensor.async_update_callback()

    assert sensor.native_value == 70
