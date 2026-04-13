# agent-retro

> **Compatibility: Claude Code and OpenAI Codex.** The shared retro workflow is runtime-agnostic; transcript discovery and parsing are handled by provider adapters.

A session retrospective skill for AI coding agents. Run `/agent-retro` at the end of a session to analyze what happened, identify friction, and get concrete suggestions for improving skills, rules, and workflows.

Follows the [Agent Skills](https://agentskills.io) open standard.

## What it does

`/agent-retro` reads your session transcript from disk and produces a structured analysis:

- **Full conversation arc**: every user message and assistant response, in order
- **Token budget breakdown**: totals plus runtime-estimated cost when available
- **Tool result waste detection**: flags oversized tool results that were likely wasted
- **Friction analysis**: identifies corrections, redirects, and abandoned approaches
- **Actionable proposals**: concrete edits to skills, rules, or setup

The output is a markdown retro file plus an interactive walkthrough where you approve or defer each proposed action.

## Install

**Recommended**:

```bash
npx skills add giannimassi/agent-retro
```

**Manual clone**:

```bash
# Claude Code
git clone https://github.com/giannimassi/agent-retro.git ~/.claude/skills/agent-retro

# OpenAI Codex
git clone https://github.com/giannimassi/agent-retro.git ~/.codex/skills/agent-retro
```

## Usage

At the end of any session:

```text
/agent-retro
```

The skill will:

1. Discover the current session transcript
2. Verify the provider and candidate file
3. Extract structured data
4. Analyze the conversation arc
5. Classify outcomes and friction
6. Propose concrete follow-up actions

## Extraction script

The bundled script supports both runtimes.

```bash
# Discover and verify the current session
python3 scripts/extract.py --discover-current --provider auto --metadata-only

# Compact extraction for the current session
python3 scripts/extract.py --discover-current --provider auto --summary

# Extract a known transcript path
python3 scripts/extract.py <session.jsonl> --provider auto
```

Supported providers:
- `auto`
- `claude`
- `codex`

## How it works

### Shared core plus provider adapters

The repo uses one shared retro workflow plus provider-specific session adapters:

- Claude adapter: `~/.claude/sessions` and `~/.claude/projects/...`
- Codex adapter: `~/.codex/sessions/.../rollout-*.jsonl`
- Shared workflow: classification, friction analysis, action proposals, retro markdown format

### What the extraction captures

| Field | What | Why |
|---|---|---|
| `provider` | Runtime that produced the transcript | Adapter routing |
| `session` | ID, cwd, branch when available, duration | Context |
| `tokens` | Token totals and estimated USD cost when available | Budget analysis |
| `tools` | Tool counts or full call list | Pattern detection |
| `agents` | Agent dispatches with type/model when available | Delegation analysis |
| `skills` | Explicit skill invocations when exposed by the runtime | Skill triggering analysis |
| `git` | Branch, commit, and PR operations | What was shipped |
| `files` | Files read, written, or edited | Scope tracking |
| `conversation_arc` | Full message timeline | Friction detection |
| `tool_result_sizes` | Per-tool total/avg/max bytes | Waste detection |

## Example output

See [examples/sample-retro.md](examples/sample-retro.md) for a Claude retro example. The markdown structure is shared across providers.

## Runtime status

| Agent | Transcript format | Status |
|---|---|---|
| **Claude Code** | `~/.claude/projects/<cwd>/<session>.jsonl` | Supported |
| **OpenAI Codex** | `~/.codex/sessions/**/rollout-*.jsonl` | Supported |
| **Gemini CLI** | TBD | Planned |
| **Cursor** | TBD | Planned |
| **Roo Code** | TBD | Planned |

## Requirements

- Python 3.8+
- Claude Code for Claude transcripts
- OpenAI Codex for Codex transcripts

## License

MIT
