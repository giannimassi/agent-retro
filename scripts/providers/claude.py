#!/usr/bin/env python3
"""Claude Code transcript extraction."""

from __future__ import annotations

import glob
import json
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path

from providers.common import (
    classify_tool_name,
    encoded_size,
    extract_json_field,
    iso_duration_seconds,
    parse_ts,
    read_head_tail,
    stream_jsonl,
)

PRICING_LAST_VERIFIED = "2026-04-06"
PRICE_PER_M = {
    "input": 15.0,
    "output": 75.0,
    "cache_create": 18.75,
    "cache_read": 1.50,
}


def is_match(head_text):
    return (
        '"sessionId"' in head_text
        or '"type":"session_start"' in head_text
        or '"type": "session_start"' in head_text
        or '"message":{"role"' in head_text
        or '"message": {"role"' in head_text
    )


def discover_current_session(cwd):
    sessions_dir = Path.home() / ".claude" / "sessions"
    project_dir = Path.home() / ".claude" / "projects" / cwd.replace("/", "-")

    session_files = sorted(sessions_dir.glob("*.json"), key=os.path.getmtime, reverse=True)
    for session_file in session_files[:10]:
        try:
            data = json.loads(session_file.read_text())
        except (OSError, json.JSONDecodeError):
            continue

        if data.get("cwd") != cwd:
            continue

        session_id = data.get("sessionId")
        if not session_id:
            continue

        transcript_path = project_dir / f"{session_id}.jsonl"
        if transcript_path.is_file():
            return str(transcript_path)

    if project_dir.is_dir():
        candidates = sorted(project_dir.glob("*.jsonl"), key=os.path.getmtime, reverse=True)
        if candidates:
            return str(candidates[0])

    return None


def extract_metadata_lite(path):
    head, tail, size = read_head_tail(path)

    session_id = extract_json_field(head, "sessionId")
    cwd = extract_json_field(head, "cwd")
    git_branch = extract_json_field(head, "gitBranch")
    version = extract_json_field(head, "version")
    start_time = extract_json_field(head, "timestamp")

    end_time = extract_json_field(tail, "timestamp")
    for line in reversed(tail.split("\n")):
        ts = extract_json_field(line, "timestamp")
        if ts:
            end_time = ts
            break

    first_prompt = None
    for line in head.split("\n"):
        if '"role":"user"' not in line and '"role": "user"' not in line:
            continue
        if '"tool_result"' in line:
            continue
        text = extract_json_field(line, "text")
        if text and not text.startswith("<system-reminder>"):
            first_prompt = text[:200]
            break

    return {
        "session_id": session_id,
        "cwd": cwd,
        "git_branch": git_branch,
        "version": version,
        "start_time": start_time,
        "end_time": end_time,
        "duration_seconds": iso_duration_seconds(start_time, end_time),
        "file_size_bytes": size,
        "first_prompt": first_prompt,
    }


