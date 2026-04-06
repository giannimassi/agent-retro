# Design Decisions

## Why post-session, not inline?

Most agent reflection happens inline — a critic agent reviews output before it's returned, or a retry loop generates reflections on failed attempts (see [Reflexion](https://arxiv.org/abs/2303.11366)). These patterns improve single-task success rates.

`/retro` does something different: it looks at an **entire session** after the fact. The goal isn't "make this one task succeed" — it's "find systemic patterns across the session that indicate my setup (skills, rules, CLAUDE.md, workflows) needs to change."

Inline reflection can't do this because:
- It only sees one task at a time
- It has no concept of "this same mistake happened 3 times today"
- It can't propose changes to configuration files or skills
- It doesn't track cost efficiency across the session

## Why preserve the full conversation arc?

The extraction script keeps every user message and assistant text response. No sampling, no skipping, no summarization.

We considered arc sampling (keep first 5, last 10, every Nth in between) but rejected it because:
- **Friction detection requires continuity.** A user correction only makes sense in the context of what Claude just said. Skip the wrong turn and you miss the cause.
- **Retros are high-value, low-frequency.** You run `/retro` maybe once per session, not every turn. Spending 20KB of context on the arc is a reasonable trade-off for a $5-50 session.
- **The rest of the extraction is lean.** Tool result content (the actual 45KB file reads, command outputs) is excluded entirely. The arc is the biggest piece of the extraction at ~68% of output, but the total output is still only ~3-4% of the raw JSONL file.

## Why track tool result sizes without content?

Tool results dominate session transcripts. A single `Read` call can return 30KB of file content. Including this content in the extraction would make the retro itself a token-budget disaster.

But **knowing the size** is valuable:
- "Read returned 45KB that was never referenced" = actionable waste finding
- "Bash average output was 1KB" = healthy, no action needed
- "MCP tool returned 23KB for a search" = maybe the search was too broad

The extraction script captures `tool_result_sizes` as a per-tool aggregate (count, total bytes, average, max). This is enough to identify waste patterns without the content.

## Inspiration: Claude Code's session storage

The `--metadata-only` mode borrows a technique from Claude Code's own codebase. Internally, Claude Code uses a `readSessionLite` function that reads only the first and last 64KB of a JSONL file (`LITE_READ_BUF_SIZE = 65536`) to extract session metadata without parsing every line.

We use the same pattern for session verification — confirming you're analyzing the right transcript costs one 64KB read instead of parsing a multi-megabyte file.

The streaming extraction (`stream_jsonl`) processes records one at a time, matching Claude Code's internal `listSessionsTouchedSince` which only does `stat()` calls for session discovery.

## Inspiration: Reflexion (Shinn et al., 2023)

The Reflexion paper introduced "verbal reinforcement learning" — agents store natural-language self-reflections in an episodic memory buffer and use them to improve on retry. The key insight: reflections as text, not weights.

`/retro` extends this from "reflect on one failed task" to "reflect on an entire session." The reflections aren't used for retry — they're used to improve the system configuration (skills, rules, CLAUDE.md) so that future sessions start from a better baseline.

## Comparison with existing tools

| Tool | What it does | What /retro adds |
|---|---|---|
| **Reflexion** | Inline retry reflection (one task) | Post-session systemic reflection (entire conversation) |
| **LangGraph reflection** | Generator-critic loop during execution | Root cause analysis across the full session |
| **CrewAI training** | Human-in-the-loop live feedback | Automated friction detection from transcript |
| **everything-claude-code** continuous-learning | Passive hook-based pattern extraction | Deliberate analysis with causal chains |
| **Vibe-Log** | Standup summaries of accomplishments | "What went wrong and why" with proposed fixes |
| **claude-devtools** | Execution tree viewer | Actionable proposals, not just observability |

These tools are complementary, not competing. Continuous-learning is the always-on immune system; `/retro` is the periodic health checkup.
