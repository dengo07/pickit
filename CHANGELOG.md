# Changelog

All notable changes to this project are documented here.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [1.5.1] - 2026-09-30

A security release. Please update, especially if you open `.pickit` files from other people. Thanks to the researcher(silverfox-2096) who reported these issues privately.

### Security
- **HTML widgets could read your files and send them out.** Widget pages ran from `file://` with local file access turned on and no Content Security Policy. A widget, including an imported `.pickit` file without any commands, could read files such as SSH keys or `config.json` and send them to a server, without asking. Now:
  - Pages are served from Pickit's own `pickit-widget://` address, which serves the widget's page and nothing else.
  - A Content Security Policy blocks `fetch`, `XMLHttpRequest`, WebSocket, `sendBeacon`, forms, frames, workers, and images or media from URLs. The one exception: scripts, styles and fonts may still load from `cdn.jsdelivr.net`, `cdnjs.cloudflare.com` and Google Fonts, so those requests still leave your computer (see SECURITY.md).
  - Widget pages can't navigate away, open windows or start downloads.
  - Each widget is its own origin, so one widget can't read another's `localStorage`.
- **Imported widgets open only when you trust them.** An HTML widget from a `.pickit` file asks before it opens even when it has no commands, since it contains JavaScript. Rejecting a file's commands now cancels the import instead of opening it without them.
- **Claude Code runs isolated.** Generating a widget with the Claude Code CLI no longer loads your Claude Code hooks, plugins, skills or MCP servers: before, each generation could start your MCP servers, including ones holding credentials. It also runs in an empty folder, so no `CLAUDE.md` is read.
- **API keys are kept in your desktop keyring** (GNOME Keyring, KWallet or another Secret Service) instead of `config.json`. Keys saved by earlier versions move there the first time you open Pickit. Without a keyring they stay in `config.json`, readable only by you, as before. The widget daemon never reads them.
- SECURITY.md now says clearly that the Flatpak sandbox doesn't contain widget commands or the Claude Code CLI, that command approval doesn't protect against software already running as you, and that desktop widget pages share one WebKit process.

### Added
- `"autostart_command"` in `config.json` sets the command the login entry runs, for example to start Pickit inside a Firejail or bubblewrap sandbox.

### Changed
- **HTML widgets can no longer use the network from their page.** `fetch` and images from URLs no longer work. Their data comes through approved commands, as the AI instructions already said, and pictures come as `data:` URLs. The AI instructions now say so, but an older HTML widget that relied on them may show empty parts.
- **HTML widgets start with empty `localStorage`**, because each widget has a new origin. Anything a widget saved there before, such as a timer's state, is gone once.
- **The Claude Code CLI's model setting is ignored**, since its settings aren't loaded. Choose the model in Pickit's Settings; when that's empty, the CLI's default model is used.

### Fixed
- The Pickit window no longer leaves a WebKit process (about 150 MB) running each time it replaces an HTML widget's preview, for example when you open another widget to edit. This happened with the Flatpak, whose newer WebKit keeps the process of a closed view. Desktop HTML widgets also end their shared process when the last of them closes.

## [1.5.0] - 2026-09-28

