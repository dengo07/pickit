# Security policy

Pickit runs AI-generated code on your desktop, so its safety model is worth understanding.

## How Pickit contains widgets

- **Widget JavaScript can't reach your system directly.** It runs in WebKit like a normal web page. The only way out is the `window.widget` bridge, which can only run commands **declared in the widget's `widget.json`**.
- **Declared commands never run until you approve them.** The approval dialog shows every command and its interval. Pickit stores a SHA-256 hash of the approved command set, so any change to any command, including one made by the AI during a refine, requires approval again.
- **Commands run as your user**, through `bash -c`, with a 20-second timeout. Treat approving a command exactly like pasting it into your terminal.
- **Network:** widget pages can load resources from the internet like any web page. Cross-origin `fetch()` is blocked by CORS, which is why data comes through approved commands instead.
- **Flatpak:** the Flatpak needs permission to run commands on the host (`org.freedesktop.Flatpak`), because running your approved commands there is the app's purpose. The sandbox therefore does not isolate approved commands.
- **API keys** are stored in `~/.config/pickit/config.json` with mode `0600`. You can use the `ANTHROPIC_API_KEY` environment variable instead.

Read commands before approving them. A generated command should be short, read-only and obviously related to the widget. Reject anything that deletes files, uses `sudo`, downloads and runs scripts, or sends data somewhere unexpected.

## Reporting a vulnerability

Please **don't open a public issue**. Use [GitHub private vulnerability reporting](https://github.com/dengobey/pickit/security/advisories/new) instead.

Examples of what we want to hear about:

- A way for widget HTML/JS to run commands that aren't declared or approved
- A way to change a widget's commands without triggering re-approval
- Flaws in how commands, API keys or widget files are handled

You'll get a reply within a week. Supported versions: the latest release.
