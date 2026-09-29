"""Disposable subprocess fixture for private IPC supervision tests; no ASR."""

import json
import os
import signal
import subprocess
import sys
import time

data = json.loads(sys.stdin.buffer.readline())
mode = sys.argv[1]
epoch = data["epoch"]


def emit(record):
    print(json.dumps({"epoch": epoch, **record}), flush=True)


if mode == "identity_missing":
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    time.sleep(30)
elif mode == "timeout":
    time.sleep(30)
elif mode == "bad_ready":
    emit({"kind": "ready", "version": 1, "profile": {}})
    time.sleep(30)
elif mode == "oversize":
    print("x" * 65537, flush=True)
    time.sleep(30)
else:
    if mode == "child":
        child = subprocess.Popen([sys.executable, "-c", "import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(30)"])
        sys.stderr.write("Private diagnostic never presented to users\n")
        sys.stderr.flush()
    emit({"kind": "ready", "version": 1, "profile": data["profile"]})
    session = None
    turn = None
    for raw in sys.stdin.buffer:
        request = json.loads(raw)
        command = request["command"]
        if mode == "exit" and command == "begin":
            os._exit(7)
        if command == "open":
            session = request["session_id"]
        elif command == "begin":
            turn = request["utterance_id"]
        elif command == "audio":
            emit({"kind": "event", "session_id": session, "utterance_id": turn,
                  "event": "partial", "text": "Fixture partial"})
        emit({"kind": "reply", "id": request["id"], "ok": True})
        if command == "finalize":
            emit({"kind": "event", "session_id": session, "utterance_id": turn,
                  "event": "final", "text": "Fixture final"})
            turn = None
        elif command == "cancel":
            turn = None
        elif command == "close":
            session = None
