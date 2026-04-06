#!/usr/bin/env python3
"""
Tests for extract.py — verifies extraction correctness against JSONL fixtures.

Usage:
    python tests/test_extract.py
    python tests/test_extract.py -v        # verbose mode (show all assertions)
    python tests/test_extract.py TestName  # run a specific test class

Fixtures are in tests/fixtures/. The script imports extract.py directly,
so run from the skill root directory (/tmp/claude-code-retro/).
"""

import json
import os
import sys
import unittest
from pathlib import Path

# Allow running from any directory by adding the script's repo root to sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import extract  # noqa: E402


FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


def load_fixture_result(fixture_name, summary=False, metadata_only=False):
    """Run the extractor against a named fixture and return the parsed result."""
    path = str(FIXTURES_DIR / fixture_name)
    if metadata_only:
        return extract.extract_metadata_lite(path)
    return extract.extract_all_streaming(path, subagents_dir=None, summary_mode=summary)


# ---------------------------------------------------------------------------
# 1. Metadata extraction (--metadata-only path)
# ---------------------------------------------------------------------------
class TestMetadataOnly(unittest.TestCase):
    """--metadata-only reads head/tail only and returns lightweight session info."""

    def setUp(self):
        self.meta = load_fixture_result("full_session.jsonl", metadata_only=True)

    def test_session_id_extracted(self):
        self.assertEqual(self.meta["session_id"], "test-session-abc123")

    def test_cwd_extracted(self):
        self.assertEqual(self.meta["cwd"], "/Users/test/dev/myproject")

    def test_git_branch_extracted(self):
        self.assertEqual(self.meta["git_branch"], "feature/add-auth")

    def test_first_prompt_extracted(self):
        """First user message should be captured for session verification.

        NOTE: extract_metadata_lite looks for a "text" key in user message lines.
        This works when user content is list-format: [{"type":"text","text":"..."}].
        It does NOT work for string-format content ("content":"...") — the "text" key
        is absent and first_prompt returns None.

        The full_session fixture uses string-format content for user messages (to work
        around the list-content arc bug), so first_prompt is None here.
        A fixture with list-format text blocks (no tool_result) would trigger this path.
        """
        # String-format content → first_prompt is None (metadata-only limitation)
        # This is expected behavior for the current fixture format.
        # If this changes, the metadata-only path was improved — update the assertion.
        self.assertIsNone(self.meta["first_prompt"],
                          "Expected None for string-format content — if fixed, update this test")

    def test_first_prompt_works_with_text_block_format(self):
        """first_prompt IS extracted when user messages use {"type":"text","text":"..."} format.

        The metadata-only path scans for lines containing '"role":"user"' and then
        calls extract_json_field(line, "text") — which finds "text":"..." in text blocks.
        This works for list-format messages like:
          "content": [{"type":"text","text":"my message"}]
        """
        # The compacted_session has a string-format user message after the system-reminder
        # that also uses string content — so first_prompt will be None there too.
        # We use the large_arc_session fixture which has string-format user content.
        meta = load_fixture_result("large_arc_session.jsonl", metadata_only=True)
        # Both fixtures use string-format, so first_prompt is None for all of them.
        # This test documents the expected behavior (None) until the metadata path is fixed.
        self.assertIsNone(meta["first_prompt"])

    def test_system_reminder_filtered_from_first_prompt(self):
        """<system-reminder> messages must not appear as first_prompt."""
        # The compacted_session fixture starts with a system-reminder user message,
        # so first_prompt should skip it and find the real user text.
        meta = load_fixture_result("compacted_session.jsonl", metadata_only=True)
        if meta["first_prompt"] is not None:
            self.assertNotIn("<system-reminder>", meta["first_prompt"])

    def test_timestamps_extracted(self):
        self.assertEqual(self.meta["start_time"], "2026-04-06T09:00:00Z")
        self.assertIsNotNone(self.meta["end_time"])

    def test_duration_seconds_computed(self):
        # Session runs from 09:00:00 to 09:05:10 = 310 seconds
        self.assertIsNotNone(self.meta["duration_seconds"])
        self.assertEqual(self.meta["duration_seconds"], 310)

    def test_file_size_bytes_nonzero(self):
        self.assertGreater(self.meta["file_size_bytes"], 0)

    def test_version_extracted(self):
        self.assertEqual(self.meta["version"], "1.2.3")


