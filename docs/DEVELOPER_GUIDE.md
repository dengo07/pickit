# Developer guide

Everything in this repository, file by file, and step-by-step recipes for the changes you're most likely to make. Read [ARCHITECTURE.md](ARCHITECTURE.md) for the *why* behind the big decisions; this guide is the *where* and *how*.

## 1. The big picture

Pickit is two programs that share one folder of files:

```
 you ──► Pickit window (app.py)            desktop daemon (daemon.py) ──► widget windows
          │  describe, preview, refine       ▲  watches the folder,          (widget_window.py)
          │  approve commands                │  creates/updates/closes        │
          ▼                                  │  one window per widget         ▼
   ~/.local/share/pickit/widgets/<id>/  ─────┘                           the view draws it:
   widget.json, ui.json or index.html,                                    native/render.py (GTK)
   versions/                                                              html_view.py (WebKit)
```

- **The Pickit window** (`pickit`, class `MakerWindow`) is where widgets are made. It talks to an AI through `backends.py`, turns the answer into a checked *spec* with `generator.py`, previews it, and saves it with `store.py`.
- **The desktop daemon** (`pickit run`, class `DesktopDaemon`) starts at login and owns every widget on the desktop. It never talks to the AI. When a widget's files change, `store.notify_changed()` rewrites a small "changed" file, and the daemon's file watcher calls `reconcile()`.
- **A spec** is the dict that describes one widget: `name, engine, width, height, position, commands`, plus `ui` (native) or `html` (HTML). Everything that creates widgets (AI, gallery, `.pickit` files, the Code tab) produces a spec and runs it through `generator.validate()`.
- **Commands** are shell commands a widget declares. They run only after you approve them; the approval is a hash of the commands, so any change needs approval again. `bridge.py` runs them.

A widget's life: prompt → `backends.*.complete()` → `generator.generate()` returns a validated spec → approval dialog → preview (`make_view()`) → **Place on desktop** → `store.save_spec()` → daemon `reconcile()` → `WidgetWindow` → the view loads the spec and `CommandRunner` feeds it data.

**Reading order if you're new:** `store.py` → `generator.py` → `native/spec.py` → `native/data.py` → `native/render.py` → `widget_window.py` → `daemon.py` → `app.py`.

## 2. Every file

### `pickit/`: the app

