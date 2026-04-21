"""Persistent position tracker for Bubendorff shutters.

The Netatmo cloud only reports two read-back values for a shutter position:
0 (fully closed) or 100 (fully open). Intermediate states are invisible to
the API. To support `cover.set_cover_position` with arbitrary percentages,
we maintain our OWN position estimate between HA restarts, backed by
HomeAssistant's Store helper (writes to `.storage/`).

Confidence semantics:
  * KNOWN      — shutter just hit 0 or 100 for real (API confirmed).
  * ESTIMATED  — we drove it to an intermediate position; accurate within
                 ±15% depending on motor variance and API latency.
  * UNKNOWN    — first install, physical wall-switch was used, or any
                 other out-of-band movement we didn't observe.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    POSITION_CONFIDENCE_KNOWN,
    POSITION_CONFIDENCE_UNKNOWN,
    POSITION_STORE_KEY_PREFIX,
    POSITION_STORE_VERSION,
)

_LOGGER = logging.getLogger(__name__)


@dataclass
class PositionEntry:
    """One shutter's persisted state."""

    position: float            # 0.0 – 100.0
    confidence: str            # POSITION_CONFIDENCE_*
    last_updated: str          # ISO-8601 UTC

    @classmethod
    def unknown(cls) -> PositionEntry:
        """Initial entry for a shutter we haven't observed yet."""
        return cls(
            position=0.0,
            confidence=POSITION_CONFIDENCE_UNKNOWN,
            last_updated=dt_util.utcnow().isoformat(),
        )

    @classmethod
    def known(cls, position: float) -> PositionEntry:
        """Entry after a confirmed arrival at 0 or 100."""
        return cls(
            position=position,
            confidence=POSITION_CONFIDENCE_KNOWN,
            last_updated=dt_util.utcnow().isoformat(),
        )


class PositionStore:
    """Thin wrapper around HA's Store for per-shutter position dicts.

    Storage shape on disk:
        {
            "cover.roleta":   {"position": 50.0, "confidence": "estimated", ...},
            "cover.roleta_2": {"position": 100.0, "confidence": "known", ...}
        }

    Scoped per config entry so two Netatmo homes won't collide.
    """

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self._hass = hass
        self._store: Store[dict[str, Any]] = Store(
            hass,
            POSITION_STORE_VERSION,
            f"{POSITION_STORE_KEY_PREFIX}_{entry_id}",
        )
        self._cache: dict[str, PositionEntry] = {}
        self._loaded = False

    async def async_load(self) -> None:
        """Populate the in-memory cache from disk."""
        raw = await self._store.async_load() or {}
        self._cache = {
            entity_id: PositionEntry(**data)
            for entity_id, data in raw.items()
        }
        self._loaded = True
        _LOGGER.debug("Loaded %d persisted positions", len(self._cache))

    async def async_save(self) -> None:
        """Flush the cache to disk."""
        await self._store.async_save(
            {entity_id: asdict(entry) for entity_id, entry in self._cache.items()}
        )

    def get(self, entity_id: str) -> PositionEntry:
        """Read a shutter's last persisted state, defaulting to UNKNOWN."""
        return self._cache.get(entity_id, PositionEntry.unknown())

    async def async_update(
        self,
        entity_id: str,
        position: float,
        confidence: str,
    ) -> None:
        """Record a new position estimate and persist to disk."""
        self._cache[entity_id] = PositionEntry(
            position=float(position),
            confidence=confidence,
            last_updated=dt_util.utcnow().isoformat(),
        )
        await self.async_save()
