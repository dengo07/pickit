# Security policy

Pickit runs AI-generated code on your desktop, so its safety model is worth understanding.

## How Pickit contains widgets

- **Widget JavaScript can't reach your system directly.** Pages are served from Pickit's own `pickit-widget://` scheme, which serves the widget's page and nothing else: scripts can't read local files (`file://` access is off). Each widget is its own origin, so one widget can't read another's `localStorage`. The only way out is the `window.widget` bridge, which can only run commands **declared in the widget's `widget.json`**.
- **Declared commands never run until you approve them.** The approval dialog shows every command and its interval. Pickit stores a SHA-256 hash of the approved command set, so any change to any command, including one made by the AI during a refine, requires approval again. The approval is a safeguard in Pickit's interface, not protection against software that already runs as you: such a program could write a widget with a matching hash, just as it could edit your `~/.bashrc`.
- **Commands run as your user**, through `bash -c`, with a 20-second timeout. Treat approving a command exactly like pasting it into your terminal.
- **Network:** widget pages can reach only three content delivery networks, and only to load files. A Content Security Policy blocks `fetch`, `XMLHttpRequest`, `WebSocket`, `sendBeacon`, forms, frames, workers, and images or media from URLs. Pickit also blocks navigating away, opening windows and downloads. Data from the internet comes through approved commands instead. Two kinds of requests can still leave your computer:
  - **Scripts, styles and fonts from the allowed CDNs:** `cdn.jsdelivr.net`, `cdnjs.cloudflare.com` and Google Fonts (`fonts.googleapis.com`, `fonts.gstatic.com`). The AI uses them for libraries and fonts. The CDN sees your IP address and which files were requested. A malicious page could also hide a small amount of data in those addresses, for example in a font or package name. Who can read it depends on the CDN: its operator's logs, and possibly its public usage statistics. So this is a narrow channel, not a sealed wall.
  - **DNS lookups** that a page triggers with `<link rel="dns-prefetch">`. A determined page could use them to leak a few bytes.

  Widgets that load nothing from these CDNs, and all native widgets, make neither kind of request.
- **Flatpak:** the Flatpak sandbox does not contain widget commands or the Claude Code CLI. Both run on your system, outside the sandbox, through `flatpak-spawn --host` (the `org.freedesktop.Flatpak` permission), because running your approved commands there is the app's purpose. The sandbox protects Pickit's own window and widget pages, not what the commands do.
- **Widget pages share one WebKit process** on the desktop, which saves most of their memory. Pages are still separate origins and can't reach each other's storage, but a crash or hang restarts them all, and a WebKit flaw that escaped one page would reach the others.
- **Running Pickit in your own sandbox** (Firejail, bubblewrap): the login entry normally starts Pickit directly. Set `"autostart_command"` in `~/.config/pickit/config.json` to the command that starts it in your sandbox, for example `"firejail --profile=pickit ~/Apps/Pickit-x86_64.AppImage run"`; Pickit writes that into the login entry instead. `PICKIT_CONFIG_HOME` and `PICKIT_DATA_HOME` move Pickit's settings and widgets to other folders.
- **Imported widgets** (`.pickit` files) are treated like AI-generated ones: validated against the same whitelist and stripped of any approval they claim to carry. Nothing from a file opens until you trust it: its commands are shown for approval with a warning that anyone can write such a file, and an HTML widget without commands still asks, because it contains JavaScript. Rejecting cancels the import.
- **Gallery widgets** ship with Pickit and are reviewed like code, but they also ask for approval before their commands run. Previews in the gallery use sample data and run nothing.
- **API keys** are kept in your desktop keyring (GNOME Keyring, KWallet or another Secret Service) when there is one, and keys saved by earlier versions are moved there. Without a keyring they stay in `~/.config/pickit/config.json` with mode `0600`. Only the Pickit window reads them; the widget daemon never does. You can use the `ANTHROPIC_API_KEY` or `OPENROUTER_API_KEY` environment variables instead.
- **Where your prompts go:** to Anthropic with Claude Code or the Anthropic API; to OpenRouter **and the provider running the model you picked** with OpenRouter (check that provider's data policy, especially for free models); nowhere with Ollama, which runs on your computer. The prompt contains your widget description and, when refining, the widget's current files and commands.

Read commands before approving them, whichever model wrote them. Small local models make more mistakes. A generated command should be short, read-only and obviously related to the widget. Reject anything that deletes files, uses `sudo`, downloads and runs scripts, or sends data somewhere unexpected.

## Reporting a vulnerability

Please **don't open a public issue**. Use [GitHub private vulnerability reporting](https://github.com/dengo07/pickit/security/advisories/new) instead.

Examples of what we want to hear about:

- A way for widget HTML/JS to run commands that aren't declared or approved
- A way to change a widget's commands without triggering re-approval
- A `.pickit` file that runs commands, or gets past validation, without the user approving it
- Flaws in how commands, API keys or widget files are handled

You'll get a reply within a week. Supported versions: the latest release.
