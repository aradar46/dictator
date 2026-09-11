#!/usr/bin/env python3
import argparse
import asyncio
import json
import logging
import os
import sys
import webbrowser
from pathlib import Path

from aiohttp import web
from moonshine_voice import AgentFlow, MicTranscriber, ModelArch, MoonshineError

STATIC_DIR = Path(__file__).parent / "static"

def limit_cpu_cores(num_cores: int = 2):
    """Cap process to specific number of CPU cores."""
    try:
        os.environ["OMP_NUM_THREADS"] = str(num_cores)
        os.environ["OPENBLAS_NUM_THREADS"] = str(num_cores)
        os.environ["MKL_NUM_THREADS"] = str(num_cores)
        os.environ["ORT_NUM_THREADS"] = str(num_cores)
        total_cpus = os.cpu_count() or 4
        cores = set(range(min(num_cores, total_cpus)))
        os.sched_setaffinity(0, cores)
    except Exception:
        pass


def enforce_offline():
    import socket
    orig_connect = socket.socket.connect
    def blocked_connect(self, address):
        host = address[0]
        if host not in ("127.0.0.1", "localhost", "::1"):
            raise RuntimeError(f"Offline mode active: blocked outbound connection to {address}")
        return orig_connect(self, address)
    socket.socket.connect = blocked_connect

