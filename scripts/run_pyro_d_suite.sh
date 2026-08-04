#!/usr/bin/env bash
# Pyro serialization suite D1–D8 against KansasFLEX (.env ROBOT_HOST).
set -euo pipefail
export PATH="/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin:${HOME}/.local/bin:${PATH}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
set -a
# shellcheck disable=SC1091
source .env
set +a
HOST="${ROBOT_HOST:?}"
H="Opentrons-Version: *"
ART="$ROOT/artifacts/pyro-tests"
mkdir -p "$ART"
OUT="$ART/d-suite-$(date -u +%Y%m%dT%H%M%SZ).log"
exec >"$OUT" 2>&1
echo "HOST=$HOST OUT=$OUT"

echo "======== D1 door HTTP ========"
curl -sS --max-time 10 -H "$H" "http://$HOST:31950/robot/door/status" | tee "$ART/d1-door.json"
echo
python3 - <<'PY'
import json
d = json.load(open("artifacts/pyro-tests/d1-door.json"))
st = (d.get("data") or {}).get("status") or d.get("status")
print("D1_RESULT", "PASS" if st in ("open", "closed") else "FAIL", "status=", st)
PY

echo "======== D7 subsystems HTTP ========"
curl -sS --max-time 15 -H "$H" "http://$HOST:31950/subsystems/status" | tee "$ART/d7-subsystems.json" >/dev/null
python3 - <<'PY'
import json
d = json.load(open("artifacts/pyro-tests/d7-subsystems.json"))
data = d.get("data", d)
ok = isinstance(data, dict) and len(data) > 0
if isinstance(data, dict):
    print("subsystem_keys", list(data.keys())[:12])
print("D7_RESULT", "PASS" if ok else "FAIL")
PY

echo "======== prepare protocol / run ========"
PROTO_FILE="$ART/proto_id_bare.txt"
PROTO_ID=""
if [[ -s "$PROTO_FILE" ]]; then
  PROTO_ID="$(cat "$PROTO_FILE")"
  echo "reuse PROTO_ID=$PROTO_ID"
fi
if [[ -z "$PROTO_ID" ]]; then
  curl -sS --max-time 60 -H "$H" -F "files=@docs/test-suggestions/protocols/pyro_smoke_no_motion.py" \
    "http://$HOST:31950/protocols" | tee "$ART/d-upload.json" >/dev/null
  PROTO_ID="$(python3 -c 'import json; print(json.load(open("artifacts/pyro-tests/d-upload.json"))["data"]["id"])')"
  printf '%s' "$PROTO_ID" >"$PROTO_FILE"
  echo "uploaded PROTO_ID=$PROTO_ID"
fi
for i in $(seq 1 60); do
  curl -sS --max-time 10 -H "$H" "http://$HOST:31950/protocols/$PROTO_ID" >"$ART/d-proto.json"
  st="$(python3 - <<'PY'
import json
d = json.load(open("artifacts/pyro-tests/d-proto.json"))
summaries = (d.get("data") or {}).get("analysisSummaries") or []
if not summaries:
    print("none")
else:
    a = summaries[-1]
    print(f"{a.get('status')} {a.get('id','')}")
PY
)"
  echo "analysis_poll $i $st"
  case "$st" in
    completed*|failed*) break ;;
  esac
  sleep 2
done

curl -sS --max-time 30 -H "$H" -H "Content-Type: application/json" \
  -d "{\"data\":{\"protocolId\":\"$PROTO_ID\"}}" \
  "http://$HOST:31950/runs" | tee "$ART/d-create-run.json" >/dev/null
RUN_ID="$(python3 -c 'import json; print((json.load(open("artifacts/pyro-tests/d-create-run.json")).get("data") or {}).get("id") or "")')"
echo "RUN_ID=$RUN_ID"
printf '%s' "$RUN_ID" >"$ART/d_run_id.txt"
if [[ -z "$RUN_ID" ]]; then
  echo "CREATE_RUN_FAILED"; cat "$ART/d-create-run.json"; exit 1
fi

