# Changelog

All notable changes to this project are documented here.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- One-click Flatpak install with automatic updates: a Flatpak repository and landing page on GitHub Pages, plus `Pickit.flatpakref` in every release.

## [1.0.0] - 2026-09-24

### Added
- Generate desktop widgets from a plain-language description, with a live preview and conversational refinement.
- Claude backends: the Claude Code CLI (uses your existing login) and the Anthropic API; "Auto" picks whichever is available.
- A desktop daemon that keeps widgets in the desktop layer: below all windows, on every workspace, unaffected by Show Desktop, and back after a reboot.
- Shell-command data sources with an explicit approval step and hash-based re-approval.
- A widget context menu: edit with AI, reload, review commands, reset position, hide, delete.
- Self-contained Flatpak and AppImage packages.

[Unreleased]: https://github.com/dengo07/pickit/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/dengo07/pickit/releases/tag/v1.0.0
