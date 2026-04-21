# Netatmo (Bubendorff Fistacho)

Fork of the official Home Assistant Netatmo integration that adds
**jalousie / tilted-slats control** for Bubendorff roller shutters
(`target_position: -2`) — a mode the official integration does not expose.

## What's different

| Action | Official `netatmo` | This integration (`netatmo_bubendorff`) |
| --- | --- | --- |
| Open / Close / Stop | ✅ | ✅ |
| Jalousie tilt (slats mode) | ❌ | ✅ |
| Continuous 0-100 slider | ✅ (misleading — hardware ignores it) | 🚫 intentionally removed |

Bubendorff shutters only accept **4 discrete states**: open (100), closed (0),
stop (-1), and jalousie/preferred (-2). This integration exposes exactly those.

## Important

Uses a different domain (`netatmo_bubendorff`) so it installs side-by-side
with the official integration — **but you should only enable one at a time**.
Both register the same webhook with Netatmo cloud; running both breaks push
updates. Remove the official integration before configuring this one.

Built on a vendored fork of `pyatmo==7.5.0` with slat-tilt patches applied.
