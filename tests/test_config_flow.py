"""Options flow opened through the real flow manager (1.6.2).

Since HA 2025.12 `OptionsFlow.config_entry` is a read-only property filled in
by the flow manager; assigning it in `__init__` raised AttributeError and the
"Configure" button crashed (seen live on HA 2026.10.4).
"""
from __future__ import annotations

# The package import registers the vendored pyatmo in sys.modules; it MUST
# precede `import pyatmo` below.
from custom_components.netatmo_bubendorff.const import (  # isort: skip
    CONF_NEW_AREA,
    CONF_WEATHER_AREAS,
    DOMAIN,
)

import pyatmo
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType


def _entry(options: dict | None = None) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        unique_id=DOMAIN,
        data={
            "auth_implementation": DOMAIN,
            "token": {"scope": list(pyatmo.const.ALL_SCOPES), "access_token": "x"},
        },
        options=options or {},
    )


async def test_options_flow_opens_form(hass: HomeAssistant) -> None:
    """Opening the options flow returns the weather areas form, no exception."""
    entry = _entry()
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "public_weather_areas"


async def test_options_flow_new_area_reads_entry_options(hass: HomeAssistant) -> None:
    """Adding an area uses `self.config_entry` (set by the flow manager)."""
    entry = _entry({CONF_WEATHER_AREAS: {}})
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input={CONF_NEW_AREA: "Home"}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "public_weather"
