<img src="icon_transparent.png" width="120" alt="Dictator icon">

# Dictator : Hold To Dictate, Locally

Dictator is a small GTK4/libadwaita app for GNOME. Hold a shortcut, speak, release. Local Whisper transcription, copied to clipboard. Nothing leaves your machine.

## Install

```sh
flatpak info org.gnome.Platform//50 || flatpak install flathub org.gnome.Platform//50
python3 setup-transcription.py   # builds whisper.cpp into ~/.cache/dictator
bash build-flatpak.sh
flatpak run io.github.aradar46.Dictator
```

`build-flatpak.sh` is the quick path: it reuses the `whisper-cli` that `setup-transcription.py` builds on the host, so run that first. For a reproducible build that compiles whisper.cpp inside the sandbox instead (what Flathub uses):

```sh
flatpak install --user flathub org.gnome.Sdk//50
flatpak-builder --user --install --force-clean build-dir io.github.aradar46.Dictator.yml
```

Pick a Whisper model from the settings menu ("..." in the header bar), let it download, then click **Enable Global Shortcut** and approve a binding in GNOME's dialog.

`small-q5` is the default: good accuracy without needing a GPU.

## Use

Hold the shortcut, speak, release, Ctrl+V. Esc cancels mid-recording.

"Hide to Background" keeps Dictator running so the shortcut still works while the window is gone. To stop it: **Quit** in the menu, Ctrl+Q, the tray icon's Quit, or closing the window while it's idle. It does not autostart; once quit, it stays quit until you launch it again.

## Permissions

The Flatpak asks for four things and nothing else. No filesystem access, no home directory, no arbitrary D-Bus.

| Permission | Why |
|---|---|
| `--socket=wayland` | Draws the window, and the shortcut portal needs a Wayland surface handle to bind against. Wayland only, so there is no X11 fallback. |
| `--socket=pulseaudio` | Records the microphone. This is the PipeWire socket on current systems. |
| `--share=network` | Downloads the Whisper model from huggingface.co on first use. Nothing is uploaded, and nothing else talks to the network. |
| `--device=dri` | GPU rendering for the GTK4 window. |
| `--talk-name=org.kde.StatusNotifierWatcher` | The optional tray icon. Absent on desktops without a StatusNotifier watcher, and the app works fine without it. |

Models and settings live in the app's own sandboxed cache (`~/.var/app/io.github.aradar46.Dictator/`), not in your home directory.

## Develop

```sh
python3 src/dictator/dictator.py   # run directly (needs GTK4, libadwaita, GStreamer, PyGObject)
python3 check.py               # regression check, synthetic audio/fakes, no real portal or mic
python3 -m unittest discover -s tests
```

## Notes

- Shortcut binding goes through `org.freedesktop.portal.GlobalShortcuts`, sandboxed apps can't grab hotkeys directly.
- GNOME's portal sometimes doesn't fire `Deactivated` if a modifier is released before the main key; the app also watches local modifier releases as a backup.
- Transcription runs via [whisper.cpp](https://github.com/ggml-org/whisper.cpp) against a GGML model downloaded on first use.

## License

GPL-3.0-or-later, see [LICENSE](LICENSE).
