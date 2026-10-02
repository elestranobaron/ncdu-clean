#!/usr/bin/env python3
# Copyright (C) 2026 Thomas Lloancy
# SPDX-License-Identifier: GPL-3.0-or-later
"""NCDU_CLEAN_AI command for an OpenAI-compatible chat endpoint.

Reads the scan summary on stdin. Writes {"items": [...]} on stdout.
The key stays in the environment and is not printed.

    NCDU_CLEAN_AI_URL    chat completions URL
    NCDU_CLEAN_AI_MODEL  model name
    NCDU_CLEAN_AI_KEY    bearer token, when the endpoint requires one
"""
import json
import os
import sys
import urllib.error
import urllib.request

PROMPT = (
    "You suggest a cleanup plan for an ncdu export. "
    "The user message is JSON: a scan root, disks, the total number of entries, "
    "and items. Items are the largest entries only, each with path, type "
    "(file or dir) and size in bytes. "
    "disks lists mounts and disks that are present. Each has mount, device, fs, "
    "size, free, kind (disk, removable or unmounted) and writable. "
    "Reply with JSON only, no markdown, in this shape: "
    '{"items":[{"path":"...","action":"delete","reason":"short"}],'
    '"quarantine_to":{"path":"/mount/ncdu-clean","create":true,"reason":"short"}} '
    "action is delete or quarantine. "
    "Copy item paths exactly from items. Do not invent item paths. "
    "quarantine_to.path is one folder on a writable mount from disks. "
    "Prefer a mount other than the scan root, with enough free bytes for the quarantine. "
    "create is true when that folder does not exist yet. "
    "The program keeps the original paths inside that one folder. "
    "Do not suggest a user profile, pagefile.sys, swapfile.sys, hiberfil.sys, "
    "or the Windows, System32, SysWOW64 or WinSxS directories. "
    "Prefer caches, temporary files, dumps and old update folders. "
    "Use quarantine when unsure. One short reason, a single line."
)


def fail(msg):
    print(f"ncdu-clean: {msg}", file=sys.stderr)
    sys.exit(1)


def message_text(payload):
    try:
        message = payload["choices"][0]["message"]
    except (KeyError, IndexError, TypeError):
        fail("model reply has no message")
    content = message.get("content")
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict) and isinstance(part.get("text"), str):
                parts.append(part["text"])
        content = "".join(parts)
    if isinstance(content, str) and content.strip():
        return content
    reasoning = message.get("reasoning")
    if isinstance(reasoning, str) and reasoning.strip():
        return reasoning
    fail("model reply has no message")


def extract_json(text):
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(text[start:end + 1])
        raise


def piece_text(value):
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts = []
        for part in value:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict) and isinstance(part.get("text"), str):
                parts.append(part["text"])
        return "".join(parts)
    return ""


def emit(text):
    if text:
        sys.stdout.write(text)
        sys.stdout.flush()


def emit_think(text):
    text = text.replace("\r", " ").replace("\n", " ")
    if text:
        sys.stderr.write("THINK\t" + text + "\n")
        sys.stderr.flush()


def read_reply(resp):
    """Write the answer as it arrives. Thinking goes to stderr, marked THINK."""
    content, reasoning = [], []
    first = resp.readline()
    if not first:
        fail("model reply is empty")
    if first.lstrip().startswith(b"{"):
        raw = first + resp.read()
        text = message_text(json.loads(raw.decode("utf-8")))
        emit(text)
        return text
    pending = first
    while pending:
        line = pending.decode("utf-8", "replace").strip()
        pending = resp.readline()
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if data == "[DONE]":
            break
        try:
            event = json.loads(data)
        except json.JSONDecodeError:
            continue
        choice = (event.get("choices") or [{}])[0]
        delta = choice.get("delta") or choice.get("message") or {}
        word = piece_text(delta.get("content"))
        thought = piece_text(delta.get("reasoning")) or piece_text(delta.get("reasoning_content"))
        if word:
            content.append(word)
            emit(word)
        elif thought:
            reasoning.append(thought)
            emit_think(thought)
    if content:
        return "".join(content)
    text = "".join(reasoning)
    emit(text)
    return text


def main():
    url = os.environ.get("NCDU_CLEAN_AI_URL", "").strip()
    model = os.environ.get("NCDU_CLEAN_AI_MODEL", "").strip()
    key = os.environ.get("NCDU_CLEAN_AI_KEY", "").strip()
    if not url or not model:
        fail("set NCDU_CLEAN_AI_URL and NCDU_CLEAN_AI_MODEL")
    summary = sys.stdin.read()
    if not summary.strip():
        fail("empty summary")
    body_obj = {
        "model": model,
        "max_tokens": 1200,
        "stream": True,
        "messages": [
            {"role": "system", "content": PROMPT},
            {"role": "user", "content": summary},
        ],
    }
    if os.environ.get("NCDU_CLEAN_AI_THINK", "").strip() != "1":
        body_obj["reasoning_effort"] = "none"
    body = json.dumps(body_obj).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = "Bearer " + key
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=None) as resp:
            text = read_reply(resp)
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:2000]
        fail(f"suggestion endpoint returned {e.code}: {detail}")
    except urllib.error.URLError as e:
        fail(f"suggestion endpoint unreachable: {e.reason}")
    try:
        extract_json(text)
    except (UnicodeError, json.JSONDecodeError, ValueError) as e:
        fail(f"model reply is not JSON ({e})")


if __name__ == "__main__":
    main()
