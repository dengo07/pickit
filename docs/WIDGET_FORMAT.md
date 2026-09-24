# Widget format

Each widget is a folder in `~/.local/share/pickit/widgets/<id>/`:

```
widget.json   manifest (size, position, commands, approval, state)
index.html    the widget itself: a normal web page
```

You can write widgets by hand, or edit generated ones. After changing files, right-click the widget and choose **Reload**.

## `widget.json`

```jsonc
{
  "id": "cpu-meter-3f9a1c",          // folder name
  "name": "CPU Meter",
  "width": 300,                      // window size in px
  "height": 120,
  "position": "bottom-right",        // initial anchor (see below)
  "x": 1596, "y": 936,               // set once the widget has been moved
  "enabled": true,                   // shown on the desktop
  "commands": {
    "cpu":  { "cmd": "awk '{print $1}' /proc/loadavg", "interval": 2 },
    "play": { "cmd": "playerctl play-pause",            "interval": 0 }
  },
  "approved_hash": "…",              // written when you approve the commands
  "history": ["a CPU meter", "make it blue"]
}
```

- `position` is one of `top-left`, `top-center`, `top-right`, `center-left`, `center`, `center-right`, `bottom-left`, `bottom-center`, `bottom-right`. It's used until the widget is moved.
- `interval` is in seconds (minimum 1). `0` marks an **action** (play/pause, next track...): it never runs by itself, only when the widget calls `widget.run()`. For data that only needs loading once, use a long interval such as `86400`.
- Commands run through `bash -c` as your user, in your home directory, with a 20-second timeout and 256 KB of captured output.
- Periodic commands (`interval` > 0) also re-run right away when something relevant happens: power plugged or unplugged, or battery level changes (commands with an interval of 5 minutes or less), and waking from sleep or network changes (all periodic commands). On-demand commands (`interval: 0`) only ever run when the widget calls them.
- Widgets heal themselves: if a widget's page crashes, or stops responding for about a minute, Pickit restarts it.

## The `window.widget` JS API

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

## Rendering rules

- The window is exactly `width` × `height` and transparent. Use `html, body { margin: 0; background: transparent; overflow: hidden; }` and draw your own panel if you want one.
- `backdrop-filter` can't blur what's behind the window.
- Browser `fetch()` to other sites is blocked by CORS. Fetch data with a command instead (`curl -s …`).
- External scripts and fonts load normally over the network, for example from `cdn.jsdelivr.net` or `fonts.googleapis.com`.
- Right-click is reserved for Pickit's widget menu.

The full contract the model is given is in [`pickit/prompts/system.md`](../pickit/prompts/system.md).
