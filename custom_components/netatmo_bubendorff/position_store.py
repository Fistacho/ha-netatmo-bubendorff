"""Target-position store for Bubendorff shutters.

Netatmo cloud never returns -2 (jalousie/tilt) in current_position — it
always reports 0 or 100. To survive HA restarts with tilt state intact,
we persist the last-commanded target_position per cover in HA's Store.
"""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import STATE_STORE_KEY_PREFIX, STATE_STORE_VERSION

_LOGGER = logging.getLogger(__name__)


class StateStore:
    """Maps entity_id → last known target_position (int: 0, 100, -1, -2)."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self._store: Store[dict[str, int]] = Store(
            hass,
            STATE_STORE_VERSION,
            f"{STATE_STORE_KEY_PREFIX}_{entry_id}",
        )
        self._cache: dict[str, int] = {}

    async def async_load(self) -> None:
        raw = await self._store.async_load() or {}
        self._cache = {k: int(v) for k, v in raw.items()}
        _LOGGER.debug("Loaded %d persisted target positions", len(self._cache))

    def get(self, entity_id: str) -> int | None:
        """Return last persisted target_position, or None if unknown."""
        return self._cache.get(entity_id)

    async def async_update(self, entity_id: str, target_position: int) -> None:
        self._cache[entity_id] = target_position
        await self._store.async_save(self._cache)
