# Widget format

Each widget is a folder in `~/.local/share/pickit/widgets/<id>/`:

```
widget.json   manifest: engine, size, position, commands, approval, state
ui.json       native engine: the component tree
index.html    html engine: the widget page
versions/     the last 10 earlier versions, for Undo in the editor
```

A widget has exactly one of `ui.json` or `index.html`, depending on its engine. The easiest way to edit one is the **Code** tab in the Pickit window, which checks your changes before applying them. You can also edit the files directly; then right-click the widget and choose **Reload**.

## Engines

| | `native` (default) | `html` |
|---|---|---|
| Drawn by | GTK + Cairo, inside Pickit's widget daemon | WebKit (a web page) |
| Memory | a few MB per widget; a native-only desktop never loads WebKit | about 50–150 MB for the first widget; the others share its web process |
| Can draw | the components below: text, icons, images, bars, rings, sparklines, buttons, cards, rows, columns | anything: SVG, canvas, animation, filters |
| Written as | a JSON component tree with data bindings (no code) | HTML/CSS/JavaScript |

In **Auto** mode, the AI uses native whenever the design fits and HTML otherwise. You can force either engine in the Pickit window, or convert a widget by refining it ("make it native", "rewrite it in HTML").

## `widget.json`

```jsonc
{
  "id": "cpu-meter-3f9a1c",          // folder name
  "name": "CPU Meter",
  "engine": "native",                // "native" or "html" (a missing engine means html)
  "width": 300,                      // window size in px
  "height": 120,
  "position": "bottom-right",        // initial anchor (see below)
  "x": 1596, "y": 936,               // set once the widget has been moved
  "enabled": true,                   // shown on the desktop
  "monitor": 1,                      // optional: which monitor (0 = first); unset = the main one
  "locked": false,                   // optional: can't be dragged
  "click_through": false,            // optional: clicks go to whatever is underneath
  "expandable": {"width": 300, "height": 230},  // optional: the size when expanded (see below)
  "expanded": false,                 // set while the widget is open; never exported
  "commands": {
    "cpu":  { "cmd": "awk '{print $1}' /proc/loadavg", "interval": 2 },
    "w":    { "cmd": "curl -s 'https://wttr.in/?format=j1'", "interval": 900, "network": true },
    "play": { "cmd": "busctl --user call …",            "interval": 0 }
  },
  "history": ["a CPU meter", "make it blue"]
}
```

- `position` is one of `top-left`, `top-center`, `top-right`, `center-left`, `center`, `center-right`, `bottom-left`, `bottom-center`, `bottom-right`. It's used until the widget is moved.
- `interval` is in seconds (minimum 1). `0` marks an **action** (play/pause, next track...). It never runs by itself, only when a button (native) or `widget.run()` (html) triggers it. For data that only needs loading once, use a long interval such as `86400`.
- `"network": true` marks a command that uses the internet. In the restricted command runner, only marked commands can reach the network; with full access it changes nothing. Mark every command that uses the internet, and only those.
- Commands run through `bash -c`, with a 20-second timeout and 256 KB of captured output: as your user in your home directory (the default), or in a restricted sandbox without your home folder and desktop session (Settings; see [SECURITY.md](../SECURITY.md)).
- Approvals aren't stored in the widget. Pickit keeps them in `~/.config/pickit/approvals.json`, so a widget folder that's copied or edited never arrives approved.
- Periodic commands (`interval` > 0) also re-run right away when something relevant happens: power plugged or unplugged, or battery level changes (commands with an interval of 5 minutes or less), and waking from sleep or network changes (all periodic commands).
- Widgets heal themselves. If an html widget's page crashes, or stops responding for about a minute, Pickit restarts it. Native widgets have no separate page process that could crash.

## Native engine: `ui.json`

`ui.json` is one component. Each component is an object with a `"type"`, and **only the listed properties are allowed**. The validator rejects anything else with a message pointing at the exact spot, for example `ui.children[1] (label): unknown property "colour"`.

### Components

| type | purpose | properties |
|---|---|---|
| `column`, `row` | stack children vertically / horizontally | `children`, `spacing`, `padding`, `background`, `radius`, `border`, `border_width`, `shadow` (none/soft/medium/strong) |
| `card` | a `column` with panel defaults: dark translucent background, radius 16, padding 12, soft shadow | same as `column` |
| `overlay` | layers children; the first is the base, the others are placed with `halign`/`valign` | `children` |
| `spacer` | flexible space along its row or column, or a fixed `size` | `size` |
| `label` | text | `text`, `size`, `weight` (light…heavy), `color`, `align`, `font`, `ellipsize`, `wrap`, `letter_spacing`, `text_shadow` |
| `icon` | a theme icon (`name`, e.g. `media-playback-start-symbolic`) or an emoji/glyph (`text`) | `name`/`text`, `size`, `color` |
| `image` | a picture from a `data:` URL, a local path or http(s) | `src`, `size`, `radius`, `fit` (cover/contain) |
| `progress` | a horizontal bar | `value`, `max`, `color`, `track`, `thickness`, `radius` |
| `ring` | a circular gauge; its `children` are centered inside | `value`, `max`, `size`, `thickness`, `color`, `track`, `start`, `children` |
| `sparkline` | a small line chart of a value's recent history | `value`, `points`, `color`, `fill`, `min`, `max`, `line_width` |
| `button` | runs an interval-0 command, or expands/collapses the widget | `action` (a command key) **or** `toggle: true` (never both), `text` and/or `icon`, `size`, `color`, `background`, `radius` |
| `expander` | the expandable part of an expandable widget: `header` always shows, `children` only when expanded | `header`, `children` (lists of components), `animation` (`slide`/`fade`/`none`), `chevron` (draw ▾/▴, default true), `trigger` (`header`: a click on the header toggles, the default; `button`: only a `toggle` button does) |

