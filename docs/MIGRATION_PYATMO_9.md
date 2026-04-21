# Migration plan: vendored pyatmo 7.5.0 → unvendored pyatmo 9.x

**Status:** planned, not started
**Estimated effort:** 1–2 dev days + thorough testing of every device category
**Triggers work when:** Netatmo deprecates an endpoint that 7.5.0 still calls, or HA core bumps pyatmo past 9.2.3 in a way that clashes with our vendored copy.

---

## Why migrate

- Drop ~50 files of vendored pyatmo — no more parallel maintenance.
- Stay aligned with `home-assistant/core` (currently pyatmo 9.2.3).
- Automatic security patches from PyPI.
- Easier for new contributors — no "why are there two module.py files?" confusion.

## Why *not* yet (and why v1.2.0 is fine for now)

- pyatmo 7.5 → 9.x is **not** a drop-in version bump. The library was restructured.
- Current vendoring guarantees behavior is frozen to what we tested.
- Real users depend on `cover.open_cover_tilt`; breaking the integration is worse than carrying 50 extra files.

## Verified API breakages (tested 2026-04-21)

pyatmo 9.2.3 **removed** the following modules the current integration code (or the vendored pyatmo it imports) touches:

| Removed / changed | Used by | Replacement in 9.x |
| --- | --- | --- |
| `pyatmo.camera` (whole module) | vendored `pyatmo/` internal, old `CameraData` API | Unified `pyatmo.Home.cameras` |
| `pyatmo.weather_station` (whole module) | vendored `pyatmo/` internal | `AsyncAccount.async_update_weather_stations()` |
| `pyatmo.home_coach` (whole module) | vendored `pyatmo/` internal | `AsyncAccount.async_update_air_care()` |
| `pyatmo.public_data` (whole module) | vendored `pyatmo/` internal | `AsyncAccount.async_update_public_data()` |
| `pyatmo.thermostat` (whole module) | vendored `pyatmo/` internal | unified `pyatmo.Home` / `pyatmo.Module` |
| `pyatmo.auth.ClientAuth` class | vendored `pyatmo/__init__.py` | `pyatmo.AbstractAsyncAuth` (async-only) |
| `pyatmo.exceptions.InvalidHome` | vendored `pyatmo/home.py` | removed — `ValueError` or similar |

## Stable APIs (confirmed working in 9.2.3)

```python
import pyatmo                                     # ok
from pyatmo import ApiError, modules, const      # ok
from pyatmo.account import AsyncAccount          # ok
from pyatmo.auth import AbstractAsyncAuth, NetatmoOAuth2   # ok
from pyatmo.const import ALL_SCOPES              # ok
from pyatmo.event import Event                   # ok
from pyatmo.exceptions import ApiError, NoDevice # ok (lost some variants)
from pyatmo.home import Home                     # ok
from pyatmo.modules import Module, NATherm1      # ok
from pyatmo.modules.base_class import EntityBase, NetatmoBase, Place   # ok
from pyatmo.modules.device_types import DeviceCategory, DeviceType    # ok
from pyatmo.modules.module import FirmwareMixin, ShutterMixin, RfMixin # ok
from pyatmo.room import Room                     # ok
```

The **integration's** own code mostly uses the stable surface. It's the vendored `pyatmo/` internals that would need rewriting.

## Proposed migration steps

### Step 1 — unvendor (biggest win, most work)

1. Delete `custom_components/netatmo_bubendorff/pyatmo/` entirely.
2. Change `manifest.json` to declare the dependency:

   ```json
   "requirements": ["pyatmo==9.2.3"]
   ```

3. Replace the `sys.modules["pyatmo"]` loader block in `__init__.py` with a runtime monkey-patch:

   ```python
   # Add Bubendorff tilt methods to pyatmo's ShutterMixin the moment we import it.
   from pyatmo.modules.module import ShutterMixin

   async def _async_open_tilt(self):
       """Move shutter to preferred (jalousie) position."""
       return await self.async_set_target_position(-2)

   async def _async_close_tilt(self):
       """Exit jalousie — return slats flat (shutter closed)."""
       return await self.async_set_target_position(0)

   if not hasattr(ShutterMixin, "async_open_tilt"):
       ShutterMixin.async_open_tilt = _async_open_tilt
   if not hasattr(ShutterMixin, "async_close_tilt"):
       ShutterMixin.async_close_tilt = _async_close_tilt
   ```

4. Remove the `from .pyatmo import ...` relative imports — replace with absolute `from pyatmo import ...`.

### Step 2 — adapt integration files to 9.x API

Likely refactors required in:

- `api.py` — probably unchanged (uses OAuth abstract).
- `camera.py` — change `CameraData` / `AsyncCameraData` usage → `home.cameras`.
- `data_handler.py` — adapt whatever still calls removed modules.
- `sensor.py` — check if `rf_strength` still exists on 9.x `RfMixin`.
- `climate.py` — verify `NATherm1` still exported.

### Step 3 — test every device category

- [ ] Shutter — open/close/stop/tilt (primary use case)
- [ ] Thermostat — schedule, temperature setpoint
- [ ] Camera — snapshot, motion, person detection
- [ ] Weather station — outdoor/indoor modules
- [ ] Home coach / air care
- [ ] Light — switch on/off, brightness
- [ ] Switch — toggle

Requires a HA instance with each device category. Users without a device type should still see the integration load without errors.

### Step 4 — release

- Bump major: v2.0.0 (the integration's `requirements` change is breaking for the install profile).
- Mention migration in CHANGELOG prominently — users must update via HACS, restart HA, re-reauth *might* be needed.

## Rollback plan

If Step 2 proves impractical or user reports break:

1. Revert `manifest.json` (remove requirements, restore vendored loader block).
2. Restore `custom_components/netatmo_bubendorff/pyatmo/` from git history.
3. Keep living on 7.5 as long as Netatmo API stays stable there.

## Trigger conditions (when to actually do this)

- Netatmo returns HTTP 4xx/5xx on endpoints pyatmo 7.5 uses (would only affect older auth flow today).
- HA core bumps to a pyatmo version that stops being backward-compatible in a way our vendored loader can't isolate.
- Community contributor volunteers to own Step 2/3.
