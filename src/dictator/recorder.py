"""GStreamer audio recorder with microphone 
level metering and validation."""
import os
from pathlib import Path
import tempfile
import wave
from gi.repository import Gst


def get_audio_input_devices():
    devices = []
    try:
        monitor = Gst.DeviceMonitor()
        monitor.add_filter("Audio/Source", None)
        monitor.start()
        for dev in monitor.get_devices():
            name = dev.get_display_name()
            if name.lower().startswith("monitor of"):
                continue
            props = dev.get_properties()
            pulse_device = (
                props.get_string("pulsesrc.device")
                or props.get_string("node.name")
                or props.get_string("device.name")
            )
            devices.append({"name": name, "device": pulse_device})
        monitor.stop()
    except Exception:
        pass
    return devices


class AudioRecorder:
    def __init__(self, cache_dir, on_level=None, on_eos=None, on_error=None):
        self.cache_dir = Path(cache_dir)
        self.on_level = on_level
        self.on_eos = on_eos
        self.on_error = on_error
        self.pipeline = None
        self.wav_path = None

    def start(self, device=None):
        """device=None means the system default mic, not "keep whatever was last used"."""
        self.stop()
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix="recording-", suffix=".wav", dir=self.cache_dir)
        os.close(fd)
        self.wav_path = Path(name)

        self.pipeline = Gst.parse_launch(
            "pulsesrc name=src ! audioconvert ! audioresample ! audio/x-raw,format=S16LE,channels=1,rate=16000 ! "
            "level interval=100000000 post-messages=true ! wavenc ! filesink name=output"
        )
        if device:
            src = self.pipeline.get_by_name("src")
            if src and hasattr(src.props, "device"):
                src.set_property("device", device)

        self.pipeline.get_by_name("output").set_property("location", str(self.wav_path))
        bus = self.pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect("message", self._on_bus_message)
        if self.pipeline.set_state(Gst.State.PLAYING) == Gst.StateChangeReturn.FAILURE:
            self.stop()
            raise RuntimeError("Could not start microphone recording.")
        return self.wav_path

    def request_eos(self):
        if self.pipeline:
            return self.pipeline.send_event(Gst.Event.new_eos())
        return False

    def validate_recording(self, min_seconds=0.15):
        self.stop_pipeline()
        if not self.wav_path or not self.wav_path.exists():
            raise ValueError("The recording was missing.")
        size = self.wav_path.stat().st_size
        if size <= 44:
            raise ValueError("The recording was too short.")
        with wave.open(str(self.wav_path), "rb") as rec:
            rate = rec.getframerate()
            ch = rec.getnchannels()
            sw = rec.getsampwidth()
            frames = min(rec.getnframes(), (size - 44) // (ch * sw))
            duration = frames / rate
            if duration < min_seconds:
                raise ValueError("The recording was too short.")
        return self.wav_path, round(duration, 3), frames

    def _on_bus_message(self, bus, msg):
        if msg.type == Gst.MessageType.ERROR:
            err = msg.parse_error()[0].message
            if self.on_error:
                self.on_error(err)
        elif msg.type == Gst.MessageType.ELEMENT:
            st = msg.get_structure()
            if st and st.get_name() == "level" and self.on_level:
                rms = st.get_value("rms")
                level = min(1.0, max(0.0, 10 ** (rms[0] / 20)))
                self.on_level(level)
        elif msg.type == Gst.MessageType.EOS and self.on_eos:
            self.on_eos()

    def stop_pipeline(self):
        if self.pipeline:
            self.pipeline.set_state(Gst.State.NULL)
            bus = self.pipeline.get_bus()
            bus.disconnect_by_func(self._on_bus_message)
            bus.remove_signal_watch()
            self.pipeline = None

    def delete_recording(self):
        if self.wav_path:
            self.wav_path.unlink(missing_ok=True)
            self.wav_path = None

    def stop(self):
        self.stop_pipeline()
        self.delete_recording()