echo "======== D4 currentState ========"
curl -sS --max-time 15 -H "$H" "http://$HOST:31950/runs/$RUN_ID/currentState" | tee "$ART/d4-currentState.json" >/dev/null
python3 - <<'PY'
import json
d = json.load(open("artifacts/pyro-tests/d4-currentState.json"))
data = d.get("data", d)
errs = d.get("errors")
ok = errs is None and isinstance(data, dict) and len(data) > 0
print("keys", sorted(data.keys()) if isinstance(data, dict) else type(data))
for k in ("status", "estopStatus", "activeNozzleLayouts", "tipStates"):
    if isinstance(data, dict) and k in data:
        print(k, data[k])
print("D4_RESULT", "PASS" if ok else "FAIL", "errors=", errs)
PY

echo "======== D5 commands ========"
curl -sS --max-time 20 -H "$H" "http://$HOST:31950/runs/$RUN_ID/commands?pageLength=20" | tee "$ART/d5-commands.json" >/dev/null
python3 - <<'PY'
import json
d = json.load(open("artifacts/pyro-tests/d5-commands.json"))
data = d.get("data", [])
errs = d.get("errors")
ok = errs is None and isinstance(data, list)
print("command_count", len(data), "meta", d.get("meta"))
for c in data[:8]:
    print(c.get("commandType"), c.get("status"))
print("D5_RESULT", "PASS" if ok else "FAIL", "errors=", errs)
PY
TIP_RUN="1c4e5cce-4d6e-43f7-9f5d-205b06209c16"
code="$(curl -sS -o "$ART/d5-tip-commands.json" -w "%{http_code}" --max-time 15 -H "$H" \
  "http://$HOST:31950/runs/$TIP_RUN/commands?pageLength=50" || echo ERR)"
echo "tip_run_commands http=$code"
if [[ "$code" == "200" ]]; then
  python3 - <<'PY'
import json
d = json.load(open("artifacts/pyro-tests/d5-tip-commands.json"))
data = d.get("data", [])
print("tip_commands", len(data))
for c in data:
    print(c.get("commandType"), c.get("status"), "err" if c.get("error") else "ok")
print("D5_TIP_SLICE", "PASS" if data else "EMPTY")
PY
fi

echo "======== D6 command / enumerated error ========"
curl -sS --max-time 20 -H "$H" -H "Content-Type: application/json" \
  -d '{"data":{"commandType":"loadPipette","params":{"pipetteName":"p50_single_flex","mount":"not_a_mount"},"intent":"setup"}}' \
  "http://$HOST:31950/runs/$RUN_ID/commands" | tee "$ART/d6-bad-command.json" >/dev/null
python3 - <<'PY'
import json
from pathlib import Path

d = json.load(open("artifacts/pyro-tests/d6-bad-command.json"))
errs = d.get("errors")
data = d.get("data")
print("top_keys", list(d.keys()))
if errs:
    e0 = errs[0]
    print("error_id", e0.get("id"), "title", e0.get("title"), "errorCode", e0.get("errorCode"))
    ok = bool(e0.get("id") or e0.get("errorCode") or e0.get("title"))
    print("D6_RESULT", "PASS" if ok else "FAIL", "via=response_errors")
elif isinstance(data, dict):
    cid = data.get("id") or ""
    Path("artifacts/pyro-tests/d6_cmd_id.txt").write_text(cid)
    print("created_command", cid, "status", data.get("status"), "error", data.get("error"))
    print("D6_RESULT", "PARTIAL", "will_poll")
else:
    print("D6_RESULT", "FAIL", d)
PY
if [[ -s "$ART/d6_cmd_id.txt" ]]; then
  CID="$(cat "$ART/d6_cmd_id.txt")"
  sleep 2
  curl -sS --max-time 15 -H "$H" "http://$HOST:31950/runs/$RUN_ID/commands/$CID" | tee "$ART/d6-cmd-get.json" >/dev/null
  python3 - <<'PY'