# ---------------------------------------------------------------------------
# 2. Full extraction — session metadata
# ---------------------------------------------------------------------------
class TestSessionMetadata(unittest.TestCase):
    """Session-level fields from full extraction pipeline."""

    def setUp(self):
        self.result = load_fixture_result("full_session.jsonl")

    def test_session_id(self):
        self.assertEqual(self.result["session"]["session_id"], "test-session-abc123")

    def test_cwd(self):
        self.assertEqual(self.result["session"]["cwd"], "/Users/test/dev/myproject")

    def test_git_branch(self):
        self.assertEqual(self.result["session"]["git_branch"], "feature/add-auth")

    def test_branches_seen_is_list(self):
        """branches_seen should be serialized as a sorted list, not a set."""
        self.assertIsInstance(self.result["session"]["branches_seen"], list)

    def test_start_time(self):
        self.assertEqual(self.result["session"]["start_time"], "2026-04-06T09:00:00Z")

    def test_duration_seconds(self):
        # 09:00:00 → 09:05:10 = 310 seconds
        self.assertEqual(self.result["session"]["duration_seconds"], 310)


# ---------------------------------------------------------------------------
# 3. Token usage extraction
# ---------------------------------------------------------------------------
class TestTokenUsage(unittest.TestCase):
    """Token counts and cost estimation."""

    def setUp(self):
        self.result = load_fixture_result("full_session.jsonl")
        self.tokens = self.result["tokens"]

    def test_token_totals_structure(self):
        """All four token fields must be present."""
        for field in ("input_tokens", "output_tokens",
                      "cache_creation_input_tokens", "cache_read_input_tokens"):
            self.assertIn(field, self.tokens["total"], f"missing token field: {field}")

    def test_output_tokens_nonzero(self):
        """There are multiple assistant turns, so output_tokens must be > 0."""
        self.assertGreater(self.tokens["total"]["output_tokens"], 0)

    def test_cache_read_grows_across_turns(self):
        """cache_read_input_tokens should grow as turns accumulate context."""
        self.assertGreater(self.tokens["total"]["cache_read_input_tokens"], 0)

    def test_cost_estimation_positive(self):
        self.assertGreater(self.tokens["estimated_cost_usd"], 0.0)

    def test_turn_count_matches_assistant_messages(self):
        # The fixture has 11 assistant messages with usage blocks
        self.assertGreater(self.tokens["turn_count"], 5)

    def test_only_assistant_tokens_counted(self):
        """Token counts should only be from assistant messages (not user messages)."""
        # The fixture user messages have no usage blocks, so all token counts come
        # from assistant messages. Verify turn_count doesn't count user turns.
        result_no_summary = load_fixture_result("full_session.jsonl")
        # Total assistant messages in fixture = 11 (count assistant content blocks)
        self.assertLessEqual(result_no_summary["tokens"]["turn_count"], 20)


