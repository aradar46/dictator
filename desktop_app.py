#!/usr/bin/env python3
"""Dictator - Standalone Desktop Dictation Popup for GNOME Wayland."""
import argparse
import os
from pathlib import Path
import re
import subprocess
import sys
import threading

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("GdkWayland", "4.0")
from gi.repository import Adw, Gdk, GdkWayland, Gio, GLib, Gtk

from background import request_background
from shortcuts import PortalShortcuts

from moonshine_voice import AgentFlow, MicTranscriber, ModelArch, get_spelling_model_path

APP_ID = "io.github.aradar46.Dictator"
VERSION = "0.2.0"
REPO_URL = "https://github.com/aradar46/dictator"

def limit_cpu_cores(num_cores: int = 2):
    """Cap process to specific number of CPU cores to avoid pegging all CPUs."""
    try:
        os.environ["OMP_NUM_THREADS"] = str(num_cores)
        os.environ["OPENBLAS_NUM_THREADS"] = str(num_cores)
        os.environ["MKL_NUM_THREADS"] = str(num_cores)
        os.environ["ORT_NUM_THREADS"] = str(num_cores)
        total_cpus = os.cpu_count() or 4
        cores = set(range(min(num_cores, total_cpus)))
        os.sched_setaffinity(0, cores)
    except Exception as e:
        pass

CSS = b"""
window.dictate-window {
    border-radius: 12px;
}
.dictate-text text {
    font-size: 15pt;
    line-height: 1.5;
    padding: 14px;
    background-color: @theme_bg_color;
    color: @theme_fg_color;
}
.status-pill {
    padding: 3px 10px;
    border-radius: 12px;
    font-size: 0.85rem;
    font-weight: 600;
}
.status-loading {
    background-color: rgba(255, 204, 102, 0.18);
    color: #ffcc66;
}
.status-listening {
    background-color: rgba(61, 220, 151, 0.2);
    color: #3ddc97;
}
.status-paused {
    background-color: rgba(255, 123, 114, 0.2);
    color: #ff7b72;
}
.big-action {
    font-weight: 700;
    padding: 8px 18px;
}
"""


def copy_to_clipboard(text: str):
    """Copy text to clipboard with Wayland persistence."""
    try:
        clipboard = Gdk.Display.get_default().get_clipboard()
        clipboard.set(text)
    except Exception:
        pass
    try:
        subprocess.run(["wl-copy", text], check=False)
    except Exception:
        pass


