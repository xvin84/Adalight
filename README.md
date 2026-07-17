# Adalight

**English** | [Русский](README.ru.md)

Screen-edge ambient lighting (ambilight) for an LED strip behind your monitor:
the app captures the screen, averages the colors along the edges and streams
them to an Arduino/ESP over the classic **Adalight** serial protocol.

Runs on **Windows** (DXGI Desktop Duplication via `dxcam`, `mss` fallback) and
**Linux/Wayland** (Hyprland/wlroots: `wf-recorder`, `grim` fallback), with a
Qt (PySide6) GUI: every setting in one window, a live preview of the LED
layout, and a tray icon so the lighting keeps running with the window closed.

## Features

- Serial port with autodetection, baud rate, **channel order** (RGB/GRB/BGR/…) —
  WS2812 strips usually expect GRB.
- LED counts per side, start corner, strip direction (cw/ccw), X/Y mirroring.
- Monitor selection, target FPS, gamma / brightness / saturation / smoothing.
- **Live settings**: image parameters, schedule and adaptive brightness apply
  instantly without restarting (and without resetting the board); layout/port
  changes auto-apply 5 seconds after the last edit.
- **Brightness schedule**: time ranges with their own brightness
  (e.g. 08:00–20:00 → 0.9, 20:00–00:00 → 0.5), overnight ranges supported,
  the default brightness applies outside all ranges.
- **Adaptive brightness**: dims the strip on dark scenes and ramps it up on
  bright ones, with min/max bounds and reaction speed.
- **Autostart**: launch on login minimized to tray with lighting on
  (Windows registry / XDG autostart).
- **Lamp mode**: solid color / gradient / rainbows / breathing / **fireplace**
  (a hearth with sparks) / **comet** / **aurora** / **starry sky** — the strip
  works without screen capture.
- **Tray notifications**: lighting on/off (when the window is hidden) and new
  version releases (checked every 30 minutes); can be disabled in System.
- **Music mode**: system loopback audio drives the LEDs — a perimeter spectrum,
  a bass-driven pulse, **bass waves** and **beat flashes**, with adjustable
  sensitivity.
- **Night mode**: one button makes everything warmer (3400K), dimmer (×0.6)
  and smoother — on top of your current settings.
- **Color pipeline**: color temperature (white balance) and a shadow noise
  cut-off so dark scenes don't make the LEDs glow with noise.
- **Auto-update**: the app checks GitHub Releases, downloads the new binary and
  restarts itself — no manual downloading; with "update automatically" enabled
  new versions install silently at startup.
- **Plugins**: an extension system — drop .py files with `create_plugin()` into
  `<config>/plugins/`; the API provides strip flashes and tray notifications.
  Docs and a template: [docs/PLUGINS.md](docs/PLUGINS.md) (ru),
  [examples/plugins/break_reminder.py](examples/plugins/break_reminder.py).
- **Notification flashes** (built-in plugin): Telegram — a blue flash,
  Discord — purple, at any point of the perimeter, over any mode.
  Windows requires notification-access permission.
- **WLED transport (beta)**: an ESP strip running WLED over Wi-Fi
  (UDP DRGB/DNRGB, port 21324) — no wire, no baud-rate cap.
- **Modern UI**: sidebar navigation with SVG icons, a status card
  (state · backend · fps), live preview with the captured screen and sampling
  zones — **clicking an LED in the preview flashes it on the real strip**;
  dark / light / system theme.
- **First-run wizard**: port → LEDs → side check in three steps
  (also available anytime: System → "Setup wizard…").
- **Windows installer** (`Adalight-Setup.exe`): installs per-user (no admin),
  start-menu/desktop shortcuts and optional autostart.
- Single-instance: launching the app again just raises the running window.
- **Settings profiles**: built-in presets 🎬 Movie / 🎮 Game / 💼 Work (layered
  on top of your hardware settings) plus your own saved profiles; one-click
  switching from the window or the tray menu.
- **White balance**: per-channel R/G/B multipliers to calibrate the strip.
- **Import/export settings** to a JSON file — backup and transfer between machines.
- Calibration test modes: color-per-side fill and a running-dot chase.
- Headless CLI for autostart setups; GUI and CLI share the same JSON config
  (`%APPDATA%\adalight\config.json` on Windows, `~/.config/adalight/` on Linux).

## If FPS is low

- **Baud rate is a hard cap**: at 115200 the wire fits ~11.5 KB/s, i.e. ~76 fps
  for 48 LEDs but only ~13 fps for 300. Raise the baud rate both in the app and
  in your firmware (ESP boards handle 921600, classic Arduino 500000).
