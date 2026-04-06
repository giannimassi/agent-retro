# agent-retro

> **Compatibility: Claude Code only (for now).** This skill reads Claude Code's JSONL session transcripts. Support for other agents (Gemini CLI, Codex, Cursor, etc.) is on the [roadmap](#roadmap).

A session retrospective skill for AI coding agents. Run `/agent-retro` at the end of a session to analyze what happened, identify friction, and get concrete suggestions for improving your skills, rules, and workflows.

Follows the [Agent Skills](https://agentskills.io) open standard.

## What it does

`/agent-retro` reads your session transcript from disk and produces a structured analysis:

- **Full conversation arc** — every user message and assistant response, in order. No sampling, no skipping.
- **Token cost breakdown** — per-agent attribution so you can see where the budget went.
- **Tool result waste detection** — flags oversized tool results (a 45KB file read that was never used is money burned).
- **Friction analysis** — identifies user corrections, redirects, and abandoned approaches, then traces each to a root cause.
- **Actionable proposals** — specific edits to skills, rules, or config. Not vague "improve X" — the actual text to change.

The output is a markdown retro file plus an interactive walkthrough where you approve or defer each proposed action.

## Why this exists

Every agent framework has inline reflection (retry loops, critic agents). None of them do **post-session systemic reflection** — looking across an entire conversation to find patterns of failure and proposing configuration changes to prevent them next time.

This is the equivalent of an agile sprint retrospective, but for a single AI session, producing machine-editable artifacts rather than sticky notes on a board. See [references/design.md](references/design.md) for the full design rationale and comparison with Reflexion, LangGraph, CrewAI, and others.

## Install

**Recommended** (works with any Agent Skills-compatible tool):

```bash
npx skills add giannimassi/agent-retro
```

**Or clone manually** into your skills directory:

```bash
# Claude Code
git clone https://github.com/giannimassi/agent-retro.git ~/.claude/skills/agent-retro

# Gemini CLI (when supported)
# git clone https://github.com/giannimassi/agent-retro.git ~/.gemini/skills/agent-retro
```

## Usage

At the end of any session:

```
/agent-retro
```

The skill will:

1. Find your current session's transcript
2. Extract structured data (streaming, no full file load)
3. Analyze the conversation arc for friction patterns
4. Classify what the session produced
5. Propose concrete improvements
6. Walk you through each proposal for approval

### Extraction script standalone

The Python extraction script can be used independently:

```bash
# Quick session verification (reads only first/last 64KB)
python3 scripts/extract.py <session.jsonl> --metadata-only

# Compact extraction (tool counts, no individual calls)
python3 scripts/extract.py <session.jsonl> --summary

# Full extraction (includes every tool call detail)
python3 scripts/extract.py <session.jsonl>
```

## How it works

### Token-efficient extraction

The extraction script (`scripts/extract.py`) minimizes token usage:

- **Streaming** — processes JSONL line-by-line, never loads the full file into memory
- **No tool result content** — tracks result **sizes** without including the content. A 50MB session transcript produces ~30KB of extraction output.
- **Head/tail metadata** — `--metadata-only` reads only the first and last 64KB of the file for session verification, borrowing a technique from Claude Code's internal `readSessionLite` function.
- **Full conversation arc** — all user messages and assistant text are preserved. The arc is the whole point of a retro — you can't analyze friction you can't see.

### What the extraction captures

| Field | What | Why |
|---|---|---|
| `session` | ID, cwd, branch, duration | Context |
| `tokens` | Input/output/cache totals + USD cost | Budget analysis |
| `tools` | Call counts or full call list | Pattern detection |
| `agents` | Each dispatch with type, model, cost | Delegation efficiency |
| `skills` | Each invocation with args | Skill triggering analysis |
| `git` | Branches, commits, PR operations | What was shipped |
| `files` | Files read/written/edited | Scope tracking |
| `conversation_arc` | Full timeline of messages | Friction detection |
| `tool_result_sizes` | Per-tool total/avg/max bytes | Waste detection |

## Example output

See [examples/sample-retro.md](examples/sample-retro.md) for a retro from a real session.

## Roadmap

This skill currently only works with **Claude Code**. The analysis steps (friction detection, root cause tracing, action proposals) are agent-agnostic — only the transcript reading is Claude-specific.

Planned support:

| Agent | Transcript format | Status |
|---|---|---|
| **Claude Code** | `~/.claude/projects/<cwd>/<session>.jsonl` | Supported |
| **Gemini CLI** | `~/.gemini/sessions/` | Planned |
| **OpenAI Codex** | TBD | Planned |
| **Cursor** | TBD | Planned |
| **Roo Code** | TBD | Planned |

Contributions welcome — if you know where another agent stores its session data, open an issue.

## Requirements

- Python 3.8+ (stdlib only, no dependencies)
- Currently: Claude Code v2.1.59+

## License

MIT