def extract_all_streaming(jsonl_path, subagents_dir=None, summary_mode=False):
    session = {
        "session_id": None,
        "cwd": None,
        "git_branch": None,
        "version": None,
        "start_time": None,
        "end_time": None,
        "duration_seconds": None,
        "branches_seen": set(),
    }
    tokens_total = {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
    }
    turn_count = 0
    tool_calls = []
    tool_counts = Counter()
    total_tool_calls = 0
    tool_result_sizes = {}
    arc = []
    branches = set()
    commits = []
    prs = []
    files = defaultdict(set)

    for rec in stream_jsonl(jsonl_path):
        if rec.get("sessionId") and not session["session_id"]:
            session["session_id"] = rec["sessionId"]
        if rec.get("cwd") and not session["cwd"]:
            session["cwd"] = rec["cwd"]
        if rec.get("gitBranch"):
            if not session["git_branch"]:
                session["git_branch"] = rec["gitBranch"]
            session["branches_seen"].add(rec["gitBranch"])
            branches.add(rec["gitBranch"])
        if rec.get("version") and not session["version"]:
            session["version"] = rec["version"]

        ts = rec.get("timestamp")
        if ts:
            if not session["start_time"]:
                session["start_time"] = ts
            session["end_time"] = ts

        msg = rec.get("message", {})
        role = msg.get("role")
        content = msg.get("content", "")
        usage = msg.get("usage", {})

        if usage and role == "assistant":
            tokens_total["input_tokens"] += usage.get("input_tokens", 0)
            tokens_total["output_tokens"] += usage.get("output_tokens", 0)
            tokens_total["cache_creation_input_tokens"] += usage.get("cache_creation_input_tokens", 0)
            tokens_total["cache_read_input_tokens"] += usage.get("cache_read_input_tokens", 0)
            turn_count += 1

        if isinstance(content, list):
            for block in content:
                if not isinstance(block, dict):
                    continue

                block_type = block.get("type")
                if block_type == "tool_use":
                    name = block.get("name", "unknown")
                    tool_input = block.get("input", {})
                    tool_counts[name] += 1
                    total_tool_calls += 1

                    call_summary = {
                        "name": name,
                        "category": classify_tool_name(name),
                        "timestamp": ts,
                        "tool_use_id": block.get("id", ""),
                    }

                    if name == "Agent":
                        call_summary["agent_description"] = tool_input.get("description", "")
                        call_summary["agent_type"] = tool_input.get("subagent_type", "")
                        call_summary["agent_model"] = tool_input.get("model", "")
                        call_summary["agent_prompt_preview"] = tool_input.get("prompt", "")[:300]
                        call_summary["run_in_background"] = tool_input.get("run_in_background", False)
                    elif name == "Skill":
                        call_summary["skill_name"] = tool_input.get("skill", "")
                        call_summary["skill_args"] = tool_input.get("args", "")
                    elif name == "Bash":
                        call_summary["command"] = tool_input.get("command", "")[:300]
                    elif name in ("Read", "Write", "Edit"):
                        call_summary["file_path"] = tool_input.get("file_path", "")
                    elif name in ("Grep", "Glob"):
                        call_summary["pattern"] = tool_input.get("pattern", "")
                    elif name in ("TaskCreate", "TaskUpdate", "TaskList", "TaskOutput"):
                        call_summary["task_detail"] = {
                            key: value
                            for key, value in tool_input.items()
                            if key in ("description", "status", "id")
                        }
                    elif name == "AskUserQuestion":
                        questions = tool_input.get("questions", [])
                        call_summary["questions"] = [q.get("question", "") for q in questions]
                    elif name.startswith("mcp__"):
                        call_summary["mcp_inputs_preview"] = json.dumps(tool_input)[:300]

                    tool_calls.append(call_summary)

                    file_path = tool_input.get("file_path", "")
                    if file_path:
                        if name == "Read":
                            files["read"].add(file_path)
                        elif name == "Write":
                            files["written"].add(file_path)
                        elif name == "Edit":
                            files["edited"].add(file_path)

                    if name == "Bash":
                        command = tool_input.get("command", "")
                        if "git commit" in command:
                            commits.append({"command": command[:200], "timestamp": ts})
                        if "gh pr" in command:
                            prs.append({"command": command[:200], "timestamp": ts})

                elif block_type == "tool_result":
                    tool_use_id = block.get("tool_use_id", "")
                    if tool_use_id:
                        tool_result_sizes[tool_use_id] = encoded_size(block.get("content", ""))

                elif block_type == "text":
                    text = block.get("text", "").strip()
                    if role == "assistant" and text and len(text) > 20:
                        arc.append({"role": "assistant", "text": text[:1000], "timestamp": ts})

            if role == "user":
                user_text = ""
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        user_text += block.get("text", "")
                    elif isinstance(block, str):
                        user_text += block
                user_text = user_text.strip()
                if user_text and not user_text.startswith("<system-reminder>"):
                    arc.append({"role": "user", "text": user_text[:2000], "timestamp": ts})

        elif role == "user":
            text = content.strip() if isinstance(content, str) else ""
            if text and not text.startswith("<system-reminder>"):
                arc.append({"role": "user", "text": text[:2000], "timestamp": ts})

    session["duration_seconds"] = iso_duration_seconds(session["start_time"], session["end_time"])
    session["branches_seen"] = sorted(session["branches_seen"])

    cost = (
        tokens_total["input_tokens"] / 1_000_000 * PRICE_PER_M["input"]
        + tokens_total["output_tokens"] / 1_000_000 * PRICE_PER_M["output"]
        + tokens_total["cache_creation_input_tokens"] / 1_000_000 * PRICE_PER_M["cache_create"]
        + tokens_total["cache_read_input_tokens"] / 1_000_000 * PRICE_PER_M["cache_read"]
    )

    for call in tool_calls:
        tool_use_id = call.get("tool_use_id", "")
        if tool_use_id in tool_result_sizes:
            call["result_size_bytes"] = tool_result_sizes[tool_use_id]

    result_size_stats = {}
    if tool_result_sizes:
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

    agents = _extract_agents(tool_calls, subagents_dir)
    skills = [
        {
            "name": call.get("skill_name", ""),
            "args": call.get("skill_args", ""),
            "timestamp": call.get("timestamp"),
        }
        for call in tool_calls
        if call["name"] == "Skill"
    ]

    agents_without_cost = [
        agent
        for agent in agents
        if agent.get("estimated_cost_usd") is None
        and agent.get("description")
        and not agent.get("description", "").startswith("[unmatched")
    ]
    if agents_without_cost:
        print(
            f"Warning: {len(agents_without_cost)} agent dispatch(es) have no subagent cost data. "
            "Pass --subagents-dir <path> to attribute subagent costs.",
            file=sys.stderr,
        )

    result = {
        "session": session,
        "tokens": {
            "total": tokens_total,
            "turn_count": turn_count,
            "estimated_cost_usd": round(cost, 4),
        },
        "agents": agents,
        "skills": skills,
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


def _extract_agents(tool_calls, subagents_dir=None):
    agents = []
    for call in tool_calls:
        if call["name"] != "Agent":
            continue
        agent = {
            "description": call.get("agent_description", ""),
            "type": call.get("agent_type", "") or "general-purpose",
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

    if subagents_dir and os.path.isdir(subagents_dir):
        _match_subagent_files(agents, subagents_dir)

    return agents


def _match_subagent_files(agents, subagents_dir):
    subagent_files = sorted(glob.glob(os.path.join(subagents_dir, "*.jsonl")))
    max_match_window_s = 60
    subagent_info = []

    for subagent_file in subagent_files:
        subagent_tokens = {
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0,
        }
        subagent_start = None

        for rec in stream_jsonl(subagent_file):
            msg = rec.get("message", {})
            usage = msg.get("usage", {})
            if usage and msg.get("role") == "assistant":
                subagent_tokens["input_tokens"] += usage.get("input_tokens", 0)
                subagent_tokens["output_tokens"] += usage.get("output_tokens", 0)
                subagent_tokens["cache_creation_input_tokens"] += usage.get("cache_creation_input_tokens", 0)
                subagent_tokens["cache_read_input_tokens"] += usage.get("cache_read_input_tokens", 0)
            if subagent_start is None and "timestamp" in rec:
                subagent_start = parse_ts(rec["timestamp"])

        cost = (
            subagent_tokens["input_tokens"] / 1_000_000 * PRICE_PER_M["input"]
            + subagent_tokens["output_tokens"] / 1_000_000 * PRICE_PER_M["output"]
            + subagent_tokens["cache_creation_input_tokens"] / 1_000_000 * PRICE_PER_M["cache_create"]
            + subagent_tokens["cache_read_input_tokens"] / 1_000_000 * PRICE_PER_M["cache_read"]
        )

        meta = None
        meta_file = subagent_file.replace(".jsonl", ".meta.json")
        if os.path.exists(meta_file):
            with open(meta_file) as handle:
                meta = json.load(handle)

        subagent_info.append(
            {
                "file": os.path.basename(subagent_file),
                "tokens": subagent_tokens,
                "cost": round(cost, 4),
                "start_time": subagent_start,
                "meta": meta,
            }
        )

    matched_dispatches = set()
    matched_subagents = set()
    for subagent_index, subagent in enumerate(subagent_info):
        if not subagent["start_time"]:
            continue
        best_match = None
        best_delta = None

        for agent_index, agent in enumerate(agents):
            if agent_index in matched_dispatches:
                continue
            dispatch_time = parse_ts(agent["timestamp"])
            if not dispatch_time:
                continue
            delta = abs((subagent["start_time"] - dispatch_time).total_seconds())
            if delta <= max_match_window_s and (best_delta is None or delta < best_delta):
                best_match = agent_index
                best_delta = delta

        if best_match is not None:
            agents[best_match]["tokens"] = subagent["tokens"]
            agents[best_match]["estimated_cost_usd"] = subagent["cost"]
            agents[best_match]["subagent_file"] = subagent["file"]
            agents[best_match]["match_delta_s"] = round(best_delta, 1)
            if subagent["meta"]:
                agents[best_match]["meta"] = subagent["meta"]
            matched_dispatches.add(best_match)
            matched_subagents.add(subagent_index)

    for subagent_index, subagent in enumerate(subagent_info):
        if subagent_index in matched_subagents:
            continue
        agents.append(
            {
                "description": f"[unmatched subagent: {subagent['file']}]",
                "type": "unknown",
                "model": "unknown",
                "prompt_preview": "",
                "background": False,
                "timestamp": str(subagent["start_time"]) if subagent["start_time"] else None,
                "tool_use_id": "",
                "tokens": subagent["tokens"],
                "estimated_cost_usd": subagent["cost"],
                "subagent_file": subagent["file"],
                "match_confidence": "unmatched",
                "meta": subagent["meta"],
            }
        )
