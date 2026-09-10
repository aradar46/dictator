#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "$0")"
app_id=io.github.aradar46.Dictator
arch=$(flatpak --default-arch)
flatpak info org.gnome.Platform//50 >/dev/null
build_dir=$(mktemp -d "${TMPDIR:-/tmp}/dictator-build.XXXXXX")
trap 'rm -rf -- "$build_dir"' EXIT
mkdir -p "$build_dir/files/bin" "$build_dir/files/share/applications" "$build_dir/files/share/metainfo" "$build_dir/files/share/icons/hicolor/512x512/apps"
install -m755 src/dictator/dictator.py "$build_dir/files/bin/dictator"
install -m644 src/dictator/transcriber.py src/dictator/shortcuts.py src/dictator/recorder.py src/dictator/session.py src/dictator/background.py src/dictator/tray.py "$build_dir/files/bin/"
cached_engine="$HOME/.cache/dictator/whisper.cpp-306c88f4d1286aec1bf96e544632897886af5501/build/bin/whisper-cli"
if [ ! -f "$cached_engine" ]; then
    echo "No whisper-cli at $cached_engine" >&2
    echo "Run 'python3 setup-transcription.py' first, or build with flatpak-builder." >&2
    exit 1
fi
install -m755 "$cached_engine" "$build_dir/files/bin/whisper-cli"
install -m644 "$app_id.desktop" "$build_dir/files/share/applications/"
install -m644 "$app_id.metainfo.xml" "$build_dir/files/share/metainfo/"
install -m644 icon_transparent.png "$build_dir/files/share/icons/hicolor/512x512/apps/$app_id.png"
cat > "$build_dir/metadata" <<EOF
[Application]
name=$app_id
runtime=org.gnome.Platform/$arch/50
sdk=org.gnome.Sdk/$arch/50
command=dictator
EOF
flatpak build-finish --socket=wayland --socket=pulseaudio --device=dri --share=network --filesystem=xdg-cache/dictator:create --talk-name=org.kde.StatusNotifierWatcher "$build_dir"
flatpak build-export --arch="$arch" .flatpak-repo "$build_dir" dictator
flatpak build-bundle .flatpak-repo Dictator.flatpak "$app_id" dictator
flatpak install --user --noninteractive --assumeyes ./Dictator.flatpak
