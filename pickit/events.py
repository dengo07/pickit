"""System events that should refresh widget data right away instead of on the next timer:
power changes (UPower), waking from sleep (logind) and network changes (NetworkManager)."""

from gi.repository import Gio, GLib

DEBOUNCE_MS = 700
# UPower re-broadcasts timestamps every ~30 s; only these properties mean something changed.
POWER_PROPERTIES = {"OnBattery", "Percentage", "State", "IsPresent"}


class SystemEvents:
    """Calls `on_change(reason)` on the GTK main loop, debounced, after relevant events.

    Every source is optional: if a service is missing (or the sandbox doesn't allow it),
    widgets simply keep their normal refresh intervals.
    """

    def __init__(self, on_change):
        self.on_change = on_change
        self._pending: dict[str, int] = {}
        self._bus = None
        try:
            self._bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
        except GLib.Error as e:
            print(f"pickit: no system bus, event refresh disabled ({e.message})", flush=True)
            return
        # Battery level, charging state, AC plugged in or out.
        self._subscribe("org.freedesktop.UPower", "org.freedesktop.DBus.Properties",
                        "PropertiesChanged", self._on_power)
        # Suspend and resume: arg0 is True before sleeping and False after waking.
        self._subscribe("org.freedesktop.login1", "org.freedesktop.login1.Manager",
                        "PrepareForSleep", self._on_sleep)
        # Connectivity changes (weather, IP, VPN widgets...).
        self._subscribe("org.freedesktop.NetworkManager", "org.freedesktop.NetworkManager",
                        "StateChanged", lambda _p: self._fire("network"))

    def _subscribe(self, sender, interface, member, handler):
        self._bus.signal_subscribe(sender, interface, member, None, None, Gio.DBusSignalFlags.NONE,
                                   lambda _c, _s, _o, _i, _m, params: handler(params))

    def _on_power(self, params):
        _interface, changed, _invalidated = params.unpack()
        if POWER_PROPERTIES & set(changed):
            self._fire("power")

    def _on_sleep(self, params):
        if not params.unpack()[0]:  # woke up
            self._fire("resume", 2000)
            self._fire("resume-late", 15000)  # again once Wi-Fi has reconnected

    def _fire(self, reason, delay_ms=DEBOUNCE_MS):
        if reason in self._pending:
            return

        def run():
            del self._pending[reason]
            self.on_change(reason)
            return False

        self._pending[reason] = GLib.timeout_add(delay_ms, run)
