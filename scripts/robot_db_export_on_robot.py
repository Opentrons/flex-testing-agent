"""Run on KansasFLEX to emit newest robot_server.db as base64 chunks."""

from __future__ import annotations

import base64
import glob
import os
import subprocess
import time

subprocess.run(["systemctl", "stop", "opentrons-robot-server"], check=False)
time.sleep(1)
glob_pattern = "/var/lib/opentrons-robot-server/**/robot_server.db"
paths = [p for p in glob.glob(glob_pattern, recursive=True) if os.path.isfile(p)]
paths.sort(key=os.path.getmtime)
path = paths[-1] if paths else ""
print("DBPATH", path, flush=True)
size = os.path.getsize(path) if path else 0
print("DBSIZE", size, flush=True)
if path:
    with open(path, "rb") as handle:
        enc = base64.b64encode(handle.read()).decode("ascii")
    step = 48000
    for i in range(0, len(enc), step):
        print(f"DBCHUNK {i} {enc[i : i + step]}", flush=True)
subprocess.run(["systemctl", "start", "opentrons-robot-server"], check=False)
print("DBDONE", flush=True)
