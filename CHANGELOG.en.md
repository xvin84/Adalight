# Changelog

Format inspired by [Keep a Changelog](https://keepachangelog.com/);
versions follow [SemVer](https://semver.org/). Full diffs are in the
[GitHub releases](https://github.com/xvin84/Adalight/releases).

## [0.24.2] — 2026-08-02

The monitor picker broke itself: "Monitor 'HDMI-A-1 (1920x1080)' not found.
Available: eDP-1, HDMI-A-1". The list label ended up in `output` while capture
needs the bare name — deleting " (1920x1080)" by hand really did help.

- Cause: when the monitor list was rebuilt (refresh button, re-applying the
  settings) the field's text was remembered instead of the monitor name. The
  field is editable, so the text went straight back in, the selected item was
  "lost", and the full label got saved into the config.
- A list's value now always comes from the item's data, not from its caption; a
  name typed by hand is still kept as is.
- An already broken config heals itself: the label is recognized both when
  loading the UI and in capture itself — no manual `config.json` editing, `--live`
  without the GUI included.

## [0.24.1] — 2026-08-02

Wayland capture did not work in the built binary: "Could not get the monitor
list via hyprctl … returned non-zero exit status 1". Running from source worked
fine, so the bug stayed invisible during development.

- Cause: PyInstaller puts its temporary folder — with libraries from the build
  machine (Ubuntu) — into `LD_LIBRARY_PATH`, and child processes inherit it, so
  `hyprctl`, `grim` and `wf-recorder` loaded a foreign `libstdc++` and died
  before doing anything ("version GLIBCXX_3.4.35 not found"). On distributions
  with a newer toolchain (Arch and others) capture never started.
- External programs now run through `adalight.subproc`, with the environment as
  it was before the bundle started (`hyprctl`, `grim`, `wf-recorder`, `pkexec`
  for the udev rule, `dbus-monitor` for notification flashes).
- Errors became explainable: the tool's own output is included — "returned
  non-zero exit status 1" became "hyprctl monitors: code 1, hyprctl: … version
  GLIBCXX_3.4.35 not found". Same for `wf-recorder`: its stderr is no longer
  discarded but shown as the reason for the crash.
- Layout: long list items ("Perimeter spectrum", a port path, a monitor name)
  stretched the settings column past its maximum and the right edge of the form
  slid under the preview — on multi-monitor systems the "refresh monitors"
  button became unreachable.
- The brightness schedule explanation moved from the checkbox label into a
  tooltip; a long plugin name in the manager is elided instead of growing a
  scrollbar.
- README screenshots updated: English ones for `README.md`, Russian ones for
  `README.ru.md`.

## [0.24.0] — 2026-07-25

Output performance and port handling. The app was pushing ~25 fps to the strip
while the link could do 137; profiling showed nearly the whole frame was spent
averaging zones over the full frame, with the loop capped by `target_fps: 30`.

- Zone averaging now uses a fixed sample grid (16×16 per zone, one vectorized
  numpy call per frame): ~35 ms on a 1080p frame became ~1.5 ms — the cost no
  longer depends on the screen resolution.
- Default `target_fps` raised from 30 to 120: the ceiling is now set by capture
  and port speed, not by an app timer. A saved config keeps the old value —
  raise "Target FPS" in the settings.
- The "sides" and "running dot" tests send frames at the full pipeline rate and
  report fps — a built-in throughput measurement without external scripts (the
  dot still moves at an eye-friendly pace).
- A real fps counter (averaged over a second) in every mode, in the status card
  and in the tray icon tooltip.
- The preview refreshes at its own rate (15 fps by default, configurable in
  "Appearance") — UI repaints no longer get in the way of the output loop.
- Built-in pipeline profiler: `ADALIGHT_PROFILE=1` prints the per-section frame
  breakdown (capture / frame / port / preview / wait) to stderr.
- Unplugging the board no longer kills the backlight: the engine switches to
  "Waiting for the board…", reopens the port every 2 seconds and resumes on its
  own after replugging (`device.lost` / `device.restored` events for plugins too).
- On Linux the port is remembered by its stable `/dev/serial/by-id/…` path,
  which is tied to the chip and survives renumbering (`ttyUSB0` → `ttyUSB1`).
  If the port is still gone and exactly one board is present — it is used.
- Chips are told apart by the VID:PID pair (CH340 vs CH9102 are no longer
  confused); ports with unknown chips are not hidden but shown in an
  "other ports" group.
- Release builds are now verified by running them: the built binary must start
  (and, on Linux, bring up its window) or the release is not published. The old
  check only made sure the file existed.
- The permission error (`errno 13`) no longer looks like "board not found": a
  dedicated dialog explains the device is visible and offers to install the
  udev rule with one button (via pkexec) or show the manual command. The rule
  (`packaging/99-adalight.rules`, `TAG+="uaccess"` — access via systemd-logind,
  no groups or re-login) ships with the app and the release.

## [0.23.0] — 2026-07-21

- Fixed: on Windows the built-in mods (lamp effects, music, screen capture,
  transports) were not found — the app reported "plugin not found" and did not
  really work. The cause was loading mods dynamically by string name, which the
  `.exe` builder (PyInstaller) did not see and did not bundle. Mods are now
  imported statically and always end up in the build. Linux was unaffected
  (running from source).

## [0.22.0] — 2026-07-21

- Smart port picker: by default the list shows only boards (Arduino/ESP) and USB
  devices — with friendly labels ("COM5 — Arduino Uno"); noisy system ports
  (ttyS*) are hidden. Recognition is by the USB descriptor (VID/PID), like "Get
  Board Info" in the Arduino IDE — the board is never opened or probed.
- A "Show all ports" checkbox — for a board with an exotic chip that isn't listed.
- Beta marker in the window title and the About dialog.
- Board firmware added to the repo (firmware/) — a reference Adalight sketch by
  AlexGyver (alexgyver.ru/arduino_ambilight), included with attribution.
- Richer GitHub release notes: what's new, a description and the features,
  English first, then Russian.

## [0.21.0] — 2026-07-19

- "Everything is a mod", stage 5 (migration complete): an event bus. Mods and
  plugins can react to the app's state and to each other without depending on
  their internals.
- A plugin can subscribe to events (`api.on`) and broadcast its own (`api.emit`):
  lighting start/stop, frame, notification, available update.
- An event-driven plugin example — "Notification logger" in `examples/plugins`.
- CI fix: Qt system libraries are installed on the runner (tests that touch the
  UI run on CI again).

## [0.20.0] — 2026-07-19

- "Everything is a mod", stage 4: the ways colors reach the strip (serial over
  USB and WLED over Wi-Fi) became a built-in "Transports" mod — visible and
  manageable in the plugin manager.
- A plugin can add its own transport (`register_transport`).
- The core (`device.py`) became a thin facade: the color pipeline stays in the
  core while a registry transport delivers the bytes; the transport picker in
  the UI is built from the registry, connection fields show per transport type.

## [0.19.0] — 2026-07-19

- "Everything is a mod", stage 3: screen capture sources became a built-in
  "Screen capture" mod — visible and manageable in the plugin manager.
- A plugin can add its own capture source.
- Headless mode (CLI) now also loads the built-in mods — effects and capture
  work without the GUI too.

## [0.18.0] — 2026-07-19

- "Everything is a mod", stage 2: the "Music" mode effects became a built-in
  "Music" mod — visible and manageable in the plugin manager.
- Plugins can add their own music effects the same way the built-in ones do.

## [0.17.0] — 2026-07-19

- Sleep mode: on a static picture the strip no longer goes dark — the app keeps
  the board awake (keep-alive). Previously the board turned the strip off itself
  after ~10 seconds without changes.
- With sleep mode enabled the strip instead turns off when idle — the time is
  set by a slider (Brightness → Sleep mode).

## [0.16.0] — 2026-07-19

- "Everything is a mod", stage 1: the "Lamp" mode effects became a built-in
  "Lamp effects" mod — visible and manageable in the plugin manager.
- Mods can be enabled and disabled; disabling actually removes the capability
  (with a warning when disabling base mods).
- Plugins add their own effects the same way the built-in ones do.

## [0.15.0] — 2026-07-19

- Plugins can add their own lamp effects — they appear in the effect list next
  to the built-in ones ("everything is a mod"); example —
  examples/plugins/plasma_effect.py.
- Built-in lamp effects moved to a shared effect registry.
- The "What's new" dialog, when updating from a version before it existed, now
  shows the full history up to the current version instead of only the current one.

## [0.14.0] — 2026-07-19

- "What's new" dialog after an update: the list of changes (across several
  versions too) in the interface language, with a language switch right in
  the window.
- Plugins from the catalog install without a restart; installed ones are
  shown greyed out with an "Installed" mark.
- Languages appear in the manager's "Installed" list — "Use as interface
  language"; English uses the same `create_locale()` contract as locale plugins.
- Community languages install from the catalog and appear in the list at once.
- Fixed the notification settings layout (a clipped hint, the position picker
  overlapping rows with a wide font).

## [0.13.0] — 2026-07-19

- Interface localization: Russian and English (System → Language); the language
  change applies after a restart.
- Languages are plugins: add your own translation as a file with
  `create_locale()` in the plugins folder; template — examples/locales/en.py.
- English is built in and available immediately, without installing.

## [0.12.0] — 2026-07-18

- Plugin manager in a separate window: "Installed" (enable/disable, settings,
  delete) and "Catalog" (search, install). The sidebar tab is a summary.
- Plugins declare a `settings_schema` — the manager builds the settings form
  itself, no GUI code (a first step toward "everything is a plugin").
- The "ripple" notification flash: a drop with a wave spreading along the strip
  (choose the style — "ripple" or "blob").
- The flash position is set by dragging along the screen edge (perimeter only).
- Hint in settings: only system notifications are caught on Windows.
- "Report a bug" / "Suggest an idea" buttons in "System" open a prefilled
  GitHub issue with diagnostics.

## [0.11.0] — 2026-07-17

- The notification flash position is set by dragging a spot on a screen diagram
  (with an instant test flash on the strip when released).
- Plugin catalog: official and community, one-click install.
- "Any app" mode: a flash in the color of the sending app's icon.

## [0.10.0] — 2026-07-17

- Plugin docs (docs/PLUGINS.md) and a working template
  (examples/plugins/break_reminder.py); an "Open plugins folder" button.
- Lamp effects: Comet, Aurora, Starry sky.
- Music effects: Bass waves, Beat flashes.

## [0.9.x] — 2026-07-17

- Plugin system: your own .py files with `create_plugin()`, error isolation,
  settings in the shared config.
- Built-in "Notification flashes" plugin: Telegram — blue, Discord — purple,
  over any mode.
- WLED-UDP transport (beta): an ESP strip over Wi-Fi, DRGB/DNRGB.
- Silent auto-update at startup (optional).
- Quick lamp effects from the tray menu.

## [0.8.x] — 2026-07-17

- Vertical sidebar with SVG icons, a status card, toasts, friendly errors,
  first-run wizard, micro-animations.
- Clickable preview: clicking an LED flashes it on the strip.
- "Fireplace" effect with settings (height, intensity, sparks).
- Tray notifications; a save-current-profile button with an indicator.
- Fixed the auto-update race and the PyInstaller environment leak
  ("Python312.dll in Temp"), single instance, Windows autostart.

## [0.7.0] — 2026-07-17

- Built-in presets 🎬 Movie / 🎮 Game / 💼 Work on top of the hardware settings.
- QSS design system: dark and light themes from the same tokens.

## [0.6.0] — 2026-07-16

- Settings profiles switchable from the window and tray; JSON import/export.
- White balance (R/G/B multipliers); the window remembers geometry and tab.

## [0.5.x] — 2026-07-16

- Tabbed UI; a live screen preview with color-sampling zones.
- Dark/light/system theme; auto-update from GitHub Releases; a Windows
  installer (Inno Setup); single instance.
- Flexible gradient (2–8 points); static rainbow; music sensitivity; app icon.

## [0.4.0] — 2026-07-16

- "Lamp" (solid/gradient/rainbow/breathing) and "Music" (spectrum, bass pulse)
  modes over loopback audio.
- Night mode; color temperature; shadow threshold; update check; a Linux
  binary in releases.

## [0.3.x] — 2026-07-16

- Live settings without resetting the board; auto-apply after 5 s.
- Brightness schedule (overnight ranges); adaptive brightness.
- Launch on login; the bettercam backend (a dxcam bug workaround).

## [0.2.0] — 2026-07-16

- Rewritten as a package with a GUI (PySide6): port, per-side LEDs, angle,
  direction, channel order; tray; preview.
- Windows (DXGI) and Wayland capture; CI and tagged release builds.
