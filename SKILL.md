---
name: agent-retro
description: Run a conversation retrospective — analyze what happened in this session, what worked, what didn't, and propose concrete improvements. Use when the user says "retro", "retrospective", "what happened in this session", "session review", "what did we do", or "analyze this conversation". Works in Claude Code and OpenAI Codex by reading the local session transcript and producing a structured retro plus follow-up actions.
metadata:
  author: giannimassi
  version: "0.2.0"
---

# /agent-retro — Conversation Retrospective

Analyze the current session end-to-end: what happened, what it produced, what worked, what did not, and what to improve. The output is a structured retro file plus a set of proposed actions you walk through with the user.

## Step 1: Discover The Runtime And Transcript

Always work from the session transcript on disk, not just current context.

Start with the bundled extractor:

```bash
python3 scripts/extract.py --discover-current --provider auto --metadata-only
```

This returns:
- `provider`
- `transcript_path`
- `session_id`
- `cwd`
- `git_branch` when available
- `first_prompt`
- timestamps and file size

Check that `cwd` matches the current project and that `first_prompt` matches the start of the conversation.

Then load the provider-specific guidance:
- If `provider` is `claude`, read [references/provider-claude.md](references/provider-claude.md)
- If `provider` is `codex`, read [references/provider-codex.md](references/provider-codex.md)

Once the provider is confirmed, read [references/workflow-core.md](references/workflow-core.md) and follow it for the rest of the retro.

## Fallbacks

- If `--discover-current` fails, use the manual discovery steps in the provider reference.
- If extraction fails, fall back to analyzing current conversation context and explicitly note that compacted or omitted transcript content may be missing.