Every component also accepts `margin`, `width`, `height`, `halign`/`valign` (start/center/end/fill), `hexpand`/`vexpand`, `visible`, `tooltip` and `opacity`.

Colors are `#rrggbb`, `#rrggbbaa`, `rgba(...)`, or, for `background`, a `linear-gradient(...)`/`radial-gradient(...)`. Styling is generated by Pickit from these properties only. Values containing `;`, braces, quotes or `url(` are rejected, so a widget can't inject CSS.

### Expandable widgets

A widget opens to show more when it declares a second size and, for native widgets, has one `expander`:

```jsonc
{"width": 300, "height": 84,                       // collapsed
 "expandable": {"width": 300, "height": 230},      // expanded: 80–1600 × 40–1200, like width/height
 "ui": {"type": "expander",
        "header": [{"type": "label", "text": "CPU {s.cpu}%"}],
        "children": [{"type": "label", "text": "Memory {s.mem}%"}]}}
```

- One `expander` per widget, as the root or a direct child of it. `expandable` without an expander (or the reverse) is rejected, and so is a `toggle` button without one.
- Click the header (without dragging) to toggle it, use a `"toggle": true` button with `"trigger": "button"`, or choose **Expand**/**Collapse** in the widget's menu. Toggling never runs a command.
- The window grows away from the edge it's anchored to: down from the top, up from the bottom. It's kept on screen, and a widget pushed back to fit returns to its place when it collapses.
- Pickit remembers whether a widget is open (`expanded` in `widget.json`) without reloading it. Exports and imports never carry it, so an imported widget starts collapsed.

### Data binding

A command's output becomes data under the command's key. JSON is parsed as JSON, `key=value` lines become an object, and anything else is plain text.

```jsonc
{"type": "ring", "value": "{battery.capacity}",                       // a template
 "color": [{"when": "{battery.capacity} <= 15", "value": "#f87171"},  // a choice: first match wins,
           "#4ade80"],                                                //   the last plain entry is the default
 "children": [{"type": "label", "text": "{battery.capacity|default:--}%"}]}
```

- **Templates** work in any text or number property: `"{w.weather.0.maxtempC}°"` (list items by index). A property that is exactly one `{...}` keeps its type.
- **Filters**: `round`, `round:1`, `int`, `upper`, `lower`, `trim`, `truncate:20`, `default:--`, `bytes`, `duration`, `mmss`, `time:%H:%M` (timestamps and ISO dates), `mul:x`, `div:x`, `add:x`, `sub:x`, `percent`, `word:n`, `join:, `.
- **`now`** is always available and updates every second: `"{now|time:%H:%M:%S}"`.
- **Conditions** for `visible` and choices: `== != < <= > >=`, `and`, `or`, `not`, parentheses, and quoted strings (`{battery.status} == 'Not charging'`).
- Bindings are evaluated by a small built-in interpreter, never by `eval`, so a widget file can't run code. Only the approved commands ever run.
- Only the parts of a widget that depend on changed data are updated, so an idle native widget costs no CPU.

### The theme

`theme` is also always available: the colors of the user's widget theme (**Theme** in Pickit's header). Use them instead of fixed colors so the widget restyles with the theme and stays readable in light and dark mode:

| Token | Use it for |
|---|---|
| `{theme.accent}` | the highlight: ring and bar fills, today's date, a play button |
| `{theme.text}` / `{theme.muted}` | main and secondary text |
| `{theme.card}` / `{theme.border}` | panel backgrounds and borders; `{theme.border}` also suits ring and bar tracks |
| `{theme.good}` / `{theme.warn}` / `{theme.bad}` | levels, e.g. in a choice: `[{"when": "{cpu} > 90", "value": "{theme.bad}"}, "{theme.accent}"]` |

A widget that uses any `{theme.…}` token is *themed*: its `card`s also take the theme's background, border and corner radius, and its text the theme's text color and font. Widgets without tokens (everything made before Pickit 1.5.0) keep the fixed dark card look, so a light theme never makes their white text unreadable. Fixed colors still work in themed widgets when a design needs them.

Complete examples, which the AI also learns from: [`pickit/prompts/native_examples/`](../pickit/prompts/native_examples/).

## HTML engine: `index.html` and the `window.widget` JS API

The API is available before your scripts run:

```js
// Called every time `cpu` finishes. `out` is trimmed stdout; `res` is {out, err, code}.
widget.on("cpu", (out, res) => {
  if (res.code !== 0) return;          // command failed; keep the last value
  document.querySelector("#cpu").textContent = `${out}`;
});

// Run a declared command now, e.g. from a button.
button.onclick = () => widget.run("play");

// Let the user drag the window from any element:
header.addEventListener("mousedown", (e) => widget.drag(e));
// ...or mark it declaratively:
// <div data-drag>...</div>
```

If a result already exists when you subscribe, the callback fires immediately.

Expandable HTML widgets (with `expandable` in `widget.json`) can ask to change size, but never say a size; Pickit uses the declared one:

```js
header.onclick = () => widget.toggle();   // also widget.expand(), widget.collapse()
widget.expanded;                          // the current state
window.addEventListener("pickit-expand", (e) => console.log(e.detail.expanded));
// and in CSS: html[data-pickit-expanded="true"] .details { opacity: 1; }
```

Lay the page out for the expanded size with `overflow: hidden`: while collapsed, the window clips the details away. Pickit accepts about one request per 220 ms, ignores them in widgets without `expandable`, and restores the saved state when the page loads.

The theme is available as CSS variables: `--pickit-accent`, `--pickit-text`, `--pickit-muted`, `--pickit-card`, `--pickit-border`, `--pickit-good`, `--pickit-warn`, `--pickit-bad`, `--pickit-radius` (with `px`) and `--pickit-font` (only when the user chose a font). Give a fallback so the page also works outside Pickit: `color: var(--pickit-text, #f4f1ea)`. The variables change live when the user switches themes; for anything CSS can't do, read `widget.theme` (the same values, plus `mode`: `"dark"` or `"light"`) and listen for the change:

```js
window.addEventListener("pickit-theme", () => chart.setColor(widget.theme.accent));
```

Rendering rules:
- The window is exactly `width` × `height` and transparent. Use `html, body { margin: 0; background: transparent; overflow: hidden; }` and draw your own panel if you want one.
- `backdrop-filter` can't blur what's behind the window.
- The page is served from `pickit-widget://<widget id>/` with a Content Security Policy. It may load scripts and styles from `cdn.jsdelivr.net` and `cdnjs.cloudflare.com`, and fonts from Google Fonts (`fonts.googleapis.com`, `fonts.gstatic.com`) and those CDNs. Everything else that could reach the network is blocked: `fetch`, `XMLHttpRequest`, `WebSocket`, `sendBeacon`, forms, frames, workers, and images or media from URLs. Fetch data with a command instead (`curl -s …`), and use `data:` URLs, inline SVG or `<canvas>` for pictures.
- `file://` URLs are blocked too, and the scheme serves nothing but the page itself, so there are no separate asset files: keep everything in `index.html`.
- The page can't navigate away, open windows or start downloads.
- `localStorage` works and belongs to that widget alone; other widgets can't read it.
- Right-click is reserved for Pickit's widget menu.
- Never animate forever (`animation: … infinite`, or re-triggered transitions). WebKit then redraws at 60 fps nonstop.

The full contract the model is given is in [`pickit/prompts/system.md`](../pickit/prompts/system.md).

## .pickit files

A shared widget is one JSON file with the `.pickit` extension (MIME type `application/x-pickit-widget`):

```jsonc
{
  "pickit": 1,                       // file format version
  "exported_by": "Pickit 1.3.0",
  "name": "System Rings",
  "engine": "native",
  "width": 380, "height": 156,
  "position": "top-right",
  "commands": { "stats": { "cmd": "…", "interval": 3 } },
  "ui": { "type": "card", "children": [ … ] }   // or "html": "<!doctype html>…"
}
```

- Export writes only these fields. The approval hash, the screen position you dragged it to, whether it's shown, and your prompt history stay on your machine.
- Import validates the file exactly like an AI-generated widget (same whitelist, same limits, at most 2 MB), ignores any approval inside it, and asks you to approve its commands. A plain widget spec without the `pickit` key also imports.
- A file from a newer Pickit with a higher `pickit` version is refused with a message to update.

## Gallery widgets

The gallery is [`pickit/gallery/`](../pickit/gallery/): one widget spec per file, plus a `gallery` object that Pickit strips before using the spec:

```jsonc
"gallery": {
  "order": 20,                      // position in the gallery
  "category": "Time",
  "description": "New York, London and Tokyo at a glance.",
  "sample": { "t": "ny=09:41 Fri\nlondon=14:41 Fri\ntokyo=22:41 Fri" }
}
```

`sample` is made-up command output that the gallery preview shows instead of running the commands, so browsing never runs anything. A list of outputs is delivered in order, which fills sparklines. The tests check that every gallery widget validates, that every data command has sample output, and that every field the widget displays exists in its sample.
