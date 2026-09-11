import uuid
from gi.repository import Gio, GLib

PORTAL = "org.freedesktop.portal.Desktop"
ROOT = "/org/freedesktop/portal/desktop"
BACKGROUND = "org.freedesktop.portal.Background"


def request_background(reason, on_result=None):
    """Ask the portal to register this process as a background app.

    on_result(granted: bool) is called once the user responds (or the
    portal auto-grants, which it does for unsandboxed apps on many setups).
    """
    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    token = "hold_bg_" + uuid.uuid4().hex
    sender = bus.get_unique_name()[1:].replace(".", "_")
    path = f"{ROOT}/request/{sender}/{token}"

    def on_response(conn, sender_name, obj_path, iface, sig, params):
        bus.signal_unsubscribe(sub[0])
        code, results = params.unpack()
        granted = code == 0 and results.get("background", False)
        if on_result:
            on_result(granted)

    sub = [bus.signal_subscribe(PORTAL, "org.freedesktop.portal.Request", "Response", path, None, Gio.DBusSignalFlags.NONE, on_response)]

    def on_call_done(conn, result):
        try:
            conn.call_finish(result)
        except GLib.Error:
            bus.signal_unsubscribe(sub[0])
            if on_result:
                on_result(False)

    options = {
        "handle_token": GLib.Variant("s", token),
        "reason": GLib.Variant("s", reason),
        "autostart": GLib.Variant("b", False),
    }
    bus.call(
        PORTAL, ROOT, BACKGROUND, "RequestBackground",
        GLib.Variant("(sa{sv})", ("", options)),
        GLib.VariantType.new("(o)"), Gio.DBusCallFlags.NONE, 10000, None,
        on_call_done,
    )
