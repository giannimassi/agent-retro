# claude-code-retro

A session retrospective skill for [Claude Code](https://docs.anthropic.com/en/docs/claude-code). Run `/retro` at the end of a session to analyze what happened, identify friction, and get concrete suggestions for improving your skills, rules, and workflows.

## What it does

`/retro` reads your session transcript from disk (the JSONL file Claude Code writes during every conversation) and produces a structured analysis:

- **Full conversation arc** — every user message and assistant response, in order. No sampling, no skipping.
- **Token cost breakdown** — per-agent attribution so you can see where the budget went.
- **Tool result waste detection** — flags oversized tool results (a 45KB file read that was never used is money burned).
- **Friction analysis** — identifies user corrections, redirects, and abandoned approaches, then traces each to a root cause.
- **Actionable proposals** — specific edits to skills, rules, or CLAUDE.md. Not vague "improve X" — the actual text to change.

The output is a markdown retro file saved to `~/.claude/worklog/retros/`, plus an interactive walkthrough where you approve or defer each proposed action.

## Why this exists

Every agent orchestration framework has inline reflection (retry loops, critic agents). None of them do **post-session systemic reflection** — looking across an entire conversation to find patterns of failure and proposing configuration changes to prevent them next time.

This is the equivalent of an agile sprint retrospective, but for a single AI session, and the output is machine-editable artifacts rather than sticky notes.

## Install

```bash
claude plugin add giannimassi/claude-code-retro
```

Or install manually by cloning to your skills directory:

```bash
git clone https://github.com/giannimassi/claude-code-retro.git ~/.claude/skills/retro
```

## Usage

At the end of any Claude Code session:

```
/retro
```

That's it. The skill will:

1. Find your current session's JSONL transcript
2. Extract structured data (streaming, no full file load into memory)
3. Analyze the conversation arc for friction patterns
4. Classify what the session produced
5. Propose concrete improvements
6. Walk you through each proposal for approval

### Extraction script standalone

The Python extraction script can also be used independently:

```bash
# Quick session verification (reads only first/last 64KB)
python3 scripts/extract.py <session.jsonl> --metadata-only

# Compact extraction (tool counts, no individual calls)
python3 scripts/extract.py <session.jsonl> --summary

# Full extraction (includes every tool call detail)
python3 scripts/extract.py <session.jsonl>
```

## How it works

### Session discovery

Claude Code writes every conversation to a JSONL file at `~/.claude/projects/<encoded-cwd>/<session-id>.jsonl`. The skill finds the current session by checking `~/.claude/sessions/*.json` (maps PID to session ID), then verifying via a cheap head/tail read.

### Token-efficient extraction

The extraction script (`scripts/extract.py`) is designed to minimize token usage:

- **Streaming** — processes JSONL line-by-line, never loads the full file into memory
- **No tool result content** — tool results (file contents, command output) are the biggest token hogs. The script tracks their **size** without including the content. A 50MB session transcript produces ~30KB of extraction output.
- **Head/tail metadata** — `--metadata-only` reads only the first and last 64KB of the file for session verification. This technique is borrowed from [Claude Code's own session storage](docs/design.md#inspiration-claude-codes-session-storage), which uses the same pattern to list sessions without parsing every line.
- **Conversation arc preservation** — all user messages (500 char) and assistant text (300 char) are kept. The arc is the whole point of a retro — you can't analyze friction you can't see.

### What the extraction captures

| Field | What | Why |
|---|---|---|
| `session` | ID, cwd, branch, duration | Context |
| `tokens` | Input/output/cache totals + USD cost | Budget analysis |
| `tools` | Call counts (summary) or full call list | Pattern detection |
| `agents` | Each dispatch with type, model, cost, prompt preview | Delegation efficiency |
| `skills` | Each skill invocation with args | Skill triggering analysis |
| `git` | Branches, commits, PR operations | What was shipped |
| `files` | Files read/written/edited | Scope tracking |
| `conversation_arc` | Full timeline of messages | Friction detection |
| `tool_result_sizes` | Per-tool total/avg/max bytes | Waste detection |

## Example output

See [examples/sample-retro.md](examples/sample-retro.md) for a complete retro output from a real session.

## Design decisions

See [docs/design.md](docs/design.md) for the reasoning behind key choices — why we don't sample the arc, why tool results are size-only, and how this relates to Claude Code's internal auto-dream feature.

## Requirements

- Claude Code v2.1.59+
- Python 3.8+ (for `extract.py` — stdlib only, no dependencies)

## License

MIT
