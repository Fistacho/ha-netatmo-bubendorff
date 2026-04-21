# Changelog

All notable changes to this project are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [1.0.0] — 2026-04-21

First clean release as an independent HACS integration.

### Added
- **Jalousie mode** for Bubendorff shutters via `OPEN_TILT` / `CLOSE_TILT`
  cover commands (uses Netatmo API `target_position: -2`).
- `current_cover_tilt_position` attribute — reports 100 when shutter is in
  jalousie mode, 0 otherwise. Lets Lovelace cards show a "slats tilted" badge.
- Shutter position constants (`SHUTTER_POSITION_OPEN / CLOSED / STOP / PREFERRED`)
  in `const.py` — no more magic `-1` / `-2` numbers.
- Proper `manifest.json` with `version`, `issue_tracker`, single `codeowners`.
- HACS metadata: `hacs.json`, `info.md`, MIT `LICENSE`.

### Changed
- **Domain** from `netatmo` → `netatmo_bubendorff`. Now installs side-by-side
  with the official integration (but you should only enable one at a time).
- Vendored `pyatmo` loader uses `__file__`-relative path instead of a hardcoded
  `custom_components/idiamant/...` string. Works regardless of mount location.
- **Removed `SET_POSITION` cover feature.** Bubendorff hardware only accepts
  4 discrete `target_position` values (0, 100, -1, -2) — exposing a 0-100
  slider was misleading.
- `is_closed` now reflects physical state (`current_position == 0`) instead
  of being set eagerly on every action. Fixes incorrect "closed" reporting
  after jalousie.

### Removed
- Dead `async_set_cover_position` debug spam (`x = dir(self._cover)` on every
  call, 4× `_LOGGER.debug`).
- Commented-out polling while-loops in `async_open_cover` / `async_close_cover`.
- Duplicate `/idiamant/module.py` that shadowed the vendored `pyatmo` version
  and was never actually imported.
- Commented-out `async_stop_tilt` in `ShutterMixin`.

### Fixed
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