class DictateWindow(Adw.ApplicationWindow):
    def __init__(self, app, model_name="medium", device=None):
        super().__init__(application=app, title="Dictator")
        self.app = app
        self.model_name = model_name
        self.device = device
        self.arch_map = {
            "tiny": ModelArch.TINY_STREAMING,
            "base": ModelArch.BASE_STREAMING,
            "medium": ModelArch.MEDIUM_STREAMING,
        }
        self.arch = self.arch_map.get(model_name.lower(), ModelArch.MEDIUM_STREAMING)

        self.mic = None
        self.agent = None
        self.is_listening = False
        self.undo_stack = []

        self.set_default_size(560, 320)
        self.add_css_class("dictate-window")

        self.build_ui()

        self.shortcuts = None
        self.connect("map", lambda _: self.bind_shortcut())
        self.connect("close-request", self.on_close_request)

        # Start loading model in background thread
        threading.Thread(target=self.load_model_worker, daemon=True).start()

    def build_ui(self):
        # Header bar
        header = Adw.HeaderBar()
        title_widget = Adw.WindowTitle(
            title="Dictator",
            subtitle=f"{self.model_name.capitalize()} Streaming Model",
        )
        header.set_title_widget(title_widget)

        # Status badge
        self.status_label = Gtk.Label(label="Loading...")
        self.status_label.add_css_class("status-pill")
        self.status_label.add_css_class("status-loading")
        header.pack_start(self.status_label)

        # Mic button
        self.mic_btn = Gtk.Button(icon_name="audio-input-microphone-symbolic")
        self.mic_btn.set_sensitive(False)
        self.mic_btn.connect("clicked", lambda _: self.toggle_mic())
        header.pack_start(self.mic_btn)

        about_btn = Gtk.Button(icon_name="help-about-symbolic", tooltip_text="About Dictator")
        about_btn.connect("clicked", lambda _: self.show_about())
        header.pack_end(about_btn)

        # Layout
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        box.append(header)

        # Scrolled Text view
        self.scroll = Gtk.ScrolledWindow(vexpand=True, hexpand=True)
        self.text_view = Gtk.TextView(
            wrap_mode=Gtk.WrapMode.WORD_CHAR,
            top_margin=12,
            bottom_margin=12,
            left_margin=14,
            right_margin=14,
        )
        self.text_view.add_css_class("dictate-text")
        self.buffer = self.text_view.get_buffer()

        self.tag_prov = self.buffer.create_tag("provisional", font="italic", foreground="#6ea8fe")
        self.mark_prov = None

        self.scroll.set_child(self.text_view)
        box.append(self.scroll)

        # Bottom actions
        bottom_bar = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=8,
            margin_top=8,
            margin_bottom=10,
            margin_start=12,
            margin_end=12,
        )

        cancel_btn = Gtk.Button(label="Cancel (Esc)")
        cancel_btn.connect("clicked", lambda _: self.hide_session())
        bottom_bar.append(cancel_btn)

        clear_btn = Gtk.Button(label="Clear")
        clear_btn.connect("clicked", lambda _: self.clear_text())
        bottom_bar.append(clear_btn)

        spacer = Gtk.Box(hexpand=True)
        bottom_bar.append(spacer)

        self.copy_btn = Gtk.Button(label="Copy & Close (↵)")
        self.copy_btn.add_css_class("suggested-action")
        self.copy_btn.add_css_class("big-action")
        self.copy_btn.set_icon_name("edit-copy-symbolic")
        self.copy_btn.connect("clicked", lambda _: self.copy_and_hide())
        bottom_bar.append(self.copy_btn)

        box.append(bottom_bar)
        self.set_content(box)

        # Key controller
        key_ctrl = Gtk.EventControllerKey()
        key_ctrl.connect("key-pressed", self.on_key_pressed)
        self.add_controller(key_ctrl)

    def load_model_worker(self):
        spelling_path = None
        try:
            spelling_path = get_spelling_model_path("en")
        except Exception:
            pass

        self.mic = (
            MicTranscriber()
            .model_arch(self.arch)
            .spelling_model(spelling_path)
            .update_interval(0.6)
            .on_text(lambda t: GLib.idle_add(self.on_provisional, t))
        )
        if self.device is not None:
            dev = int(self.device) if str(self.device).isdigit() else self.device
            self.mic.device(dev)

        self.mic.load()

        self.agent = (
            AgentFlow()
            .speech(False)
            .beeps(False)
            .trigger_threshold(0.8)
            .otherwise(lambda t: GLib.idle_add(self.on_commit, t))
            .use_mic_transcriber(self.mic)
        )

        commands = [
            (["new line"], "new_line"),
            (["scratch that"], "scratch_that"),
            (["delete character", "delete letter"], "delete_character"),
            (["delete word"], "delete_word"),
            (["delete sentence"], "delete_sentence"),
            (["stop dictation", "pause dictation"], "pause"),
            (["start dictation", "resume dictation"], "resume"),
        ]

        for phrases, cmd_name in commands:
            handler = (lambda name: (lambda d: GLib.idle_add(self.on_command, name)))(cmd_name)
            for phrase in phrases:
                self.agent.always(phrase, handler)

        self.agent.load()

        GLib.idle_add(self.on_engine_ready)

    def on_engine_ready(self):
        self.mic_btn.set_sensitive(True)
        self.start_listening()

    def start_listening(self):
        if self.agent and not self.is_listening:
            self.agent.start_listening()
            self.is_listening = True
            self.status_label.set_label("Listening")
            self.status_label.remove_css_class("status-loading")
            self.status_label.remove_css_class("status-paused")
            self.status_label.add_css_class("status-listening")

    def stop_listening(self):
        if self.agent and self.is_listening:
            self.agent.stop_listening()
            self.release_microphone()
            self.is_listening = False
            self.status_label.set_label("Paused")
            self.status_label.remove_css_class("status-listening")
            self.status_label.add_css_class("status-paused")

    def bind_shortcut(self):
        """Bind Ctrl+Alt+Space through the portal, which needs a Wayland handle."""
        if self.shortcuts:
            return
        surface = self.get_surface()
        if not isinstance(surface, GdkWayland.WaylandToplevel):
            return

        def exported(toplevel, handle, *_):
            self.shortcuts = PortalShortcuts(
                on_activated=lambda token: GLib.idle_add(self.toggle_dictation, token),
                on_error=lambda msg: print(f"Shortcut: {msg}", file=sys.stderr),
            )
            self.shortcuts.bind(f"wayland:{handle}")
            request_background("Listen for the dictation shortcut while hidden")

        surface.export_handle(exported)

    def present_with_token(self, token):
        """Raise the window. Wayland needs the portal's activation token."""
        if token:
            self.set_startup_id(token)
        self.present()

    def toggle_dictation(self, token=None):
        """Show and listen when parked, otherwise pause or resume in place."""
        if self.is_listening:
            self.stop_listening()
        else:
            self.present_with_token(token)
            self.start_listening()
        return GLib.SOURCE_REMOVE

    def show_about(self):
        # AdwDialog is clipped by the 560x320 parent window.
        about = Adw.AboutWindow(
            transient_for=self,
            modal=True,
            application_name="Dictator",
            application_icon=APP_ID,
            version=VERSION,
            developer_name="aradar46",
            developers=["aradar46 https://github.com/aradar46"],
            website=REPO_URL,
            issue_url=f"{REPO_URL}/issues",
            license_type=Gtk.License.GPL_3_0,
            comments="Hold to dictate, locally.\n"
                     "Offline speech to text, powered by Moonshine Voice.",
        )
        about.present()

    def release_microphone(self):
        """Close the audio stream so the desktop stops showing a recording icon.

        stop_listening() halts transcription but leaves the stream open.
        close() would release it but also drops the loaded model, so close
        the stream directly; start() reopens it when _sd_stream is None.
        """
        stream = getattr(self.mic, "_sd_stream", None)
        if stream is not None:
            try:
                stream.close()
            except Exception:
                pass
            self.mic._sd_stream = None

    def toggle_mic(self):
        if self.is_listening:
            self.stop_listening()
        else:
            self.start_listening()

    def clear_provisional(self):
        if self.mark_prov:
            iter_start = self.buffer.get_iter_at_mark(self.mark_prov)
            iter_end = self.buffer.get_end_iter()
            self.buffer.delete(iter_start, iter_end)
            self.buffer.delete_mark(self.mark_prov)
            self.mark_prov = None

    def on_provisional(self, text):
        if not self.is_listening or not text:
            self.clear_provisional()
            return GLib.SOURCE_REMOVE

        self.clear_provisional()
        end_iter = self.buffer.get_end_iter()

        needs_space = False
        if end_iter.get_offset() > 0:
            prev = end_iter.copy()
            prev.backward_char()
            char = self.buffer.get_text(prev, end_iter, False)
            if char and not char.isspace():
                needs_space = True

        prefix = " " if needs_space else ""
        offset = end_iter.get_offset()
        self.buffer.insert_with_tags(end_iter, prefix + text, self.tag_prov)

        prov_iter = self.buffer.get_iter_at_offset(offset)
        self.mark_prov = self.buffer.create_mark("prov_start", prov_iter, True)
        self.scroll_to_bottom()
        return GLib.SOURCE_REMOVE

    def on_commit(self, text):
        words = text.strip()
        self.clear_provisional()
        if not words:
            return GLib.SOURCE_REMOVE

        self.remember_state()
        end_iter = self.buffer.get_end_iter()

        needs_space = False
        if end_iter.get_offset() > 0:
            prev = end_iter.copy()
            prev.backward_char()
            char = self.buffer.get_text(prev, end_iter, False)
            if char and not char.isspace():
                needs_space = True

        prefix = " " if needs_space else ""
        self.buffer.insert(end_iter, prefix + words)
        self.scroll_to_bottom()
        return GLib.SOURCE_REMOVE

    def on_command(self, cmd_name):
        self.clear_provisional()
        if cmd_name == "new_line":
            self.remember_state()
            end_iter = self.buffer.get_end_iter()
            self.buffer.insert(end_iter, "\n")
        elif cmd_name == "scratch_that":
            self.undo_last()
        elif cmd_name == "delete_word":
            self.delete_word_backward()
        elif cmd_name == "delete_sentence":
            self.delete_sentence_backward()
        elif cmd_name == "pause":
            self.stop_listening()
        elif cmd_name == "resume":
            self.start_listening()
        self.scroll_to_bottom()
        return GLib.SOURCE_REMOVE

    def remember_state(self):
        start = self.buffer.get_start_iter()
        end = self.buffer.get_end_iter()
        text = self.buffer.get_text(start, end, False)
        self.undo_stack.append(text)
        if len(self.undo_stack) > 30:
            self.undo_stack.pop(0)

    def undo_last(self):
        if self.undo_stack:
            prev = self.undo_stack.pop()
            self.buffer.set_text(prev)

    def delete_word_backward(self):
        start = self.buffer.get_start_iter()
        end = self.buffer.get_end_iter()
        text = self.buffer.get_text(start, end, False)
        trimmed = re.sub(r"\s+$", "", text)
        m = re.search(r"\S+$", trimmed)
        if m:
            new_text = trimmed[: m.start()]
            self.buffer.set_text(new_text)

    def delete_sentence_backward(self):
        start = self.buffer.get_start_iter()
        end = self.buffer.get_end_iter()
        text = self.buffer.get_text(start, end, False)
        trimmed = re.sub(r"[\s.!?]+$", "", text)
        idx = max(trimmed.rfind("."), trimmed.rfind("!"), trimmed.rfind("?"), trimmed.rfind("\n"))
        if idx >= 0:
            new_text = trimmed[: idx + 1]
            self.buffer.set_text(new_text)
        else:
            self.buffer.set_text("")

    def clear_text(self):
        self.clear_provisional()
        self.buffer.set_text("")

    def scroll_to_bottom(self):
        end = self.buffer.get_end_iter()
        self.text_view.scroll_to_iter(end, 0.0, False, 0.0, 0.0)

    def on_key_pressed(self, controller, keyval, keycode, state):
        if keyval == Gdk.KEY_Escape:
            self.hide_session()
            return True
        elif keyval == Gdk.KEY_q and (state & Gdk.ModifierType.CONTROL_MASK):
            self.quit_app()
            return True
        elif keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            if not (state & Gdk.ModifierType.SHIFT_MASK):
                self.copy_and_hide()
                return True
        return False

    def copy_and_hide(self):
        # Keep the provisional text; clear_provisional() would drop it.
        if self.mark_prov:
            self.buffer.delete_mark(self.mark_prov)
            self.mark_prov = None
        start = self.buffer.get_start_iter()
        end = self.buffer.get_end_iter()
        text = self.buffer.get_text(start, end, False).strip()
        if text:
            copy_to_clipboard(text)
        self.hide_session()

    def hide_session(self):
        """Hide the window and release the mic, leaving the process running."""
        self.stop_listening()
        self.clear_text()
        self.set_visible(False)

    def on_close_request(self, *_):
        self.quit_app()
        return False

    def quit_app(self):
        if self.shortcuts:
            self.shortcuts.close()
        if self.agent and self.is_listening:
            try:
                self.agent.stop_listening()
            except Exception:
                pass
        self.app.quit()


