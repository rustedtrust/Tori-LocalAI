#!/usr/bin/env python3
"""Fixed private bridge/worker entry point, not a public or product API."""

import asyncio
import base64
import contextlib
import json
import os
from pathlib import Path
import signal
import secrets
import subprocess
import sys


_output = sys.stdout.buffer
MAX_FRAME = 65536
PROFILE = {"realtime": "tiny.en", "final": "small.en", "device": "cuda",
           "compute_type": "int8_float16", "energy_threshold": 100,
           "pre_roll": 0.5, "trailing_silence": 0.8}


def frame(document):
    raw = json.dumps(document, ensure_ascii=True, separators=(",", ":")).encode() + b"\n"
    if len(raw) > MAX_FRAME:
        raise RuntimeError("backpressure")
    return raw


def read_frame(pipe):
    raw = pipe.readline(MAX_FRAME + 1)
    if not raw:
        return None
    if len(raw) > MAX_FRAME or not raw.endswith(b"\n"):
        raise RuntimeError("communication_failed")
    result = json.loads(raw)
    if not isinstance(result, dict):
        raise RuntimeError("communication_failed")
    return result


def write_frame(document):
    _output.write(frame(document))
    _output.flush()


def bootstrap():
    data = read_frame(sys.stdin.buffer)
    if not data or set(data) != {"version", "epoch", "secret", "models", "port", "profile", "readiness_seconds"}:
        raise RuntimeError("runtime_unavailable")
    if data["version"] != 1 or data["profile"] != PROFILE:
        raise RuntimeError("runtime_unavailable")
    if type(data["port"]) is not int or not 1024 <= data["port"] <= 65535:
        raise RuntimeError("runtime_unavailable")
    return data


