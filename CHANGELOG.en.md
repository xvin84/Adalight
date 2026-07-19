# Changelog

Format inspired by [Keep a Changelog](https://keepachangelog.com/);
versions follow [SemVer](https://semver.org/). Full diffs are in the
[GitHub releases](https://github.com/xvin84/Adalight/releases).

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