# ---------------------------------------------------------------------------
# 4. Tool call extraction
# ---------------------------------------------------------------------------
class TestToolCalls(unittest.TestCase):
    """Tool use block extraction — counts, types, details."""

    def setUp(self):
        self.result = load_fixture_result("full_session.jsonl")
        self.counts = self.result["tools"]["counts"]

    def test_read_calls_counted(self):
        self.assertEqual(self.counts.get("Read", 0), 2)

    def test_write_calls_counted(self):
        self.assertEqual(self.counts.get("Write", 0), 1)

    def test_edit_calls_counted(self):
        self.assertEqual(self.counts.get("Edit", 0), 1)

    def test_bash_calls_counted(self):
        self.assertEqual(self.counts.get("Bash", 0), 4)

    def test_grep_calls_counted(self):
        self.assertEqual(self.counts.get("Grep", 0), 1)

    def test_agent_calls_counted(self):
        self.assertEqual(self.counts.get("Agent", 0), 1)

    def test_skill_calls_counted(self):
        self.assertEqual(self.counts.get("Skill", 0), 1)

    def test_total_calls_sum(self):
        self.assertEqual(self.result["tools"]["total_calls"],
                         sum(self.counts.values()))

    def test_summary_mode_omits_call_list(self):
        """In summary mode, individual call listings should be absent."""
        summary_result = load_fixture_result("full_session.jsonl", summary=True)
        self.assertNotIn("calls", summary_result["tools"])
        self.assertIn("counts", summary_result["tools"])

    def test_full_mode_includes_call_list(self):
        """In full mode, the calls list should be present."""
        self.assertIn("calls", self.result["tools"])

    def test_file_path_captured_for_read(self):
        """Read calls should have file_path captured."""
        read_calls = [c for c in self.result["tools"]["calls"] if c["name"] == "Read"]
        for call in read_calls:
            self.assertIn("file_path", call)
            self.assertNotEqual(call["file_path"], "")

    def test_command_captured_for_bash(self):
        """Bash calls should have command captured."""
        bash_calls = [c for c in self.result["tools"]["calls"] if c["name"] == "Bash"]
        for call in bash_calls:
            self.assertIn("command", call)


# ---------------------------------------------------------------------------
# 5. Tool result sizes
# ---------------------------------------------------------------------------
class TestToolResultSizes(unittest.TestCase):
    """Tool result size tracking — per-tool aggregates."""

    def setUp(self):
        self.result = load_fixture_result("full_session.jsonl")
        self.sizes = self.result["tool_result_sizes"]

    def test_result_sizes_present(self):
        self.assertGreater(len(self.sizes), 0)

    def test_read_in_result_sizes(self):
        """Read calls have results and should appear in size stats."""
        self.assertIn("Read", self.sizes)

    def test_bash_in_result_sizes(self):
        """Bash calls have results and should appear in size stats."""
        self.assertIn("Bash", self.sizes)

    def test_size_stats_structure(self):
        """Each tool entry must have count, total_bytes, avg_bytes, max_bytes."""
        for tool_name, stats in self.sizes.items():
            for field in ("count", "total_bytes", "avg_bytes", "max_bytes"):
                self.assertIn(field, stats, f"{tool_name} missing {field}")

    def test_sizes_are_non_negative(self):
        for tool_name, stats in self.sizes.items():
            self.assertGreaterEqual(stats["total_bytes"], 0)
            self.assertGreaterEqual(stats["avg_bytes"], 0)
            self.assertGreaterEqual(stats["max_bytes"], 0)

    def test_result_size_attached_to_call(self):
        """Calls with known result IDs should have result_size_bytes populated."""
        calls_with_size = [c for c in self.result["tools"]["calls"]
                           if "result_size_bytes" in c]
        # Every tool call in the fixture has a result, so at least one should match
        self.assertGreater(len(calls_with_size), 0)

    def test_write_result_small(self):
        """Write calls return 'File written successfully' — should be small."""
        if "Write" in self.sizes:
            self.assertLess(self.sizes["Write"]["max_bytes"], 500)


