"""The Netatmo Bubendorff integration."""
from __future__ import annotations

# --- Vendored pyatmo registration -------------------------------------------
# This integration bundles a patched copy of pyatmo 7.5.0 that adds Bubendorff
# jalousie (target_position -2) support. We register it as `pyatmo` in
# sys.modules BEFORE any other code imports it, so every `import pyatmo`
# across this package resolves to our vendored copy — not the pip-installed
# one that Home Assistant core may also have.
#
# Using importlib.util with an absolute path (__file__) instead of a hardcoded
# relative string so the integration works no matter where the user mounts it.
#
# KNOWN RISK (evaluated 2026-09-27, see docs/MIGRATION_PYATMO_9.md): this
# overwrites the *global*, process-wide `sys.modules["pyatmo"]` entry. If the
# official core `netatmo` integration is also enabled in this Home Assistant
# instance and imports the real pip-installed pyatmo (9.x) lazily *after* this
# module has already run once, it will receive our vendored 7.5.0 fork
# instead — pyatmo 9.x removed/renamed several modules this integration's own
# code does not use but core `netatmo` does (see the migration doc's
# breakage table), so that would break core `netatmo`, not us. We deliberately
# do NOT attempt a scoped/meta-path fix here (e.g. hijacking only imports
# performed by this package) — that requires call-stack introspection in a
# sys.meta_path finder, which is fragile and out of proportion for a
# lightweight pass. Full remediation is unvendoring per the migration doc.
# Until then, we can only make the collision observable instead of silent.
import importlib.util
import logging
import os
import sys

_LOGGER = logging.getLogger(__name__)

_PKG_DIR = os.path.dirname(os.path.abspath(__file__))
_VENDORED_PYATMO_INIT = os.path.join(_PKG_DIR, "pyatmo", "__init__.py")

if os.path.isfile(_VENDORED_PYATMO_INIT):
    _existing_pyatmo = sys.modules.get("pyatmo")
    _existing_file = getattr(_existing_pyatmo, "__file__", None)
    if _existing_pyatmo is not None and (
        _existing_file is None
        or not os.path.abspath(_existing_file).startswith(_PKG_DIR)
    ):
        _LOGGER.warning(
            "Netatmo (Bubendorff Fistacho): a different 'pyatmo' package was "
            "already imported (%s) before this integration loaded. It is "
            "about to be replaced in sys.modules with this integration's "
            "bundled pyatmo 7.5.0 fork for the rest of this Home Assistant "
            "process. If you also use the official 'netatmo' integration in "
            "this instance, it may break as a result — see "
            "docs/MIGRATION_PYATMO_9.md in this integration's repository.",
            _existing_file or "<unknown location>",
        )

    _spec = importlib.util.spec_from_file_location(
        "pyatmo",
        _VENDORED_PYATMO_INIT,
        submodule_search_locations=[os.path.join(_PKG_DIR, "pyatmo")],
    )
    _module = importlib.util.module_from_spec(_spec)
    sys.modules["pyatmo"] = _module
    _spec.loader.exec_module(_module)
# ---------------------------------------------------------------------------

from datetime import datetime
from http import HTTPStatus
import secrets
from typing import Any

import aiohttp

from .pyatmo import exceptions
from pyatmo.const import ALL_SCOPES as NETATMO_SCOPES
import voluptuous as vol

from homeassistant.components import cloud
from homeassistant.components.application_credentials import (
    ClientCredential,
    async_import_client_credential,
)
from homeassistant.components.webhook import (
    async_generate_url as webhook_generate_url,
    async_register as webhook_register,
    async_unregister as webhook_unregister,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_CLIENT_ID,
    CONF_CLIENT_SECRET,
    CONF_WEBHOOK_ID,
    EVENT_HOMEASSISTANT_STARTED,
    EVENT_HOMEASSISTANT_STOP,
)
from homeassistant.core import (
    DOMAIN as HOMEASSISTANT_DOMAIN,
    CoreState,
    Event,
    HomeAssistant,
    ServiceCall,
    callback,
)
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import (
    aiohttp_client,
    config_entry_oauth2_flow,
    config_validation as cv,
)
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.issue_registry import IssueSeverity, async_create_issue
from homeassistant.helpers.typing import ConfigType

