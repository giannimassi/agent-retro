---
name: agent-retro
description: Run a conversation retrospective — analyze what happened in this session, what worked, what didn't, and propose concrete improvements. Use when the user says "retro", "retrospective", "what happened in this session", "session review", "what did we do", "analyze this conversation", or when wrapping up a long session and wanting to capture lessons. Especially useful after using a skill you're developing — identifies what can be improved about the skill, rules, setup, or process.
compatibility: Requires Claude Code. Reads session transcripts from ~/.claude/projects/ (JSONL format). Python 3.8+ for the extraction script (stdlib only). Other agents are on the roadmap.
metadata:
  author: giannimassi
  version: "0.1.0"
---

# /retro — Conversation Retrospective

Analyze the current session end-to-end: what happened, what it produced, what worked, what didn't, and what to improve. The output is a structured retro file plus a set of proposed actions you walk through with the user.

## Step 1: Extract Session Data

The full conversation lives in a JSONL file on disk — including tool calls, agent dispatches, and messages that may have been compacted from current context. Always use this source, not just what's in context.

### Find the current session

The session file links a running process to its transcript. But session files are keyed by PID and may be cleaned up when processes end, so use a two-step approach with verification.

**Step A: Try the sessions directory first**
```bash
ls -t ~/.claude/sessions/*.json | head -5
```

Read the most recent file(s). Match by `cwd` (should equal current working directory). The `sessionId` maps to:

```
~/.claude/projects/<encoded-cwd>/<sessionId>.jsonl
```

Where `<encoded-cwd>` replaces `/` with `-` (e.g., `/Users/foo/dev/myproject` → `-Users-foo-dev-myproject`).

**Step B: If no session file matches** (PID rotated, file cleaned up), fall back to the most recently modified `.jsonl` in the project directory:
```bash
ls -t ~/.claude/projects/<encoded-cwd>/*.jsonl | head -3
```

**Step C: Verify you have the right file.** Use `--metadata-only` for cheap verification — it reads only the first/last 64KB of the file (no full parse):
```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/extract.py <candidate.jsonl> --metadata-only
```

This returns session_id, cwd, git_branch, first_prompt, timestamps, and file size. Check `first_prompt` matches what was said at the start of the conversation.

If it doesn't match, try the next most recent file. If none match, state this in the retro output — analyzing the wrong session is worse than no analysis.

