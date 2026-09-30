# Contributing to Pickit

Thanks for helping. Bug reports, widget ideas, desktop-compatibility reports and pull requests are all welcome.

## Reporting bugs

Please [open an issue](https://github.com/dengo07/pickit/issues/new/choose) and include:

- How you installed Pickit (Flatpak, AppImage or source) and the version (`pickit --version`)
- Your distro, desktop environment and session type (`echo $XDG_SESSION_TYPE`)
- The relevant lines of `~/.local/share/pickit/daemon.log`
- For a widget problem, its `widget.json` and `index.html` from `~/.local/share/pickit/widgets/<id>/`

**Compatibility reports are especially useful.** If Pickit works on a desktop not yet listed in the README (KDE, GNOME, Xfce, Wayland and so on), please tell us, even when everything works.

## How changes get into Pickit

`main` is protected: nobody pushes to it directly, not even the maintainer. Every change goes through a pull request:

1. **Fork the repository** and create a branch for your change, for example `git switch -c fix-battery-ring`. Keep one change per branch.
2. **Open a pull request against `main`** and fill in the template.
3. **CI runs** lint, the unit tests and the GTK and Wayland smoke tests. On your first contribution, a maintainer approves the run first.
4. **The maintainer reviews it.** Every pull request needs their approval (see [CODEOWNERS](.github/CODEOWNERS)). If you push new commits after an approval, it needs another look.
5. **It gets merged** once CI passes and every review conversation is resolved. Pull requests are merged with *Squash and merge*, so yours becomes one commit on `main`: write its title like a commit message, for example "Battery ring: show the charging state".

**Security problems never go in a public issue or pull request.** Report them privately, as described in [SECURITY.md](SECURITY.md).

## Development setup

```bash
sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-3.0 gir1.2-webkit2-4.1 gir1.2-gtklayershell-0.1 gir1.2-secret-1
git clone https://github.com/dengo07/pickit && cd pickit
python3 -m venv --system-site-packages .venv && . .venv/bin/activate   # system-site for PyGObject
pip install -e ".[api,dev]"
pickit
```

While you work, `pickit stop` followed by `pickit run` restarts the desktop daemon with your changes. The maker window reloads when you reopen it.

## Before opening a pull request

```bash
ruff check .
pytest
xvfb-run -a python3 tests/gtk_smoke.py    # X11 widgets and the Pickit window
```

Changes to how widgets are placed or moved should also pass the Wayland smoke test, which runs in a headless Sway (`sudo apt install sway gir1.2-gtklayershell-0.1`); CI runs it the same way:

```bash
export XDG_RUNTIME_DIR=$(mktemp -d); chmod 700 "$XDG_RUNTIME_DIR"
WLR_BACKENDS=headless WLR_RENDERER=pixman WLR_LIBINPUT_NO_DEVICES=1 sway -c tests/sway-headless.conf &
WAYLAND_DISPLAY=wayland-1 GDK_BACKEND=wayland python3 tests/wayland_smoke.py
```

- Keep pull requests focused, and describe what you tested and on which desktop.
- UI changes: include a screenshot.
- Changes to `pickit/prompts/system.md` affect every generated widget. Show a few before-and-after examples.
- Anything that touches command execution or approval (`bridge.py`, `store.py`'s hashing, `runtime.py`'s host wrappers) needs extra care. See [SECURITY.md](SECURITY.md).

## Adding a widget to the gallery

Gallery widgets live in [`pickit/gallery/`](pickit/gallery/), one JSON file each (see [the gallery format](docs/WIDGET_FORMAT.md#gallery-widgets)). A good gallery widget:

- is native (a few MB of memory) and looks good on both light and dark wallpapers,
- uses only tools every distro has (`/proc`, `/sys`, coreutils, `awk`, `python3`'s standard library) and read-only commands,
- has `sample` output with made-up values, never your own hostname, location or music,
- passes `pytest tests/test_gallery.py`, which checks that the sample covers every field it displays.

Include a screenshot of it on your desktop in the pull request. The easiest way to make one: build it in Pickit, then run `pickit export <id>` and add a `gallery` object to the file.

## Project layout

[docs/DEVELOPER_GUIDE.md](docs/DEVELOPER_GUIDE.md) explains every file and has recipes for common changes (a new component, filter, setting, menu action, backend or gallery widget).

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for how the maker, the daemon and the widget store fit together, and [docs/PACKAGING.md](docs/PACKAGING.md) for the Flatpak and AppImage builds.

## Releasing (maintainers)

1. On a branch, bump `__version__` in `pickit/__init__.py`, add a `<release>` to `pickit/data/io.github.dengo07.Pickit.metainfo.xml` and update `CHANGELOG.md`. Merge it through a pull request like any other change.
2. Tag the merged commit and push the tag:
   ```bash
   git switch main && git pull
   git tag -a v1.2.3 -m "Pickit 1.2.3" && git push origin v1.2.3
   ```
   The release workflow builds and attaches `Pickit.flatpak`, `Pickit-x86_64.AppImage` and `Pickit.flatpakref`, and updates the Flatpak repository on GitHub Pages.
3. **Security fixes** don't go through a public pull request. Prepare them in the security advisory's temporary private fork, let the reporter verify them, merge them from the advisory page, release, and then publish the advisory.

By contributing you agree that your contributions are licensed under the [MIT License](LICENSE), and to follow the [Code of Conduct](CODE_OF_CONDUCT.md).
