"""Warnings for the approval dialog about commands that do risky things.

This is a reading aid, not a security check: shell is too flexible to prove a command safe, and
a command without warnings can still be harmful. It points out the patterns a widget almost
never needs, so they stand out when the user reads the command.
"""

import re

_HOME = r"(?:~|\$HOME|\$\{HOME\}|/home/[^/\s]+)"

# (pattern, warning). Patterns are matched case-sensitively against the whole command.
DANGER = [
    (r"(?:^|[\s;&|(`])(?:sudo|pkexec|doas|su)(?:\s|$)", "Asks for administrator rights"),
    (r"(?:curl|wget|fetch)\b[^|;&]*\|\s*(?:sudo\s+)?(?:ba|z|da)?sh\b"
     r"|(?:curl|wget)\b[^|;&]*\|\s*(?:python3?|perl|ruby|node)\b",
     "Downloads code from the internet and runs it"),
    (r"base64\s+(?:-d|--decode)\b[^|;&]*\|\s*(?:ba)?sh\b|\beval\s+[\"']?\$\(",
     "Runs code that it builds while running"),
    (r"(?:sh|bash)\s+<\(\s*(?:curl|wget)", "Downloads code from the internet and runs it"),
    (_HOME + r"/\.(?:ssh|gnupg|password-store|pki)\b|\bid_(?:rsa|ed25519|ecdsa)\b|\.netrc\b|"
     r"\.git-credentials\b|\.docker/config\.json",
     "Touches passwords, keys or other credentials"),
    (_HOME + r"/(?:\.mozilla|\.config/(?:google-chrome|chromium|BraveSoftware|vivaldi|microsoft-edge)|"
     r"\.local/share/keyrings|snap/firefox)", "Touches browser data or saved passwords"),
    (r"\.config/autostart\b|\.(?:bashrc|bash_profile|profile|zshrc|zprofile|xprofile|xinitrc)\b|\bcrontab\b|"
     r"systemctl\s+--user\s+(?:enable|link|edit)|\.config/systemd/user\b|\.local/share/applications\b",
     "Makes something start automatically or changes your shell setup"),
    (r"(?:\.local/share|\.config)/pickit\b|approvals\.json|widget\.json",
     "Changes Pickit's own widgets, settings or approvals"),
    (r"\brm\s+(?:-[a-zA-Z]*[rR]|--recursive)|\bshred\b|\bmkfs\b|\bdd\s+[^|;&]*\bof=|>\s*/dev/(?:sd|nvme|hd)",
     "Deletes or overwrites files or disks"),
    (r"(?:^|[\s;&|(])(?:nc|ncat|netcat|socat|telnet)\s|/dev/(?:tcp|udp)/", "Opens a raw network connection"),
    (r"\bcurl\b[^|;&]*(?:\s-d\s|\s--data\b|\s-F\s|\s--form\b|\s-T\s|\s--upload-file\b|-X\s*(?:POST|PUT))"
     r"|\bwget\b[^|;&]*--post-(?:data|file)",
     "Sends data to a server"),
    (r"\bchmod\s+[^|;&]*(?:\+s|[0-7]?[4-7][0-7]{3})\b", "Changes file permissions in an unusual way"),
]
# Not dangerous, but worth knowing when choosing how commands run.
NOTES = [
    (r"\bbusctl\s+--user\b|\bgdbus\b|\bdbus-send\b|\bplayerctl\b|\bqdbus\b",
     "Uses your desktop session (D-Bus): it only works with full access, not in the restricted sandbox"),
]
_DANGER = [(re.compile(p), w) for p, w in DANGER]
_NOTES = [(re.compile(p), w) for p, w in NOTES]


def warnings(cmd: str) -> list[str]:
    """Risky things this command appears to do, each once, most serious first."""
    found = []
    for pattern, text in _DANGER:
        if pattern.search(cmd) and text not in found:
            found.append(text)
    return found


_INTERNET = re.compile(r"\b(?:curl|wget)\b|https?://")


def notes(cmd: str, network: bool = False) -> list[str]:
    """Things that matter in the restricted sandbox."""
    found = [text for pattern, text in _NOTES if pattern.search(cmd)]
    if not network and _INTERNET.search(cmd):
        found.append('Seems to use the internet but isn\'t marked "network": true, so it can\'t reach it in the '
                     "sandbox. Ask the AI to mark it, or add it in the Code tab")
    return found