### Run extraction

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/extract.py <path-to-session.jsonl> --summary
```

Use `--summary` to get compact output (tool counts only, no individual call listings). If you need to drill into specific tool calls later, re-run without `--summary`.

The script outputs JSON with:
- **session**: id, cwd, branch, duration, branches seen
- **tokens**: input/output/cache totals + estimated USD cost
- **tools**: call counts by tool name
- **agents**: each dispatch with type, model, description, prompt preview, subagent tokens
- **skills**: each skill invocation with name and args
- **git**: branches, commits, PR operations
- **files**: files read/written/edited
- **conversation_arc**: complete timeline of user messages and assistant text responses (tells the full story of the session — all messages preserved, no sampling)
- **tool_result_sizes**: per-tool breakdown of total/avg/max result sizes in bytes — use this to identify token waste (e.g., a 45KB Read result that was never referenced again)

Note: tool result **content** is not included in the extraction (it would dominate the output). Only the size is tracked. If you need to see what a specific tool returned, grep the JSONL directly for the tool_use_id.

### Understanding the cost data

The JSONL records cache-aware token usage:
- `input_tokens`: non-cached input (typically very low due to prompt caching)
- `cache_creation_input_tokens`: new cache writes (charged at 1.25x input rate)
- `cache_read_input_tokens`: cache hits (charged at 0.1x input rate — this is usually the biggest number)
- `output_tokens`: generated tokens (most expensive per-token)

The script computes estimated USD cost using Opus pricing. For sessions with subagents, the subagent cost is separate and additive.

### If extraction fails

Fall back to analyzing current conversation context. Note this limitation — compacted content is lost.

## Step 2: Read the Conversation Arc

The `conversation_arc` field is the story of the session — user requests and assistant responses in chronological order. Read it to understand:

1. **What the user actually asked for** (their words, not your interpretation)
2. **How the approach evolved** — did the plan change? Were there pivots?
3. **Where friction occurred** — look for user corrections, redirects, or repeated instructions

This is the foundation for everything that follows. Don't skip it.

## Step 3: Classify Outcomes

What did this session actually produce? List all that apply.

| Outcome | Detection signal |
|---|---|
| New code | Write/Edit to source files, git commits |
| Bug fix | Commits with "fix" prefix, debugging patterns |
| Communication | Slack/email MCP calls, PR comments |
| Local files | Writes to non-code files (plans, notes, docs) |
| Setup changes | Edits to config, CLAUDE.md, settings, skills |
| Spec / Design | Plan files, design discussion, no implementation |
| Process improvement | Rule updates, workflow changes, skill creation |
| Review | PR review calls, code-review agents |
| Research | Heavy Read/Grep with minimal Write/Edit |
| Skill development | Writes to `skills/` directories |

## Step 4: Analyze What Worked

Look for these concrete patterns — don't just say "things went well":

- **First-try success**: a tool call or agent dispatch that produced the right result without retries. Name the specific call.
- **Efficient delegation**: a subagent that cost < $0.50 and produced a useful result. Compare to what it would have cost to do inline.
- **Good skill match**: a skill triggered at the right time. What was the trigger phrase? Did the skill's output align with what the user wanted?
- **Clean conversation flow**: stretches where the user didn't need to correct or redirect. What made those stretches smooth?
- **Smart tool choice**: using Grep instead of spawning an Explore agent, or vice versa — whichever was more efficient for the situation.

## Step 5: Analyze What Didn't Work

This is the most valuable part. Go beyond listing problems — trace each one to its root cause.

### How to identify friction

Read the conversation arc. Look for these patterns in user messages:
- **Corrections**: "no", "not that", "wrong", "that's not what I meant"
- **Redirects**: "instead do X", "let's try a different approach"
- **Repetitions**: "I already said", "like I mentioned", "I asked for"
- **Stops**: "wait", "hold on", "stop", "undo", "revert"
- **Frustration**: short terse responses after previously being engaged

For each friction point, trace the causal chain:

```
User correction -> What did Claude do wrong -> Why did Claude do that ->
Was it a wrong assumption? Missing context? Bad skill guidance? Wrong tool?
```

### Specific failure patterns to check

**Wasted agent dispatches**: Compare each agent's token cost to the usefulness of its output. If an agent cost > $1 and its result was discarded or only partially used, that's a failure. Root cause: was the prompt too vague? Wrong agent type? Missing context in the dispatch?

**Oversized tool results**: Check `tool_result_sizes` — if a tool (especially Read) returned huge results (>10KB avg) that weren't meaningfully used, that's token waste. Could Claude have used offset/limit to read just the relevant section? Could an Explore agent have answered the question without loading the full file into context?

**Tool call retries**: Same tool called 3+ times in a row with different inputs. Root cause: was the first attempt a guess? Should Claude have read more context first?

**Abandoned approaches**: Stretches of work (5+ tool calls) followed by a pivot to a completely different approach. Root cause: did Claude commit too early before understanding the problem? Should it have asked?

**Over-engineering**: More tool calls or agent dispatches than the task warranted. Root cause: did a skill push Claude toward a heavyweight process when something simpler would have worked?

**Under-specification**: Claude asked clarifying questions the user shouldn't have needed to answer (information was available in files, context, or memory). Root cause: missing research step? Skill didn't tell Claude where to look?

### For skill-development retros

When the session involved using a skill under development, go deeper:

1. **Read the skill's SKILL.md** that was active during the session
2. For each friction point, identify which skill instruction (or missing instruction) caused it
3. Categorize skill issues:
   - **Triggering**: skill should have triggered but didn't, or triggered when it shouldn't have
   - **Missing guidance**: skill didn't cover an edge case the session encountered
   - **Wrong guidance**: skill told Claude to do X but Y would have been better
   - **Over-specification**: skill was too rigid, forced a workflow that didn't fit the situation
   - **Under-specification**: skill left too much to Claude's judgment in an area where it consistently makes bad choices
   - **Missing tool/script**: skill described a manual process that should have been automated
4. For each issue, draft the specific SKILL.md edit that would fix it (not vague "improve X" — write the actual text change)

## Step 6: Propose Actions

For every issue from Step 5, propose a concrete action:

| Type | What it means | Must include |
|---|---|---|
| `skill-update` | Edit an existing skill | The specific text to change and why |
| `skill-create` | New skill needed | What it would do and when it triggers |
| `rule-update` | Edit CLAUDE.md or rules/ | The rule text and which file |
| `rule-create` | New rule file | The rule content |
| `setup-change` | Config, hooks, tools | What to change and where |
| `memory-update` | Save to auto-memory | The fact to remember |
| `investigate` | Needs more research | What question to answer |
| `acknowledge` | No systemic fix | Why this was one-off |

**Priority order**: systemic fixes (skill/rule) > setup changes > one-offs.

For skill-update actions specifically, include:
- Which section of SKILL.md to edit
- The before text (or "new section after X")
- The after text
- Which test case / friction point this addresses

## Step 7: Write the Retro File

Save to `~/.claude/worklog/retros/YYYY-MM-DD-<slug>.md` (create the directory if it doesn't exist).

```markdown
# Retro: <Session Description>