class DictationManager:
    def __init__(self, model_name: str = "medium", device: str | int | None = None):
        self.model_name = model_name
        self.device = device
        self.arch_map = {
            "tiny": ModelArch.TINY_STREAMING,
            "base": ModelArch.BASE_STREAMING,
            "medium": ModelArch.MEDIUM_STREAMING,
        }
        self.arch = self.arch_map.get(model_name.lower(), ModelArch.MEDIUM_STREAMING)
        self.mic: MicTranscriber | None = None
        self.agent: AgentFlow | None = None
        self.clients: set[web.WebSocketResponse] = set()
        self.state: str = "ready"  # ready | listening | paused
        self.loop: asyncio.AbstractEventLoop | None = None

    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self.loop = loop

    def broadcast_threadsafe(self, msg: dict) -> None:
        if not self.clients or not self.loop or self.loop.is_closed():
            return
        data = json.dumps(msg)
        for ws in list(self.clients):
            if not ws.closed:
                asyncio.run_coroutine_threadsafe(ws.send_str(data), self.loop)

    def on_provisional(self, text: str) -> None:
        if self.state == "paused":
            return
        self.broadcast_threadsafe({"type": "provisional", "text": text})

    def on_commit(self, text: str) -> None:
        if self.state == "paused":
            return
        self.broadcast_threadsafe({"type": "commit", "text": text})

    def on_command(self, name: str) -> None:
        if name == "pause":
            self.state = "paused"
            self.broadcast_threadsafe({"type": "status", "state": "paused"})
        elif name == "resume":
            self.state = "listening"
            self.broadcast_threadsafe({"type": "status", "state": "listening"})
        self.broadcast_threadsafe({"type": "command", "name": name})

    def load(self) -> None:
        from moonshine_voice import get_spelling_model_path
        print(f"Loading Moonshine Voice ({self.model_name} streaming - official website accuracy)...")
        spelling_path = None
        try:
            spelling_path = get_spelling_model_path("en")
        except Exception:
            pass

        self.mic = (
            MicTranscriber()
            .model_arch(self.arch)
            .spelling_model(spelling_path)
            .on_text(self.on_provisional)
        )
        if self.device is not None:
            # Handle int if digits
            dev_val = int(self.device) if str(self.device).isdigit() else self.device
            self.mic.device(dev_val)

        self.mic.load()

        self.agent = (
            AgentFlow()
            .speech(False)
            .beeps(False)
            .trigger_threshold(0.8)
            .otherwise(self.on_commit)
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
            handler = (lambda name: (lambda d: self.on_command(name)))(cmd_name)
            for phrase in phrases:
                self.agent.always(phrase, handler)

        self.agent.load()
        print(f"Moonshine Voice ready ({self.model_name} streaming).")

    def start_listening(self) -> None:
        if self.agent and self.state != "listening":
            self.agent.start_listening()
            self.state = "listening"
            self.broadcast_threadsafe({"type": "status", "state": "listening"})

    def stop_listening(self) -> None:
        if self.agent and self.state != "ready":
            self.agent.stop_listening()
            self.state = "ready"
            self.broadcast_threadsafe({"type": "status", "state": "ready"})

    def pause(self) -> None:
        self.state = "paused"
        self.broadcast_threadsafe({"type": "status", "state": "paused"})

    def resume(self) -> None:
        if self.agent:
            self.agent.start_listening()
            self.state = "listening"
            self.broadcast_threadsafe({"type": "status", "state": "listening"})

    def handle_utterance(self, text: str) -> None:
        if self.agent:
            self.agent.handle_utterance(text)

    def close(self) -> None:
        try:
            if self.agent:
                self.agent.close()
        except Exception:
            pass
        try:
            if self.mic:
                self.mic.close()
        except Exception:
            pass


async def index_handler(request: web.Request) -> web.FileResponse:
    return web.FileResponse(STATIC_DIR / "index.html")


async def ws_handler(request: web.Request) -> web.WebSocketResponse:
    ws = web.WebSocketResponse()
    await ws.prepare(request)

    manager: DictationManager = request.app["manager"]
    manager.clients.add(ws)

    # Send initial state
    await ws.send_str(json.dumps({
        "type": "status",
        "state": manager.state,
        "model": manager.model_name,
    }))

    try:
        async for msg in ws:
            if msg.type == web.WSMsgType.TEXT:
                try:
                    payload = json.loads(msg.data)
                    action = payload.get("action")
                    if action == "start":
                        manager.start_listening()
                    elif action == "stop":
                        manager.stop_listening()
                    elif action == "pause":
                        manager.pause()
                    elif action == "resume":
                        manager.resume()
                    elif action == "utterance":
                        text = payload.get("text", "").strip()
                        if text:
                            loop = asyncio.get_running_loop()
                            await loop.run_in_executor(None, manager.handle_utterance, text)
                except Exception as e:
                    await ws.send_str(json.dumps({"type": "error", "message": str(e)}))
            elif msg.type == web.WSMsgType.ERROR:
                break
    finally:
        manager.clients.discard(ws)

    return ws


@web.middleware
async def security_headers_middleware(request: web.Request, handler) -> web.Response:
    response = await handler(request)
    response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
    response.headers["Cross-Origin-Embedder-Policy"] = "require-corp"
    return response


def create_app(manager: DictationManager) -> web.Application:
    app = web.Application(middlewares=[security_headers_middleware])
    app["manager"] = manager
    app.router.add_get("/", index_handler)
    app.router.add_get("/ws", ws_handler)
    app.router.add_static("/static", STATIC_DIR, show_index=False)

    async def on_cleanup(app: web.Application) -> None:
        manager.stop_listening()
        manager.close()

    app.on_cleanup.append(on_cleanup)
    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="Moonshine Voice Local Dictation App")
    parser.add_argument("--model", choices=["tiny", "base", "medium"], default="medium",
                        help="Model size to use (default: medium - exact same model used by moonshine.ai)")
    parser.add_argument("--host", default="127.0.0.1", help="Host interface (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8000, help="Port to listen on (default: 8000)")
    parser.add_argument("--device", default=None,
                        help="Audio input device index or name (use --list-devices to view)")
    parser.add_argument("--cpus", type=int, default=2,
                        help="Max CPU cores to use (default: 2, prevents pegging all cores)")
    parser.add_argument("--list-devices", action="store_true",
                        help="List available audio input devices and exit")
    parser.add_argument("--offline", action="store_true", default=True,
                        help="Enforce strict offline mode (blocks non-loopback connections, default: True)")
    parser.add_argument("--allow-network", dest="offline", action="store_false",
                        help="Allow network access (e.g. to download new models)")
    parser.add_argument("--no-browser", action="store_true", help="Don't open browser automatically")
    args = parser.parse_args()

    limit_cpu_cores(args.cpus)

    if args.list_devices:
        import sounddevice as sd
        print("Available audio input devices:")
        for idx, dev in enumerate(sd.query_devices()):
            if dev["max_input_channels"] > 0:
                print(f"  [{idx}] {dev['name']} (inputs: {dev['max_input_channels']})")
        return

    if args.offline:
        enforce_offline()
        print("[Offline mode active: all outbound network calls strictly blocked]")

    manager = DictationManager(model_name=args.model, device=args.device)
    manager.load()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    manager.set_loop(loop)

    app = create_app(manager)

    url = f"http://{args.host}:{args.port}"
    print(f"\n=======================================================")
    print(f" Moonshine Dictation App running at: {url}")
    print(f" Model: {args.model} streaming")
    print(f" Press Ctrl+C to stop.")
    print(f"=======================================================\n")

    if not args.no_browser:
        webbrowser.open(url)

    web.run_app(app, host=args.host, port=args.port, loop=loop)


if __name__ == "__main__":
    main()
