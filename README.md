# Netatmo (Bubendorff jalousie) — Home Assistant integration

A patched fork of the official [Home Assistant Netatmo](https://www.home-assistant.io/integrations/netatmo) integration that adds **jalousie / tilted slats control** for Bubendorff roller shutters (iDiamant with Netatmo).

The official integration only exposes `open / close / stop`. Bubendorff shutters with adjustable slats also support a **jalousie position** (slats tilted so light passes through), mapped in Netatmo's API to `target_position: -2`. This integration exposes it via the standard HA cover `OPEN_TILT` / `CLOSE_TILT` commands.

---

## What's different from the official integration

| Feature | Official `netatmo` | This fork |
| --- | --- | --- |
| Open / close / stop | ✅ | ✅ |
| Position 0-100 slider | ✅ (but hardware ignores it) | ❌ (removed — misleading) |
| Open tilt (jalousie) | ❌ | ✅ |
| Close tilt (slats flat) | ❌ | ✅ |
| Other Netatmo devices (camera, thermostat, lights, etc.) | ✅ | ✅ |

### Why no 0-100 slider?

Bubendorff shutters only honour **4 discrete `target_position` values**:

- `100` — fully open
- `0` — fully closed
- `-1` — stop current movement (write-only)
- `-2` — jalousie / preferred slat position

Values like `30%` or `75%` are rejected by the hardware. Exposing a 0-100 slider in HA created a false UX — users moved it and nothing happened. This fork removes the slider entirely.

---

## Installation

### Via HACS (recommended)

1. HACS → Integrations → ⋮ → **Custom repositories**
2. Add `https://github.com/LukaszZochowski/ha-netatmo-bubendorff` as type **Integration**
3. Install **Netatmo (Bubendorff jalousie)**
4. Restart Home Assistant

### Manual

1. Copy `custom_components/netatmo_bubendorff/` into your `/config/custom_components/`
2. Restart Home Assistant

### Configure

1. Settings → Devices & Services → **Add integration** → search **Netatmo (Bubendorff jalousie)**
2. Complete the OAuth flow with your Netatmo account

---

## ⚠️ Coexistence with the official Netatmo integration

This uses a **different domain** (`netatmo_bubendorff`) so Home Assistant will load both if you also have the official `netatmo` integration configured. **Don't.**

- Both register the **same webhook URL** with Netatmo's cloud — the last one wins and the other stops receiving push updates
- Both pull state for the same home — double API calls, possible rate-limit hits

**Recommended:** remove the official Netatmo integration *before* configuring this one. All your devices (cameras, thermostats, lights, switches, shutters) will show up under the new integration.

---

## Lovelace example

```yaml
type: tile
entity: cover.roleta
name: Roleta salon
icon: mdi:blinds
features:
  - type: cover-open-close     # open / stop / close
  - type: cover-tilt           # open tilt / close tilt (jalousie)
```

Or the original button-card pattern still works — it calls `cover.open_cover_tilt` which this integration maps to `target_position: -2`.

---

## How the jalousie integration works internally

```
HA command                 pyatmo method         Netatmo API target_position
-----------                -------------         ---------------------------
cover.open_cover           async_open()          100
cover.close_cover          async_close()           0
cover.stop_cover           async_stop()           -1
cover.open_cover_tilt      async_open_tilt()      -2   ← added by this fork
cover.close_cover_tilt     async_close_tilt()      0
```

The vendored copy of pyatmo 7.5.0 (in `custom_components/netatmo_bubendorff/pyatmo/`) has the added `async_open_tilt` / `async_close_tilt` methods on `ShutterMixin`. The integration's `__init__.py` registers that vendored copy in `sys.modules['pyatmo']` before anything else imports it, so the same `import pyatmo` statements that the rest of the integration uses resolve to the patched version.

---

## Roadmap

- **Faza 3** — submit upstream PRs:
  - [cgtobi/pyatmo](https://github.com/cgtobi/pyatmo) — add tilt methods to `ShutterMixin` (small, focused change)
  - [home-assistant/core](https://github.com/home-assistant/core) — expose `OPEN_TILT`/`CLOSE_TILT` on `netatmo/cover.py` (requires upstream pyatmo merge first)
- Migrate from vendored `pyatmo 7.5.0` to `pyatmo 9.x` (current HA core version)
- Separate the pyatmo fork into its own repo `pyatmo-bubendorff` on PyPI

---

## Credits

- Upstream [home-assistant/core](https://github.com/home-assistant/core) Netatmo integration (Apache 2.0)
- Upstream [cgtobi/pyatmo](https://github.com/cgtobi/pyatmo) (MIT)
- Bubendorff jalousie behaviour discovered and documented by the HA community:
  [WTH: update netatmo integration for use with bubendorff shutters](https://community.home-assistant.io/t/wth-update-netatmo-integration-for-use-with-bubendorff-shutters/814580)

## License

MIT — see [LICENSE](LICENSE). Upstream portions remain under their original Apache 2.0.