**Date**: YYYY-MM-DD
**Duration**: Xh Ym
**Session ID**: <uuid>
**Branch**: <git branch>
**Transcript**: `<path to .jsonl>`
**Estimated cost**: $X.XX (main) + $Y.YY (subagents) = $Z.ZZ total

## What Happened
<!-- 3-5 sentence narrative of the session -->

## Outcomes
- <type>: <description>

## Token Budget
| Component | Output tokens | Cache read | Cache write | Est. cost |
|---|---|---|---|---|
| Main context | X | X | X | $X.XX |
| Agent: <desc> (<model>) | X | X | X | $X.XX |
| **Total** | | | | **$X.XX** |

## Tool Result Waste
<!-- Highlight any tools with disproportionately large results relative to their usefulness -->

## What Worked
- **<specific thing>**: <why it worked, what made it efficient>

## What Didn't Work
- **<specific friction>**: <root cause chain: what happened -> why -> systemic cause>

## Actions
| # | Type | Action | Where | Status |
|---|------|--------|-------|--------|
| 1 | skill-update | <specific change> | <file:section> | proposed |
| 2 | rule-update | <specific rule> | <file> | proposed |
```

## Step 8: Walk Through Actions

Present the retro summary in conversation, then walk through proposed actions one by one with the user.

For actions the user approves:
- **skill-update / rule-update / rule-create**: make the edit, show the diff
- **memory-update**: save via the memory system
- **setup-change**: apply the config change

Update the retro file's action table as you go (proposed -> done / deferred / rejected).

## Step 9: Preemptive Handoff Recommendation

If session stats exceed ANY of these thresholds:
- **500+ turns** (`tokens.turn_count` from extraction)
- **4h+ wall-clock** (`session.duration_seconds` > 14400)
- **$300+ estimated cost** (`tokens.estimated_cost_usd`)

...the retro MUST include a specific action flagged as high-priority:

> "Consider fresh-session handoff next time. Long sessions accumulate context overhead — 247M cache reads and 7.7M cache writes for every new turn compound quickly. A fresh session with a targeted resume-prompt is cheaper and keeps reasoning cleaner."

Include **two concrete prompts** in the retro file itself:

### Prompt A: `/compact` preserve (if user keeps going in same session)
```
Preserve for the continued session:
- Active project + state summary
- Non-negotiable invariants (things NOT to rederive)
- Immediate next steps
- User preferences/posture (auto mode on/off, skill patterns, etc.)
```

### Prompt B: `/clear` resume (fresh session)
```
Resume <project>. Load in order before doing anything:
1. <primary design doc path>
2. <key knowledge files>
3. <state commands to run>
Do NOT rederive: <list of settled decisions>.
Pick up at: <next specific step>.
Posture: <auto mode? terse? ask-before-act?>
```

Fill both prompts with session-specific content drawn from the evolution doc, specs, and user voice excerpts. Offer the user both options at the end of the walk-through — copy-paste ready.

**Why both**: sometimes the user wants to keep momentum (compact); sometimes a hard reset is cleaner (clear). Don't pick for them.