from . import api
from .const import (
    AUTH,
    CONF_CLOUDHOOK_URL,
    DATA_CAMERAS,
    DATA_DEVICE_IDS,
    DATA_EVENTS,
    DATA_HANDLER,
    DATA_HOMES,
    DATA_PERSONS,
    DATA_SCHEDULES,
    DOMAIN,
    PLATFORMS,
    WEBHOOK_DEACTIVATION,
    WEBHOOK_PUSH_TYPE,
)
from .data_handler import NetatmoDataHandler
from .webhook import async_handle_webhook

CONFIG_SCHEMA = vol.Schema(
    vol.All(
        cv.deprecated(DOMAIN),
        {
            DOMAIN: vol.Schema(
                {
                    vol.Required(CONF_CLIENT_ID): cv.string,
                    vol.Required(CONF_CLIENT_SECRET): cv.string,
                }
            )
        },
    ),
    extra=vol.ALLOW_EXTRA,
)

MAX_WEBHOOK_RETRIES = 3

# Webhook registration is retried with exponential backoff when the Netatmo
# API is down: 30 s, 60 s, 120 s ... capped at 15 min.
WEBHOOK_RETRY_BASE_DELAY = 30
WEBHOOK_RETRY_MAX_DELAY = 900


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the Netatmo component."""
    hass.data[DOMAIN] = {
        DATA_PERSONS: {},
        DATA_DEVICE_IDS: {},
        DATA_SCHEDULES: {},
        DATA_HOMES: {},
        DATA_EVENTS: {},
        DATA_CAMERAS: {},
    }

    if DOMAIN not in config:
        return True

    await async_import_client_credential(
        hass,
        DOMAIN,
        ClientCredential(
            config[DOMAIN][CONF_CLIENT_ID],
            config[DOMAIN][CONF_CLIENT_SECRET],
        ),
    )
    _LOGGER.warning(
        "Configuration of Netatmo integration in YAML is deprecated and "
        "will be removed in a future release; Your existing configuration "
        "(including OAuth Application Credentials) have been imported into "
        "the UI automatically and can be safely removed from your "
        "configuration.yaml file"
    )
    async_create_issue(
        hass,
        HOMEASSISTANT_DOMAIN,
        f"deprecated_yaml_{DOMAIN}",
        breaks_in_ha_version="2024.2.0",
        is_fixable=False,
        issue_domain=DOMAIN,
        severity=IssueSeverity.WARNING,
        translation_key="deprecated_yaml",
        translation_placeholders={
            "domain": DOMAIN,
            "integration_title": "Netatmo",
        },
    )

    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Netatmo from a config entry."""
    implementation = (
        await config_entry_oauth2_flow.async_get_config_entry_implementation(
            hass, entry
        )
    )

    # Set unique id if non was set (migration)
    if not entry.unique_id:
        hass.config_entries.async_update_entry(entry, unique_id=DOMAIN)

    session = config_entry_oauth2_flow.OAuth2Session(hass, entry, implementation)
    try:
        await session.async_ensure_token_valid()
    except aiohttp.ClientResponseError as ex:
        _LOGGER.debug("API error: %s (%s)", ex.status, ex.message)
        if ex.status in (
            HTTPStatus.BAD_REQUEST,
            HTTPStatus.UNAUTHORIZED,
            HTTPStatus.FORBIDDEN,
        ):
            raise ConfigEntryAuthFailed("Token not valid, trigger renewal") from ex
        raise ConfigEntryNotReady from ex

    if entry.data["auth_implementation"] == cloud.DOMAIN:
        required_scopes = {
            scope
            for scope in NETATMO_SCOPES
            if scope not in ("access_doorbell", "read_doorbell")
        }
    else:
        required_scopes = set(NETATMO_SCOPES)

    if not (set(session.token["scope"]) & required_scopes):
        _LOGGER.debug(
            "Session is missing scopes: %s",
            required_scopes - set(session.token["scope"]),
        )
        raise ConfigEntryAuthFailed("Token scope not valid, trigger renewal")

    hass.data[DOMAIN][entry.entry_id] = {
        AUTH: api.AsyncConfigEntryNetatmoAuth(
            aiohttp_client.async_get_clientsession(hass), session
        )
    }

    data_handler = NetatmoDataHandler(hass, entry)
    hass.data[DOMAIN][entry.entry_id][DATA_HANDLER] = data_handler
    try:
        await data_handler.async_setup()
    except BaseException:
        # ConfigEntryNotReady (Netatmo outage) makes HA call us again from
        # scratch; do not leave a half-initialised entry behind.
        hass.data[DOMAIN].pop(entry.entry_id, None)
        raise

    webhook_retry: dict[str, Any] = {"attempt": 0, "cancel": None}

    @callback
    def cancel_webhook_retry() -> None:
        """Cancel a pending webhook registration retry (if any)."""
        if (cancel := webhook_retry["cancel"]) is not None:
            webhook_retry["cancel"] = None
            cancel()

    entry.async_on_unload(cancel_webhook_retry)

    async def retry_webhook_registration(now: datetime) -> None:
        webhook_retry["cancel"] = None  # the timer has just fired
        await register_webhook(None)

    @callback
    def schedule_webhook_retry() -> None:
        delay = min(
            WEBHOOK_RETRY_BASE_DELAY * 2 ** webhook_retry["attempt"],
            WEBHOOK_RETRY_MAX_DELAY,
        )
        webhook_retry["attempt"] += 1
        webhook_retry["cancel"] = async_call_later(
            hass, delay, retry_webhook_registration
        )
        _LOGGER.debug(
            "Netatmo webhook registration will be retried in %s s (attempt %s)",
            delay,
            webhook_retry["attempt"],
        )

    async def unregister_webhook(
        call_or_event_or_dt: ServiceCall | Event | datetime | None,
    ) -> None:
        cancel_webhook_retry()
        if CONF_WEBHOOK_ID not in entry.data:
            return
        _LOGGER.debug("Unregister Netatmo webhook (%s)", entry.data[CONF_WEBHOOK_ID])
        async_dispatcher_send(
            hass,
            f"signal-{DOMAIN}-webhook-None",
            {"type": "None", "data": {WEBHOOK_PUSH_TYPE: WEBHOOK_DEACTIVATION}},
        )
        webhook_unregister(hass, entry.data[CONF_WEBHOOK_ID])
        try:
            await hass.data[DOMAIN][entry.entry_id][AUTH].async_dropwebhook()
        except pyatmo.ApiError:
            _LOGGER.debug(
                "No webhook to be dropped for %s", entry.data[CONF_WEBHOOK_ID]
            )

    async def register_webhook(
        call_or_event_or_dt: ServiceCall | Event | datetime | None,
    ) -> None:
        if CONF_WEBHOOK_ID not in entry.data:
            data = {**entry.data, CONF_WEBHOOK_ID: secrets.token_hex()}
            hass.config_entries.async_update_entry(entry, data=data)

        if cloud.async_active_subscription(hass):
            webhook_url = await async_cloudhook_generate_url(hass, entry)
        else:
            webhook_url = webhook_generate_url(hass, entry.data[CONF_WEBHOOK_ID])

        if entry.data[
            "auth_implementation"
        ] == cloud.DOMAIN and not webhook_url.startswith("https://"):
            _LOGGER.warning(
                "Webhook not registered - "
                "https and port 443 is required to register the webhook"
            )
            return

        cancel_webhook_retry()  # a manual call supersedes a pending retry

        # Re-registering (retry / manual service call) must not raise
        # "Handler is already defined"; unregister is a no-op when absent.
        webhook_unregister(hass, entry.data[CONF_WEBHOOK_ID])
        webhook_register(
            hass,
            DOMAIN,
            "Netatmo",
            entry.data[CONF_WEBHOOK_ID],
            async_handle_webhook,
        )

        try:
            await hass.data[DOMAIN][entry.entry_id][AUTH].async_addwebhook(webhook_url)
            _LOGGER.info("Register Netatmo webhook: %s", webhook_url)
        except (pyatmo.ApiError, aiohttp.ClientError) as err:
            if webhook_retry["attempt"] == 0:
                _LOGGER.error(
                    "Error during webhook registration - %s "
                    "(will keep retrying in the background)",
                    err,
                )
            else:
                _LOGGER.warning(
                    "Netatmo webhook registration retry failed - %s", err
                )
            schedule_webhook_retry()
        else:
            webhook_retry["attempt"] = 0
            entry.async_on_unload(
                hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, unregister_webhook)
            )

    async def manage_cloudhook(state: cloud.CloudConnectionState) -> None:
        if state is cloud.CloudConnectionState.CLOUD_CONNECTED:
            await register_webhook(None)

        if state is cloud.CloudConnectionState.CLOUD_DISCONNECTED:
            await unregister_webhook(None)
            async_call_later(hass, 30, register_webhook)

    if cloud.async_active_subscription(hass):
        if cloud.async_is_connected(hass):
            await register_webhook(None)
        entry.async_on_unload(
            cloud.async_listen_connection_change(hass, manage_cloudhook)
        )

    elif hass.state == CoreState.running:
        await register_webhook(None)
    else:
        entry.async_on_unload(
            hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, register_webhook)
        )

    hass.services.async_register(DOMAIN, "register_webhook", register_webhook)
    hass.services.async_register(DOMAIN, "unregister_webhook", unregister_webhook)

    async def set_shutters_batch(call: ServiceCall) -> None:
        """Move several Bubendorff shutters with a SINGLE Netatmo API call.

        Netatmo's setstate endpoint accepts a list of modules; using it for
        N shutters costs 1 request instead of N — faster and friendlier to
        the per-account rate limit (especially for 'close all' automations).
        """
        from homeassistant.helpers import entity_registry as er
        from homeassistant.helpers.entity_component import EntityComponent

        raw = call.data.get("entity_id", [])
        entity_ids: list[str] = [raw] if isinstance(raw, str) else list(raw)
        # services.yaml select selector returns strings — coerce to int.
        target_position: int = int(call.data["target_position"])

        cover_component: EntityComponent | None = hass.data.get("cover")
        if cover_component is None:
            _LOGGER.warning("cover platform not loaded; cannot run batch")
            return

        ent_reg = er.async_get(hass)
        # Group payload entries per Netatmo home — each home = 1 API call.
        modules_by_home: dict[Any, list[dict[str, Any]]] = {}

        for entity_id in entity_ids:
            entry_r = ent_reg.async_get(entity_id)
            if (
                entry_r is None
                or entry_r.platform != DOMAIN
                or entry_r.domain != "cover"
            ):
                _LOGGER.warning(
                    "Skipping %s — not a %s cover entity", entity_id, DOMAIN
                )
                continue

            cover_entity = cover_component.get_entity(entity_id)
            if cover_entity is None or not hasattr(cover_entity, "_cover"):
                continue

            shutter = cover_entity._cover  # pyatmo Shutter module
            modules_by_home.setdefault(shutter.home, []).append(
                {
                    "id": shutter.entity_id,
                    "target_position": target_position,
                    "bridge": shutter.bridge,
                }
            )

        for home, modules in modules_by_home.items():
            await home.async_set_state({"modules": modules})
            _LOGGER.info(
                "Batch-set %d shutter(s) to position %d on home %s",
                len(modules),
                target_position,
                home.entity_id,
            )

    hass.services.async_register(
        DOMAIN, "set_shutters_batch", set_shutters_batch
    )

    entry.add_update_listener(async_config_entry_updated)

    return True


