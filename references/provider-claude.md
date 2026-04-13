# Claude Provider

Use this reference when `python3 scripts/extract.py --discover-current --provider auto --metadata-only` reports `provider: claude`.

## Discover the current session

Preferred path:

```bash
python3 scripts/extract.py --discover-current --provider claude --metadata-only
```

If discovery fails, use the manual fallback:

1. Inspect the recent session index files:

```bash
ls -t ~/.claude/sessions/*.json | head -5
```

2. Read the most recent file whose `cwd` matches the current project. Its `sessionId` maps to:

```text
~/.claude/projects/<encoded-cwd>/<sessionId>.jsonl
```

Where `<encoded-cwd>` is the working directory with `/` replaced by `-`.

3. If no session index file matches, fall back to the newest transcripts in the project directory:

```bash
ls -t ~/.claude/projects/<encoded-cwd>/*.jsonl | head -3
```

4. Verify the candidate transcript:

```bash
python3 scripts/extract.py <candidate.jsonl> --provider claude --metadata-only
```

Confirm that `cwd` and `first_prompt` match the current session.

## Run extraction

```bash
python3 scripts/extract.py --discover-current --provider claude --summary
```

If you need raw call details:

```bash
python3 scripts/extract.py <path-to-session.jsonl> --provider claude
```

## Claude-specific notes

- Claude transcripts expose cache-aware token fields directly.
- Estimated USD cost uses Claude Opus pricing.
- Subagent cost attribution is available when the sibling subagents directory exists or when you pass `--subagents-dir`.

## Retro file location

Write retros to:

```text
~/.claude/worklog/retros/YYYY-MM-DD-<slug>.md
```
