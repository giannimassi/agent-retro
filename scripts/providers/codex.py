#!/usr/bin/env python3
"""Codex transcript extraction."""

from __future__ import annotations

import json
import os
from collections import Counter, defaultdict
from pathlib import Path

from providers.common import (
    classify_tool_name,
    encoded_size,
    extract_patch_file_changes,
    iso_duration_seconds,
    load_tool_arguments,
    read_head_tail,
    stream_jsonl,
)


def is_match(head_text):
    return '"type":"session_meta"' in head_text or '"type": "session_meta"' in head_text


def discover_current_session(cwd):
    sessions_root = Path.home() / ".codex" / "sessions"
    if not sessions_root.is_dir():
        return None

    candidates = sorted(sessions_root.rglob("rollout-*.jsonl"), key=os.path.getmtime, reverse=True)
    for candidate in candidates[:20]:
        metadata = extract_metadata_lite(candidate)
        if metadata.get("cwd") == cwd:
            return str(candidate)
    return None


def extract_metadata_lite(path):
    head, tail, size = read_head_tail(path)
    session_id = None
    cwd = None
    version = None
    start_time = None
    first_prompt = None

    for line in head.splitlines():
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue

        if rec.get("type") == "session_meta":
            payload = rec.get("payload", {})
            session_id = payload.get("id")
            cwd = payload.get("cwd")
            version = payload.get("cli_version")
            start_time = payload.get("timestamp") or rec.get("timestamp")
        elif rec.get("type") == "event_msg":
            payload = rec.get("payload", {})
            if payload.get("type") == "user_message" and payload.get("message"):
                first_prompt = payload["message"][:200]
                break

    end_time = None
    for line in reversed(tail.splitlines()):
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        end_time = rec.get("timestamp") or end_time
        if end_time:
            break

    return {
        "session_id": session_id,
        "cwd": cwd,
        "git_branch": None,
        "version": version,
        "start_time": start_time,
        "end_time": end_time,
        "duration_seconds": iso_duration_seconds(start_time, end_time),
        "file_size_bytes": size,
        "first_prompt": first_prompt,
    }


