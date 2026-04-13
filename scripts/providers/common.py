#!/usr/bin/env python3
"""Shared helpers for provider-specific transcript extraction."""

from __future__ import annotations

import json
import os
import re
from datetime import datetime

SCHEMA_VERSION = "0.2.0"
LITE_READ_BUF_SIZE = 65536

PATCH_FILE_RE = re.compile(r"^\*\*\* (Add|Delete|Update) File: (.+)$")
PATCH_MOVE_RE = re.compile(r"^\*\*\* Move to: (.+)$")


def stream_jsonl(path):
    """Yield parsed JSONL records one at a time without loading the file."""
    with open(path) as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def read_head_tail(path):
    """Read the first and last 64KB of a file."""
    size = os.path.getsize(path)
    with open(path, "rb") as handle:
        head_bytes = handle.read(LITE_READ_BUF_SIZE)
        head = head_bytes.decode("utf-8", errors="replace")

        if size <= LITE_READ_BUF_SIZE:
            return head, head, size

        handle.seek(max(0, size - LITE_READ_BUF_SIZE))
        tail_bytes = handle.read(LITE_READ_BUF_SIZE)
        tail = tail_bytes.decode("utf-8", errors="replace")

    return head, tail, size


def extract_json_field(text, key):
    """Extract a JSON string field value without full parsing."""
    for pattern in [f'"{key}":"', f'"{key}": "']:
        idx = text.find(pattern)
        if idx < 0:
            continue
        start = idx + len(pattern)
        i = start
        while i < len(text):
            if text[i] == "\\":
                i += 2
                continue
            if text[i] == '"':
                return text[start:i]
            i += 1
    return None


def parse_ts(ts_str):
    """Parse ISO 8601 timestamps used by transcript files."""
    if not ts_str:
        return None
    try:
        return datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def encoded_size(value):
    """Estimate the UTF-8 byte length of a structured value."""
    if isinstance(value, bytes):
        return len(value)
    if isinstance(value, str):
        return len(value.encode("utf-8", errors="replace"))
    return len(json.dumps(value, default=str).encode("utf-8"))


def load_tool_arguments(arguments):
    """Parse a tool-call argument payload while preserving raw text."""
    if isinstance(arguments, dict):
        return arguments, json.dumps(arguments)
    if not isinstance(arguments, str):
        return {}, ""

    stripped = arguments.strip()
    if not stripped:
        return {}, arguments

    if stripped.startswith("{") or stripped.startswith("["):
        try:
            return json.loads(stripped), arguments
        except json.JSONDecodeError:
            pass

    return {"_raw": arguments}, arguments


def extract_patch_file_changes(patch_text):
    """Parse apply_patch file operations into written and edited file sets."""
    changes = {
        "written": set(),
        "edited": set(),
        "deleted": set(),
    }
    pending_update_path = None

    for raw_line in patch_text.splitlines():
        match = PATCH_FILE_RE.match(raw_line)
        if match:
            op, file_path = match.groups()
            pending_update_path = None
            if op == "Add":
                changes["written"].add(file_path)
            elif op == "Update":
                changes["edited"].add(file_path)
                pending_update_path = file_path
            elif op == "Delete":
                changes["deleted"].add(file_path)
            continue

        move_match = PATCH_MOVE_RE.match(raw_line)
        if move_match and pending_update_path:
            changes["edited"].discard(pending_update_path)
            changes["written"].add(move_match.group(1))
            changes["deleted"].add(pending_update_path)
            pending_update_path = move_match.group(1)

    return changes


def classify_tool_name(name):
    """Map provider-specific tool names into coarse shared categories."""
    if name in {"Read", "Grep", "Glob"}:
        return "read"
    if name in {"Write", "Edit", "apply_patch"}:
        return "write"
    if name in {"Bash", "exec_command"}:
        return "exec"
    if name in {"Agent", "spawn_agent"}:
        return "agent"
    if name in {"Skill", "request_user_input"}:
        return "skill"
    if name.startswith("mcp__"):
        return "mcp"
    return "other"


def iso_duration_seconds(start_time, end_time):
    start = parse_ts(start_time)
    end = parse_ts(end_time)
    if not start or not end:
        return None
    return round((end - start).total_seconds())
