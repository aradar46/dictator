#!/usr/bin/env python3
"""Hold global shortcut, record audio, transcribe locally, paste 
from clipboard."""
import json
from pathlib import Path
import sys
import threading

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gst", "1.0")
gi.require_version("GdkWayland", "4.0")
from gi.repository import Adw, Gdk, GdkWayland, Gio, GLib, Gst, Gtk

from shortcuts import PortalShortcuts, clean_trigger
from recorder import AudioRecorder, get_audio_input_devices
from transcriber import Transcriber, MODELS, model_exists, download_model_async, load_config, save_config
from session import DictationSession
from background import request_background
from tray import TrayIcon

APP_ID = "io.github.aradar46.Dictator"


def log(event, **fields):
    print(json.dumps({"event": event, **fields}), flush=True)


class Dictator(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID)
        self.window = self.portal = None
        self.shortcut_trigger = None
        self.downloading_model = None
        self.download_cancel = None
        self.needs_model = False
        cfg = load_config()
        self.selected_mic_device = cfg.get("mic_device", None)
        self.selected_mic_name = cfg.get("mic_name", "System Default")
        self.transcriber = Transcriber()
        cache = Path(GLib.get_user_cache_dir()) / APP_ID
        self.recorder = AudioRecorder(
            cache,
            on_level=lambda level: self.dictation.on_audio_level(level),
            on_eos=lambda: self.dictation.on_audio_eos(),
            on_error=lambda msg: self.dictation.fail(msg),
        )
        self.dictation = DictationSession(self.recorder, self.transcriber, ui=self, log=log)

    def toast(self, message):
        self.overlay.add_toast(Adw.Toast.new(message))

    def update_idle_ui(self):
        trig = clean_trigger(self.shortcut_trigger)
        curr = self.transcriber.model_name
        label = MODELS.get(curr, {}).get("label", curr.capitalize())
        self.label.set_label("Dictator")
        self.detail.set_label(
            f"✓ Shortcut: {trig}\n\nHold to speak\nRelease to copy · Ctrl+V to paste\n"
            f"Mic: {self.selected_mic_name} · Model: {label}"
        )
        self.meter.set_value(0)
        self.settings_btn.set_sensitive(True)
        self.button.set_label("Hide to Background")
        self.button.set_sensitive(True)
        self.button.set_visible(True)
        self.button.remove_css_class("suggested-action")

    def show_about(self, *_):
        about = Adw.AboutWindow(
            application_name="Dictator",
            application_icon="io.github.aradar46.Dictator",
            version="0.1",
            developer_name="Aradar46",
            comments="Hold a global shortcut, record audio, transcribe it locally, and paste the result.",
            website="https://github.com/aradar46/dictator",
            issue_url="https://github.com/aradar46/dictator/issues",
            license_type=Gtk.License.GPL_3_0,
        )
        about.set_transient_for(self.window)
        about.present()

    def open_shortcut_settings(self):
        self.settings_popover.popdown()
        # Sandboxed: launching a host binary would need --talk-name=org.freedesktop.Flatpak,
        # which Flathub review treats as a sandbox escape. Show the steps instead.
        if Path("/.flatpak-info").is_file():
            return self.show_manual_shortcut_instructions()
        try:
            Gio.AppInfo.create_from_commandline(
                "gnome-control-center keyboard", None, Gio.AppInfoCreateFlags.NONE
            ).launch(None, None)
        except GLib.Error:
            self.show_manual_shortcut_instructions()

    def show_manual_shortcut_instructions(self):
        dialog = Adw.AlertDialog(
            heading="Change the Shortcut Manually",
            body=(
                "Settings couldn’t be opened automatically. To change it yourself:\n\n"
                "1. Open Settings → Keyboard.\n"
                "2. Choose “View and Customize Shortcuts”.\n"
                "3. Find Dictator under Global Shortcuts (granted by apps).\n"
                "4. Click it and press your new key combination."
            ),
        )
        dialog.add_response("ok", "Got it")
        dialog.present(self.window)

    def _build_picker(self, heading, items, on_pick):
        """items: list of (key, display_text). Returns (box, {key: button})."""
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.append(Gtk.Label(label=heading, halign=Gtk.Align.START, css_classes=["heading"]))
        buttons = {}
        for key, text in items:
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            row.append(Gtk.Label(label=text, halign=Gtk.Align.START, hexpand=True))
            btn = Gtk.Button()
            btn.connect("clicked", lambda _, k=key: on_pick(k))
            row.append(btn)
            box.append(row)
            buttons[key] = btn
        return box, buttons

    def build_settings_menu(self):
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, margin_top=10, margin_bottom=10, margin_start=10, margin_end=10)

        devs = [{"name": "System Default", "device": None}]
        try:
            devs.extend(get_audio_input_devices())
        except Exception:
            pass
        self.mic_devices = {d["name"]: d["device"] for d in devs}
        mic_box, self.mic_buttons = self._build_picker(
            "Microphone", [(d["name"], d["name"]) for d in devs],
            lambda name: self.choose_mic(name, self.mic_devices[name]))
        outer.append(mic_box)
        outer.append(Gtk.Separator())

        model_box, self.model_buttons = self._build_picker(
            "Whisper Model", [(k, f"{v['label']} ({v['size']})") for k, v in MODELS.items()],
            self.choose_model)
        outer.append(model_box)

        self.dl_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6, visible=False)
        self.download_progress = Gtk.ProgressBar(hexpand=True, show_text=True)
        self.dl_cancel_btn = Gtk.Button(label="Cancel")
        self.dl_cancel_btn.connect("clicked", lambda _: self.cancel_download())
        self.dl_box.append(self.download_progress)
        self.dl_box.append(self.dl_cancel_btn)
        outer.append(self.dl_box)
        outer.append(Gtk.Separator())

        shortcut_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        shortcut_row.append(Gtk.Label(label="Keyboard Shortcut", halign=Gtk.Align.START, hexpand=True))
        change_btn = Gtk.Button(label="Change…")
        change_btn.set_tooltip_text("Opens GNOME Settings ▸ Keyboard Shortcuts")
        change_btn.connect("clicked", lambda _: self.open_shortcut_settings())
        shortcut_row.append(change_btn)
        outer.append(shortcut_row)

        self.settings_popover.set_child(outer)
        self.refresh_mic_popover()
        self.refresh_model_popover()

    def refresh_mic_popover(self):
        curr = self.selected_mic_name
        for name, btn in self.mic_buttons.items():
            if name == curr:
                btn.set_label("✓ Active")
                btn.set_sensitive(False)
                accessible = f"Active microphone: {name}"
            else:
                btn.set_label("Select")
                btn.set_sensitive(True)
                accessible = f"Select microphone: {name}"
            btn.update_property([Gtk.AccessibleProperty.LABEL], [accessible])

    def choose_mic(self, name, device):
        self.selected_mic_name = name
        self.selected_mic_device = device
        cfg = load_config()
        cfg["mic_name"] = name
        cfg["mic_device"] = device
        save_config(cfg)
        if self.dictation.state == "idle":
            self.update_idle_ui()
        self.refresh_mic_popover()
        self.settings_popover.popdown()
        self.toast(f"Microphone: {name}")

    def auto_connect(self):
        if self.dictation.state == "setup" and not self.portal:
            self.enable()
        return GLib.SOURCE_REMOVE

    def prompt_for_model(self):
        """First run: no model on disk yet. Offer to fetch the default one."""
        model = MODELS[self.transcriber.model_name]
        self.needs_model = True
        self.dictation.state = "setup"
        self.label.set_label("One thing first")
        self.detail.set_label(
            f"Dictator transcribes on your machine, so it needs a speech model.\n"
            f"{model['label']} is a good default. Other sizes are in the menu."
        )
        self.button.set_label(f"Download {model['label']} ({model['size']})")
        self.button.add_css_class("suggested-action")
        self.button.set_sensitive(True)
        self.button.set_visible(True)
        self.settings_btn.set_sensitive(True)

    def on_button_clicked(self, button):
        if self.needs_model:
            return self.choose_model(self.transcriber.model_name)
        if self.dictation.state == "idle":
            self.window.set_visible(False)
        else:
            self.enable()

    def do_activate(self):
        if self.window:
            if self.dictation.state == "idle":
                self.update_idle_ui()
            self.window.present()
            return
        self.hold()
        Gst.init(None)
        self.window = Adw.ApplicationWindow(application=self, title="Dictator")
        self.window.set_default_size(520, 240)
        self.window.set_resizable(True)
        self.window.connect("close-request", self.close_window)
        self.window.connect("notify::is-active", self.focus_changed)

        header = Adw.HeaderBar()
        about_btn = Gtk.Button(icon_name="help-about-symbolic")
        about_btn.set_tooltip_text("About Dictator")
        about_btn.connect("clicked", self.show_about)
        header.pack_start(about_btn)

        self.settings_popover = Gtk.Popover()
        self.settings_btn = Gtk.MenuButton(icon_name="open-menu-symbolic")
        self.settings_btn.set_popover(self.settings_popover)
        self.settings_btn.set_tooltip_text("Microphone, model & shortcut settings")
        header.pack_end(self.settings_btn)

        layout = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        layout.append(header)

        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14, margin_start=24, margin_end=24, margin_top=14, margin_bottom=20)
        self.label = Gtk.Label(label="Dictator")
        self.label.add_css_class("title-2")
        self.detail = Gtk.Label(wrap=True, justify=Gtk.Justification.CENTER)
        self.detail.add_css_class("dim-label")
        self.build_settings_menu()

        self.meter = Gtk.LevelBar(min_value=0, max_value=1)
        self.meter.set_size_request(-1, 10)
        self.meter.set_margin_top(4)
        self.meter.set_margin_bottom(4)
        self.meter.update_property([Gtk.AccessibleProperty.LABEL], ["Microphone level"])
        self.spinner = Gtk.Spinner(visible=False)
        self.button = Gtk.Button(label="Enable Global Shortcut")
        self.button.add_css_class("suggested-action")
        self.button.connect("clicked", self.on_button_clicked)

        for w in (self.label, self.detail, self.meter, self.spinner, self.button):
            body.append(w)
        layout.append(body)

        self.overlay = Adw.ToastOverlay(child=layout)
        self.window.set_content(self.overlay)

        keys = Gtk.EventControllerKey()
        keys.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        keys.connect("key-pressed", self.key_pressed)
        keys.connect("key-released", self.key_released)
        self.window.add_controller(keys)

        quit_act = Gio.SimpleAction.new("quit", None)
        quit_act.connect("activate", lambda *_: self.quit())
        self.add_action(quit_act)
        self.set_accels_for_action("app.quit", ["<Control>q"])

        self.window.present()
        GLib.idle_add(self.auto_connect)
        try:
            request_background("Stays ready to transcribe your held-shortcut dictation",
                                on_result=lambda granted: log("background-registered", granted=granted))
        except GLib.Error as err:
            log("background-portal-unavailable", error=str(err))
        try:
            self.tray = TrayIcon(APP_ID, "Dictator", self.toggle_window, lambda: self.quit())
        except GLib.Error as err:
            log("tray-unavailable", error=str(err))

    def toggle_window(self):
        if self.window.get_visible():
            self.window.set_visible(False)
        else:
            self.window.present()
        log("started", flatpak=Path("/.flatpak-info").exists(), display=type(self.window.get_display()).__name__)

    def refresh_model_popover(self):
        curr = self.transcriber.model_name
        is_dl = bool(self.downloading_model)
        for k, btn in self.model_buttons.items():
            name = MODELS[k]["label"]
            if k == curr:
                btn.set_label("✓ Active")
                btn.set_sensitive(False)
                btn.remove_css_class("suggested-action")
                accessible = f"Active model: {name}"
            elif model_exists(k):
                btn.set_label("Select")
                btn.set_sensitive(not is_dl)
                btn.remove_css_class("suggested-action")
                accessible = f"Select {name} model"
            elif is_dl and k == self.downloading_model:
                btn.set_label("Downloading…")
                btn.set_sensitive(False)
                btn.remove_css_class("suggested-action")
                accessible = f"Downloading {name} model"
            else:
                btn.set_label("Download")
                btn.set_sensitive(not is_dl)
                btn.add_css_class("suggested-action")
                accessible = f"Download {name} model"
            btn.update_property([Gtk.AccessibleProperty.LABEL], [accessible])

    def choose_model(self, key):
        if model_exists(key):
            self.transcriber.set_model(key)
            if self.dictation.state == "idle":
                self.update_idle_ui()
            self.refresh_model_popover()
            self.settings_popover.popdown()
            self.toast(f"Switched to Whisper {MODELS[key]['label']}")
            if self.needs_model:
                self.needs_model = False
                self.button.remove_css_class("suggested-action")
                self.enable()
            return
        if self.downloading_model:
            return
        self.downloading_model = key
        self.download_cancel = threading.Event()
        self.refresh_model_popover()
        self.dl_box.set_visible(True)
        self.download_progress.set_fraction(0.0)
        self.download_progress.set_text(f"Downloading {MODELS[key]['label']}...")
        if self.needs_model:
            self.meter.set_value(0)
            self.detail.set_label("Downloading the speech model\nStarting…")
            self.button.set_label("Downloading…")
            self.button.set_sensitive(False)
        download_model_async(
            key,
            self.on_download_progress,
            lambda ok, err: self.on_download_done(key, ok, err),
            self.download_cancel
        )

    def cancel_download(self):
        if self.download_cancel:
            self.download_cancel.set()
        self.downloading_model = None
        self.dl_box.set_visible(False)
        self.refresh_model_popover()
        self.toast("Download cancelled")
        if self.needs_model:
            self.meter.set_value(0)
            self.prompt_for_model()

    def on_download_progress(self, frac, done, total):
        text = f"{int(frac * 100)}% ({done // (1024 * 1024)}MB / {total // (1024 * 1024)}MB)"
        self.download_progress.set_fraction(frac)
        self.download_progress.set_text(text)
        if self.needs_model:
            # Started from the main window, where the popover's progress bar isn't visible.
            self.meter.set_value(frac)
            self.detail.set_label(f"Downloading the speech model\n{text}")

    def on_download_done(self, key, success, error):
        self.downloading_model = None
        self.dl_box.set_visible(False)
        if success:
            self.transcriber.set_model(key)
            if self.dictation.state == "idle":
                self.update_idle_ui()
            self.refresh_model_popover()
            self.settings_popover.popdown()
            self.toast(f"Whisper {MODELS[key]['label']} ready")
            if self.needs_model:
                self.needs_model = False
                self.button.remove_css_class("suggested-action")
                self.enable()
        else:
            self.refresh_model_popover()
            if error:
                self.toast(f"Download failed: {error}")
            if self.needs_model:
                self.meter.set_value(0)
                self.prompt_for_model()   # back to a usable button, not a dead one

    def enable(self, button=None):
        if not self.transcriber.available():
            return self.prompt_for_model()
        if self.portal and self.portal.session:
            self.dictation.state = "idle"
            return self.update_idle_ui()
        self.button.set_sensitive(False)
        self.button.set_label("Connecting Shortcut...")
        self.detail.set_label("Choose and approve the shortcut in GNOME’s dialog.")
        try:
            self.portal = PortalShortcuts(
                on_activated=self.begin,
                on_deactivated=self.finish,
                on_bound=self._on_shortcut_bound,
                on_error=self.permission_denied
            )
            if not self.window.get_surface():
                self.window.realize()
            surface = self.window.get_surface()
            if isinstance(surface, GdkWayland.WaylandToplevel):
                surface.export_handle(lambda s, h, d: self.portal.bind("wayland:" + h), None)
            else:
                self.dictation.fail("Dictator needs a GNOME Wayland session.")
        except GLib.Error as err:
            self.dictation.fail(str(err))

    def _on_shortcut_bound(self, trigger, shortcuts):
        log("shortcut-bound", shortcuts=shortcuts)
        self.shortcut_trigger = trigger
        self.dictation.state = "idle"
        self.update_idle_ui()

    def begin(self, activation_token):
        self.dictation.begin(activation_token, self.selected_mic_device)

    def finish(self):
        self.dictation.finish()

    def focus_changed(self, *args):
        self.dictation.focus_changed()

    def key_pressed(self, ctrl, keyval, keycode, state):
        if keyval == Gdk.KEY_Escape and self.dictation.state in ("recording", "finalizing", "transcribing", "waiting-for-focus"):
            self.dictation.cancel()
            return True
        return False

    def key_released(self, ctrl, keyval, keycode, state):
        self.dictation.key_released(keyval)

    def close_window(self, win):
        if self.dictation.state in ("recording", "finalizing", "transcribing", "waiting-for-focus", "copied", "dismiss"):
            self.dictation.cancel()
        else:
            self.quit()
        return True

    def permission_denied(self, message):
        if self.portal:
            self.portal.close()
            self.portal = None
        self.dictation.state = "setup"
        self.label.set_label("Dictator")
        self.detail.set_label(message + "\nClick button below to enable.")
        self.button.set_label("Enable Global Shortcut")
        self.button.set_visible(True)
        self.button.set_sensitive(True)
        self.button.add_css_class("suggested-action")
        self.settings_btn.set_sensitive(True)
        self.window.present()
        log("permission-denied", message=message)

    def do_shutdown(self):
        self.dictation.stop_pipeline()
        self.transcriber.cancel()
        self.dictation.delete_recording()
        if self.portal:
            self.portal.close()
        Adw.Application.do_shutdown(self)


if __name__ == "__main__":
    raise SystemExit(Dictator().run(sys.argv))
