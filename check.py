"""Run with python3 check.py.

Uses synthetic audio and fake windows/clipboard. Does NOT certify the portal,
real microphone, compositor focus, or clipboard delivery to another app.
"""
import importlib.machinery
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import tempfile
import time
from unittest.mock import Mock, patch

source = "/app/bin/dictator" if Path("/.flatpak-info").exists() else str(Path(__file__).resolve().parent / "src" / "dictator" / "dictator.py")
loader = importlib.machinery.SourceFileLoader("dictator", source)
spec = importlib.util.spec_from_loader(loader.name, loader)
app = importlib.util.module_from_spec(spec)
loader.exec_module(app)
app.Gst.init(None)


def fake_ui(held_modifiers):
    window = Mock()
    window.is_active.return_value = True
    window.get_display().get_default_seat().get_keyboard().get_modifier_state.return_value = held_modifiers
    return SimpleNamespace(
        window=window, button=Mock(), label=Mock(), detail=Mock(), meter=Mock(),
        spinner=Mock(), settings_btn=Mock(),
        toast=Mock(), update_idle_ui=Mock(),
    )


def new_session(recorder=None, transcriber=None, held_modifiers=None):
    held_modifiers = held_modifiers if held_modifiers is not None else app.Gdk.ModifierType.CONTROL_MASK | app.Gdk.ModifierType.ALT_MASK
    ui = fake_ui(held_modifiers)
    transcriber = transcriber or Mock()
    transcriber.start.side_effect = lambda path, callback: app.GLib.idle_add(callback, "Recognized speech.", None)
    if recorder is None:
        cache = Path(app.GLib.get_user_cache_dir()) / app.APP_ID
        recorder = app.AudioRecorder(cache, on_level=lambda l: session.on_audio_level(l), on_eos=lambda: session.on_audio_eos(), on_error=lambda m: session.fail(m))
    session = app.DictationSession(recorder, transcriber, ui, log=lambda *a, **k: None)
    session.state = "idle"
    return session


def spin_until(predicate, timeout=7):
    deadline = time.monotonic() + timeout
    context = app.GLib.MainContext.default()
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError("Timed out waiting for recording state")
        context.iteration(False)
        time.sleep(0.005)


real_parse = app.Gst.parse_launch


def synthetic(description):
    return real_parse(description.replace("pulsesrc", "audiotestsrc is-live=true wave=sine"))


with tempfile.TemporaryDirectory() as directory, patch.object(app.GLib, "get_user_cache_dir", return_value=directory), patch.object(app.Gst, "parse_launch", side_effect=synthetic):
    s = new_session()
    s.finish()  # Spurious release does nothing.
    assert s.state == "idle"
    s.begin("test-token", None)
    pipeline = s.recorder.pipeline
    s.begin("repeat-token", None)
    assert s.recorder.pipeline is pipeline
    spin_until(lambda: s.ui.meter.set_value.call_count > 1)
    s.finish()
    s.finish()
    spin_until(lambda: s.state in ("copied", "error"))
    assert s.state == "copied"
    s.ui.window.get_clipboard().set.assert_called_once()
    assert s.ui.window.get_clipboard().set.call_args.args[0] == "Recognized speech."
    assert s.recorder.pipeline is None and s.wav_path is None
    spin_until(lambda: s.state == "idle")
    s.ui.window.set_visible.assert_called_with(False)

    # GNOME may omit Deactivated when a shortcut modifier is released first.
    # The focused window must finish on that modifier's local release instead.
    for modifier in (app.Gdk.KEY_Control_L, app.Gdk.KEY_Alt_R):
        s = new_session()
        s.begin(None, None)
        s.held_modifiers = app.Gdk.ModifierType.CONTROL_MASK | app.Gdk.ModifierType.ALT_MASK
        spin_until(lambda: s.ui.meter.set_value.call_count > 1)
        s.key_released(app.Gdk.KEY_b)
        s.key_released(app.Gdk.KEY_Shift_L)
        assert s.state == "recording", "Unrelated key releases must not end the hold"
        s.key_released(modifier)
        s.finish()  # A late portal Deactivated must not finalize twice.
        spin_until(lambda: s.state in ("copied", "error"))
        assert s.state == "copied"
        s.ui.window.get_clipboard().set.assert_called_once()
        spin_until(lambda: s.state == "idle")
        s.ui.window.set_visible.assert_called_with(False)

    s = new_session()
    s.begin(None, None)
    spin_until(lambda: s.ui.meter.set_value.call_count > 1)
    s.cancel()
    s.finish()
    assert s.state == "idle" and s.recorder.pipeline is None and s.wav_path is None
    s.ui.window.get_clipboard.assert_not_called()

    s = new_session()
    s.state = "waiting-for-focus"
    s.pending_text = "test"
    s.ui.window.is_active.return_value = False
    s.copy_if_focused()
    s.ui.window.get_clipboard.assert_not_called()
    s.deadline = 0
    s.tick()
    assert s.state == "error" and s.pending_text is None
    s.ui.window.get_clipboard.assert_not_called()

    s = new_session()
    s.begin(None, None)
    s.deadline = 0
    timer = s.timer
    s.tick()  # Lost release must stop the microphone.
    app.GLib.source_remove(timer)
    assert s.state == "error" and s.recorder.pipeline is None and s.wav_path is None
    # Ultra-short hold or empty audio must dismiss gracefully without failing.
    s = new_session()
    s.begin(None, None)
    s.finish()
    spin_until(lambda: s.state in ("dismiss", "error"))
    assert s.state == "dismiss"
    s.ui.window.get_clipboard.assert_not_called()
    assert s.recorder.pipeline is None and s.wav_path is None
    spin_until(lambda: s.state == "idle")
    s.ui.window.set_visible.assert_called_with(False)

    assert not list(Path(directory).rglob("*.wav"))

    s = new_session()
    s.state = "transcribing"
    s.cancel()
    s.transcription_done("Late text must not be copied", None)
    s.ui.window.get_clipboard.assert_not_called()
    s.transcriber.cancel.assert_called_once()

    for text, error, expected_state in [("", None, "dismiss"), (None, "Engine failed", "error")]:
        s = new_session()
        s.state = "transcribing"
        s.transcription_done(text, error)
        assert s.state == expected_state
        s.ui.window.get_clipboard.assert_not_called()

    s = new_session()
    s.state = "transcribing"
    s.deadline = 0
    s.tick()
    assert s.state == "error"
    s.transcriber.cancel.assert_called_once()
    s.ui.window.get_clipboard.assert_not_called()

    # Model selection test (exercises Dictator's own UI code, not the session)
    h = SimpleNamespace()
    h.dictation = SimpleNamespace(state="idle")
    h.settings_popover = Mock()
    h.model_buttons = {k: Mock() for k in app.MODELS}
    h.download_progress = Mock()
    h.transcriber = Mock()
    h.transcriber.model_name = "base"
    h.downloading_model = None
    h.toast = Mock()
    h.update_idle_ui = Mock()
    h.refresh_model_popover = lambda: app.Dictator.refresh_model_popover(h)
    h.choose_model = lambda key: app.Dictator.choose_model(h, key)
    with patch.object(app, "model_exists", return_value=True):
        h.choose_model("small")
        h.transcriber.set_model.assert_called_with("small")
        h.settings_popover.popdown.assert_called_once()

print("PASS: synthetic WAV + level meter; repeat/spurious events; modifier-first release without portal Deactivated; focused copy; hide; cancel; missing focus; missing release; model selection; temporary audio cleanup.")
