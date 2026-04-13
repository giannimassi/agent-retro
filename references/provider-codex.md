# Codex Provider

Use this reference when `python3 scripts/extract.py --discover-current --provider auto --metadata-only` reports `provider: codex`.

## Discover the current session

Preferred path:

```bash
python3 scripts/extract.py --discover-current --provider codex --metadata-only
```

If discovery fails, inspect recent rollout transcripts manually:

```bash
find ~/.codex/sessions -type f -name 'rollout-*.jsonl' | sort | tail -10
```

Then verify the likely candidate:

```bash
python3 scripts/extract.py <candidate.jsonl> --provider codex --metadata-only
```

Confirm that `cwd` matches the current project and `first_prompt` matches the start of the session.

## Run extraction

```bash
python3 scripts/extract.py --discover-current --provider codex --summary
```

If you need raw call details:

```bash
python3 scripts/extract.py <path-to-session.jsonl> --provider codex
```

## Codex-specific notes

- Codex transcripts are event-based rather than message-block-based.
- Token totals come from the latest `token_count` event.
- Estimated USD cost is left unavailable by default because local Codex transcripts do not expose a stable pricing model in the same way as Claude.
- File edits are inferred from `apply_patch` calls when present.

## Retro file location

Write retros to:

```text
~/.codex/worklog/retros/YYYY-MM-DD-<slug>.md
```
