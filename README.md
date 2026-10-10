# Home Assistant Integration - GoXLR Utility

[GoXLR Utility](https://github.com/GoXLR-on-Linux/goxlr-utility) integration for [Home Assistant](https://www.home-assistant.io/). Exposes live audio channel levels, physical faders, mute states, assignments, buttons and device lighting. You can bind each fader to a house light and synchronize brightness in both directions.

Requires Home Assistant **2025.3 or newer** and a GoXLR Utility daemon using the [documented WebSocket API](https://github.com/GoXLR-on-Linux/goxlr-utility/wiki/The-GoXLR-Utility-API). The integration uses Home Assistant's HTTP session and applies JSON Patch batches to the full daemon status.

> This integration does not connect to the official GoXLR application!

Be sure to check out the [GoXLR Utility](https://github.com/GoXLR-on-Linux/goxlr-utility) project for more information.

![Screenshot](https://github.com/timmo001/homeassistant-integration-goxlr-utility/assets/28114703/cb6f6dac-e571-45ce-8848-45c8449ed84c)

## Installation

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=timmo001&repository=homeassistant-integration-goxlr-utility&category=integration)

This integration is available in the [Home Assistant Community Store](https://hacs.xyz/).

## Setup and Configuration

- Enable `Allow UI network access` in GoXLR Utility settings.
- Add **GoXLR Utility** under **Settings → Devices & services → Add integration**.
- Enter the host of the computer running the daemon and its web port (default `14564`). `localhost` only works if the daemon runs on the Home Assistant host.

### Control house lights with the faders

1. Open **Settings → Devices & services → GoXLR Utility → Configure** (the options button).
2. Choose a dimmable `light` entity or light group for any of faders **A–D** (left to right). Leave unused faders blank. Each target must be different; clearing a target disables its mapping.
3. Move a fader to change the target's brightness. The bottom position turns the light off; moving up turns it on.
4. Change the light in Home Assistant to set the assigned GoXLR channel volume. On a full GoXLR the motorized fader follows; a GoXLR Mini has no motors, so its physical position cannot follow remote changes.

**Faders still control their assigned audio channels.** Light changes also change audio volume, including setting volume to zero when a light turns off. Use a spare channel if that suits your setup. Assign different audio channels to faders controlling different lights; faders on the same channel share one volume.

The light's current brightness wins when the integration starts, reconnects, or a fader is reassigned. This preserves the room's lighting and updates the new audio channel. Unavailable lights wait until they return. Mute remains a separate audio control and does not toggle the bound light.

Fader updates are limited to roughly one per 120 ms, with the latest position used for each update, including during continuous movement. Writes from Home Assistant suppress motor-position echoes for 1.5 seconds, then reconcile the final hardware position. Light service contexts and a short target-value guard prevent feedback loops. GoXLR's physical faders may slightly overshoot, so the final brightness can differ slightly from a requested value.

### Upgrading an existing installation

Replace `custom_components/goxlr_utility` with this version and restart Home Assistant, or update through your configured HACS repository. Existing entity registry entries are migrated to serial-based unique IDs while keeping their entity IDs. Configure the new light targets after upgrading. No light binding is enabled by default.

## Features

### Binary Sensors

- Button Pressed

### Media Players

Slider control (volume, muted)

Channel volume is reported at full precision (`0..1`). Mute controls follow the channel's current fader assignment after profile changes.

### Numbers, selects and switches

| Entity | State | Writable behavior |
| --- | --- | --- |
| Channel level | Integer `0..255` | Sets the named audio channel's volume |
| Fader A–D level | Integer `0..255` | Sets the fader's currently assigned channel |
| Fader A–D channel | Channel name | Reassigns the physical fader |
| Fader A–D mute | On/off | Sets the fader's configured mute state |

Fader level entities include `channel`, `fader`, `volume_percent`, `mute_state` and `mute_type` attributes. Channel levels include `channel` and `volume_percent`. These entities can also be used in your own automations; avoid additional two-way automations for targets already bound through the integration's options.

### Sensors

- Profile

### Lights

- Accent
- Buttons (Inactive, Active)
- Faders (Bottom, Top)

## Development and validation

Use Python 3.13 or newer. Home Assistant integration tests require Linux.

```sh
python -m pip install -e '.[test,ha-test,dev]'
python -m pytest -q
ruff check custom_components tests
ruff format --check custom_components tests
```

On Windows, install `.[test,dev]` and run `python -m pytest tests/unit -q`. The portable tests use a real local WebSocket server for protocol coverage and mock Home Assistant boundaries for light synchronization. GitHub Actions runs the complete suite on Linux with Python 3.13 and 3.14; HACS and Hassfest validation remain enabled.

Before using this on hardware, verify fader movement updates a number entity, a Home Assistant number change updates GoXLR, both directions of brightness control work, profile reassignment follows the new channel, and unplugging/restarting the daemon marks entities unavailable then recovers.
