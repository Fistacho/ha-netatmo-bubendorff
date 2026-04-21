# Changelog

All notable changes to this project are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [1.3.0] — 2026-04-21

### Fixed in 1.3.0

- **Tilt state was invisible to HA.** Netatmo's cloud never reports `-2`
  in `current_position` after a tilt — it stays at 0/100 even though the
  slats are physically tilted. The integration therefore showed every
  tilted shutter as "closed", making automations unable to tell tilted
  from fully-closed.

### Added in 1.3.0

- **Optimistic state update** — every `cover.*` command we issue now
  writes its target into the pyatmo module in memory, so HA attributes
  flip to the new state immediately instead of waiting for a webhook /
  poll round-trip (which never brings tilt info anyway).
- **`intended_state` attribute** on every cover entity — one of
  `open` / `closed` / `tilted` / `stopped` / `unknown`. Easy to use in
  automations:

  ```yaml
  condition: "{{ state_attr('cover.roleta', 'intended_state') == 'tilted' }}"
  ```

- **`netatmo_current_position` / `netatmo_target_position` attributes** —
  raw values from the Netatmo API for debugging. Useful when tracing
  webhook behaviour or physical-switch events.
- **`current_cover_tilt_position`** is now driven by `target_position`
  (which persists after a tilt), not by `current_position` (which does
  not). Lovelace cards that read tilt position now render correctly.

## [1.2.1] — 2026-04-21

### Added in 1.2.1

- README badges (HACS, release version, license, issues, minimum HA version).
- `.github/ISSUE_TEMPLATE/` with structured bug report and feature request
  forms, plus links to the HA community Bubendorff thread and Netatmo API docs.
- `.github/PULL_REQUEST_TEMPLATE.md` with a testing checklist.
- `SUPPORT.md` explaining escalation order and documenting hardware / API
  limits that are not fixable here (continuous 0-100 %, tilt angles,
  obstacle readback, built-in weather sensors).
- `docs/MIGRATION_PYATMO_9.md` — migration plan from the vendored
  `pyatmo 7.5.0` to unvendored `pyatmo 9.x`. Includes verified API
  breakage table, monkey-patch approach, step-by-step migration, rollback
  procedure, and trigger conditions. **Not executed** — v1.2.1 still ships
  with vendored 7.5.0; the plan is there for when we need it.

### Changed in 1.2.1

No functional code changes. Users updating from v1.2.0 will see no
behavioural difference — this release is housekeeping only.

## [1.2.0] — 2026-04-21

### Added in 1.2.0

- **Brand icons** — `icon.png`, `icon@2x.png`, `logo.png`, `logo@2x.png`
  in the repo root, sourced from `home-assistant/brands` core Netatmo
  integration. HACS now shows the familiar orange Netatmo logo instead
  of a generic placeholder.
- **Translations:** `es.json` (Spanish), `de.json` (German),
  `pl.json` (Polish) — added alongside existing `en` and `fr`.
- **Expanded OAuth setup documentation** in README:
  - Full `dev.netatmo.com/apps` walkthrough with the exact redirect URI
  - Both routes for adding Application Credentials (from dialog, from
    Settings menu)
  - Troubleshooting table for the most common first-install errors
    (invalid redirect, login loop, missing entities, reload-needed).

## [1.1.1] — 2026-04-21

### Fixed in 1.1.1

- `_create_sensor_entity` filter now matches on `netatmo_name` (falling
  back to `key`) instead of only `key`. Upstream bug prevented
  `rf_status` / `wifi_status` diagnostic sensors from ever being created
  because `key` ≠ `netatmo_name` for those two descriptions — the
  module's `features` set holds pyatmo attribute names, not entity keys.
  Now the RF sensor promised in 1.1.0 actually shows up.

## [1.1.0] — 2026-04-21

### Added in 1.1.0

- **RF signal strength sensor** per shutter (`sensor.roleta_rf` etc.) —
  auto-created now that the shutter device category dispatches
  `NETATMO_CREATE_SENSOR`.
- **`available` state driven by `reachable`** — cover becomes `unavailable`
  in HA when the bridge reports the shutter offline. Stops automations from
  silently no-op'ing on a dead device.
- **`netatmo_bubendorff.set_shutters_batch` service** — moves N shutters in
  one Netatmo API call by grouping modules per home in a single `setstate`
  payload. Dramatically faster for "close all" scenes and lighter on the
  rate limit.
- **README section on `netatmo_event` bus events** — documents how to
  trigger automations from physical wall switches and the Netatmo app. The
  underlying webhook dispatch was always firing; only the docs + example
  were missing.

### Changed in 1.1.0

- `services.yaml` entity selectors now point at
  `integration: netatmo_bubendorff` (were still hardcoded to `netatmo`
  from the upstream fork).

## [1.0.0] — 2026-04-21

First clean release as an independent HACS integration.

### Added in 1.0.0

- **Jalousie mode** for Bubendorff shutters via `OPEN_TILT` / `CLOSE_TILT`
  cover commands (uses Netatmo API `target_position: -2`).
- `current_cover_tilt_position` attribute — reports 100 when shutter is in
  jalousie mode, 0 otherwise. Lets Lovelace cards show a "slats tilted"
  badge.
- Shutter position constants (`SHUTTER_POSITION_OPEN / CLOSED / STOP /
  PREFERRED`) in `const.py` — no more magic `-1` / `-2` numbers.
- Proper `manifest.json` with `version`, `issue_tracker`, single
  `codeowners`.
- HACS metadata: `hacs.json`, `info.md`, MIT `LICENSE`.

### Changed in 1.0.0

- **Domain** from `netatmo` → `netatmo_bubendorff`. Now installs side-by-side
  with the official integration (but you should only enable one at a time).
- Vendored `pyatmo` loader uses `__file__`-relative path instead of a
  hardcoded `custom_components/idiamant/...` string. Works regardless of
  mount location.
- **Removed `SET_POSITION` cover feature.** Bubendorff hardware only accepts
  4 discrete `target_position` values (0, 100, -1, -2) — exposing a 0-100
  slider was misleading.
- `is_closed` now reflects physical state (`current_position == 0`) instead
  of being set eagerly on every action. Fixes incorrect "closed" reporting
  after jalousie.

### Removed in 1.0.0

- Dead `async_set_cover_position` debug spam (`x = dir(self._cover)` on
  every call, 4× `_LOGGER.debug`).
- Commented-out polling while-loops in `async_open_cover` /
  `async_close_cover`.
- Duplicate `/idiamant/module.py` that shadowed the vendored `pyatmo`
  version and was never actually imported.
- Commented-out `async_stop_tilt` in `ShutterMixin`.

### Fixed in 1.0.0

- `async_close_tilt` now delegates to `POSITION_CLOSED` via the named
  constant — was `0` magic-literal before.
- Duplicated `"codeowners"` key in `manifest.json`.
- Typo `Healty` → `Healthy` in HomeKit models list.

## Unreleased / planned

- Faza 3 — submit upstream PRs to
  [cgtobi/pyatmo](https://github.com/cgtobi/pyatmo) (tilt methods) and
  [home-assistant/core](https://github.com/home-assistant/core)
  (OPEN_TILT / CLOSE_TILT on cover platform).
- Migrate to `pyatmo 9.x` (HA core current).
- Move vendored `pyatmo` out to a separate PyPI package
  `pyatmo-bubendorff`.