class DictationApp(Adw.Application):
    def __init__(self, model_name="medium", device=None, cpus=2):
        super().__init__(
            application_id=APP_ID,
            )
        self.model_name = model_name
        self.device = device
        self.cpus = cpus

    def do_activate(self):
        # Stay alive while the window is hidden, so the shortcut keeps working.
        self.hold()
        if self.props.active_window:
            self.props.active_window.present()
            return

        limit_cpu_cores(self.cpus)
        Gtk.Window.set_default_icon_name(APP_ID)
        provider = Gtk.CssProvider()
        provider.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

        win = DictateWindow(self, model_name=self.model_name, device=self.device)
        win.present()


def main():
    parser = argparse.ArgumentParser(description="Dictator - local desktop dictation popup")
    parser.add_argument("--model", choices=["tiny", "base", "medium"], default="medium",
                        help="Model size (default: medium - official website accuracy)")
    parser.add_argument("--device", default=None, help="Microphone device name or index")
    parser.add_argument("--cpus", type=int, default=2,
                        help="Max CPU cores to use (default: 2, prevents pegging all cores)")
    args = parser.parse_args()

    limit_cpu_cores(args.cpus)
    app = DictationApp(model_name=args.model, device=args.device, cpus=args.cpus)
    sys.exit(app.run([]))


if __name__ == "__main__":
    main()
