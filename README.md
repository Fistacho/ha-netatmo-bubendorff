# Netatmo (Bubendorff Fistacho) — Home Assistant integration

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
2. Add `https://github.com/Fistacho/ha-netatmo-bubendorff` as type **Integration**
3. Install **Netatmo (Bubendorff Fistacho)**
4. Restart Home Assistant

### Manual

1. Copy `custom_components/netatmo_bubendorff/` into your `/config/custom_components/`
2. Restart Home Assistant

### Configure

OAuth flow is identical to the official Netatmo integration. The full steps:

#### 1. Create (or reuse) a Netatmo developer app

1. Go to **<https://dev.netatmo.com/apps>** and sign in with your normal
   Netatmo account (same one as in the mobile app).
2. If you already created an app for the official Netatmo / iDiamant
   integration — reuse it. **The same Client ID / Secret works here.**
3. Otherwise click **Create** and fill:
   - **App name:** anything, e.g. `Home Assistant`
   - **Description:** anything
   - **Data Protection Officer name + email:** your own
   - **Company:** Private
4. On the app page, verify the **Redirect URI** contains:

   ```text
   https://my.home-assistant.io/redirect/oauth
   ```

   Add it if missing — OAuth will fail with "invalid redirect" otherwise.
   Click **Save**.
5. Note your **Client ID** and **Client Secret** (click the 👁 icon to
   reveal the secret) — you'll paste them into HA in a moment.

#### 2. Add credentials to Home Assistant

Two entry points, same result:

**Option A — via the "Enter application credentials" dialog** (shown
automatically when you first add the integration):

- **Name:** anything, e.g. `Netatmo Bubendorff`
- **OAuth Client ID:** *(paste from dev.netatmo.com)*
- **OAuth Client Secret:** *(paste from dev.netatmo.com)*
- Click **Add**

**Option B — pre-configure via Settings:**

- **Settings → Devices & Services → ⋮ (top right) → Application Credentials**
- **Add application credential**
- Choose integration: **Netatmo (Bubendorff Fistacho)**
- Fill the same fields as above

#### 3. Add the integration

1. **Settings → Devices & Services → Add integration** → search
   **Netatmo (Bubendorff Fistacho)**
2. HA opens Netatmo's OAuth login page → click **YES, I ACCEPT**
3. You're redirected back to HA → integration loads → devices appear
   (shutters, cameras, thermostats, lights — all your Netatmo devices)

#### Troubleshooting

| Symptom | Cause | Fix |
| --- | --- | --- |
| "Invalid redirect URI" | Redirect URI missing in Netatmo app | Step 1.4 — add the URI and Save |
| Loops back to login | Netatmo session cache | Log out at dev.netatmo.com, retry |
| "Integration not found" | HACS not restarted | Restart HA after HACS install |
| No shutters visible | Devices not in the Netatmo home | Check Netatmo mobile app — confirm Bubendorff is paired |
| `update.*_update` shows version but no entities | Config entry needs reload | **Settings → Devices & Services → Netatmo (Bubendorff Fistacho) → ⋮ → Reload** |

---

## ⚠️ Coexistence with the official Netatmo integration

This uses a **different domain** (`netatmo_bubendorff`) so Home Assistant will load both if you also have the official `netatmo` integration configured. **Don't.**

- Both register the **same webhook URL** with Netatmo's cloud — the last one wins and the other stops receiving push updates
- Both pull state for the same home — double API calls, possible rate-limit hits

**Recommended:** remove the official Netatmo integration *before* configuring this one. All your devices (cameras, thermostats, lights, switches, shutters) will show up under the new integration.

---

## Services

### `netatmo_bubendorff.set_shutters_batch`

Move multiple shutters in a **single Netatmo API call**. Much faster than
firing N separate `cover.*` services — and friendlier to the account-level
rate limit (important for "close all" automations at sunset).

```yaml
service: netatmo_bubendorff.set_shutters_batch
data:
  entity_id:
    - cover.roleta
    - cover.roleta_2
    - cover.roleta_3
    - cover.roleta_4
  target_position: "0"   # 100=open, 0=closed, -1=stop, -2=jalousie
```

Mixed targets (different positions per shutter) are not supported in one
call — call the service once per target group.

---

## Physical button / app events

Every webhook push from Netatmo cloud fires the `netatmo_event` event on the
HA bus, including shutter state changes triggered by the **physical wall
switch** or the official Netatmo mobile app. You can trigger automations
directly from those events.

Debug what your home sends:

```yaml
# Dev Tools → Events → listen to: netatmo_event
```

Example automation — react when someone opens roleta manually:

```yaml
- alias: "Roleta salon opened manually — turn on lamp"
  trigger:
    platform: event
    event_type: netatmo_event
  condition:
    - "{{ trigger.event.data.device_id == '<device_id_of_your_shutter>' }}"
    - "{{ trigger.event.data.data.push_type is defined }}"
  action:
    - service: light.turn_on
      target:
        entity_id: light.salon
```

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

```text
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