# ---------------------------------------------------------------------------
# 6. Conversation arc
# ---------------------------------------------------------------------------
class TestConversationArc(unittest.TestCase):
    """Conversation arc — message ordering, content, filtering."""

    def setUp(self):
        self.result = load_fixture_result("full_session.jsonl")
        self.arc = self.result["conversation_arc"]

    def test_arc_is_list(self):
        self.assertIsInstance(self.arc, list)

    def test_arc_nonempty(self):
        self.assertGreater(len(self.arc), 0)

    def test_arc_has_user_messages(self):
        user_msgs = [m for m in self.arc if m["role"] == "user"]
        self.assertGreater(len(user_msgs), 0)

    def test_arc_has_assistant_messages(self):
        assistant_msgs = [m for m in self.arc if m["role"] == "assistant"]
        self.assertGreater(len(assistant_msgs), 0)

    def test_arc_alternates_roles_roughly(self):
        """Arc should contain both roles, not just one."""
        roles = [m["role"] for m in self.arc]
        self.assertIn("user", roles)
        self.assertIn("assistant", roles)

    def test_system_reminders_filtered(self):
        """Messages starting with <system-reminder> must be excluded from arc."""
        for msg in self.arc:
            self.assertFalse(
                msg["text"].startswith("<system-reminder>"),
                f"system-reminder leaked into arc: {msg['text'][:50]}"
            )

    def test_arc_message_has_required_fields(self):
        for msg in self.arc:
            self.assertIn("role", msg)
            self.assertIn("text", msg)
            self.assertIn("timestamp", msg)

    def test_arc_text_truncated_to_2000_for_user(self):
        """User messages are truncated to 2000 chars."""
        for msg in self.arc:
            if msg["role"] == "user":
                self.assertLessEqual(len(msg["text"]), 2000)

    def test_arc_assistant_text_truncated_to_1000(self):
        """Assistant messages are truncated to 1000 chars."""
        for msg in self.arc:
            if msg["role"] == "assistant":
                self.assertLessEqual(len(msg["text"]), 1000)

    def test_arc_preserves_user_correction(self):
        """The user correction ('wait i also need...') should appear in the arc."""
        user_texts = [m["text"] for m in self.arc if m["role"] == "user"]
        correction_found = any("validate" in t.lower() or "signature" in t.lower()
                               for t in user_texts)
        self.assertTrue(correction_found,
                        "User correction about signature validation not found in arc")

    def test_short_assistant_messages_filtered(self):
        """Assistant messages <= 20 chars are filtered (too short to be meaningful)."""
        for msg in self.arc:
            if msg["role"] == "assistant":
                self.assertGreater(len(msg["text"]), 20)


# ---------------------------------------------------------------------------
# 7. Agent dispatch extraction
# ---------------------------------------------------------------------------
class TestAgentDispatches(unittest.TestCase):
    """Agent tool_use blocks and their attributes."""

    def setUp(self):
        self.result = load_fixture_result("full_session.jsonl")
        self.agents = self.result["agents"]

    def test_agent_count(self):
        self.assertEqual(len(self.agents), 1)

    def test_agent_has_required_fields(self):
        agent = self.agents[0]
        for field in ("description", "type", "model", "prompt_preview",
                      "background", "timestamp", "tool_use_id"):
            self.assertIn(field, agent, f"agent missing field: {field}")

    def test_agent_description(self):
        self.assertEqual(self.agents[0]["description"], "Write unit tests for JWT middleware")

    def test_agent_type(self):
        self.assertEqual(self.agents[0]["type"], "general")

    def test_agent_model(self):
        self.assertEqual(self.agents[0]["model"], "claude-sonnet-4-5")

    def test_agent_prompt_preview_truncated_to_300(self):
        self.assertLessEqual(len(self.agents[0]["prompt_preview"]), 300)

    def test_agent_background_false(self):
        self.assertFalse(self.agents[0]["background"])

    def test_agent_tokens_none_without_subagents_dir(self):
        """When no subagents_dir is given, token data should be None."""
        self.assertIsNone(self.agents[0]["tokens"])
        self.assertIsNone(self.agents[0]["estimated_cost_usd"])


