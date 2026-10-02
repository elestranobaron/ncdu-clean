#!/bin/sh
# Suggestion plan: keep in-scan paths, drop the rest, do not touch the journal.
set -eu
export LC_ALL=C.UTF-8
unset LANGUAGE
T=$(mktemp -d)
trap 'rm -rf "$T"' EXIT
export NCDU_CLEAN_AI="python3 tests/fake_ai.py"
export NCDU_CLEAN_AI_KEY="secret-key-should-not-leak"
export NCDU_CLEAN_LOG="$T/journal.jsonl"

python3 ncdu-clean suggest tests/sample.json \
  --delete-list "$T/delete.list" \
  --quarantine-list "$T/quarantine.list" \
  >"$T/out.json" 2>"$T/err.txt"

[ ! -e "$T/journal.jsonl" ]
! grep -q secret-key-should-not-leak "$T/out.json"
! grep -q secret-key-should-not-leak "$T/err.txt"
! grep -q . "$T/delete.list"
grep -q '/srv/data/logs/app.log$' "$T/quarantine.list"
! grep -q '/srv/data/logs$' "$T/quarantine.list"
! grep -q big.bin "$T/quarantine.list" "$T/delete.list"
python3 - "$T/out.json" <<'PY'
import json, sys
plan = json.load(open(sys.argv[1]))
quarantine = [row["path"] for row in plan["quarantine"]]
assert plan["delete"] == [], plan["delete"]
assert quarantine == ["/srv/data/logs/app.log"], quarantine
assert plan["quarantine"][0]["size"] == 303104
dropped = {row["path"] for row in plan["dropped"]}
assert "/etc" in dropped
assert "/not/in/scan" in dropped
assert "/srv/data" in dropped
assert "/srv/data/big.bin" in dropped
assert "/srv/data/logs" in dropped
PY

if NCDU_CLEAN_AI=false python3 ncdu-clean suggest tests/sample.json \
  >"$T/no.json" 2>"$T/no.err"
then
  echo "a failing suggestion command must not succeed" >&2
  exit 1
fi
[ ! -s "$T/no.json" ]
grep -q "The suggestion command stopped before returning a plan." "$T/no.err"
grep -q "Nothing was deleted." "$T/no.err"

if env -u NCDU_CLEAN_AI python3 ncdu-clean suggest tests/sample.json \
  >"$T/unset.json" 2>"$T/unset.err"
then
  echo "suggest without NCDU_CLEAN_AI must not succeed" >&2
  exit 1
fi
grep -q "No suggestion command is set." "$T/unset.err"

python3 - <<'PY'
import importlib.machinery
mod = importlib.machinery.SourceFileLoader("ncdu_clean", "ncdu-clean").load_module()
assert mod.suggestion_block("/mnt/win/Users/tom") == "user profile directory"
assert mod.suggestion_block("/mnt/win/Users") == "user profile directory"
assert mod.suggestion_block("/mnt/win/pagefile.sys") == "Windows system file"
assert mod.suggestion_block("/mnt/win/swapfile.sys") == "Windows system file"
assert mod.suggestion_block("/mnt/win/Windows") == "Windows system directory"
assert mod.suggestion_block("/mnt/win/Windows/System32") == "Windows system directory"
assert mod.suggestion_block("/mnt/win/Windows/WinSxS") == "Windows system directory"
assert mod.suggestion_block("/mnt/win/Users/tom/AppData/Local/Temp") is None
assert mod.suggestion_block("/mnt/win/Windows/SoftwareDistribution") is None
PY

python3 - <<'PY'
import importlib.machinery, os
mod = importlib.machinery.SourceFileLoader("ncdu_clean", "ncdu-clean").load_module()
for row in mod.list_storage():
    assert row["kind"] in ("disk", "removable", "unmounted"), row
    assert isinstance(row["size"], int) and row["size"] > 0
disks = [
    {"mount": "/tmp", "device": "/dev/sda1", "fs": "ext4", "size": 10**12,
     "free": 10**11, "kind": "disk", "writable": True},
    {"mount": "/mnt/win", "device": "/dev/sdb1", "fs": "ntfs", "size": 10**12,
     "free": 10**9, "kind": "disk", "writable": True},
]
kept = mod.choose_quarantine_dir(
    {"path": "/tmp/ncdu-clean-suggest-test", "create": True, "reason": "scratch"},
    disks, "/mnt/win", 100, ["/mnt/win/Users"])
