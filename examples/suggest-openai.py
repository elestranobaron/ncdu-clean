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
import time
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
    "Prefer a removable disk. Do not put the folder on the scan disk when a "
    "removable disk is listed. "
    "The scan disk must be freed. The removable disk's free space is the room "
    "for quarantine. "
    "delete is for caches, temporary files, dumps and old update folders. "
    "Then quarantine the largest other items, including a whole installed "
    "program, until the quarantined sizes are close to that free space. "
    "Do not stop once the caches are listed when larger items are in the list. "
    "Do not take the Program Files directory or Program Files (x86) as one item: "
    "that is every program at once. Do take the large programs inside them "
    "when those programs are in the list. "
    "create is true when that folder does not exist yet. "
    "The program keeps the original paths inside that one folder. "
    "Never suggest a user profile, pagefile.sys, swapfile.sys, hiberfil.sys, "
    "or the Windows, System32, SysWOW64 or WinSxS directories. "
    "Those break the system. One short reason, a single line."
)

THINK_PROMPT = (
    PROMPT.replace(
        "Reply with JSON only, no markdown, in this shape: ",
        "The JSON object has this shape: ",
    )
    + " Write at most 12 short lines. Name the chosen paths and the action. "
    "Copy every path exactly from the items list. "
    "Then write a line that contains only DONE. "
    "Then write the JSON object and nothing else. "
    "Do not discuss these instructions."
)

PROMPT += " The answer itself is only that JSON object."


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
        obj = json.loads(text)
    except json.JSONDecodeError:
        obj = None
    items = obj.get("items") if isinstance(obj, dict) else None
    if isinstance(items, list) and (
            not items or any(
                isinstance(item, dict)
                and isinstance(item.get("path"), str)
                and item["path"].startswith("/")
                and "..." not in item["path"]
                and item.get("action") in ("delete", "quarantine")
                for item in items)):
        return obj
    decoder = json.JSONDecoder()
    start = 0
    while True:
        brace = text.find("{", start)
        if brace < 0:
            break
        try:
            found, end = decoder.raw_decode(text, brace)
        except json.JSONDecodeError:
            start = brace + 1
            continue
        items = found.get("items") if isinstance(found, dict) else None
        if isinstance(items, list) and (
                not items or any(
                    isinstance(item, dict)
                    and isinstance(item.get("path"), str)
                    and item["path"].startswith("/")
                    and "..." not in item["path"]
                    and item.get("action") in ("delete", "quarantine")
                    for item in items)):
            return found
        start = end if isinstance(end, int) and end > brace else brace + 1
    raise json.JSONDecodeError("no plan", text, 0)


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


def read_reply(resp, on_content):
    """Stream one reply. Reasoning deltas go to stderr. Content goes to on_content."""
    content, reasoning = [], []

    def take(piece):
        if piece:
            content.append(piece)
            on_content(piece)

    first = resp.readline()
    if not first:
        fail("model reply is empty")
    if first.lstrip().startswith(b"{"):
        raw = first + resp.read()
        payload = json.loads(raw.decode("utf-8"))
        try:
            message = payload["choices"][0]["message"]
        except (KeyError, IndexError, TypeError):
            fail("model reply has no message")
        thought = message.get("reasoning") or message.get("reasoning_content")
        text = message_text(payload)
        if isinstance(thought, str) and thought != text:
            emit_think(thought)
        take(text)
        return "".join(content)
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
        if thought:
            reasoning.append(thought)
            emit_think(thought)
        if word:
            take(word)
    if content:
        return "".join(content)
    text = "".join(reasoning)
    take(text)
    return text


def post(url, key, body_obj, on_content):
    body = json.dumps(body_obj).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = "Bearer " + key
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=None) as resp:
            return read_reply(resp, on_content)
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:2000]
        fail(f"suggestion endpoint returned {e.code}: {detail}")
    except urllib.error.URLError as e:
        fail(f"suggestion endpoint unreachable: {e.reason}")


def signal_think_done(started):
    elapsed = 0 if started is None else time.monotonic() - started
    sys.stderr.write(f"THINK_DONE\t{elapsed:.3f}\n")
    sys.stderr.flush()


def think_and_answer(url, key, model, summary):
    """One request. The essay and the JSON share that context.

    Lines before a line that is only DONE are the reasoning. The rest is the plan.
    16000 is a ceiling: the server stops when the model stops."""
    state = {"held": "", "passed": False, "answer": [], "started": None}

    def on_content(piece):
        if state["started"] is None:
            state["started"] = time.monotonic()
        if state["passed"]:
            state["answer"].append(piece)
            emit(piece)
            return
        if not state["held"].strip() and piece.lstrip().startswith("{"):
            state["passed"] = True
            signal_think_done(state["started"])
            state["answer"].append(piece)
            emit(piece)
            return
        state["held"] += piece
        while "\n" in state["held"] and not state["passed"]:
            line, state["held"] = state["held"].split("\n", 1)
            if line.strip() == "DONE":
                state["passed"] = True
                signal_think_done(state["started"])
                if state["held"]:
                    state["answer"].append(state["held"])
                    emit(state["held"])
                    state["held"] = ""
                return
            emit_think(line + "\n")

    text = post(url, key, {
        "model": model,
        "max_tokens": 16000,
        "stream": True,
        "messages": [
            {"role": "system", "content": THINK_PROMPT},
            {"role": "user", "content": summary},
        ],
    }, on_content) or ""
    if state["passed"]:
        return "".join(state["answer"]), True
    rest = state["held"]
    if rest.strip() == "DONE":
        signal_think_done(state["started"])
        return "", False
    if rest:
        emit_think(rest)
    if state["started"] is not None:
        signal_think_done(state["started"])
    return text, False


def json_only(url, key, model, summary):
    """One short call that writes the plan, used when the reasoning never reached it."""
    return post(url, key, {
        "model": model,
        "max_tokens": 1200,
        "stream": True,
        "reasoning_effort": "none",
        "messages": [
            {"role": "system", "content": PROMPT},
            {"role": "user", "content": summary},
        ],
    }, emit) or ""


def main():
    url = os.environ.get("NCDU_CLEAN_AI_URL", "").strip()
    model = os.environ.get("NCDU_CLEAN_AI_MODEL", "").strip()
    key = os.environ.get("NCDU_CLEAN_AI_KEY", "").strip()
    if not url or not model:
        fail("set NCDU_CLEAN_AI_URL and NCDU_CLEAN_AI_MODEL")
    summary = sys.stdin.read()
    if not summary.strip():
        fail("empty summary")
    thinking = os.environ.get("NCDU_CLEAN_AI_THINK", "").strip() == "1"
    if thinking:
        text, emitted = think_and_answer(url, key, model, summary)
        try:
            plan = extract_json(text)
        except (UnicodeError, json.JSONDecodeError, ValueError):
            plan = None
        if plan is None:
            text = json_only(url, key, model, summary)
        elif not emitted:
            text = json.dumps(plan, ensure_ascii=False)
            emit(text)
    else:
        text = json_only(url, key, model, summary)
    try:
        extract_json(text)
    except (UnicodeError, json.JSONDecodeError, ValueError) as e:
        fail(f"model reply is not JSON ({e})")


if __name__ == "__main__":
    main()