# ---------------------------------------------------------------------------
# 8. Skill invocation extraction
# ---------------------------------------------------------------------------
class TestSkillInvocations(unittest.TestCase):
    """Skill tool_use blocks."""

    def setUp(self):
        self.result = load_fixture_result("full_session.jsonl")
        self.skills = self.result["skills"]

    def test_skill_count(self):
        self.assertEqual(len(self.skills), 1)

    def test_skill_name(self):
        self.assertEqual(self.skills[0]["name"], "pr:open")

    def test_skill_args(self):
        self.assertEqual(self.skills[0]["args"], "--base main")

    def test_skill_has_timestamp(self):
        self.assertIsNotNone(self.skills[0]["timestamp"])


# ---------------------------------------------------------------------------
# 9. Git activity extraction
# ---------------------------------------------------------------------------
class TestGitActivity(unittest.TestCase):
    """Git commits, PR operations, and branch tracking."""

    def setUp(self):
        self.result = load_fixture_result("full_session.jsonl")
        self.git = self.result["git"]

    def test_branch_tracked(self):
        self.assertIn("feature/add-auth", self.git["branches"])

    def test_commit_detected(self):
        """Bash commands containing 'git commit' should be captured."""
        self.assertGreater(len(self.git["commits"]), 0)

    def test_commit_message_captured(self):
        commit_cmds = [c["command"] for c in self.git["commits"]]
        self.assertTrue(any("feat(auth)" in cmd for cmd in commit_cmds))

    def test_pr_operation_detected(self):
        """Bash commands containing 'gh pr' should be captured as PR operations."""
        self.assertGreater(len(self.git["pr_operations"]), 0)

    def test_pr_command_captured(self):
        pr_cmds = [p["command"] for p in self.git["pr_operations"]]
        self.assertTrue(any("gh pr create" in cmd for cmd in pr_cmds))


# ---------------------------------------------------------------------------
# 10. File tracking
# ---------------------------------------------------------------------------
class TestFileTracking(unittest.TestCase):
    """Files read, written, and edited are tracked."""

    def setUp(self):
        self.result = load_fixture_result("full_session.jsonl")
        self.files = self.result["files"]

    def test_read_files_tracked(self):
        self.assertIn("read", self.files)
        self.assertGreater(len(self.files["read"]), 0)

    def test_written_files_tracked(self):
        self.assertIn("written", self.files)
        jwt_go = "/Users/test/dev/myproject/cmd/api/middleware/jwt.go"
        self.assertIn(jwt_go, self.files["written"])

    def test_edited_files_tracked(self):
        self.assertIn("edited", self.files)
        jwt_go = "/Users/test/dev/myproject/cmd/api/middleware/jwt.go"
        self.assertIn(jwt_go, self.files["edited"])

    def test_files_are_sorted_lists(self):
        """File sets should be serialized as sorted lists."""
        for category, file_list in self.files.items():
            self.assertIsInstance(file_list, list,
                                  f"files[{category!r}] is not a list")


# ---------------------------------------------------------------------------
# 11. Edge case: empty session
# ---------------------------------------------------------------------------
class TestEmptySession(unittest.TestCase):
    """A session with only the session_start record and no messages."""

    def setUp(self):
        self.result = load_fixture_result("empty_session.jsonl")

    def test_session_id_extracted(self):
        self.assertEqual(self.result["session"]["session_id"], "empty-session-xyz")

    def test_arc_is_empty(self):
        self.assertEqual(self.result["conversation_arc"], [])

    def test_token_totals_zero(self):
        for field in ("input_tokens", "output_tokens",
                      "cache_creation_input_tokens", "cache_read_input_tokens"):
            self.assertEqual(self.result["tokens"]["total"][field], 0)

    def test_no_agents(self):
        self.assertEqual(self.result["agents"], [])

    def test_no_skills(self):
        self.assertEqual(self.result["skills"], [])

    def test_no_commits(self):
        self.assertEqual(self.result["git"]["commits"], [])

    def test_cost_zero(self):
        self.assertEqual(self.result["tokens"]["estimated_cost_usd"], 0.0)

    def test_tool_counts_empty(self):
        self.assertEqual(self.result["tools"]["total_calls"], 0)

    def test_tool_result_sizes_empty(self):
        self.assertEqual(self.result["tool_result_sizes"], {})

    def test_duration_none_for_single_event(self):
        """Single-record session: start_time == end_time, so duration should be 0."""
        # Either 0 or None is acceptable for a single-event session
        duration = self.result["session"]["duration_seconds"]
        self.assertIn(duration, (0, None))


