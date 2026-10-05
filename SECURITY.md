# Security policy

Pickit runs AI-generated code on your desktop, so its safety model is worth understanding.

## How Pickit contains widgets

- **Widget JavaScript can't reach your system directly.** Pages are served from Pickit's own `pickit-widget://` scheme, which serves the widget's page and nothing else: scripts can't read local files (`file://` access is off). Each widget is its own origin, so one widget can't read another's `localStorage`. The only way out is the `window.widget` bridge, which can only run commands **declared in the widget's `widget.json`**.
- **Declared commands never run until you approve them.** The approval dialog shows every command, its interval, whether it may use the internet, how it will run, and warnings for risky patterns (administrator rights, downloading and running code, touching credentials or browser data, autostart entries, Pickit's own files, sending data out). The warnings are a reading aid: shell is too flexible to prove a command safe.
- **Approvals are Pickit's own record, not part of the widget.** They live in `~/.config/pickit/approvals.json` (mode `0600`): which widget, the SHA-256 of its exact command set, when, from which Pickit version, where the widget came from (AI, gallery, file) and how commands ran. A widget file can't approve itself: copying or editing a widget's folder never carries an approval, and any change to any command, interval or internet flag needs approval again. **Settings → Approved commands** lists every approval and revokes any of them. Approvals that Pickit 1.5.1 and earlier stored inside `widget.json` were moved there once, when 1.5.2 first started; after that, an `approved_hash` in a widget file means nothing. This record proves consent to Pickit; it isn't protection against software that already runs as you, which could edit it like it could edit your `~/.bashrc`. With the restricted runner, widget commands themselves can't reach it.
- **How approved commands run** (**Settings → Widget commands run**, config `"command_runner"`):
  - **With full access to your account** (`"host"`, the default): through `bash -c` as your user, with a 20-second timeout. They can read and change your files, use the network and talk to your desktop session. Treat approving a command exactly like pasting it into your terminal.
  - **In a restricted sandbox** (`"restricted"`, needs bubblewrap): the system is read-only; your home folder (and every other home), `/run` (session and system sockets, including Docker's), the real `/tmp` and removable drives are hidden, and D-Bus, X11, Wayland and SSH-agent variables are removed. Only commands marked `"network": true` can use the internet. With the `passt` package installed, those get a network of their own; without it, they share your network, which also lets them reach the X server's abstract socket (other windows and the keyboard), and the approval dialog says so. Media widgets need the desktop session (D-Bus), so they only work with full access. Switching from the sandbox to full access asks again for every widget approved in the sandbox.
  - **Through your own wrapper** (a list, e.g. `["firejail", "--profile=pickit-widget", "--"]`), put in front of `bash -c`.

  Every runner fails closed: if bubblewrap or your wrapper is missing, or the setting is invalid, commands don't run, and Pickit never falls back to full access. `daemon.log` records why.
- **Network:** widget pages can reach only three content delivery networks, and only to load files. A Content Security Policy blocks `fetch`, `XMLHttpRequest`, `WebSocket`, `sendBeacon`, forms, frames, workers, and images or media from URLs. Pickit also blocks navigating away, opening windows and downloads. Data from the internet comes through approved commands instead. Two kinds of requests can still leave your computer:
  - **Scripts, styles and fonts from the allowed CDNs:** `cdn.jsdelivr.net`, `cdnjs.cloudflare.com` and Google Fonts (`fonts.googleapis.com`, `fonts.gstatic.com`). The AI uses them for libraries and fonts. The CDN sees your IP address and which files were requested. A malicious page could also hide a small amount of data in those addresses, for example in a font or package name. Who can read it depends on the CDN: its operator's logs, and possibly its public usage statistics. So this is a narrow channel, not a sealed wall.
  - **DNS lookups** that a page triggers with `<link rel="dns-prefetch">`. A determined page could use them to leak a few bytes.

  Widgets that load nothing from these CDNs, and all native widgets, make neither kind of request.
- **Flatpak:** the Flatpak sandbox does not contain widget commands or the Claude Code CLI. Both run on your system, outside the sandbox, through `flatpak-spawn --host` (the `org.freedesktop.Flatpak` permission), because running your approved commands there is the app's purpose. The sandbox protects Pickit's own window and widget pages, not what the commands do. To contain the commands, use the restricted runner above: it runs on the host too, so it works the same in the Flatpak, the AppImage and from source.
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