assert kept["path"] == "/tmp/ncdu-clean-suggest-test", kept
assert kept["create"] is True and kept["same_disk"] is False
overlap = mod.choose_quarantine_dir(
    {"path": "/mnt/win/Users/trash", "create": True, "reason": "bad"},
    disks, "/mnt/win", 100, ["/mnt/win/Users"])
assert overlap["path"] == "/tmp/ncdu-clean", overlap
unknown = mod.choose_quarantine_dir(
    {"path": "/no/such", "create": True}, disks, "/mnt/win", 100, [])
assert unknown["path"] == "/tmp/ncdu-clean", unknown
tight = mod.choose_quarantine_dir(None, disks, "/mnt/win", 10**12, [])
assert tight["path"] == mod.default_trash(), tight
PY

python3 - "$T/out.json" <<'PY'
import json, sys
plan = json.load(open(sys.argv[1]))
dest = plan["quarantine_to"]
assert dest["path"].startswith("/"), dest
assert isinstance(dest["create"], bool)
assert dest["reason"]
PY

python3 - <<'PY'
import importlib.machinery, os
mod = importlib.machinery.SourceFileLoader("ncdu_clean", "ncdu-clean").load_module()
script = "/tmp/ncdu-clean-slow-ai.py"
open(script, "w", encoding="utf-8").write(
    "import sys, time\n"
    "sys.stdin.read()\n"
    "sys.stderr.write('THINK\\tlooking\\n')\n"
    "sys.stderr.flush()\n"
    "sys.stdout.write('{\"items\":')\n"
    "sys.stdout.flush()\n"
    "time.sleep(0.4)\n"
    "sys.stdout.write('[]}\\n')\n"
    "sys.stdout.flush()\n"
)
os.environ["NCDU_CLEAN_AI"] = "python3 " + script
seen, thinks = [], []
plan = mod.run_ai({"root": "/", "items": [], "disks": []},
                  on_text=seen.append, on_think=thinks.append)
assert plan == {"items": []}, plan
assert any(text.startswith('{"items":') and "[]" not in text for text in seen), seen
assert any("looking" in text for text in thinks), thinks
fenced = b'```json\n{"items": [{"path": "/tmp/a", "action": "delete"}]}\n```'
assert mod._json_plan(fenced)["items"][0]["path"] == "/tmp/a"
PY

python3 - <<'PY'
import importlib.machinery
mod = importlib.machinery.SourceFileLoader("ncdu_clean", "ncdu-clean").load_module()
GiB = 1024 ** 3
disks = [
    {"mount": "/boot/efi", "device": "/dev/sda1", "size": 96 * 1024 * 1024,
     "free": 40 * 1024 * 1024, "kind": "disk", "writable": True},
    {"mount": "/", "device": "/dev/sda4", "size": 27 * GiB, "free": 2 * GiB,
     "kind": "disk", "writable": True},
    {"mount": "/media/tom/8666-DE95", "device": "/dev/sdb1", "size": 29 * GiB,
     "free": 29 * GiB, "kind": "removable", "writable": True},
]
lines, more = mod.disk_rows(disks, scan_root="/mnt/win")
text = "\n".join(lines)
assert "/boot/efi" not in text, text
assert "This computer" in text and "scan is here" in text, text
assert "USB" in text and "8666-DE95" in text, text
assert text.splitlines()[0].strip().startswith("Name"), text
raw = ('{"items":[{"path" "/mnt/win/Program Files","action":"quarantine",'
       '"reason":"Large application folder"},{"path":"/mnt/win/tmp",'
       '"action":"delete","reason":"cache"}],'
       '"quarantine_to":{"path":"/media/tom/8666-DE95/ncdu-clean","create":true,'
       '"reason":"USB"}}')
plan = mod.salvage_plan(raw)
paths = {row["path"]: row["action"] for row in plan["items"]}
assert paths["/mnt/win/Program Files"] == "quarantine", plan
assert paths["/mnt/win/tmp"] == "delete", plan
assert plan["quarantine_to"]["path"].endswith("/ncdu-clean"), plan
assert mod._json_plan(raw.encode())["items"]
view = "\n".join(mod.reply_lines(raw))
assert "{" not in view and "/mnt/win/Program Files" in view, view
assert "Writing the plan." in mod.reply_lines('{"items":[', waiting=True)[0]
PY

echo "OK"