- The status bar shows which capture backend is actually running; on Windows
  the fast path is `bettercam` (a maintained dxcam fork), then `dxcam`, and if
  both fall back to `mss` the reason is shown. The `mss` backend captures only
  the edge bands rather than the full screen.

## Download

Grab a binary from the [latest release](https://github.com/xvin84/Adalight/releases) —
no Python required:

- **Windows**: `Adalight-Setup.exe` (installer, recommended) or portable `Adalight.exe`
- **Linux**: `Adalight-linux-x86_64` (then `chmod +x Adalight-linux-x86_64`;
  Wayland capture additionally needs `wf-recorder` installed)

## Run from source

Requires [uv](https://docs.astral.sh/uv/):

```bash
uv sync

# GUI
uv run main.py

# headless & service modes
uv run main.py --live
uv run main.py --sides          # test: top=red, right=green, bottom=blue, left=yellow
uv run main.py --chase          # test: running dot
uv run main.py --off            # turn the strip off
uv run main.py --list-monitors
uv run main.py --list-ports
```

## Calibration

1. Start **“Test: sides”**: the top edge must light up red, right green,
   bottom blue, left yellow. If sides are mixed up, adjust the start corner,
   direction or mirroring — the preview in the window mirrors your changes live.
2. If the *hues* are wrong (red shows as green etc.), change the channel order —
   WS2812 is usually GRB.
3. **“Test: chase”** runs a single bright dot along the strip to verify the
   exact LED order; the first LED is marked with a ring in the preview.

## Tech map

| Layer | Module | What it does |
|---|---|---|
| Capture | `capture/` | Windows: bettercam → dxcam (DXGI, `grab()` polling), mss fallback; Wayland: wf-recorder / grim; mss grabs edge bands only |
| Geometry | `geometry.py` | LED layout around the perimeter, color-sampling zones |
| Engine | `engine.py` | Capture→process→send loop (Qt-free); live/lamp/music/test modes; schedule, adaptive and night brightness; live settings |
| Effects | `effects.py`, `audio.py` | Lamp (solid/gradient/rainbows/breathing), music (FFT + AGC over loopback audio via soundcard) |
| Device | `device.py` | Adalight protocol, channel order, LUT gamma, color temperature, shadow cut-off |
| GUI | `gui/` | PySide6: tabs, live preview with zones, tray, themes, auto-update |
| Infra | `updates.py`, `autostart.py`, CI | GitHub Releases (auto-update), autostart (registry/XDG), exe+installer+linux binary built on `v*` tags |

## Roadmap

- [x] **Settings profiles** ("Movie", "Game", "Work") with quick switching from the tray
- [x] **WLED-UDP transport** — ESP strip over Wi-Fi, no wire and no baud-rate cap (beta)
- [x] **Notification integrations** — a color flash: Telegram blue, Discord purple
- [x] **Plugin system** — custom effects and integrations without rebuilding (first API)
- [x] **More music effects** (bass waves, beat flashes)
- [ ] **Multi-monitor** — independent strip segments across screens
- [ ] **xdg-desktop-portal / PipeWire capture** — GNOME and KDE support on Wayland
- [ ] **English UI localization**
- [ ] **macOS build** (a tester with a Mac is welcome)

Got an idea? [Open an issue](https://github.com/xvin84/Adalight/issues).

## How it works

- Header `"Ada" + count_hi + count_lo + (hi^lo^0x55)`, then 3 bytes per LED —
  the standard Adalight protocol, compatible with common Arduino sketches.
- Edge zones are precomputed per LED from the layout; each frame is averaged
  per zone, exponentially smoothed and gamma-corrected through a precomputed
  LUT (no per-frame `pow`).
- The capture/processing loop is Qt-free (`adalight/engine.py`); the GUI runs
  it in a background thread, the CLI drives it directly.

```
adalight/
  config.py        # settings dataclass + JSON load/save
  geometry.py      # LED layout and capture zones
  device.py        # Adalight protocol, LUT gamma, channel order
  engine.py        # capture -> process -> send loop (no Qt)
  capture/         # backends: dxcam (Windows), mss, wf-recorder, grim
  cli.py           # headless modes
  gui/             # PySide6: main window, preview, tray
main.py            # entry point: GUI without args, CLI otherwise
```

## Releases

- **CI** (`.github/workflows/ci.yml`): ruff + pytest on every push/PR.
- **Release** (`.github/workflows/release.yml`): pushing a `v*` tag builds
  `Adalight.exe` with PyInstaller on a Windows runner and publishes a GitHub
  Release. The tag must match the version in `pyproject.toml`.

## License

[MIT](LICENSE)