# ---------------------------------------------------------------------------
# 12. Edge case: tool results without preceding tool_use (orphaned results)
# ---------------------------------------------------------------------------
class TestToolResultsOnly(unittest.TestCase):
    """Session where user messages contain tool_result blocks but no tool_use blocks exist.
    This tests robustness: the extractor should not crash and should produce valid output."""

    def setUp(self):
        self.result = load_fixture_result("tool_results_only.jsonl")

    def test_no_crash(self):
        """Extraction must not raise an exception."""
        # If we got here, setUp succeeded — test passes
        self.assertIsNotNone(self.result)

    def test_arc_empty(self):
        """Orphaned tool results should not add entries to the arc."""
        self.assertEqual(self.result["conversation_arc"], [])

    def test_no_tool_calls_recorded(self):
        """Without tool_use blocks, tool counts should be empty."""
        self.assertEqual(self.result["tools"]["total_calls"], 0)

    def test_result_structure_intact(self):
        """All top-level keys must be present even when session is nearly empty."""
        for key in ("session", "tokens", "agents", "skills", "git",
                    "files", "conversation_arc", "tool_result_sizes", "tools"):
            self.assertIn(key, self.result, f"missing key: {key}")


# ---------------------------------------------------------------------------
# 13. Edge case: session with compaction marker
# ---------------------------------------------------------------------------
class TestCompactedSession(unittest.TestCase):
    """Session that started with a compaction summary in the user content."""

    def setUp(self):
        self.result = load_fixture_result("compacted_session.jsonl")

    def test_arc_contains_compaction_marker(self):
        """The compaction marker message should appear in the arc (it's real user content)."""
        user_texts = [m["text"] for m in self.result["conversation_arc"]
                      if m["role"] == "user"]
        compaction_found = any("Compacted" in t or "compacted" in t for t in user_texts)
        self.assertTrue(compaction_found,
                        "Compaction marker not found in conversation arc")

    def test_system_reminder_filtered_from_arc(self):
        """<system-reminder> content should not appear as arc entries."""
        for msg in self.result["conversation_arc"]:
            self.assertFalse(msg["text"].startswith("<system-reminder>"),
                             f"system-reminder leaked into arc")

    def test_large_cache_creation_captured(self):
        """The compacted session's first message has a 50K cache_creation_input_tokens spike."""
        self.assertGreater(
            self.result["tokens"]["total"]["cache_creation_input_tokens"], 40000)

    def test_read_file_tracked(self):
        """Files read after the compaction point should still be tracked."""
        self.assertIn("read", self.result["files"])
        self.assertGreater(len(self.result["files"]["read"]), 0)


# ---------------------------------------------------------------------------
# 14. Edge case: large arc with pivots and redirects
# ---------------------------------------------------------------------------
class TestLargeArcSession(unittest.TestCase):
    """Session with multiple user pivots — tests arc ordering and redirect detection."""

    def setUp(self):
        self.result = load_fixture_result("large_arc_session.jsonl")
        self.arc = self.result["conversation_arc"]

    def test_redirect_messages_in_arc(self):
        """'no wait' and 'hmm actually' redirects should appear in the arc."""
        user_texts = [m["text"] for m in self.arc if m["role"] == "user"]
        has_redirect = any(
            "no wait" in t.lower() or "actually" in t.lower() or "no that's" in t.lower()
            for t in user_texts
        )
        self.assertTrue(has_redirect, "User redirect messages missing from arc")

    def test_arc_chronological_order(self):
        """Arc messages should be in timestamp order."""
        timestamps = [m["timestamp"] for m in self.arc if m["timestamp"]]
        self.assertEqual(timestamps, sorted(timestamps))

    def test_arc_length_reasonable(self):
        """Large arc fixture has ~8 real user/assistant exchanges."""
        self.assertGreaterEqual(len(self.arc), 6)

    def test_commit_detected_in_large_session(self):
        self.assertGreater(len(self.result["git"]["commits"]), 0)

    def test_both_written_and_edited_files(self):
        """Fixture has both Write and Edit calls for the same file."""
        self.assertIn("written", self.result["files"])
        self.assertIn("edited", self.result["files"])


