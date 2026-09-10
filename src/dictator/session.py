import time
import wave

from gi.repository import Gdk, GLib

MOD_MAP = {
    Gdk.KEY_Control_L: Gdk.ModifierType.CONTROL_MASK, Gdk.KEY_Control_R: Gdk.ModifierType.CONTROL_MASK,
    Gdk.KEY_Alt_L: Gdk.ModifierType.ALT_MASK, Gdk.KEY_Alt_R: Gdk.ModifierType.ALT_MASK,
    Gdk.KEY_Shift_L: Gdk.ModifierType.SHIFT_MASK, Gdk.KEY_Shift_R: Gdk.ModifierType.SHIFT_MASK,
    Gdk.KEY_Super_L: Gdk.ModifierType.SUPER_MASK, Gdk.KEY_Super_R: Gdk.ModifierType.SUPER_MASK,
}


class DictationSession:
    """Owns state, deadline, timer and every recording/transcription transition."""

    def __init__(self, recorder, transcriber, ui, log):
        self.recorder = recorder
        self.transcriber = transcriber
        self.ui = ui
        self.log = log
        self.state, self.deadline, self.timer = "setup", 0, 0
        self.held_modifiers = Gdk.ModifierType(0)
        self.wav_path = self.pending_text = None

    def begin(self, activation_token, device):
        if self.state != "idle":
            return
        self.state = "recording"
        self.held_modifiers = Gdk.ModifierType(0)
        self.ui.button.set_visible(False)
        self.ui.settings_btn.set_sensitive(False)
        self.ui.label.set_label("Listening")
        self.ui.detail.set_label("Release shortcut to finish · Esc to cancel")
        self.ui.meter.set_value(0)
        if activation_token:
            self.ui.window.set_startup_id(activation_token)
        self.ui.window.present()
        self.capture_modifiers()
        try:
            self.wav_path = self.recorder.start(device=device)
            self.deadline = time.monotonic() + 120
            self.timer = GLib.timeout_add(100, self.tick)
            self.log("recording-started")
        except Exception as err:
            self.fail(str(err))

    def finish(self):
        if self.state != "recording":
            return
        self.state = "finalizing"
        self.ui.label.set_label("Finishing recording")
        self.deadline = time.monotonic() + 5
        if not self.recorder.request_eos():
            self.fail("Could not finish recording.")
        self.log("recording-release")

    def on_audio_level(self, level):
        self.ui.meter.set_value(level)

    def on_audio_eos(self):
        if self.state != "finalizing":
            return
        try:
            self.wav_path, sec, frames = self.recorder.validate_recording()
            self.log("recording-finalized", seconds=sec, frames=frames)
            self.state = "transcribing"
            self.ui.label.set_label("Transcribing")
            self.ui.detail.set_label("Processing · Esc to cancel")
            self.ui.meter.set_value(0)
            self.ui.spinner.set_visible(True)
            self.ui.spinner.start()
            self.deadline = time.monotonic() + 120
            self.transcriber.start(self.wav_path, self.transcription_done)
            self.log("transcription-started")
        except (ValueError, wave.Error, EOFError) as err:
            self.log("recording-too-short", error=str(err))
            self.delete_recording()
            self.state = "dismiss"
            self.ui.label.set_label("Hold while speaking")
            self.ui.detail.set_label("Hold shortcut to record · Clipboard unchanged")
            self.deadline = time.monotonic() + 1.2
        except Exception as err:
            self.fail(str(err))

    def transcription_done(self, text, error):
        if self.state != "transcribing":
            return
        self.ui.spinner.stop()
        self.ui.spinner.set_visible(False)
        self.delete_recording()
        if error:
            return self.fail(error)
        if not text:
            self.state = "dismiss"
            self.ui.label.set_label("No speech detected")
            self.ui.detail.set_label("Clipboard unchanged")
            self.deadline = time.monotonic() + 1.2
            return self.log("no-speech")
        self.pending_text = text
        self.state = "waiting-for-focus"
        self.deadline = time.monotonic() + 3
        self.log("transcription-finished", characters=len(text))
        self.copy_if_focused()

    def focus_changed(self):
        self.log("focus", active=self.ui.window.is_active(), state=self.state)
        if self.state == "recording":
            self.capture_modifiers()
        self.copy_if_focused()

    def capture_modifiers(self):
        if self.ui.window.is_active():
            kb = self.ui.window.get_display().get_default_seat().get_keyboard()
            if kb:
                self.held_modifiers = kb.get_modifier_state()

    def copy_if_focused(self):
        if self.state != "waiting-for-focus" or not self.ui.window.is_active():
            return
        self.ui.window.get_clipboard().set(self.pending_text)
        self.pending_text = None
        self.state = "copied"
        self.ui.label.set_label("Copied")
        self.ui.detail.set_label("Paste with Ctrl+V")
        self.ui.toast("Transcription copied to clipboard")
        self.log("clipboard-set", focused=True)
        self.deadline = time.monotonic() + 1.2

    def tick(self):
        if self.state in ("idle", "error", "setup"):
            self.timer = 0
            return GLib.SOURCE_REMOVE
        if time.monotonic() >= self.deadline:
            if self.state in ("copied", "dismiss"):
                self.state = "idle"
                self.ui.update_idle_ui()
                self.ui.window.set_visible(False)
                self.log("window-hidden")
            elif self.state == "waiting-for-focus":
                self.fail("GNOME did not give this window focus. Clipboard unchanged; the loop has failed.")
            elif self.state == "recording":
                self.fail("Recording cancelled after two minutes: shortcut release was not received.")
            elif self.state == "transcribing":
                self.fail("Transcription took longer than two minutes and was stopped. Clipboard unchanged.")
            else:
                self.fail("Recording did not finish within five seconds.")
            self.timer = 0
            return GLib.SOURCE_REMOVE
        return GLib.SOURCE_CONTINUE

    def stop_pipeline(self):
        self.recorder.stop_pipeline()

    def delete_recording(self):
        self.recorder.delete_recording()
        self.wav_path = None

    def cancel(self):
        self.stop_pipeline()
        self.transcriber.cancel()
        self.ui.spinner.stop()
        self.ui.spinner.set_visible(False)
        self.delete_recording()
        self.pending_text = None
        self.state = "idle"
        self.ui.update_idle_ui()
        if self.timer:
            GLib.source_remove(self.timer)
            self.timer = 0
        self.ui.window.set_visible(False)
        self.log("cancelled")

    def fail(self, message):
        self.stop_pipeline()
        self.transcriber.cancel()
        self.ui.spinner.stop()
        self.ui.spinner.set_visible(False)
        self.delete_recording()
        self.pending_text = None
        self.state = "error"
        self.ui.settings_btn.set_sensitive(True)
        self.ui.label.set_label("Dictator stopped")
        self.ui.detail.set_label(message + "\nClose and reopen to retry.")
        self.ui.window.present()
        self.log("error", message=message)

    def key_released(self, keyval):
        if self.state == "recording" and self.ui.window.is_active() and (self.held_modifiers & MOD_MAP.get(keyval, 0)):
            self.log("local-modifier-release", key=Gdk.keyval_name(keyval))
            self.finish()
