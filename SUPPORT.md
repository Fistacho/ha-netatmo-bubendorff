# Support

This integration is a volunteer-maintained fork. There is no commercial support.

## Where to get help (in order of preference)

1. **[README troubleshooting table](README.md#troubleshooting)** — most common first-install issues.
2. **[GitHub Discussions](https://github.com/Fistacho/ha-netatmo-bubendorff/discussions)** — questions, tips, configuration examples.
3. **[HA community Bubendorff thread](https://community.home-assistant.io/t/bubendorff-idiamant-legrand-netatmo/265064)** — wider audience, users with similar setups.
4. **[GitHub issues](https://github.com/Fistacho/ha-netatmo-bubendorff/issues)** — only for reproducible bugs and concrete feature requests. Use the issue templates.

## What this integration cannot do

These are hard Netatmo API / Bubendorff hardware limits, not missing features:

- **Continuous 0–100 % position.** Shutters only accept discrete `target_position` values: `0` (closed), `100` (open), `-1` (stop), `-2` (jalousie).
- **Multiple tilt angles.** There is exactly one preset jalousie position; the hardware does not expose intermediate slat angles.
- **Obstacle detection readback.** The shutter stops on obstacles in firmware, but the API does not report the obstacle event.
- **Wind / rain automations.** Those require dedicated Bubendorff sensors; if yours don't have them, software can't add them.

Please don't open issues for the above — they won't be fixable here.

## When to file an issue

- OAuth fails / "invalid redirect"
- Shutter entity stays `unavailable` despite working in the Netatmo app
- `cover.open_cover_tilt` returns OK but physically nothing happens
- `sensor.*_radio` / `sensor.*_reachability` missing despite being enabled
- Integration crashes after HA update (include HA version and full stack trace)
