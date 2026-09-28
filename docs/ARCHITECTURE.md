# Architecture

Pickit runs as two processes that communicate only through files:

| Process | Command | Job |
|---|---|---|
| **Maker** | `pickit` | The window where you describe, preview, refine and place widgets. It writes widget files and exits when you close it. |
| **Desktop daemon** | `pickit run` | Owns every widget window. It starts at login (XDG autostart) and whenever the maker opens, and keeps running with or without the maker. |

Both are unique `Gtk.Application`s, so launching one that is already running just activates the existing instance. The IDs are `io.github.dengo07.Pickit` and `io.github.dengo07.Pickit.Desktop`.

```mermaid
sequenceDiagram
  participant U as User
  participant M as Maker
  participant C as AI model (Claude, Ollama, OpenRouter)
  participant S as Widget store
  participant D as Desktop daemon
  U->>M: "a CPU meter, bottom-right"
  M->>C: system prompt + request
  C-->>M: JSON {name, size, position, commands, html}
  M->>U: approve these shell commands?
  M->>S: write widget.json + index.html, touch "changed"
  S-->>D: file monitor fires
  D->>D: reconcile windows (create / reload / close)
```

## Modules (`pickit/`)

| Module | Responsibility |
|---|---|
| `__main__.py` | CLI entry. Routes `run`/`stop` to the daemon (after `session.py` picks its display system) and everything else to the maker. Sets `WEBKIT_DMABUF_RENDERER_FORCE_SHM=1`, and the program name that becomes the widgets' X11 WM_CLASS. |
| `session.py` | Chooses how the daemon shows widgets: Wayland layer-shell when the compositor supports it, X11 windows otherwise; restarts the daemon as an X11 client when a Wayland compositor lacks layer-shell. |
| `placement.py` | Widget placement without GTK: X11 coordinates and layer-shell anchors from the same `position` names, and clamping while dragging. |
| `app.py` | Maker window: prompt, examples, generation thread, preview, approval, settings. |
| `daemon.py` | Desktop daemon: watches the store and reconciles windows; handles the widget context-menu actions. |
| `widget_window.py` | `WidgetWindow`, the desktop window shared by both engines: a layer-shell surface or an X11 dock window, transparency, manual drag, context menu, position saving. `make_view()` creates the engine's view with a lazy import. |
| `native/spec.py` | The native component vocabulary and its validator: a strict property whitelist per component, safe CSS values, precise error paths. |
| `native/data.py` | Data binding: command output parsing, templates, filters, conditions and choices, all in a small interpreter with no `eval`. |
| `native/render.py`, `native/draw.py` | `NativeView`: builds GTK widgets from the tree, turns data-dependent properties into bindings that update only when their inputs change, and draws rings, bars, sparklines and rounded images with Cairo. |
| `codeedit.py` | The Code tab's logic, without GTK: split a spec into editable text and join it back with validation, map validator errors and selected components to positions in the JSON text, and find a clicked HTML element in the page source. |
| `theme.py` | The widget theme: presets, resolving the active colors (including the desktop's light/dark mode and accent color from the XDG settings portal), and CSS variables for HTML widgets. |
| `theme_ui.py`, `inspector.py` | The Theme window, and the property inspector next to the preview. The inspector only reports edits; the maker applies them through `codeedit`, which validates them like any other change. |
| `code_view.py` | The code editor: a `Gtk.TextView` with JSON/HTML highlighting, undo/redo and two-space tabs (GtkSourceView isn't available in every runtime Pickit ships on). |
| `html_view.py` | `WidgetView`: the HTML engine's WebKit view, with the JS bridge, a shared web process, crash reload and watchdog. Only imported when an HTML widget exists. |
| `bridge.py` | The `window.widget` JS API and `CommandRunner`, which runs approved commands on their intervals in threads. |
| `generator.py` | Builds the prompt, extracts and validates the JSON spec, and retries once with the error fed back. |
| `backends.py` | `ClaudeCLIBackend` (`claude -p --output-format json --tools ""`), `AnthropicBackend` (Python SDK, streaming, adaptive thinking), `OllamaBackend` (`/api/chat` with JSON output, thinking off, and a context of 16k tokens or more) and `OpenRouterBackend` (OpenAI-style chat completions, JSON mode when the model supports it). The last two use only the standard library. `resolve_auto()` picks the first backend that's set up. |
| `store.py` | Widget files, the change stamp, approval hashes and content signatures; `free_anchor()` picks a free corner for a new widget; `versions()` keeps the last 10 versions of each widget for Undo. |
| `gallery.py`, `gallery/` | The ready-made widgets: specs plus sample output for previews. |
| `gallery_ui.py` | The gallery window. Each card shows a live native preview drawn scaled down from an offscreen window, fed with sample data, so browsing never runs a command. |
| `share.py` | `.pickit` widget files: export (spec only: no approval, position or history) and import (full validation, approval required). |
| `runtime.py` | Detects source, Flatpak or AppImage; handles host command wrapping (`flatpak-spawn --host`), self-launching and locating the Claude CLI. |
| `autostart.py` | Launches the daemon detached, writes the XDG autostart entry, and adds the AppImage's menu entry. |
| `config.py` | `~/.config/pickit/config.json`. |
| `prompts/system.md`, `prompts/native_examples/` | The system prompt: engine choice, the native component reference, the HTML contract, command and design rules, plus complete native examples. |

## Key decisions

**Two engines, native first.** WebKit costs about 50–150 MB per page process, while the same widgets drawn with GTK cost a few MB. So the AI describes most widgets as a declarative component tree (`ui.json`) that Pickit renders natively, and falls back to HTML only for designs the components can't express. Measured with five typical widgets (clock, battery ring, meters, weather, media): **24 MB** as native widgets (27 MB in the Flatpak), versus 180–244 MB for four HTML widgets. A declarative tree was chosen over having the AI write GTK code, because generated code would run with the user's full permissions, while a tree is data: it's validated against a whitelist and rendered by trusted code, and only approved commands ever run. WebKit is imported lazily, so a native-only desktop never loads it; mixing in one HTML widget brings its cost back.

**Wayland: layer-shell where it exists.** The wlr-layer-shell protocol (KDE Plasma, Hyprland, Sway, COSMIC, niri, labwc and other wlroots compositors) lets a client put a surface in the compositor's "bottom" layer: above the wallpaper, below every window, on every workspace, never in a taskbar. Widgets use it through gtk-layer-shell, anchored to screen edges with margins, so a `top-right` widget stays in the corner when the resolution changes; a moved widget is pinned by its top-left corner. GNOME and Cinnamon don't implement layer-shell, so there the daemon restarts itself as an X11 client and uses the dock-window approach below through XWayland, which both handle. The Pickit window itself is an ordinary app window and runs natively on either. Wayland has no global pointer position, so dragging moves the widget by how far the pointer has slipped from where it grabbed it, skipping one step after each move so the compositor has applied it.

**Dock window type plus keep-below (X11).** On EWMH window managers this puts a window in the "bottom" layer: above the desktop background and icons, below every normal window. Show Desktop doesn't hide it, and clicking it never raises it. A `DESKTOP`-type window was rejected because it gets buried under Nemo, Nautilus or Caja's desktop window as soon as the desktop is clicked. The trade-off: window managers don't move dock windows, so Pickit implements dragging itself (polling the pointer while the button is held), and dock windows don't take keyboard focus.

**Files as the IPC channel.** Every change is written to the store and then signalled by atomically replacing `~/.local/share/pickit/changed`. The daemon watches that one file and diffs a content signature per widget that ignores position. There is no D-Bus API to keep in sync, and hand-edited widgets work too.

**Any model, same contract.** Every backend gets the same system prompt and must return the same JSON spec, which the generator validates. Nothing a backend returns is trusted: a bad spec gets fed back as an error for a repair attempt (two for Ollama, since small local models slip more often), and commands still need approval. Ollama's default context window (often 4k tokens) would silently cut off Pickit's ~8k-token instructions, so requests set `num_ctx` to at least 16k, more when refining a large widget. They also turn off "thinking": with `qwen3.5:9b` it took as long and produced much smaller widgets.

**Select part.** In the maker's preview, the native renderer records which GTK widget each component built; with select mode on, its event box sits above its children, so a click hit-tests those widgets (the innermost one wins) instead of pressing buttons, and an outline is drawn over the result. For HTML widgets a small script outlines elements on hover and posts the clicked one's CSS path and markup through the bridge, which accepts such messages only while the maker asked for them. A Refine then includes the selected component (with its path) or element in the prompt as a SELECTED PART.

**The theme is data, not a stylesheet.** Native widgets refer to theme colors with templates (`{theme.accent}`), and the theme is one more built-in data source next to `now`. So the validator, the bindings and the Code tab need nothing new, the AI can mix theme colors into conditions and choices, and a theme change is one data update. HTML widgets get the same values as CSS variables from a WebKit user style sheet, which applies before the page's own CSS, so pages don't flash unthemed colors. Only widgets that use a token are *themed*: their cards and text also take the theme's defaults. Widgets without tokens were written for a dark card with white text, so they keep that look, and a light theme can't make them unreadable. The default preset, Charcoal dark, uses the same values as Pickit's look before themes. The daemon already reloads the config on every change, so restyling all widgets is part of `reconcile()`.

**Approval by hash.** A widget's `approved_hash` is the SHA-256 of its canonicalised `commands`. Any change to a command, including one made by the model during a refine, invalidates the approval.

**Same data everywhere.** Inside Flatpak the XDG variables point into the sandbox, so `runtime.py` uses the real `~/.config` and `~/.local/share` there. The manifest grants access to just those folders. The source, Flatpak and AppImage versions therefore all share widgets, settings and the autostart entry.

**NVIDIA.** WebKit's GPU buffer sharing (DMABuf/GBM) fails on NVIDIA's proprietary driver, especially under Flatpak, and leaves windows blank. Pickit sets `WEBKIT_DMABUF_RENDERER_FORCE_SHM=1`, which keeps WebKit's normal renderer but hands frames over through shared memory. It deliberately doesn't use `WEBKIT_DISABLE_DMABUF_RENDERER`: in WebKit 2.54+ (the Flatpak's GNOME 51 runtime) that legacy path mis-draws composited layers, so shadows, rounded cards and animated elements vanish.

**One web process for all widgets.** Every WebKit view normally gets its own web process, which accounts for most of a widget's memory. Desktop widgets are created as "related views" of each other, so they share one process: about 40% less memory for a typical setup. The trade-off is that a crash or hang in that process restarts every widget, which the crash handler and watchdog do automatically. The maker's preview uses its own process.

**WebKit transparency.** Transparent WebKit pixels don't blend with parent GTK widgets. They punch through to whatever is behind the top-level window. Desktop widgets rely on exactly that. The maker's preview instead gives WebKit an opaque background matching the preview area.