def extract_all_streaming(jsonl_path, subagents_dir=None, summary_mode=False):
    del subagents_dir

    session = {
        "session_id": None,
        "cwd": None,
        "git_branch": None,
        "version": None,
        "start_time": None,
        "end_time": None,
        "duration_seconds": None,
        "branches_seen": [],
    }
    tool_calls = []
    call_index = {}
    tool_counts = Counter()
    total_tool_calls = 0
    arc = []
    branches = set()
    commits = []
    prs = []
    files = defaultdict(set)
    latest_total_usage = {}

    for rec in stream_jsonl(jsonl_path):
        ts = rec.get("timestamp")
        rec_type = rec.get("type")

        if rec_type == "session_meta":
            payload = rec.get("payload", {})
            session["session_id"] = session["session_id"] or payload.get("id")
            session["cwd"] = session["cwd"] or payload.get("cwd")
            session["version"] = session["version"] or payload.get("cli_version")
            start_time = payload.get("timestamp") or ts
            if start_time and not session["start_time"]:
                session["start_time"] = start_time
            if ts:
                session["end_time"] = ts
            continue

        if ts:
            if not session["start_time"]:
                session["start_time"] = ts
            session["end_time"] = ts

        if rec_type == "event_msg":
            payload = rec.get("payload", {})
            event_type = payload.get("type")

            if event_type == "user_message":
                text = (payload.get("message") or "").strip()
                if text:
                    arc.append({"role": "user", "text": text[:2000], "timestamp": ts})
            elif event_type == "agent_message":
                text = (payload.get("message") or "").strip()
                if text and len(text) > 20:
                    arc.append({"role": "assistant", "text": text[:1000], "timestamp": ts})
            elif event_type == "token_count":
                info = payload.get("info") or {}
                latest_total_usage = info.get("total_token_usage") or latest_total_usage
            elif event_type == "exec_command_end":
                call_id = payload.get("call_id", "")
                call = call_index.get(call_id)
                if not call:
                    continue
                output = payload.get("aggregated_output", "")
                call["result_size_bytes"] = encoded_size(output)
                call["exit_code"] = payload.get("exit_code")

        elif rec_type == "response_item":
            payload = rec.get("payload", {})
            payload_type = payload.get("type")

            if payload_type == "function_call":
                name = payload.get("name", "unknown")
                tool_input, raw_arguments = load_tool_arguments(payload.get("arguments", ""))
                tool_counts[name] += 1
                total_tool_calls += 1

                call_summary = {
                    "name": name,
                    "category": classify_tool_name(name),
                    "timestamp": ts,
                    "tool_use_id": payload.get("call_id", ""),
                }

                if name == "exec_command":
                    command = tool_input.get("cmd", "")
                    call_summary["command"] = command[:300]
                    if tool_input.get("workdir"):
                        call_summary["workdir"] = tool_input["workdir"]
                    if "git commit" in command:
                        commits.append({"command": command[:200], "timestamp": ts})
                    if "gh pr" in command:
                        prs.append({"command": command[:200], "timestamp": ts})
                elif name == "spawn_agent":
                    description = tool_input.get("message", "")
                    call_summary["agent_description"] = description[:200]
                    call_summary["agent_type"] = tool_input.get("agent_type", "")
                    call_summary["agent_model"] = tool_input.get("model", "")
                    call_summary["agent_prompt_preview"] = description[:300]
                    call_summary["run_in_background"] = False
                elif name == "request_user_input":
                    questions = tool_input.get("questions", [])
                    call_summary["questions"] = [q.get("question", "") for q in questions]
                elif name == "apply_patch":
                    patch_text = raw_arguments
                    if isinstance(tool_input, dict) and "_raw" in tool_input:
                        patch_text = tool_input["_raw"]
                    file_changes = extract_patch_file_changes(patch_text)
                    file_paths = sorted(file_changes["written"] | file_changes["edited"] | file_changes["deleted"])
                    if file_paths:
                        call_summary["file_paths"] = file_paths
                        call_summary["file_path"] = file_paths[0]
                    files["written"].update(file_changes["written"])
                    files["edited"].update(file_changes["edited"])
                elif name.startswith("mcp__"):
                    call_summary["mcp_inputs_preview"] = json.dumps(tool_input, default=str)[:300]
                    if name.endswith("github_create_pull_request"):
                        prs.append({"command": name, "timestamp": ts})

                if name == "exec_command" and tool_input.get("cmd"):
                    command = tool_input["cmd"]
                    if "git checkout -b " in command or "git switch -c " in command:
                        branches.add(command[:200])

                tool_calls.append(call_summary)
                call_index[call_summary["tool_use_id"]] = call_summary

            elif payload_type == "function_call_output":
                call_id = payload.get("call_id", "")
                call = call_index.get(call_id)
                if call and "result_size_bytes" not in call:
                    call["result_size_bytes"] = encoded_size(payload.get("output", ""))

    session["duration_seconds"] = iso_duration_seconds(session["start_time"], session["end_time"])

    tokens_total = {
        "input_tokens": latest_total_usage.get("input_tokens", 0),
        "output_tokens": latest_total_usage.get("output_tokens", 0),
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": latest_total_usage.get("cached_input_tokens", 0),
        "reasoning_output_tokens": latest_total_usage.get("reasoning_output_tokens", 0),
        "total_tokens": latest_total_usage.get("total_tokens", 0),
    }
    turn_count = sum(1 for message in arc if message["role"] == "assistant")

    result_size_stats = {}
    sizes_by_tool = defaultdict(list)
    for call in tool_calls:
        if "result_size_bytes" in call:
            sizes_by_tool[call["name"]].append(call["result_size_bytes"])

    for tool_name, sizes in sorted(sizes_by_tool.items(), key=lambda item: -sum(item[1])):
        result_size_stats[tool_name] = {
            "count": len(sizes),
            "total_bytes": sum(sizes),
            "avg_bytes": round(sum(sizes) / len(sizes)),
            "max_bytes": max(sizes),
        }

    agents = []
    for call in tool_calls:
        if call["name"] != "spawn_agent":
            continue
        agent = {
            "description": call.get("agent_description", ""),
            "type": call.get("agent_type", "") or "default",
            "model": call.get("agent_model", "") or "inherited",
            "prompt_preview": call.get("agent_prompt_preview", ""),
            "background": call.get("run_in_background", False),
            "timestamp": call.get("timestamp"),
            "tool_use_id": call.get("tool_use_id", ""),
            "tokens": None,
            "estimated_cost_usd": None,
        }
        if "result_size_bytes" in call:
            agent["result_size_bytes"] = call["result_size_bytes"]
        agents.append(agent)

    result = {
        "session": session,
        "tokens": {
            "total": tokens_total,
            "turn_count": turn_count,
            "estimated_cost_usd": None,
        },
        "agents": agents,
        "skills": [],
        "git": {
            "branches": sorted(branches),
            "commits": commits,
            "pr_operations": prs,
        },
        "files": {key: sorted(value) for key, value in files.items()},
        "conversation_arc": arc,
        "tool_result_sizes": result_size_stats,
    }

    if summary_mode:
        result["tools"] = {
            "counts": dict(tool_counts.most_common()),
            "total_calls": total_tool_calls,
        }
    else:
        result["tools"] = {
            "calls": tool_calls,
            "counts": dict(tool_counts.most_common()),
            "total_calls": total_tool_calls,
        }

    return result
