"""org.kde.StatusNotifierItem tray icon over raw D-Bus. No libayatana-appindicator,
so no GTK3/libdbusmenu dependency chain bundled into the flatpak.

Only works if the desktop implements the StatusNotifierWatcher side (GNOME needs
the "AppIndicator and KStatusNotifierItem Support" extension). If nothing is
listening, RegisterStatusNotifierItem just fails and the icon silently never
appears; the app still works without it.
"""
from gi.repository import Gio, GLib

WATCHER = "org.kde.StatusNotifierWatcher"
WATCHER_PATH = "/StatusNotifierWatcher"
ITEM_PATH = "/StatusNotifierItem"
MENU_PATH = "/MenuBar"

ITEM_XML = """
<node>
  <interface name="org.kde.StatusNotifierItem">
    <property name="Category" type="s" access="read"/>
    <property name="Id" type="s" access="read"/>
    <property name="Title" type="s" access="read"/>
    <property name="Status" type="s" access="read"/>
    <property name="IconName" type="s" access="read"/>
    <property name="Menu" type="o" access="read"/>
    <property name="ItemIsMenu" type="b" access="read"/>
    <method name="Activate">
      <arg type="i" name="x" direction="in"/>
      <arg type="i" name="y" direction="in"/>
    </method>
    <method name="SecondaryActivate">
      <arg type="i" name="x" direction="in"/>
      <arg type="i" name="y" direction="in"/>
    </method>
    <method name="ContextMenu">
      <arg type="i" name="x" direction="in"/>
      <arg type="i" name="y" direction="in"/>
    </method>
  </interface>
</node>
"""

MENU_XML = """
<node>
  <interface name="com.canonical.dbusmenu">
    <property name="Version" type="u" access="read"/>
    <method name="GetLayout">
      <arg type="i" name="parentId" direction="in"/>
      <arg type="i" name="recursionDepth" direction="in"/>
      <arg type="as" name="propertyNames" direction="in"/>
      <arg type="u" name="revision" direction="out"/>
      <arg type="(ia{sv}av)" name="layout" direction="out"/>
    </method>
    <method name="AboutToShow">
      <arg type="i" name="id" direction="in"/>
      <arg type="b" name="needUpdate" direction="out"/>
    </method>
    <method name="Event">
      <arg type="i" name="id" direction="in"/>
      <arg type="s" name="eventId" direction="in"/>
      <arg type="v" name="data" direction="in"/>
      <arg type="u" name="timestamp" direction="in"/>
    </method>
  </interface>
</node>
"""

SHOW_ID, QUIT_ID = 1, 2


class TrayIcon:
    """Left-click toggles the window; right-click shows Show/Quit."""

    def __init__(self, icon_name, title, on_toggle, on_quit):
        self.icon_name = icon_name
        self.title = title
        self.on_toggle = on_toggle
        self.on_quit = on_quit
        self.bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        item_iface = Gio.DBusNodeInfo.new_for_xml(ITEM_XML).interfaces[0]
        menu_iface = Gio.DBusNodeInfo.new_for_xml(MENU_XML).interfaces[0]
        self.bus.register_object(ITEM_PATH, item_iface, self._item_call, self._item_get_prop, None)
        self.bus.register_object(MENU_PATH, menu_iface, self._menu_call, self._menu_get_prop, None)
        self.bus.call(
            WATCHER, WATCHER_PATH, WATCHER, "RegisterStatusNotifierItem",
            GLib.Variant("(s)", (ITEM_PATH,)),
            None, Gio.DBusCallFlags.NONE, 5000, None, self._on_registered,
        )

    def _on_registered(self, conn, result):
        try:
            conn.call_finish(result)
        except GLib.Error:
            pass  # No StatusNotifierWatcher running; icon just never appears.

    def _item_call(self, conn, sender, path, iface, method, params, invocation):
        if method in ("Activate", "SecondaryActivate"):
            self.on_toggle()
        invocation.return_value(None)

    def _item_get_prop(self, conn, sender, path, iface, name):
        values = {
            "Category": GLib.Variant("s", "ApplicationStatus"),
            "Id": GLib.Variant("s", "dictator"),
            "Title": GLib.Variant("s", self.title),
            "Status": GLib.Variant("s", "Active"),
            "IconName": GLib.Variant("s", self.icon_name),
            "Menu": GLib.Variant("o", MENU_PATH),
            "ItemIsMenu": GLib.Variant("b", False),
        }
        return values.get(name)

    def _menu_call(self, conn, sender, path, iface, method, params, invocation):
        if method == "GetLayout":
            children = [
                GLib.Variant("(ia{sv}av)", (SHOW_ID, {"label": GLib.Variant("s", "Show Dictator")}, [])),
                GLib.Variant("(ia{sv}av)", (QUIT_ID, {"label": GLib.Variant("s", "Quit")}, [])),
            ]
            root = (0, {"children-display": GLib.Variant("s", "submenu")}, children)
            invocation.return_value(GLib.Variant("(u(ia{sv}av))", (1, root)))
        elif method == "AboutToShow":
            invocation.return_value(GLib.Variant("(b)", (False,)))
        elif method == "Event":
            item_id, event_id, _data, _timestamp = params.unpack()
            if event_id == "clicked":
                if item_id == SHOW_ID:
                    self.on_toggle()
                elif item_id == QUIT_ID:
                    self.on_quit()
            invocation.return_value(None)
        else:
            invocation.return_value(None)

    def _menu_get_prop(self, conn, sender, path, iface, name):
        if name == "Version":
            return GLib.Variant("u", 3)
        return None
