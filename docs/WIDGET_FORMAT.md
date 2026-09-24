# Widget format

Each widget is a folder in `~/.local/share/pickit/widgets/<id>/`:

```
widget.json   manifest: engine, size, position, commands, approval, state
ui.json       native engine: the component tree
index.html    html engine: the widget page
```

A widget has exactly one of `ui.json` or `index.html`, depending on its engine. You can write widgets by hand, or edit generated ones. After changing files, right-click the widget and choose **Reload**.

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
  "commands": {
    "cpu":  { "cmd": "awk '{print $1}' /proc/loadavg", "interval": 2 },
    "play": { "cmd": "busctl --user call …",            "interval": 0 }
  },
  "approved_hash": "…",              // written when you approve the commands
  "history": ["a CPU meter", "make it blue"]
}
```

- `position` is one of `top-left`, `top-center`, `top-right`, `center-left`, `center`, `center-right`, `bottom-left`, `bottom-center`, `bottom-right`. It's used until the widget is moved.
- `interval` is in seconds (minimum 1). `0` marks an **action** (play/pause, next track...). It never runs by itself, only when a button (native) or `widget.run()` (html) triggers it. For data that only needs loading once, use a long interval such as `86400`.
- Commands run through `bash -c` as your user, in your home directory, with a 20-second timeout and 256 KB of captured output.
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
| `button` | runs an interval-0 command | `action`, `text` and/or `icon`, `size`, `color`, `background`, `radius` |

Every component also accepts `margin`, `width`, `height`, `halign`/`valign` (start/center/end/fill), `hexpand`/`vexpand`, `visible`, `tooltip` and `opacity`.

Colors are `#rrggbb`, `#rrggbbaa`, `rgba(...)`, or, for `background`, a `linear-gradient(...)`/`radial-gradient(...)`. Styling is generated by Pickit from these properties only. Values containing `;`, braces, quotes or `url(` are rejected, so a widget can't inject CSS.

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

Rendering rules:
- The window is exactly `width` × `height` and transparent. Use `html, body { margin: 0; background: transparent; overflow: hidden; }` and draw your own panel if you want one.
- `backdrop-filter` can't blur what's behind the window.
- Browser `fetch()` to other sites is blocked by CORS. Fetch data with a command instead (`curl -s …`).
- External scripts and fonts load normally over the network, for example from `cdn.jsdelivr.net` or `fonts.googleapis.com`.
- Right-click is reserved for Pickit's widget menu.
- Never animate forever (`animation: … infinite`, or re-triggered transitions). WebKit then redraws at 60 fps nonstop.

The full contract the model is given is in [`pickit/prompts/system.md`](../pickit/prompts/system.md).
