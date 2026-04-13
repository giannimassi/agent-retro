# Shared Retro Workflow

Use this workflow after you have identified the runtime, verified the transcript, and run extraction.

## Run extraction

Use the bundled script with the confirmed provider:

```bash
python3 scripts/extract.py --discover-current --provider <claude|codex> --summary
```

If you already know the transcript path:

```bash
python3 scripts/extract.py <path-to-session.jsonl> --provider <claude|codex> --summary
```

Use `--summary` first so the tool output stays compact. Re-run without `--summary` only if you need to inspect individual call details.

The extraction output includes:
- `provider`: runtime that produced the transcript
- `session`: id, cwd, branch when available, duration, version
- `tokens`: token totals and estimated USD cost when available
- `tools`: tool call counts, and optionally individual call listings
- `agents`: agent dispatches with type, model, and prompt preview when available
- `skills`: explicit skill invocations when the runtime exposes them
- `git`: branches, commits, and PR operations
- `files`: files read, written, or edited
- `conversation_arc`: chronological user and assistant messages
- `tool_result_sizes`: total, average, and max tool-result sizes in bytes

Tool result content is intentionally excluded from the extraction. Only result sizes are tracked.

## Step 2: Read the conversation arc

The `conversation_arc` is the story of the session. Read it to understand:

1. What the user actually asked for
2. How the approach evolved
3. Where friction occurred

Do not skip this. Everything else depends on it.

## Step 3: Classify outcomes

List all outcomes that apply.

| Outcome | Detection signal |
|---|---|
| New code | Source-file writes or edits, git commits |
| Bug fix | Debugging patterns, fix commits |
| Communication | PR comments, chat/email tools |
| Local files | Writes to docs, plans, notes |
| Setup changes | Config or environment edits |
| Spec / Design | Design discussion without implementation |
| Process improvement | Rule, workflow, or skill updates |
| Review | Review tools, PR review operations |
| Research | Heavy reading/searching with little writing |
| Skill development | Writes to skill directories or skill docs |

## Step 4: Analyze what worked

Look for concrete patterns:

- First-try success: a tool call or agent dispatch that worked without retries
- Efficient delegation: an agent whose output justified its cost or latency
- Good skill match: the right skill or workflow invoked at the right time
- Clean conversation flow: stretches without user correction or redirection
- Smart tool choice: a lightweight tool used where a heavyweight step was unnecessary, or vice versa

## Step 5: Analyze what did not work

This is the most valuable part. Trace each problem to a root cause.

### How to identify friction

Look for these patterns in user messages:
- Corrections: "no", "wrong", "that's not what I meant"
- Redirects: "instead do X", "try a different approach"
- Repetitions: "I already said", "like I mentioned"
- Stops: "wait", "hold on", "stop", "undo"
- Frustration: terse replies after a previously engaged flow

For each friction point, trace the chain:

```text
User correction -> What the agent did wrong -> Why ->
Wrong assumption? Missing context? Bad skill guidance? Wrong tool?
```

### Failure patterns to check

**Wasted agent dispatches**: agent output was discarded, vague, or cost far more than it helped.

**Oversized tool results**: a tool returned large content that was not meaningfully used. This is especially important for file reads and command output.

**Tool call retries**: the same tool called multiple times with guesswork inputs instead of reading enough context first.

**Abandoned approaches**: a stretch of work followed by a pivot to a completely different approach.

**Over-engineering**: more tools or agents than the task warranted.

**Under-specification**: the agent asked the user for information that could have been discovered in files, context, or local state.

### For skill-development retros

If the session involved a skill under development:

1. Read the active skill's `SKILL.md`
2. Map each friction point to a specific instruction or missing instruction
3. Categorize the issue:
   - Triggering
   - Missing guidance
   - Wrong guidance
   - Over-specification
   - Under-specification
   - Missing tool or script
4. Draft the exact text change that would fix it

## Step 6: Propose actions

For each issue, propose one concrete action.

| Type | Meaning | Must include |
|---|---|---|
| `skill-update` | Edit an existing skill | Exact text change and why |
| `skill-create` | New skill needed | What it does and when it triggers |
| `rule-update` | Edit a rule or local instructions file | Rule text and file |
| `rule-create` | New rule file | Rule content |
| `setup-change` | Config, hooks, scripts, tools | Exact change and where |
| `memory-update` | Save a durable lesson | Fact to remember |
| `investigate` | More research needed | Precise unresolved question |
| `acknowledge` | One-off, no systemic fix | Why it should not become process |

Priority order: systemic fixes first, then setup changes, then one-offs.

For `skill-update`, include:
- which section to edit
- before text or insertion point
- after text
- which friction point it addresses

## Step 7: Write the retro file

Save the file to the runtime-specific path from the provider reference.

```markdown
# Retro: <Session Description>

**Date**: YYYY-MM-DD
**Duration**: Xh Ym
**Provider**: <claude|codex>
**Session ID**: <uuid>
**Branch**: <git branch or "unavailable">
**Transcript**: `<path to .jsonl>`
**Estimated cost**: $X.XX total, or `unavailable` if no runtime pricing is available

## What Happened
<!-- 3-5 sentence narrative of the session -->

## Outcomes
- <type>: <description>

## Token Budget
| Component | Output tokens | Cache read | Cache write | Est. cost |
|---|---|---|---|---|
| Main context | X | X | X | $X.XX or unavailable |
| Agent: <desc> (<model>) | X | X | X | $X.XX or unavailable |
| **Total** | | | | **$X.XX or unavailable** |

## Tool Result Waste
<!-- Highlight tools whose large results were not worth their cost -->

## What Worked
- **<specific thing>**: <why it worked>

## What Didn't Work
- **<specific friction>**: <root cause chain>

## Actions
| # | Type | Action | Where | Status |
|---|------|--------|-------|--------|
| 1 | skill-update | <specific change> | <file:section> | proposed |
```

## Step 8: Walk through actions

Present the retro summary in conversation, then walk through proposed actions one by one.

For actions the user approves:
- `skill-update`, `rule-update`, `rule-create`: make the edit and show the diff
- `memory-update`: save it through the available memory system
- `setup-change`: apply the exact config change

Update the retro file table as you go from `proposed` to `done`, `deferred`, or `rejected`.