async def bridge(data):
    from websockets.asyncio.client import connect
    worker = subprocess.Popen(
        [sys.executable, "-B", str(Path(__file__).resolve()), "--worker"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        # Inherit Tori's owned session/process group, never daemonize.
    )
    worker.stdin.write(frame(data))
    worker.stdin.flush()
    try:
        ready = await asyncio.wait_for(asyncio.to_thread(read_frame, worker.stdout), data["readiness_seconds"])
        if not ready or ready.get("kind") != "ready" or ready.get("epoch") != data["epoch"]:
            raise RuntimeError("startup_failed")
        async with connect(f"ws://127.0.0.1:{data['port']}", max_size=MAX_FRAME,
                           max_queue=2, open_timeout=5, close_timeout=1, proxy=None) as socket:
            await socket.send(json.dumps({"secret": data["secret"], "epoch": data["epoch"]}))
            auth = json.loads(await asyncio.wait_for(socket.recv(), 5))
            if auth != {"ok": True, "epoch": data["epoch"]}:
                raise RuntimeError("communication_failed")
            write_frame(ready)
            async def incoming():
                async for raw in socket:
                    record = json.loads(raw)
                    if not isinstance(record, dict) or record.get("epoch") != data["epoch"]:
                        raise RuntimeError("communication_failed")
                    write_frame(record)
            async def outgoing():
                # Cancellable native pipe reads; no blocked executor thread on disconnect.
                loop = asyncio.get_running_loop()
                reader = asyncio.StreamReader(limit=MAX_FRAME)
                transport, _ = await loop.connect_read_pipe(
                    lambda: asyncio.StreamReaderProtocol(reader),
                    os.fdopen(os.dup(sys.stdin.fileno()), "rb", buffering=0))
                try:
                    while True:
                        raw = await reader.readline()
                        if not raw:
                            return
                        if len(raw) > MAX_FRAME or not raw.endswith(b"\n"):
                            raise RuntimeError("communication_failed")
                        record = json.loads(raw)
                        if not isinstance(record, dict) or record.get("epoch") != data["epoch"]:
                            raise RuntimeError("communication_failed")
                        await socket.send(json.dumps(record))
                finally:
                    transport.close()
            reader, writer = asyncio.create_task(incoming()), asyncio.create_task(outgoing())
            done, pending = await asyncio.wait((reader, writer), return_when=asyncio.FIRST_COMPLETED)
            for task in pending:
                task.cancel()
            for task in done:
                task.result()
    finally:
        if worker.poll() is None:
            worker.terminate()
        try:
            worker.wait(timeout=4)
        except subprocess.TimeoutExpired:
            worker.kill()
            worker.wait(timeout=1)


async def worker(data):
    from websockets.asyncio.server import serve
    from recognizer import prepare_recognizer
    loop = asyncio.get_running_loop()
    events = asyncio.Queue(maxsize=128)
    stopped = asyncio.Event()
    connected = False
    def emit(session, turn, event, text="", code=None):
        record = {"kind": "event", "epoch": data["epoch"], "session_id": session,
                  "utterance_id": turn, "event": event, "text": text, "code": code}
        if not isinstance(text, str) or len(text.encode("utf-8")) > 8192:
            loop.call_soon_threadsafe(stopped.set)
            return
        def enqueue():
            try:
                events.put_nowait(record)
            except asyncio.QueueFull:
                stopped.set()  # never silently discard a final
        loop.call_soon_threadsafe(enqueue)
    # Libraries sometimes print audio or transcript detail. Never forward their output.
    quiet = open(os.devnull, "w")
    sys.stdout = sys.stderr = quiet
    recognizer = await asyncio.to_thread(prepare_recognizer, data["models"], emit)
    async def connection(socket):
        nonlocal connected
        if connected:
            await socket.close(code=1008)
            return
        authenticated = False
        try:
            auth = json.loads(await asyncio.wait_for(socket.recv(), 5))
            if not authenticated_bootstrap(data, auth):
                await socket.close(code=1008)
                return
            if connected:
                await socket.close(code=1008)
                return
            connected = authenticated = True
            await socket.send(json.dumps({"ok": True, "epoch": data["epoch"]}))
            async def publish():
                while True:
                    event = await events.get()
                    await socket.send(json.dumps(event))
            publisher = asyncio.create_task(publish())
            publisher.add_done_callback(lambda task: stopped.set()
                                        if not task.cancelled() and task.exception() else None)
            try:
                async for raw in socket:
                    document = json.loads(raw)
                    record = {"kind": "reply", "epoch": data["epoch"], "id": document.get("id"), "ok": False}
                    try:
                        await asyncio.to_thread(dispatch, recognizer, data, document)
                        record["ok"] = True
                    except Exception as exc:
                        record["code"] = str(exc) if str(exc) in {
                            "invalid_transition", "stale_segment", "malformed_audio", "backpressure",
                            "utterance_limit", "cleanup_pending", "communication_failed",
                        } else "communication_failed"
                    await socket.send(json.dumps(record))
            finally:
                publisher.cancel()
        finally:
            if authenticated:
                stopped.set()
    for signum in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(signum, stopped.set)
    try:
        async with serve(connection, "127.0.0.1", data["port"], max_size=MAX_FRAME,
                         max_queue=2, close_timeout=1, origins=[None]):
            write_frame({"kind": "ready", "epoch": data["epoch"], "version": 1, "profile": PROFILE})
            await stopped.wait()
    finally:
        with open(os.devnull, "w") as quiet, contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
            await asyncio.to_thread(recognizer.shutdown)



def authenticated_bootstrap(data, auth):
    return (isinstance(auth, dict) and set(auth) == {"secret", "epoch"}
            and auth["epoch"] == data["epoch"] and isinstance(auth["secret"], str)
            and auth["secret"].isascii() and len(auth["secret"]) <= 128
            and secrets.compare_digest(auth["secret"], data["secret"]))

def dispatch(recognizer, data, document):
    common = {"command", "id", "epoch", "session_id"}
    shapes = {"open": set(), "close": set(), "begin": {"utterance_id", "sample_rate"},
              "audio": {"utterance_id", "sequence", "pcm"}, "finalize": {"utterance_id"},
              "cancel": {"utterance_id"}}
    if not isinstance(document, dict) or type(document.get("id")) is not int:
        raise RuntimeError("communication_failed")
    command = document.get("command")
    if not isinstance(command, str) or command not in shapes or set(document) != common | shapes[command] or document.get("epoch") != data["epoch"]:
        raise RuntimeError("communication_failed")
    if not isinstance(document.get("session_id"), str) or len(document["session_id"]) > 128:
        raise RuntimeError("communication_failed")
    if "utterance_id" in document and (not isinstance(document["utterance_id"], str) or len(document["utterance_id"]) > 128):
        raise RuntimeError("communication_failed")
    if command == "open":
        recognizer.open(document["session_id"])
    elif document["session_id"] != recognizer.session:
        raise RuntimeError("communication_failed")
    elif command == "close":
        recognizer.close()
    elif command == "begin":
        recognizer.begin(document["utterance_id"], document["sample_rate"])
    elif command == "audio":
        pcm = base64.b64decode(document["pcm"], validate=True)
        recognizer.audio(document["utterance_id"], document["sequence"], pcm)
    elif command == "finalize":
        recognizer.finalize(document["utterance_id"])
    elif command == "cancel":
        recognizer.cancel(document["utterance_id"])


if __name__ == "__main__":
    data = None
    try:
        data = bootstrap()
        if sys.argv[1:] == ["--bridge"]:
            asyncio.run(bridge(data))
        elif sys.argv[1:] == ["--worker"]:
            asyncio.run(worker(data))
        else:
            raise RuntimeError("runtime_unavailable")
    except BaseException:
        write_frame({"kind": "failure", "epoch": (data or {}).get("epoch"), "code": "startup_failed"})
        raise SystemExit(1)