async def async_cloudhook_generate_url(hass: HomeAssistant, entry: ConfigEntry) -> str:
    """Generate the full URL for a webhook_id."""
    if CONF_CLOUDHOOK_URL not in entry.data:
        webhook_url = await cloud.async_create_cloudhook(
            hass, entry.data[CONF_WEBHOOK_ID]
        )
        data = {**entry.data, CONF_CLOUDHOOK_URL: webhook_url}
        hass.config_entries.async_update_entry(entry, data=data)
        return webhook_url
    return str(entry.data[CONF_CLOUDHOOK_URL])


async def async_config_entry_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle signals of config entry being updated."""
    async_dispatcher_send(hass, f"signal-{DOMAIN}-public-update-{entry.entry_id}")


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    data = hass.data[DOMAIN]

    if CONF_WEBHOOK_ID in entry.data:
        webhook_unregister(hass, entry.data[CONF_WEBHOOK_ID])
        try:
            await data[entry.entry_id][AUTH].async_dropwebhook()
        except pyatmo.ApiError:
            _LOGGER.debug("No webhook to be dropped")
        _LOGGER.info("Unregister Netatmo webhook")

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok and entry.entry_id in data:
        data.pop(entry.entry_id)

    return unload_ok


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Cleanup when entry is removed."""
    if CONF_WEBHOOK_ID in entry.data and cloud.async_active_subscription(hass):
        try:
            _LOGGER.debug(
                "Removing Netatmo cloudhook (%s)", entry.data[CONF_WEBHOOK_ID]
            )
            await cloud.async_delete_cloudhook(hass, entry.data[CONF_WEBHOOK_ID])
        except cloud.CloudNotAvailable:
            pass