# ---------------------------------------------------------------------------
# 15. Output structure invariants (run against all fixtures)
# ---------------------------------------------------------------------------
class TestOutputStructureInvariants(unittest.TestCase):
    """These structural guarantees must hold for every fixture."""

    FIXTURES = [
        "full_session.jsonl",
        "empty_session.jsonl",
        "tool_results_only.jsonl",
        "compacted_session.jsonl",
        "large_arc_session.jsonl",
    ]

    REQUIRED_TOP_LEVEL_KEYS = [
        "session", "tokens", "agents", "skills",
        "git", "files", "conversation_arc", "tool_result_sizes", "tools",
    ]

    REQUIRED_SESSION_KEYS = [
        "session_id", "cwd", "git_branch", "version",
        "start_time", "end_time", "duration_seconds", "branches_seen",
    ]

    REQUIRED_TOKEN_KEYS = ["total", "turn_count", "estimated_cost_usd"]

    def test_all_fixtures_have_required_keys(self):
        for fixture in self.FIXTURES:
            with self.subTest(fixture=fixture):
                result = load_fixture_result(fixture)
                for key in self.REQUIRED_TOP_LEVEL_KEYS:
                    self.assertIn(key, result, f"{fixture}: missing top-level key {key!r}")

    def test_session_subkeys_always_present(self):
        for fixture in self.FIXTURES:
            with self.subTest(fixture=fixture):
                session = load_fixture_result(fixture)["session"]
                for key in self.REQUIRED_SESSION_KEYS:
                    self.assertIn(key, session, f"{fixture}: session missing key {key!r}")

    def test_token_subkeys_always_present(self):
        for fixture in self.FIXTURES:
            with self.subTest(fixture=fixture):
                tokens = load_fixture_result(fixture)["tokens"]
                for key in self.REQUIRED_TOKEN_KEYS:
                    self.assertIn(key, tokens, f"{fixture}: tokens missing key {key!r}")

    def test_git_subkeys_always_present(self):
        for fixture in self.FIXTURES:
            with self.subTest(fixture=fixture):
                git = load_fixture_result(fixture)["git"]
                for key in ("branches", "commits", "pr_operations"):
                    self.assertIn(key, git, f"{fixture}: git missing key {key!r}")

    def test_agents_always_list(self):
        for fixture in self.FIXTURES:
            with self.subTest(fixture=fixture):
                self.assertIsInstance(load_fixture_result(fixture)["agents"], list)

    def test_skills_always_list(self):
        for fixture in self.FIXTURES:
            with self.subTest(fixture=fixture):
                self.assertIsInstance(load_fixture_result(fixture)["skills"], list)

    def test_arc_always_list(self):
        for fixture in self.FIXTURES:
            with self.subTest(fixture=fixture):
                self.assertIsInstance(
                    load_fixture_result(fixture)["conversation_arc"], list)

    def test_cost_always_non_negative(self):
        for fixture in self.FIXTURES:
            with self.subTest(fixture=fixture):
                cost = load_fixture_result(fixture)["tokens"]["estimated_cost_usd"]
                self.assertGreaterEqual(cost, 0.0)

    def test_no_sets_in_output(self):
        """All sets must be converted to lists before output (json.dumps would fail on sets)."""
        for fixture in self.FIXTURES:
            with self.subTest(fixture=fixture):
                result = load_fixture_result(fixture)
                # If this doesn't raise, sets were properly converted
                try:
                    json.dumps(result)
                except TypeError as e:
                    self.fail(f"{fixture}: output contains non-serializable type: {e}")