### Added
- **Native Wayland widgets.** On compositors with the layer-shell protocol (KDE Plasma, Hyprland, Sway, COSMIC, niri, labwc and other wlroots compositors), widgets are now real desktop-layer surfaces: above the wallpaper, below every window, on every workspace, never in a taskbar. Corners and edges are anchors, so widgets stay in place when the resolution changes, and dragging works without X11. On GNOME and Cinnamon, which have no layer-shell, widgets keep using X11 windows through XWayland, which works as before (reported working on Cinnamon's Wayland session). `daemon.log` records which one is used, and `PICKIT_WIDGET_BACKEND=x11|layer-shell` forces a choice.
- The Flatpak and the AppImage include gtk-layer-shell, and the Flatpak can use the Wayland socket.
- CI runs a Wayland smoke test in a headless Sway: widgets must be bottom-layer surfaces at the right anchors, dragging must move them (with a compositor that applies each move late), and their menu must pop up.
- A weekly check opens an issue when Flathub marks Pickit's GNOME runtime end-of-life, before users see end-of-life notices.
- **Lock position and click-through.** Right-click a widget to lock it in place (or lock them all in Settings), or to let clicks pass through it to the desktop underneath. Pickit's sidebar shows both states and can switch them off. They apply instantly, without reloading the widget.
- **Multiple monitors.** With two or more monitors, **Move to monitor** puts a widget on another screen, and dragging a widget to another screen remembers it (X11). If a widget's monitor is unplugged, it comes back on one that's still connected, and returns when you plug it in again.
- **Undo and redo** in the editor (buttons, <kbd>Ctrl</kbd>+<kbd>Z</kbd> / <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>Z</kbd>) for AI refines and code edits. Pickit keeps the last 10 saved versions of each widget, so Undo works after reopening it too. Going back to commands you already approved doesn't ask again.
- **Widget theme.** One accent color, text colors, card look, corner radius and font for all your widgets. Press **Theme** in the header to pick a preset (Charcoal, Graphite, Forest, Paper, each with a dark and a light variant), change any color, or follow the desktop's light/dark mode and accent color. Every widget on the desktop restyles at once, and a live preview shows the result before you apply it. Native widgets use tokens such as `{theme.accent}`; HTML widgets get CSS variables such as `var(--pickit-accent)` and a `pickit-theme` event. The AI and the gallery now use the theme, so new widgets match each other. Widgets made before 1.5.0 keep their own colors, so a light theme can't make their text unreadable.
- **Property inspector.** Select a part of a native widget and the inspector next to the preview shows its properties: color pickers (or a theme color), number boxes, switches and menus, with a live preview. **Add property** sets one that isn't set yet, × goes back to the default. Invalid values are refused with the reason, and each property you change is one Undo step. For HTML widgets, use the Code tab.
- **Smooth values.** Rings and progress bars ease to each new value instead of jumping. The animation runs only while a value changes and follows the desktop's "reduce animations" setting.

### Changed
- The Charcoal theme (the default) uses its amber accent for the gallery's meters and rings, which were blue, so all gallery widgets match.
- The Pickit window runs natively on Wayland instead of through XWayland.
- The release workflow pins the Flatpak builder action to a commit, as the action now asks, instead of following its main branch.

### Fixed
- Removed the one deprecated GTK call (`Gtk.Window.set_wmclass`): widgets get their `pickit-widget` class from the widget daemon's program name instead, so docks such as Plank still ignore them. Pickit now runs without any deprecation warnings.

## [1.4.0] - 2026-09-27

### Added
- **Select part.** Press **Select part** above the preview and click any piece of a widget: a label, a ring, a card, or any element of an HTML widget. It gets outlined, and a chip above the prompt shows what's selected, with buttons to select the surrounding part, show it in the code, or clear it. **Refine** then sends the selected part to the AI along with your request, so "make this orange" changes just that. Tested with two free OpenRouter models: both changed only the selected ring.
- **Code tab.** See and edit any widget's code: the layout (the native component tree as JSON, or the HTML page) and its settings and shell commands, with syntax highlighting and undo. **Apply** (Ctrl+S) validates your changes exactly like AI output and highlights the problem (for example the misspelled property) when there is one; changed commands need approval again. Unapplied edits are applied when you switch back to the preview, refine or place the widget, and Pickit asks before throwing them away.

### Changed
- The widget menu's **Edit with AI…** is now **Edit…**, since the editor also shows the code.

### Fixed
- `pickit export`, `pickit list`, `--version` and `--help` no longer need GTK to be installed; only the commands that open windows load it.

## [1.3.0] - 2026-09-27

### Added
- **Gallery.** Thirteen ready-made native widgets you can add in one click, with no AI backend set up: Big Clock, World Clock, Calendar (today highlighted), Day/Month/Year progress, System Meters, System Rings, CPU Graph, Network speed, CPU Temperature, Battery Ring, System Info, Now Playing and Weather. Previews are live but fed with sample data, so browsing runs nothing; adding a widget asks you to approve its commands first. **Customize** opens a gallery widget in the editor instead. Open it with the **Gallery** button, from the empty editor, or with `pickit gallery`.
- **Share widgets as `.pickit` files.** Export from the sidebar (⋮ → Export…), the widget's right-click menu, or `pickit export <id> [FILE]`. Import with the open-file button, `pickit import FILE`, or by double-clicking the file: Pickit registers the `application/x-pickit-widget` file type in the Flatpak, the AppImage and `install.sh`. Imports are validated like AI-generated widgets and always ask for approval, with a warning that anyone can write such a file. Exports never include your approval, screen position or prompts.
- New widgets from the gallery or a file go to a free corner instead of stacking on top of a widget that's already there.

### Changed
- Sparklines draw a flat line as soon as they have one value, instead of staying empty until the second.
- The `duration` filter shows days for long spans ("3d 4h" instead of "76h 0m").

## [1.2.0] - 2026-09-25

### Added
- **Ollama backend.** Generate widgets with a local model: free, and your prompts never leave your computer. Settings lists the installed models; Pickit asks Ollama for JSON output and a context window large enough for its instructions (at least 16k tokens, more when refining a big widget), turns off "thinking" (it made local models write smaller widgets in the same time), and gives local models a second repair attempt. Tested with `qwen3.5:9b` on an 8 GB laptop GPU: clock, battery, system meters, weather and now-playing widgets all came out valid on the first try, in 7–70 seconds each.
- **OpenRouter backend.** Use any model on OpenRouter with one key, including free ones. Pickit uses JSON mode when the model supports it and falls back gracefully when it doesn't. Busy free models (rate limits, overloaded providers) are retried twice, and if they're still busy you see OpenRouter's reason. Tested with the free `nemotron-3-ultra-550b-a55b` and `dots-3-note-preview` models: all ten widgets came out valid, a few after one repair.
- **Test connection** in Settings checks the selected backend: that Claude Code is installed, that an API key works (and how much OpenRouter credit is left), or that Ollama runs and has the chosen model.
- Settings shows only the options of the selected backend, with setup help for each. API key fields have an eye button to check what you pasted.

### Changed
- **Automatic** backend order: Claude Code, then an Anthropic API key, then Ollama with a downloaded model, then an OpenRouter key. If none is set up, Pickit says so and lists the options instead of failing on a missing Anthropic key.
- The AI instructions now warn against piping data into a heredoc script (`curl … | python3 - <<'EOF'`), which silently leaves the script without input. A model made this mistake in testing.
- HTTPS requests from the AppImage find the system's certificates on Fedora, openSUSE and other distros whose certificate paths differ from Ubuntu's.

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

[Unreleased]: https://github.com/dengo07/pickit/compare/v1.5.1...HEAD
[1.5.1]: https://github.com/dengo07/pickit/compare/v1.5.0...v1.5.1
[1.5.0]: https://github.com/dengo07/pickit/compare/v1.4.0...v1.5.0
[1.4.0]: https://github.com/dengo07/pickit/compare/v1.3.0...v1.4.0
[1.3.0]: https://github.com/dengo07/pickit/compare/v1.2.0...v1.3.0
[1.2.0]: https://github.com/dengo07/pickit/compare/v1.1.1...v1.2.0
[1.1.1]: https://github.com/dengo07/pickit/compare/v1.1.0...v1.1.1
[1.1.0]: https://github.com/dengo07/pickit/compare/v1.0.4...v1.1.0
[1.0.4]: https://github.com/dengo07/pickit/compare/v1.0.3...v1.0.4
[1.0.3]: https://github.com/dengo07/pickit/compare/v1.0.2...v1.0.3
[1.0.2]: https://github.com/dengo07/pickit/compare/v1.0.1...v1.0.2
[1.0.1]: https://github.com/dengo07/pickit/compare/v1.0.0...v1.0.1
[1.0.0]: https://github.com/dengo07/pickit/releases/tag/v1.0.0
