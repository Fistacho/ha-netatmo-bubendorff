"""Self-healing after a transient Netatmo outage (1.6.1).

Reproduces the incident of 2026-10-01: HA restarted while api.netatmo.com
answered 503, the entry stayed `loaded` with zero entities until a manual
reload. Expected behaviour: ConfigEntryNotReady (HA retries with backoff) and
a retried webhook registration.
"""
from __future__ import annotations

# The package import registers the vendored pyatmo in sys.modules; it MUST
# precede `import pyatmo` below.
from custom_components import netatmo_bubendorff as integration  # isort: skip
from custom_components.netatmo_bubendorff import const  # isort: skip
from custom_components.netatmo_bubendorff.const import DOMAIN  # isort: skip
from custom_components.netatmo_bubendorff.data_handler import (  # isort: skip
    NetatmoDataHandler,
)

from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pyatmo
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_WEBHOOK_ID
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

PKG = "custom_components.netatmo_bubendorff"


def _entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        unique_id=DOMAIN,
        data={
            "auth_implementation": DOMAIN,
            "token": {"scope": list(pyatmo.const.ALL_SCOPES), "access_token": "x"},
            CONF_WEBHOOK_ID: "hook-id",
        },
    )


@pytest.fixture
async def handler_factory(hass: HomeAssistant):
    """Build a NetatmoDataHandler bound to a real hass + entry."""

    entries: list[MockConfigEntry] = []

    def _make() -> tuple[NetatmoDataHandler, MockConfigEntry]:
        entry = _entry()
        entry.add_to_hass(hass)
        entries.append(entry)
        hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {const.AUTH: MagicMock()}
        return NetatmoDataHandler(hass, entry), entry

    yield _make

    for entry in entries:  # drop interval/dispatcher listeners left by setup
        await entry._async_process_on_unload(hass)


def _quiet_account_publishers():
    """Patch the non-topology publishers used by async_dispatch."""
    return (
        patch.object(
            pyatmo.AsyncAccount, "async_update_weather_stations", AsyncMock()
        ),
        patch.object(pyatmo.AsyncAccount, "async_update_air_care", AsyncMock()),
    )


# --- A) data handler: topology failure -> ConfigEntryNotReady ---------------


@pytest.mark.parametrize(
    "error",
    [
        pyatmo.ApiError("503 - Service temporarily unavailable (27)"),
        TimeoutError("timeout"),
        aiohttp.ClientConnectionError("boom"),
    ],
)
async def test_topology_failure_raises_not_ready(hass, handler_factory, error):
    handler, entry = handler_factory()
    forward = AsyncMock()
    weather, air = _quiet_account_publishers()
    with (
        patch.object(
            pyatmo.AsyncAccount, "async_update_topology", AsyncMock(side_effect=error)
        ),
        weather,
        air,
        patch.object(hass.config_entries, "async_forward_entry_setups", forward),
        pytest.raises(ConfigEntryNotReady),
    ):
        await handler.async_setup()

    forward.assert_not_called()


async def test_topology_failure_registers_no_listeners(hass, handler_factory):
    handler, entry = handler_factory()
    before = len(entry._on_unload or [])
    weather, air = _quiet_account_publishers()
    with (
        patch.object(
            pyatmo.AsyncAccount,
            "async_update_topology",
            AsyncMock(side_effect=pyatmo.ApiError("503")),
        ),
        weather,
        air,
        patch.object(hass.config_entries, "async_forward_entry_setups", AsyncMock()),
        pytest.raises(ConfigEntryNotReady),
    ):
        await handler.async_setup()
    assert len(entry._on_unload or []) == before


async def test_account_without_homes_and_no_error_still_sets_up(hass, handler_factory):
    """A legitimate empty account must NOT block setup."""
    handler, entry = handler_factory()
    forward = AsyncMock()
    weather, air = _quiet_account_publishers()
    with (
        patch.object(pyatmo.AsyncAccount, "async_update_topology", AsyncMock()),
        weather,
        air,
        patch.object(hass.config_entries, "async_forward_entry_setups", forward),
    ):
        await handler.async_setup()

    forward.assert_awaited_once()
    assert handler.account.homes == {}


async def test_no_device_is_not_an_error(hass, handler_factory):
    handler, entry = handler_factory()
    weather, air = _quiet_account_publishers()
    with (
        patch.object(
            pyatmo.AsyncAccount,
            "async_update_topology",
            AsyncMock(side_effect=pyatmo.NoDevice("none")),
        ),
        weather,
        air,
        patch.object(hass.config_entries, "async_forward_entry_setups", AsyncMock()),
    ):
        await handler.async_setup()


# --- A) entry level: no leak in hass.data -----------------------------------