| File | What it does | You'd edit it to… |
|---|---|---|
| `__init__.py` | Only `__version__`. | Bump the version for a release. |
| `__main__.py` | The command line (`pickit`, `pickit run`, `export`, `list`...). Commands that don't open windows (`--version`, `list`, `export`) run *before* GTK is imported, so they work without GTK. `run`/`stop` set the program name `pickit-widget` (the widgets' X11 WM_CLASS, which keeps them out of docks) and call `session.setup_widget_display()`. Everything else starts `PickitApp`. | Add a CLI command. |
| `app.py` | The Pickit window, the biggest file. `SettingsDialog` (backends, models, keys, Test connection, checkboxes). `MakerWindow`: the prompt, Generate/Refine (`generate()` runs the AI in a thread and comes back through `GLib.idle_add`), the preview and Code tab (`_show_preview`, `_fill_code`, `apply_code`), **Select part** (`_on_part_selected`, `_focus`), Undo/Redo (`undo_stack`, `_step_history`), the inspector panel (`_on_inspector_change`, `_apply_inspector_edit`), the theme (`open_theme`, `apply_theme`, `theme_tokens`), gallery/import/export (`open_spec`, `add_from_gallery`, `import_file`), the sidebar (`refresh_list`, `set_flag`). `PickitApp` handles startup and command-line routing (`do_command_line`). | Change the editor UI, add a setting, add a sidebar action. |
| `backends.py` | Talks to the AI. Every backend has `complete(system, messages) -> str` and `check() -> str`: `ClaudeCLIBackend` (runs `claude -p`), `AnthropicBackend` (Python SDK), `OllamaBackend` and `OpenRouterBackend` (plain HTTP with `urllib`). `resolve_auto()` picks the first one that's set up; `from_config()` builds one from the settings. `SetupError` means "not configured" (the UI then offers Settings). | Add an AI provider (recipe below). |
| `generator.py` | Builds the system prompt (`system.md` + the native examples), sends the request, pulls the JSON out of the reply (`_extract_json`), checks it (`validate`), and retries with the error message if it's broken (`repair_attempts`). `focus_text()` adds the SELECTED PART section. | Change what's sent to the AI, or what counts as a valid spec. |
| `store.py` | All widget files: `save_spec` (create/update; keeps earlier versions), `load`, `to_spec`, `list_widgets`, `delete`, `commands_hash`/`is_approved` (approval), `signature` (what counts as a content change; `LIVE_FIELDS` like position and lock are excluded so they don't reload the widget), `versions`, `free_anchor` (a free corner), `watch` (the file watcher), `notify_changed`. | Add a widget file or change how widgets are stored. |
| `config.py` | `~/.config/pickit/config.json`. `DEFAULTS` lists every setting; `load()` fills in defaults (`load(with_secrets=True)`, only in the Pickit window, also reads the API keys from the keyring), `save()` moves `SECRET_KEYS` to the keyring and writes the rest with mode 0600. | Add a setting (recipe below). |
| `secret_store.py` | API keys in the desktop keyring through libsecret's `Secret.Service` (directly, so the Flatpak uses the system keyring, not a file in its sandbox). Entries carry the config folder, so test configs never touch real keys. Every call fails softly. | Change how secrets are stored. |
| `runtime.py` | Where Pickit runs: source, Flatpak (`IN_FLATPAK`) or AppImage (`APPIMAGE`). The real config/data folders (`CONFIG_HOME`, `DATA_HOME`, overridable with `PICKIT_CONFIG_HOME` / `PICKIT_DATA_HOME`, which the tests use), `host_argv` (wraps commands in `flatpak-spawn --host` inside Flatpak), `host_env` (removes the AppImage's library paths for host programs), `spawn_self` (starts another Pickit process, e.g. the daemon), `find_claude`. | Support a new way of installing. |
| `session.py` | Decides how the daemon shows widgets: Wayland **layer-shell** if the compositor supports it, otherwise **X11** windows (through XWayland on Wayland). If Wayland lacks layer-shell, it restarts the process in X11 mode. `PICKIT_WIDGET_BACKEND` overrides it. | Change how the display system is chosen. |
| `placement.py` | Pure math, no GTK: X11 coordinates for a position name (`anchor_xy`), layer-shell anchors and margins (`layer_anchors`, `layer_moved`, `layer_top_left`), and `clamp` for dragging. | Add a new kind of position. |
| `daemon.py` | The desktop daemon. `acquire_instance_lock()` makes sure only one runs. `DesktopDaemon.do_startup` connects the file watcher, system events and monitor hotplug; `reconcile()` compares the files with the open windows and creates, updates or closes them, and restyles them all when the theme changed (`theme.watch_system` calls it when the desktop's light/dark mode changes); `_callbacks()` are the widget-menu actions that need the daemon (edit, approve, export, hide, delete). | Add a widget-menu action that needs dialogs. |
| `widget_window.py` | One desktop widget window, for both engines. Sets up layer-shell or the X11 hints (dock type, keep-below, sticky, skip taskbar), transparency, placement (`apply_manifest`), live switches (`update_flags`: lock, click-through), dragging (X11: poll the global pointer; Wayland: `_begin_layer_drag`), saving the position, the right-click menu (`_menu`, `_menu_action`), monitors (`monitors`, `chosen_monitor`, `_move_to_monitor`). `make_view()` creates the engine's view; `engine_of()` reads a manifest's engine. | Change how widgets sit, move or what their menu offers. |
| `bridge.py` | `BRIDGE_JS` is the `window.widget` JavaScript API for HTML widgets (`widget.on`, `widget.run`, `widget.drag`, `widget.theme` and the `pickit-theme` event). `CommandRunner` runs a widget's approved commands in threads on their intervals (`start`), on demand (`run`), or right away after system events (`refresh`), with a 20 s timeout and 256 KB output limit, and hands results back on the GTK main loop. | Change how commands run. |
| `events.py` | `SystemEvents` listens on the system D-Bus for power changes (UPower), waking from sleep (logind) and network changes (NetworkManager), and calls the daemon's `refresh_all`. | React to another system event. |
| `html_view.py` | The HTML engine: `WidgetView`, a WebKit view with the bridge script, the theme as CSS variables (`set_theme`, `_apply_theme_css`, a WebKit user style sheet) and as `widget.theme` (`_send_theme`), one shared web process for all desktop widgets, crash recovery and a watchdog (`enable_watchdog`), and Select part for HTML (`SELECT_JS`). Imported only when an HTML widget exists. | Change how HTML widgets behave. |
| `dialogs.py` | Dialogs used by both the window and the daemon: `approval_dialog` / `build_approval_dialog`, `confirm`, `error_dialog`, `export_dialog`, `choose_widget_file`, plus `label()`, `install_css()` and the app's CSS (`CSS`, `PREVIEW_BG`, `MONO_FONTS`). | Restyle the app, change a dialog. |
| `gallery.py` | Loads `pickit/gallery/*.json` into `Item`s (spec + description + category + sample data). | Change the gallery format. |
| `gallery_ui.py` | The gallery window: a grid of cards with live previews (`ScaledPreview` draws a widget scaled down from an offscreen window, fed with sample data, so nothing runs). | Change the gallery's look. |
| `share.py` | `.pickit` files: `export_widget` (spec only; no approval, position or prompts), `read_widget_file` / `parse_widget_data` (size limit, format version, full validation). | Change the file format. |
| `codeedit.py` | The Code tab's logic, no GTK: `split_spec` / `join_spec` (spec ⇄ editable text, with `CodeError` pointing at the problem), `json_spans` (where each value is in the JSON text), `node_path` / `node_at` / `path_label` (component paths like `ui.children[1]`), `describe` (chip labels), `find_element` (an HTML element in the page source), and the inspector's edits: `editable_properties` (what a component can have, from `native/spec.py`), `set_property` / `remove_property` (a validated copy of the spec). | Improve code editing or error locations. |
| `theme.py` | The widget theme, no GTK in its core: `TOKENS`, `PRESETS` (each with a dark and a light palette), `settings()` (the `config["theme"]` values, cleaned up), `tokens()` / `current()` (the active colors, radius, font and mode), `is_themed()` (whether a widget uses any `{theme.…}` token), `css_variables()` (for HTML widgets), and the desktop's light/dark mode and accent color from the XDG settings portal (`system_appearance`, `watch_system`). | Add a preset or a token. |
| `theme_ui.py` | `ThemeDialog`, the **Theme** window: preset, mode, a color button per token, corner radius, font, and a live preview of two gallery widgets. Its result is `dialog.settings`. | Add a theme option. |
| `inspector.py` | `Inspector`, the panel next to the preview for the selected native part: one editor per set property, chosen by the property's kind (`_editor`: color button + theme colors, spin button, switch, menu, text field), **Add property**, and × to remove. It only reports changes (`on_change(key, value)`, `REMOVE`); `app.py` applies them through `codeedit.set_property`. `RANGES` sets the spin buttons' limits. | Give a property a better editor or range. |
| `code_view.py` | `CodeView`, the code editor widget: a `Gtk.TextView` with JSON/HTML highlighting (`RULES`, `COLORS`), undo/redo and two-space tabs. | Add highlighting for something. |
| `autostart.py` | Starts the daemon (`ensure_daemon`, `spawn`), writes/removes the login autostart entry (`set_enabled`), and adds the AppImage's menu entry and file type (`install_launcher`). | Change startup behavior. |

### `pickit/native/`: the native engine

| File | What it does | You'd edit it to… |
|---|---|---|
| `spec.py` | The list of components and the properties each accepts (`COMPONENTS`, `COMMON`, `BOX`), required properties (`REQUIRED`), limits (`MAX_NODES`, `MAX_DEPTH`), safe CSS values (`SAFE_CSS`), and `validate_ui()`, which gives precise errors like `ui.children[1] (label): unknown property "colour"`. **Nothing reaches the renderer without passing this.** | Add a component or property (recipe below). |
| `data.py` | Data binding without `eval`: `parse_output` (command output → JSON, `key=value` pairs or text), `lookup` (`a.b.0.c` paths), `FILTERS` (`round`, `bytes`, `time:%H:%M`...), `interpolate` / `evaluate_ref` (templates like `{cpu.value|round}`), `condition` (a small hand-written parser for `==`, `<`, `and`, `not`...), `resolve` (templates, choices, plain values), `refs` (which data a template depends on). | Add a filter (recipe below). |
| `render.py` | `NativeView` turns the component tree into GTK widgets once (`_build`, one `_make_<type>` per component), then updates only the parts whose data changed (`_bind` → `_Binding`, `_update`). Styling becomes a generated CSS provider (`_style`, `_flush_css`). The theme: `set_theme` stores the tokens as the `theme` data source, and for themed widgets `_build_tree` swaps `CARD_DEFAULTS` for the theme's card look (`_card_defaults`). `update_ui` rebuilds the tree but keeps data and running commands (the inspector uses it). Also: `_Tween` (smooth ring/bar values), `show_sample`, Select part (`set_select_mode`, `node_at`, `_draw_selection`), image loading (`_load_image`). | Add a component's drawing/behavior. |
| `draw.py` | Cairo drawing: `ring`, `bar`, `sparkline`, `rounded_rect`, `pixbuf` (rounded images), `rgba` (color parsing), `fraction`. | Change how rings, bars or charts look. |
| `__init__.py` | Empty (makes it a package). | — |

### `pickit/prompts/`, `pickit/gallery/`, `pickit/data/`

| Path | What it is |
|---|---|
| `prompts/system.md` | The instructions every AI gets: output format, when to use native vs HTML, the component reference, command rules (portable tools, read-only, intervals), design and performance rules, refinement rules (including SELECTED PART). `@@NATIVE_EXAMPLES@@` is replaced with the examples below. **Changing it changes every generated widget**, so test several prompts afterwards. |
| `prompts/native_examples/*.json` | Five complete native widgets (clock, battery, meters, weather, now playing) that teach the AI the format. The tests check that they validate. |
| `gallery/*.json` | The 13 gallery widgets: a spec plus a `gallery` object (`order`, `category`, `description`, `sample` = made-up command output for the preview). `tests/test_gallery.py` checks every field shown exists in the sample. |
| `data/io.github.dengo07.Pickit.desktop` | The app-menu entry (`Exec=pickit %f`, `MimeType` for `.pickit` files, `StartupWMClass=pickit`). |
| `data/io.github.dengo07.Pickit.metainfo.xml` | What software centers show: description, screenshots, **one `<release>` per version**. Validate after editing (see §4). |
| `data/io.github.dengo07.Pickit.mime.xml` | Registers the `application/x-pickit-widget` file type (`*.pickit`). |
| `data/io.github.dengo07.Pickit.svg` | The app icon. |

### `tests/`

Run `pytest` (no display needed), then the smoke tests, which need a display.

| File | Tests |
|---|---|
| `conftest.py` | The `store` fixture: a store in a temporary folder (via `PICKIT_DATA_HOME`), so tests never touch your widgets. |
| `test_store.py` | Saving, loading, approval hashes, signatures, versions, live fields. |
| `test_generator.py` | JSON extraction, spec validation, repair retries. |
| `test_native_spec.py`, `test_native_data.py` | The component validator; filters, templates, conditions (including hostile input), durations, sparklines. |
| `test_backends.py` | Ollama and OpenRouter against a local mock HTTP server, backend auto-selection, repair attempts. |
| `test_config.py` | API keys in the keyring (with a fake keyring): migration, fallback to the file, removal, never wiping an unreadable keyring; the custom autostart command. |
| `test_codeedit.py` | Code tab logic, error positions, component paths, the SELECTED PART prompt, inspector edits (valid and refused). |
| `test_theme.py` | Presets, overrides, light/dark and system accent, themed-vs-legacy detection, CSS variables, the gallery using tokens. |
| `test_gallery.py` | Every gallery widget validates and its sample covers its fields. |
| `test_share.py` | `.pickit` export/import and what import rejects; `pickit export`; `free_anchor`. |
| `test_placement.py` | X11/Wayland placement math and the display-system decision. |
| `test_daemon_lock.py`, `test_refresh.py` | One daemon at a time; command refresh after system events. |
| `gtk_smoke.py` | Real GTK on X11: builds every example and gallery widget, checks WebKit isn't loaded for native widgets, the settings dialog, gallery window, Select part, the code editor, animations, lock, the theme (themed vs legacy widgets, HTML CSS variables) and the inspector's editors. Run: `xvfb-run -a python3 tests/gtk_smoke.py` (or just `python3 tests/gtk_smoke.py` on your desktop). |
| `wayland_smoke.py`, `sway-headless.conf` | Real GTK on Wayland in a headless Sway: layer surfaces, anchors, dragging, menus, moving to another monitor. How to run it is in CONTRIBUTING.md. |

### `packaging/`

| File | What it is |
|---|---|
| `flatpak/io.github.dengo07.Pickit.yml` | The Flatpak recipe: runtime (GNOME 51), permissions (`finish-args`, each explained), modules (Python wheels, gtk-layer-shell, Pickit itself). |
| `flatpak/python-deps.json` | Pinned Python wheels (the Anthropic SDK and its dependencies) with checksums, so the build needs no network. Regenerate with `gen-python-deps.py`. |
| `flatpak/gen-python-deps.py` | Regenerates `python-deps.json` for a Python version. |
| `flatpak/pickit.gpg` | The **public** key of the release signing key (safe to publish; users' Flatpak checks updates against it). The private key is only in `~/.local/share/pickit-release-key/` and the GitHub secret. |
| `flatpak/site/` | The GitHub Pages site: `index.html` (the install page), `Pickit.flatpakref` (one-click install), `pickit.flatpakrepo` (the repository definition). |
| `appimage/build-appimage.sh` | Builds the AppImage: copies Python, GTK, WebKit, gtk-layer-shell and every library they need from the build machine, patches WebKit's helper path, packs it with `appimagetool`. |
| `appimage/AppRun` | The AppImage's entry point: sets library and Python paths, then runs `python3 -m pickit`. |

### `.github/`

| File | What it is |
|---|---|
| `workflows/ci.yml` | On every push: lint + tests (plain Python, no GTK), the X11 smoke test (Xvfb), the Wayland smoke test (headless Sway). |
| `workflows/release.yml` | On a `v*` tag: builds the AppImage and the signed Flatpak, publishes the Flatpak repository to GitHub Pages, creates the GitHub release. Needs the `FLATPAK_GPG_PRIVATE_KEY` secret. |
| `workflows/runtime-check.yml` | Weekly: opens an issue if Flathub marks the GNOME runtime end-of-life. |
| `dependabot.yml` | Monthly pull requests to update GitHub Actions versions. |
| `ISSUE_TEMPLATE/*`, `PULL_REQUEST_TEMPLATE.md` | Forms for bug reports, compatibility reports, feature requests and pull requests. |

### Root files

| File | What it is |
|---|---|
| `README.md` | The project page: features, install, backends, usage, compatibility, troubleshooting. |
| `CHANGELOG.md` | Every version's changes. Add to `[Unreleased]` while working; rename it at release. |
| `CONTRIBUTING.md` | Development setup, tests, gallery widget rules, release steps. |
| `SECURITY.md` | How widgets are contained; how to report vulnerabilities. |
| `docs/ARCHITECTURE.md`, `docs/WIDGET_FORMAT.md`, `docs/PACKAGING.md` | Design decisions; the widget file format and component reference; how the packages are built. |
| `pyproject.toml` | Python package metadata, optional dependencies, ruff and pytest settings. |
| `Makefile` | `make flatpak`, `make appimage`, `make clean`. |
| `install.sh` | Adds a source checkout to your app menu. |
| `LICENSE`, `CODE_OF_CONDUCT.md`, `.editorconfig`, `.gitignore` | MIT license, community rules, editor settings, ignored files. |

## 3. Recipes

### Add a native component (example: a `divider`)
1. **`native/spec.py`**: add it to `COMPONENTS` with its properties, e.g. `"divider": {"color": (COLOR,), "thickness": (INT,)}`. Add required properties to `REQUIRED` if any.
2. **`native/render.py`**: add `_make_divider(self, p)`. Build the GTK widget, and for every property that can depend on data, use `self._bind(p, ["color"], lambda v: ...)` so it updates. Return the widget. (`_build` finds `_make_<type>` by name, and `_common` handles margin, size, align, visible, tooltip and opacity for you.)
3. **`prompts/system.md`**: document it in the component reference, or the AI will never use it.
4. **`docs/WIDGET_FORMAT.md`**: add it to the components table.
5. Test: add a case to `tests/test_native_spec.py`, and put one in a gallery or example widget so `gtk_smoke.py` builds it.

### Add a filter (example: `{x|pad:3}`)
Add a function to `FILTERS` in `native/data.py`. It receives `(value, argument)`, where argument is the text after the colon or `None`, and returns the new value. Never evaluate code. Document it in `system.md` and `WIDGET_FORMAT.md`, and add a test to `test_native_data.py`.

### Add a setting (example: a checkbox)
1. `config.py`: add the key and default to `DEFAULTS`.
2. `app.py`, `SettingsDialog.__init__`: create the widget and `box.pack_start` it; in `apply()` (or `values()` for backend settings) copy its value into `cfg`.
3. Read it where needed with `cfg.get("your_key")`. The daemon reloads the config in `reconcile()`; `_on_settings` calls `store.notify_changed()` so that happens right away.

### Add a widget-menu action (example: "Duplicate")
1. `widget_window.py`, `_menu()`: add `("Duplicate", "duplicate")` to `items`.
2. If it only touches files, handle it in `_menu_action()` with `store` functions. If it needs a dialog or the daemon, add `"duplicate": self._duplicate` to `daemon.py`'s `_callbacks()` and write the method there.
3. The window sidebar menu is built in `app.py`'s `refresh_list()`, if you want it there too.

### Add a field to `widget.json` (example: `"opacity"`)
Decide what kind it is:
- **Changes what the widget looks like** (needs a reload): just save it in the manifest. `store.signature()` includes it, so the daemon reloads the widget when it changes.
- **Live switch** (applied without reload, like `locked`): add it to `store.LIVE_FIELDS`, and apply it in `WidgetWindow.update_flags()`. The daemon calls that on every reconcile.

Document it in `WIDGET_FORMAT.md`. `share.file_data()` decides what goes into `.pickit` files; personal state (position, approval, lock) must stay out.

### Add an AI backend
In `backends.py`, write a class with `name`, `repair_attempts`, `complete(system, messages) -> str` and `check() -> str`. Raise `SetupError` for "not configured" (missing key, server not running) and `BackendError` for everything else. Use `_request()` for HTTP (it handles HTTPS certificates in the AppImage). Add it to `from_config()` and, if it can be detected, `resolve_auto()`. In `app.py`, add it to `BACKENDS` and give it a page in `SettingsDialog`. Add its settings to `config.DEFAULTS`. Test it against `MockServer` in `test_backends.py`.

### Add a gallery widget
Make it in Pickit, run `pickit export <id> my-widget.pickit`, rename to `pickit/gallery/my-widget.json`, delete `pickit` and `exported_by`, and add a `gallery` object with made-up `sample` output (see `WIDGET_FORMAT.md`). `pytest tests/test_gallery.py` tells you if a field is missing from the sample.

### Add a CLI command
In `__main__.py`: if it doesn't need windows, handle it before the `# Everything below opens windows` line (like `export`). If it opens the Pickit window, add its name to the list of known commands and handle it in `PickitApp.do_command_line()` in `app.py`. Update the usage text at the top of `__main__.py` and the README.

## 4. Rules that keep Pickit safe and working

- **Never run AI output as code.** Native widgets are data: validated by `spec.py`, drawn by trusted code, templates evaluated by `data.py` without `eval`. Keep it that way.
- **Commands only run after approval.** Anything that changes `commands` must lead to approval again. `store.commands_hash()` makes that automatic, so don't bypass it.
- **GTK only from the main thread.** Work in threads (AI calls, commands), then come back with `GLib.idle_add(...)`, as `generate()` and `CommandRunner` do.
- **Don't import WebKit at the top of a module.** Import it only where HTML widgets are used (`make_view` does it lazily), or native-only desktops lose their memory advantage. `gtk_smoke.py` checks this.
- **Keep both display systems working.** Anything about widget placement, moving or input has an X11 path and a Wayland layer-shell path in `widget_window.py`. Test both smoke tests.
- **Never use your real data in tests or screenshots.** Set `PICKIT_DATA_HOME` and `PICKIT_CONFIG_HOME` to temporary folders (the `store` fixture does), so your widgets and API keys are never touched.

## 5. Checking your work and releasing

```bash
ruff check .                               # style and mistakes
pytest                                     # the unit tests
python3 tests/gtk_smoke.py                 # real GTK widgets (X11)
flatpak run --command=appstreamcli --filesystem=$PWD org.flatpak.Builder \
  validate --no-net pickit/data/io.github.dengo07.Pickit.metainfo.xml
make flatpak                               # optional: build the Flatpak locally
```

To release a version:
1. Set `__version__` in `pickit/__init__.py`.
2. In `CHANGELOG.md`, rename `[Unreleased]` to the version and date, and add the compare link at the bottom.
3. Add a `<release>` to the metainfo file.
4. Commit, tag and push: `git tag -a v1.6.0 -m "Pickit 1.6.0"`, then `git push origin main` and `git push origin v1.6.0`. The release workflow does the rest.
