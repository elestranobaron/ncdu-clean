#!/usr/bin/env python3
"""Fake NCDU_CLEAN_AI used by tests/suggest.sh. Does not read the key."""
import json
import sys

data = json.load(sys.stdin)
root = data["root"]
paths = {item["path"] for item in data["items"]}
if root + "/logs/app.log" not in paths:
    print("payload missing app.log", file=sys.stderr)
    sys.exit(1)
items = [
    {"path": root + "/logs", "action": "delete", "reason": "logs"},
    {"path": root + "/logs/app.log", "action": "quarantine", "reason": "keep the log"},
    {"path": root + "/big.bin", "action": "quarantine", "reason": "binary"},
    {"path": root + "/big.bin", "action": "delete", "reason": "also delete"},
    {"path": "/etc", "action": "delete", "reason": "top"},
    {"path": "/not/in/scan", "action": "delete", "reason": "missing"},
    {"path": root, "action": "delete", "reason": "root"},
]
json.dump({"items": items}, sys.stdout)
