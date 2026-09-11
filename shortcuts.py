"""XDG Desktop Portal Global Shortcuts integration for Moonshine Dictate."""
import uuid
from gi.repository import Gio, GLib

PORTAL = "org.freedesktop.portal.Desktop"
ROOT = "/org/freedesktop/portal/desktop"
SHORTCUTS = "org.freedesktop.portal.GlobalShortcuts"


def clean_trigger(raw):
    t = str(raw or "Ctrl+Alt+Space").removeprefix("Press ")
    for k, v in [
        ("<Control>", "Ctrl+"),
        ("<Alt>", "Alt+"),
        ("<Shift>", "Shift+"),
        ("<Super>", "Super+"),
        ("<Meta>", "Meta+"),
    ]:
        t = t.replace(k, v)
    return t[:-1] + t[-1].upper() if len(t) >= 2 and t[-2] == "+" else t


class PortalShortcuts:
    def __init__(self, on_activated, on_deactivated=None, on_bound=None, on_error=None):
        self.on_activated = on_activated
        self.on_deactivated = on_deactivated
        self.on_bound = on_bound
        self.on_error = on_error
        self.session = None
        self.pending = {}
        self.bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        self.bus.signal_subscribe(
            PORTAL, SHORTCUTS, None, ROOT, None, Gio.DBusSignalFlags.NONE, self._on_signal
        )

    def bind(self, wayland_handle):
        def on_session_created(res):
            self.session = res["session_handle"]
            sc = [
                (
                    "dictate",
                    {
                        "description": GLib.Variant("s", "Toggle Moonshine Voice Dictation"),
                        "preferred_trigger": GLib.Variant("s", "CTRL+ALT+space"),
                    },
                )
            ]
            self._call(
                "BindShortcuts",
                "(oa(sa{sv})sa{sv})",
                (self.session, sc, wayland_handle),
                on_shortcuts_bound,
            )

        def on_shortcuts_bound(res):
            shortcuts = res.get("shortcuts", [])
            dictate_sc = next((props for name, props in shortcuts if name == "dictate"), None)
            if not dictate_sc:
                if self.on_error:
                    self.on_error("No recording shortcut was granted.")
                return
            trigger = clean_trigger(dictate_sc.get("trigger_description", "Ctrl+Alt+Space"))
            if self.on_bound:
                self.on_bound(trigger, shortcuts)

        self._call("CreateSession", "(a{sv})", (), on_session_created)

    def _call(self, method, signature, args, callback):
        token = "moonshine_" + uuid.uuid4().hex
        sender = self.bus.get_unique_name()[1:].replace(".", "_")
        path = f"{ROOT}/request/{sender}/{token}"

        def on_response(bus, sender, path, iface, sig, params):
            sub = self.pending.pop(path, None)
            if sub:
                self.bus.signal_unsubscribe(sub)
            code, res = params.unpack()
            if code:
                if self.on_error:
                    self.on_error("Shortcut permission was cancelled or denied.")
            else:
                callback(res)

        self.pending[path] = self.bus.signal_subscribe(
            PORTAL,
            "org.freedesktop.portal.Request",
            "Response",
            path,
            None,
            Gio.DBusSignalFlags.NONE,
            on_response,
        )
        opts = {"handle_token": GLib.Variant("s", token)}
        if method == "CreateSession":
            opts["session_handle_token"] = GLib.Variant("s", "moonshine_" + uuid.uuid4().hex)

        def on_call_done(conn, result):
            try:
                conn.call_finish(result)
            except GLib.Error as err:
                sub = self.pending.pop(path, None)
                if sub:
                    self.bus.signal_unsubscribe(sub)
                if self.on_error:
                    self.on_error(f"Could not reach shortcuts portal: {err}")

        self.bus.call(
            PORTAL,
            ROOT,
            SHORTCUTS,
            method,
            GLib.Variant(signature, (*args, opts)),
            GLib.VariantType.new("(o)"),
            Gio.DBusCallFlags.NONE,
            10000,
            None,
            on_call_done,
        )

    def _on_signal(self, bus, sender, path, iface, sig, params):
        session, *args = params.unpack()
        if session != self.session or args[0] != "dictate":
            return
        if sig == "Activated":
            token = args[2].get("activation_token") if len(args) > 2 else None
            self.on_activated(token)
        elif sig == "Deactivated" and self.on_deactivated:
            self.on_deactivated()

    def close(self):
        for path, sub in list(self.pending.items()):
            self.bus.signal_unsubscribe(sub)
        self.pending.clear()
        if self.session:
            self.bus.call(
                PORTAL,
                self.session,
                "org.freedesktop.portal.Session",
                "Close",
                None,
                None,
                Gio.DBusCallFlags.NONE,
                1000,
                None,
                None,
            )
            self.session = None
