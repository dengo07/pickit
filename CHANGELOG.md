# Changelog

All notable changes to this project are documented here.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [1.1.1] - 2026-09-25

### Fixed
- The command approval dialog showed commands in a serif math font on systems where the generic `monospace` font resolves oddly (for example "DejaVu Math TeX Gyre" on Linux Mint). It now asks for common monospace fonts by name.

### Changed
- New app icon: a charcoal tile with three miniature widgets (an amber ring gauge with a spark at its center, a graph tile and a progress bar), replacing the purple-pink gradient.
- The widget preview area in the Pickit window uses a neutral slate background instead of a purple-grey one.
- Refreshed the README and software-center screenshot.

## [1.1.0] - 2026-09-24

### Added
- **Native engine.** Widgets can now be drawn with native GTK instead of WebKit: the AI describes them as a component tree (cards, rows, columns, labels, icons, images, progress bars, rings, sparklines, buttons) with data bindings, templates, filters and conditions. Five typical widgets use about 25 MB in total (24 MB from source, 27 MB in the Flatpak), compared with 180–244 MB for four HTML widgets, and a native-only desktop never loads WebKit.
- The AI picks the engine automatically ("Auto"): native whenever the design fits, HTML for free-form art and animation. You can force either engine in the Pickit window, and convert a widget by refining it ("make it native").
- Native widgets are validated against a strict schema before they're shown. The AI gets precise error messages for its automatic repair attempt, and styling can't inject CSS.
- Native examples in `pickit/prompts/native_examples/` (clock, battery ring, system meters, weather, now playing), used to teach the AI and checked by the tests.
- CI builds every native example under Xvfb and fails if WebKit gets loaded for a native-only desktop.

### Changed
- Existing widgets keep working unchanged; they're HTML widgets.

## [1.0.4] - 2026-09-24

### Changed
- Desktop widgets share one WebKit web process instead of one each: about 40% less memory (4 widgets: 306 MB → 180 MB in the Flatpak, 379 MB → 244 MB from source). If that process crashes, every widget restarts itself.
- Generated widgets follow performance rules (no endless animations, at most one redraw per second, light polling), so they stay near 0% CPU when idle. One media widget went from about 30% of a CPU core to under 3%.

## [1.0.3] - 2026-09-24

### Changed
- Generated widgets no longer depend on optional tools such as `playerctl`. Media widgets read players directly over D-Bus (MPRIS), which works on every desktop without extra packages.

## [1.0.2] - 2026-09-24

### Fixed
- Flatpak: widgets with shadows, rounded cards or animations were drawn partly or not at all (WebKit 2.54 rendering path).

## [1.0.1] - 2026-09-24

### Added
- One-click Flatpak install with automatic updates: a GPG-signed Flatpak repository and landing page on GitHub Pages, plus `Pickit.flatpakref` in every release. The offline `Pickit.flatpak` bundle also receives updates.
- Widgets react to the system: power plugged or unplugged and battery changes refresh them immediately, and so do waking from sleep and network changes.
- Widgets heal themselves: a crashed widget page is restarted automatically, and a watchdog restarts pages that stop responding.

### Fixed
- On-demand action commands (such as play/pause) no longer run by themselves when a widget loads.
- Widgets no longer show up in docks such as Plank as a running Pickit app. Only the Pickit window does.
- Only one widget daemon runs at a time, even with several Pickit versions installed (source, Flatpak, AppImage), so widgets are no longer drawn twice.

## [1.0.0] - 2026-09-24

### Added
- Generate desktop widgets from a plain-language description, with a live preview and conversational refinement.
- Claude backends: the Claude Code CLI (uses your existing login) and the Anthropic API; "Auto" picks whichever is available.
- A desktop daemon that keeps widgets in the desktop layer: below all windows, on every workspace, unaffected by Show Desktop, and back after a reboot.
- Shell-command data sources with an explicit approval step and hash-based re-approval.
- A widget context menu: edit with AI, reload, review commands, reset position, hide, delete.
- Self-contained Flatpak and AppImage packages.

[Unreleased]: https://github.com/dengo07/pickit/compare/v1.1.1...HEAD
[1.1.1]: https://github.com/dengo07/pickit/compare/v1.1.0...v1.1.1
[1.1.0]: https://github.com/dengo07/pickit/compare/v1.0.4...v1.1.0
[1.0.4]: https://github.com/dengo07/pickit/compare/v1.0.3...v1.0.4
[1.0.3]: https://github.com/dengo07/pickit/compare/v1.0.2...v1.0.3
[1.0.2]: https://github.com/dengo07/pickit/compare/v1.0.1...v1.0.2
[1.0.1]: https://github.com/dengo07/pickit/compare/v1.0.0...v1.0.1
[1.0.0]: https://github.com/dengo07/pickit/releases/tag/v1.0.0
