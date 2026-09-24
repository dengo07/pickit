# Contributing to Pickit

Thanks for helping. Bug reports, widget ideas, desktop-compatibility reports and pull requests are all welcome.

## Reporting bugs

Please [open an issue](https://github.com/dengo07/pickit/issues/new/choose) and include:

- How you installed Pickit (Flatpak, AppImage or source) and the version (`pickit --version`)
- Your distro, desktop environment and session type (`echo $XDG_SESSION_TYPE`)
- The relevant lines of `~/.local/share/pickit/daemon.log`
- For a widget problem, its `widget.json` and `index.html` from `~/.local/share/pickit/widgets/<id>/`

**Compatibility reports are especially useful.** If Pickit works on a desktop not yet listed in the README (KDE, GNOME, Xfce, Wayland and so on), please tell us, even when everything works.

## Development setup

```bash
sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-3.0 gir1.2-webkit2-4.1
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
```

- Keep pull requests focused, and describe what you tested and on which desktop.
- UI changes: include a screenshot.
- Changes to `pickit/prompts/system.md` affect every generated widget. Show a few before-and-after examples.
- Anything that touches command execution or approval (`bridge.py`, `store.py`'s hashing, `runtime.py`'s host wrappers) needs extra care. See [SECURITY.md](SECURITY.md).

## Project layout

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for how the maker, the daemon and the widget store fit together, and [docs/PACKAGING.md](docs/PACKAGING.md) for the Flatpak and AppImage builds.

## Releasing (maintainers)

1. Bump `__version__` in `pickit/__init__.py` and add a `<release>` to `pickit/data/io.github.dengo07.Pickit.metainfo.xml`.
2. Update `CHANGELOG.md`.
3. Tag and push: `git tag v1.2.3 && git push origin v1.2.3`. The release workflow builds and attaches `Pickit.flatpak` and `Pickit-x86_64.AppImage`.

By contributing you agree that your contributions are licensed under the [MIT License](LICENSE), and to follow the [Code of Conduct](CODE_OF_CONDUCT.md).
