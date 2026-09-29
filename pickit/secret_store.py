"""API keys in the desktop keyring (the Secret Service: GNOME Keyring, KWallet, KeePassXC...).

Entries are labelled with the config folder they belong to, so a separate Pickit config
(PICKIT_CONFIG_HOME, as the tests use) never sees or changes the real keys. Every call
fails softly: without a keyring, config.py keeps the key in config.json (mode 0600) instead.
"""

_schema = None


def _secret():
    """libsecret, or None if it isn't installed."""
    global _schema
    try:
        import gi
        gi.require_version("Secret", "1")
        from gi.repository import Secret
    except (ImportError, ValueError):
        return None
    if _schema is None:
        _schema = Secret.Schema.new("io.github.dengo07.Pickit", Secret.SchemaFlags.NONE,
                                    {"key": Secret.SchemaAttributeType.STRING,
                                     "config": Secret.SchemaAttributeType.STRING})
    return Secret


def _attributes(name: str) -> dict:
    from .config import CONFIG_DIR
    return {"key": name, "config": str(CONFIG_DIR)}


def _service():
    """The desktop's Secret Service, or None. Talked to directly rather than through libsecret's
    password_* calls: inside Flatpak those use a keyring file in the sandbox instead, and the
    AppImage and source versions (which share config.json) couldn't find the keys there."""
    secret = _secret()
    if secret is None:
        return None, None
    try:
        return secret, secret.Service.get_sync(secret.ServiceFlags.OPEN_SESSION, None)
    except Exception:  # GLib.Error: no Secret Service on this desktop
        return None, None


def get(name: str) -> str | None:
    """The stored value, or None if there is none or no keyring."""
    _, service = _service()
    if service is None:
        return None
    try:
        value = service.lookup_sync(_schema, _attributes(name), None)
    except Exception:  # e.g. the keyring is locked and the user didn't unlock it
        return None
    return value.get_text() if value is not None else None


def set(name: str, value: str) -> bool:
    """Store a value. False if there's no keyring to store it in."""
    secret, service = _service()
    if service is None:
        return False
    try:
        return bool(service.store_sync(_schema, _attributes(name), secret.COLLECTION_DEFAULT,
                                       f"Pickit: {name.replace('_', ' ')}",
                                       secret.Value.new(value, -1, "text/plain"), None))
    except Exception:
        return False


def clear(name: str) -> None:
    _, service = _service()
    if service is None:
        return
    try:
        service.clear_sync(_schema, _attributes(name), None)
    except Exception:
        pass