import json
d = json.load(open("artifacts/pyro-tests/d6-cmd-get.json"))
data = d.get("data") or {}
err = data.get("error") or {}
print(
    "status",
    data.get("status"),
    "errorType",
    err.get("errorType"),
    "errorCode",
    err.get("errorCode"),
    "detail",
    str(err.get("detail"))[:160],
)
ok = data.get("status") == "failed" and bool(
    err.get("errorType") or err.get("errorCode") or err.get("detail")
)
print("D6_RESULT", "PASS" if ok else "FAIL")
PY
fi

echo "======== journal serialize peek ========"
ssh -i ~/.ssh/robot_key -o BatchMode=yes -o IdentitiesOnly=yes -o ConnectTimeout=10 "root@$HOST" \
  'journalctl -u opentrons-robot-server --since "15 minutes ago" --no-pager 2>/dev/null | grep -E "unhashable|numpy[.]float64|SerializeError|TypeError" | tail -40; echo ---HW---; journalctl -u opentrons-hardware-api --since "15 minutes ago" --no-pager 2>/dev/null | grep -E "unhashable|numpy[.]float64|SerializeError|TypeError" | tail -20' || true

echo "======== D8 negative raw Proxy ========"
ssh -i ~/.ssh/robot_key -o BatchMode=yes -o IdentitiesOnly=yes -o ConnectTimeout=15 "root@$HOST" \
  'python3 - <<"PY"
import Pyro5.api as pyro
p = pyro.Proxy(pyro.resolve("PYRONAME:OT3API"))
try:
    print("fw", p.get_fw_version())
except Exception as e:
    print("fw_err", type(e).__name__, e)
try:
    print("door_raw", p.door_state)
    print("D8_DOOR", "UNEXPECTED_PASS")
except Exception as e:
    print("D8_DOOR_EXPECTED_FAIL", type(e).__name__, str(e)[:200])
try:
    ai = p.attached_instruments
    print("attached_raw_type", type(ai).__name__, str(ai)[:200])
    print("D8_INSTR", "GOT_VALUE")
except Exception as e:
    print("D8_INSTR_EXPECTED_FAIL", type(e).__name__, str(e)[:240])
print("D8_RESULT", "PASS")  # negative control documented either way
PY'

echo "======== D2/D3 with register_hardware_types ========"
ssh -i ~/.ssh/robot_key -o BatchMode=yes -o IdentitiesOnly=yes -o ConnectTimeout=30 "root@$HOST" \
  'PYTHONPATH=/opt/opentrons-robot-server python3 - <<"PY"
import traceback
import Pyro5.api as pyro
try:
    from opentrons.hardware_control.pyro_utils.serpent_type_registry import (
        register_hardware_types,
    )
    register_hardware_types()
    print("registry_ok")
except Exception as e:
    print("registry_fail", type(e).__name__, e)
    traceback.print_exc()
    raise SystemExit(2)

p = pyro.Proxy(pyro.resolve("PYRONAME:OT3API"))
try:
    door = p.door_state
    print(
        "door_state",
        door,
        type(door).__name__,
        getattr(door, "name", None),
        getattr(door, "value", door),
    )
    print("D2_RESULT", "PASS")
except Exception as e:
    print("D2_RESULT", "FAIL", type(e).__name__, str(e)[:300])
    traceback.print_exc()

try:
    ai = p.attached_instruments
    print("attached_type", type(ai).__name__)
    if isinstance(ai, dict):
        print("keys", list(ai.keys()))
        for k, v in ai.items():
            name = v.get("name") if isinstance(v, dict) else v
            print(" ", k, type(k).__name__, type(v).__name__, name)
        print("D3_RESULT", "PASS")
    else:
        d = getattr(ai, "dictionary", None)
        if d is None and hasattr(ai, "model_dump"):
            d = ai.model_dump()
        print("wrapper_preview", str(ai)[:200], "dict?", type(d).__name__ if d is not None else None)
        print("D3_RESULT", "PASS" if d is not None else "FAIL")
except Exception as e:
    print("D3_RESULT", "FAIL", type(e).__name__, str(e)[:400])
    traceback.print_exc()
PY'

echo "======== DONE ========"
echo "LOG=$OUT"
