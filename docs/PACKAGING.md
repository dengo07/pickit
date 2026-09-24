# Packaging

Releases ship two self-contained packages. Pushing a `v*` tag triggers [`.github/workflows/release.yml`](../.github/workflows/release.yml), which:

1. builds the AppImage and the Flatpak,
2. publishes a **Flatpak repository on GitHub Pages** at `https://dengo07.github.io/pickit/`, with a landing page, `Pickit.flatpakref` and `pickit.flatpakrepo`,
3. creates the GitHub Release with `Pickit-x86_64.AppImage`, `Pickit.flatpakref` and the offline bundle `Pickit.flatpak`.

## One-time repository setup

Do this before the first release:

1. **Settings → Pages → Build and deployment → Source:** choose **GitHub Actions**.
2. **Settings → Environments → `github-pages` → Deployment branches and tags:** add a rule of type **Tag** with the pattern `v*`. By default only `main` may deploy, and releases deploy from a tag.
3. **Settings → Secrets and variables → Actions → New repository secret:** name it `FLATPAK_GPG_PRIVATE_KEY`, and paste the complete ASCII-armored private signing key as the value (`-----BEGIN PGP PRIVATE KEY BLOCK-----` … `END`).

## Why a Flatpak repository

Most desktops don't open a `.flatpak` bundle on double-click (Linux Mint's Software Manager doesn't), and bundles never update. A `.flatpakref` points at a repository instead: software centers open it with an Install button, and `flatpak update` or the system updater picks up new releases.

Each release replaces the Pages site with a fresh repository containing only the newest build; clients update from whatever commit they have.

### Signing

System-wide installs, which is what software centers do, **refuse unsigned repositories** ("Can't pull from untrusted non-gpg verified remote"). So the release workflow signs the commits, the summary and the offline bundle.

- The public key is [`packaging/flatpak/pickit.gpg`](../packaging/flatpak/pickit.gpg), fingerprint `C703 D4EE 2B0E 241A AF93  8A08 85CC 870A 31C3 A7A4`. It's embedded as `GPGKey=` in [`Pickit.flatpakref`](../packaging/flatpak/site/Pickit.flatpakref) and [`pickit.flatpakrepo`](../packaging/flatpak/site/pickit.flatpakrepo).
- The private key lives only in the `FLATPAK_GPG_PRIVATE_KEY` secret and with the maintainer. The workflow refuses to publish without it, or if it doesn't match `pickit.gpg`.
- **Don't lose or replace the key.** Installed copies trust only this key, so a new key means every user has to reinstall to keep getting updates. If you ever must rotate it, update `pickit.gpg`, the `GPGKey=` lines and the secret together.

Software centers still label the app "unverified", because that label means "not from Flathub", not "unsigned".

## Flatpak: `make flatpak` → `dist/Pickit.flatpak`

```bash
flatpak install --user flathub org.gnome.Sdk//51 org.flatpak.Builder
make flatpak
flatpak install dist/Pickit.flatpak
```

- **Runtime:** `org.gnome.Platform//51`, which provides GTK 3, WebKit2GTK 4.1, PyGObject, pycairo and Python 3.14.
- **Python dependencies:** the `anthropic` SDK and its dependencies are pinned as wheels, with URL and sha256, in [`packaging/flatpak/python-deps.json`](../packaging/flatpak/python-deps.json). The build needs no network, as Flathub requires. After changing the Python version or updating the SDK, regenerate the file:
  ```bash
  packaging/flatpak/gen-python-deps.py 3.14
  ```
- **Sandbox permissions** (all explained in the manifest):
  - `--socket=x11`: forces XWayland on Wayland, since widgets need X11 window hints.
  - `--talk-name=org.freedesktop.Flatpak`: runs approved widget commands and the Claude CLI on the host through `flatpak-spawn --host`, and starts the daemon in its own sandbox so it outlives the maker.
  - `--filesystem=xdg-config/autostart:create`, `xdg-data/pickit`, `xdg-config/pickit`: the autostart entry, plus data shared with the other builds.
- **Flathub:** the manifest follows Flathub's offline-build rules. The host-escape permission is inherent to what the app does (running commands on your system), so expect to justify it in the submission.

## AppImage: `make appimage` → `dist/Pickit-x86_64.AppImage`

Build dependencies (Debian/Ubuntu):

```bash
sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-3.0 gir1.2-webkit2-4.1 \
  glib-networking librsvg2-common libglib2.0-bin python3-pip rsync curl
make appimage
```

[`packaging/appimage/build-appimage.sh`](../packaging/appimage/build-appimage.sh) does the following:

1. Copies the system Python (the stdlib, without tests or tkinter), PyGObject and pycairo, and pip-installs `anthropic`.
2. Copies WebKit's helper processes, the typelibs, the GIO TLS module, the SVG pixbuf loader and the GTK schemas.
3. Collects every shared library these need with `ldd`, skipping the [AppImage excludelist](https://github.com/AppImageCommunity/pkg2appimage/blob/master/excludelist): glibc, GPU drivers, X11, fontconfig and similar. These must come from the user's system.
4. Binary-patches `libwebkit2gtk-4.1.so.0`. WebKit has its helper-process directory compiled in, with no runtime override in release builds, so the path is replaced by a same-length relative one. [`AppRun`](../packaging/appimage/AppRun) makes the working directory `$APPDIR/usr`.
5. Packs everything with `appimagetool` (static runtime, so users don't need libfuse2).

**Compatibility floor:** the AppImage runs on distros whose glibc is at least as new as the build machine's. The release workflow builds on Ubuntu 24.04 (glibc 2.39). Building on 22.04 would extend support to glibc 2.35.

**Testing on a different OS image:** extract the AppImage and run it inside another runtime, for example
```bash
./Pickit-x86_64.AppImage --appimage-extract
flatpak run --command=sh --socket=x11 --share=ipc --device=dri --socket=session-bus \
  --filesystem=home --env=APPDIR=$PWD/squashfs-root org.freedesktop.Platform//26.08 \
  -c "$PWD/squashfs-root/AppRun"
```