def _entry_setup_patches(auth_mock):
    session = MagicMock()
    session.token = {"scope": list(pyatmo.const.ALL_SCOPES)}
    session.async_ensure_token_valid = AsyncMock()
    return [
        patch(
            f"{PKG}.config_entry_oauth2_flow.async_get_config_entry_implementation",
            AsyncMock(return_value=MagicMock()),
        ),
        patch(f"{PKG}.config_entry_oauth2_flow.OAuth2Session", return_value=session),
        patch(f"{PKG}.api.AsyncConfigEntryNetatmoAuth", return_value=auth_mock),
        patch(f"{PKG}.cloud.async_active_subscription", return_value=False),
    ]


async def test_setup_entry_not_ready_leaves_no_state(hass):
    entry = _entry()
    entry.add_to_hass(hass)
    auth = MagicMock()
    auth.async_addwebhook = AsyncMock()
    auth.async_dropwebhook = AsyncMock()
    patches = _entry_setup_patches(auth) + [
        patch.object(
            pyatmo.AsyncAccount,
            "async_update_topology",
            AsyncMock(side_effect=pyatmo.ApiError("503")),
        ),
        *_quiet_account_publishers(),
        patch.object(
            hass.config_entries, "async_forward_entry_setups", AsyncMock()
        ),
    ]
    for p in patches:
        p.start()
    try:
        assert not await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    finally:
        for p in reversed(patches):
            p.stop()

    assert entry.state is ConfigEntryState.SETUP_RETRY
    assert entry.entry_id not in hass.data[DOMAIN]
    assert not hass.services.has_service(DOMAIN, "register_webhook")
    auth.async_addwebhook.assert_not_called()


# --- B) webhook registration retry ------------------------------------------


def _start_webhook_scenario(auth):
    """Skip topology/platform setup; capture async_call_later scheduling."""
    scheduled: list[tuple[float, object, MagicMock]] = []

    def fake_call_later(_hass, delay, action):
        cancel = MagicMock()
        scheduled.append((delay, action, cancel))
        return cancel

    patches = _entry_setup_patches(auth) + [
        patch.object(NetatmoDataHandler, "async_setup", AsyncMock()),
        patch(f"{PKG}.async_call_later", side_effect=fake_call_later),
    ]
    for p in patches:
        p.start()
    return scheduled, patches


async def test_webhook_registration_is_retried_with_backoff(hass):
    entry = _entry()
    entry.add_to_hass(hass)
    auth = MagicMock()
    auth.async_addwebhook = AsyncMock(side_effect=pyatmo.ApiError("503"))
    auth.async_dropwebhook = AsyncMock()
    scheduled, patches = _start_webhook_scenario(auth)
    try:
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        assert len(scheduled) == 1
        delays = [scheduled[0][0]]
        for _ in range(8):
            await scheduled[-1][1](None)
            delays.append(scheduled[-1][0])

        assert delays == sorted(delays)
        assert delays[0] < delays[3] < delays[-1]
        assert max(delays) == integration.WEBHOOK_RETRY_MAX_DELAY
        assert auth.async_addwebhook.await_count == 9
    finally:
        for p in reversed(patches):
            p.stop()


async def test_webhook_retry_stops_after_success_and_is_cancelled_on_unload(hass):
    entry = _entry()
    entry.add_to_hass(hass)
    auth = MagicMock()
    auth.async_addwebhook = AsyncMock(side_effect=[pyatmo.ApiError("503"), None])
    auth.async_dropwebhook = AsyncMock()
    scheduled, patches = _start_webhook_scenario(auth)
    try:
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        assert len(scheduled) == 1

        await scheduled[0][1](None)  # second attempt succeeds
        assert len(scheduled) == 1  # nothing new scheduled
        assert auth.async_addwebhook.await_count == 2

        # A failure followed by unload must cancel the pending timer.
        auth.async_addwebhook.side_effect = pyatmo.ApiError("503")
        await hass.services.async_call(DOMAIN, "register_webhook", blocking=True)
        pending_cancel = scheduled[-1][2]
        assert await hass.config_entries.async_unload(entry.entry_id)
        pending_cancel.assert_called_once()
    finally:
        for p in reversed(patches):
            p.stop()


async def test_webhook_error_logged_once_then_warning(hass, caplog):
    entry = _entry()
    entry.add_to_hass(hass)
    auth = MagicMock()
    auth.async_addwebhook = AsyncMock(side_effect=pyatmo.ApiError("503"))
    auth.async_dropwebhook = AsyncMock()
    scheduled, patches = _start_webhook_scenario(auth)
    try:
        assert await hass.config_entries.async_setup(entry.entry_id)
        for _ in range(3):
            await scheduled[-1][1](None)
        errors = [
            r
            for r in caplog.records
            if r.levelname == "ERROR" and "webhook registration" in r.getMessage()
        ]
        assert len(errors) == 1
    finally:
        for p in reversed(patches):
            p.stop()