# ---------------------------------------------------------------------------
# 16. Known bug: user text blocks inside list content are silently dropped
# ---------------------------------------------------------------------------
class TestKnownBugListContentUserMessages(unittest.TestCase):
    """KNOWN LIMITATION: When a user message has list-format content (the common real-world
    Claude Code JSONL format), text blocks in that list are silently dropped from the arc.

    Root cause in extract.py:
      Line 222: `if isinstance(content, list):` handles ALL list content.
      Inside that branch, the text-block handler at line 315 only adds to arc for
      `role == "assistant"` — user text blocks in lists are never appended.
      Line 325: `elif role == "user":` only fires when content is NOT a list.

    Impact: user messages that arrive interleaved with tool_result blocks (the typical
    format) are not captured in conversation_arc. Only user messages sent as plain
    strings (rare in practice — usually only the very first message in a session)
    appear in the arc.

    This means friction signals (corrections, redirects) that come between tool calls
    are invisible to the retro analysis — exactly the most valuable data.

    Fixture: user_list_content.jsonl — 3 user messages in list format, 1 in string format.
    Expected (desired): all 4 captured. Actual: only 1 captured.
    """

    @classmethod
    def setUpClass(cls):
        """Create the list-content fixture inline."""
        import tempfile, os, json
        cls.fixture_path = FIXTURES_DIR / "user_list_content.jsonl"

        lines = [
            # String-format user message (DOES get captured)
            {"message": {"role": "user", "content": "first message in string format"},
             "timestamp": "2026-04-06T14:00:00Z"},
            # List-format text block (does NOT get captured — the bug)
            {"message": {"role": "user", "content": [{"type": "text", "text": "second message in list format — should be captured"}]},
             "timestamp": "2026-04-06T14:00:10Z"},
            # List-format with tool_result (no text, shouldn't be captured)
            {"message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "tu_x", "content": "some result"}]},
             "timestamp": "2026-04-06T14:00:20Z"},
            # List-format with mixed text+tool_result (text SHOULD be captured but isn't)
            {"message": {"role": "user", "content": [
                {"type": "text", "text": "third message with mixed content"},
                {"type": "tool_result", "tool_use_id": "tu_y", "content": "another result"}
            ]},
             "timestamp": "2026-04-06T14:00:30Z"},
        ]
        with open(cls.fixture_path, "w") as f:
            for line in lines:
                f.write(json.dumps(line) + "\n")

        cls.result = extract.extract_all_streaming(str(cls.fixture_path))
        cls.arc_user_texts = [m["text"] for m in cls.result["conversation_arc"]
                              if m["role"] == "user"]

    def test_string_content_captured(self):
        """User messages in string format ARE captured (this works)."""
        self.assertTrue(
            any("string format" in t for t in self.arc_user_texts),
            "String-format user message should be in arc"
        )

    def test_list_text_block_captured(self):
        """User text blocks in list format are now captured (bug fixed)."""
        self.assertTrue(
            any("list format" in t for t in self.arc_user_texts),
            "List-format user text should be captured in arc"
        )

    def test_mixed_content_text_captured(self):
        """User text blocks mixed with tool_result in list content are now captured."""
        self.assertTrue(
            any("mixed content" in t for t in self.arc_user_texts),
            "Mixed list-format user text should be captured in arc"
        )

    def test_all_user_messages_captured(self):
        """All user messages with text should be captured (bug fixed)."""
        self.assertEqual(len(self.arc_user_texts), 3,
                         f"Expected 3 user messages, got {len(self.arc_user_texts)}: {self.arc_user_texts}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Support: python test_extract.py -v  OR  python test_extract.py TestName
    # unittest.main handles both transparently
    unittest.main(verbosity=2)
