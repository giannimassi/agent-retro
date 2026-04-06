#!/usr/bin/env python3
"""
TDD tests for council review fixes.

These tests are written BEFORE the fixes. They should FAIL initially,
then PASS after each fix is applied.

Fixes addressed:
  1. User messages in list-format content dropped from arc (CRITICAL BUG)
  2. Arc truncation too aggressive (300/500 chars)
  3. Hardcoded pricing has no staleness warning
  4. extract_json_field breaks on escaped quotes
  5. Subagent dir auto-detection fails silently
  6. Schema version missing from output
"""

import json
import os
import sys
import unittest
import tempfile
import io
from contextlib import redirect_stderr
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import extract  # noqa: E402

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


# ---------------------------------------------------------------------------
# Fix 1: User messages in list-format content must be captured in arc
# ---------------------------------------------------------------------------
class TestFix1_ListFormatUserMessages(unittest.TestCase):
    """CRITICAL BUG: User text blocks inside list-format content are dropped.

    Real Claude Code sessions send user messages as:
      {"role": "user", "content": [{"type": "text", "text": "..."}]}

    The current code only captures user messages when content is a plain string.
    This fix must capture text blocks from list-format user messages too.
    """

    @classmethod
    def setUpClass(cls):
        cls.fixture = FIXTURES_DIR / "user_list_content.jsonl"
        # Ensure fixture exists (created by TestKnownBugListContentUserMessages)
        if not cls.fixture.exists():
            lines = [
                {"message": {"role": "user", "content": "string format message"},
                 "timestamp": "2026-04-06T14:00:00Z"},
                {"message": {"role": "user", "content": [
                    {"type": "text", "text": "list format message with correction: no, do it differently"}
                ]}, "timestamp": "2026-04-06T14:00:10Z"},
                {"message": {"role": "user", "content": [
                    {"type": "text", "text": "mixed content message: wait, stop"},
                    {"type": "tool_result", "tool_use_id": "tu_y", "content": "result"}
                ]}, "timestamp": "2026-04-06T14:00:30Z"},
            ]
            with open(cls.fixture, "w") as f:
                for line in lines:
                    f.write(json.dumps(line) + "\n")

        cls.result = extract.extract_all_streaming(str(cls.fixture))
        cls.arc_user_texts = [m["text"] for m in cls.result["conversation_arc"]
                              if m["role"] == "user"]

    def test_list_format_text_captured(self):
        """User text in list-format content MUST appear in arc."""
        self.assertTrue(
            any("list format" in t for t in self.arc_user_texts),
            f"List-format user text not in arc. Got: {self.arc_user_texts}"
        )

    def test_mixed_content_text_captured(self):
        """User text mixed with tool_result in list content MUST appear in arc."""
        self.assertTrue(
            any("mixed content" in t or "wait, stop" in t for t in self.arc_user_texts),
            f"Mixed-content user text not in arc. Got: {self.arc_user_texts}"
        )

    def test_all_three_user_messages_captured(self):
        """All user messages with text should be in the arc (string + list + mixed)."""
        self.assertEqual(len(self.arc_user_texts), 3,
                         f"Expected 3 user messages, got {len(self.arc_user_texts)}: {self.arc_user_texts}")

    def test_tool_result_only_message_excluded(self):
        """User messages containing ONLY tool_result blocks (no text) should NOT be in arc."""
        lines = [
            {"message": {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "tu_z", "content": "just a result"}
            ]}, "timestamp": "2026-04-06T14:00:40Z"},
        ]
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            for line in lines:
                f.write(json.dumps(line) + "\n")
            f.flush()
            result = extract.extract_all_streaming(f.name)
        os.unlink(f.name)
        user_msgs = [m for m in result["conversation_arc"] if m["role"] == "user"]
        self.assertEqual(len(user_msgs), 0, "tool_result-only message should not appear in arc")

    def test_system_reminder_in_list_filtered(self):
        """System reminders in list-format should still be filtered."""
        lines = [
            {"message": {"role": "user", "content": [
                {"type": "text", "text": "<system-reminder>Auto mode active</system-reminder>"}
            ]}, "timestamp": "2026-04-06T14:00:50Z"},
        ]
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            for line in lines:
                f.write(json.dumps(line) + "\n")
            f.flush()
            result = extract.extract_all_streaming(f.name)
        os.unlink(f.name)
        user_msgs = [m for m in result["conversation_arc"] if m["role"] == "user"]
        self.assertEqual(len(user_msgs), 0, "system-reminder in list format should be filtered")


# ---------------------------------------------------------------------------
# Fix 2: Arc truncation limits raised
# ---------------------------------------------------------------------------
class TestFix2_ArcTruncationRaised(unittest.TestCase):
    """Arc truncation at 300/500 chars loses critical context.
    Limits should be raised to at least 1000/2000 chars."""

    def test_long_user_message_preserved(self):
        """A 1500-char user message should not be truncated to 500."""
        long_msg = "x" * 1500
        lines = [
            {"message": {"role": "user", "content": long_msg},
             "timestamp": "2026-04-06T15:00:00Z"},
        ]
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            for line in lines:
                f.write(json.dumps(line) + "\n")
            f.flush()
            result = extract.extract_all_streaming(f.name)
        os.unlink(f.name)
        user_msgs = [m for m in result["conversation_arc"] if m["role"] == "user"]
        self.assertGreater(len(user_msgs[0]["text"]), 500,
                           "User message truncated to <=500 chars — limit should be raised")

    def test_long_assistant_message_preserved(self):
        """A 800-char assistant message should not be truncated to 300."""
        long_text = "a" * 800
        lines = [
            {"message": {"role": "assistant",
                         "content": [{"type": "text", "text": long_text}]},
             "timestamp": "2026-04-06T15:00:10Z"},
        ]
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            for line in lines:
                f.write(json.dumps(line) + "\n")
            f.flush()
            result = extract.extract_all_streaming(f.name)
        os.unlink(f.name)
        asst_msgs = [m for m in result["conversation_arc"] if m["role"] == "assistant"]
        self.assertGreater(len(asst_msgs[0]["text"]), 300,
                           "Assistant message truncated to <=300 chars — limit should be raised")


# ---------------------------------------------------------------------------
# Fix 3: Pricing staleness warning
# ---------------------------------------------------------------------------
class TestFix3_PricingStalenessWarning(unittest.TestCase):
    """Hardcoded pricing should include a last-verified date and the script
    should have a PRICING_LAST_VERIFIED constant."""

    def test_pricing_last_verified_exists(self):
        """extract module must have a PRICING_LAST_VERIFIED constant."""
        self.assertTrue(hasattr(extract, "PRICING_LAST_VERIFIED"),
                        "Missing PRICING_LAST_VERIFIED constant in extract.py")

    def test_pricing_last_verified_is_date_string(self):
        """PRICING_LAST_VERIFIED should be an ISO date string."""
        verified = getattr(extract, "PRICING_LAST_VERIFIED", None)
        self.assertIsNotNone(verified)
        # Should parse as a date
        from datetime import datetime
        try:
            datetime.strptime(verified, "%Y-%m-%d")
        except (ValueError, TypeError):
            self.fail(f"PRICING_LAST_VERIFIED is not a valid YYYY-MM-DD date: {verified}")


# ---------------------------------------------------------------------------
# Fix 4: extract_json_field handles escaped quotes
# ---------------------------------------------------------------------------
class TestFix4_EscapedQuotesInJsonField(unittest.TestCase):
    """extract_json_field must handle escaped quotes in values correctly."""

    def test_simple_value(self):
        text = '"sessionId":"abc-123"'
        self.assertEqual(extract.extract_json_field(text, "sessionId"), "abc-123")

    def test_escaped_quote_in_value(self):
        """Value containing escaped quotes must be fully extracted."""
        text = r'"text":"She said \"hello\" to me"'
        result = extract.extract_json_field(text, "text")
        self.assertEqual(result, r'She said \"hello\" to me',
                         f"Escaped quotes not handled correctly, got: {result}")

    def test_escaped_backslash_before_quote(self):
        r"""Value with \\ before a quote: the quote terminates the value."""
        text = r'"text":"path is C:\\Users\\"'
        result = extract.extract_json_field(text, "text")
        self.assertEqual(result, r"path is C:\\Users\\")

    def test_newline_escape_in_value(self):
        r"""Value with \n should be extracted fully."""
        text = r'"text":"line1\nline2"'
        result = extract.extract_json_field(text, "text")
        self.assertEqual(result, r"line1\nline2")

    def test_multiple_fields_extracts_first(self):
        """When multiple fields exist, extract the first occurrence."""
        text = '"cwd":"/first","other":"x","cwd":"/second"'
        result = extract.extract_json_field(text, "cwd")
        self.assertEqual(result, "/first")

    def test_value_with_colon(self):
        """Value containing colons should be fully extracted."""
        text = '"url":"https://example.com:8080/path"'
        result = extract.extract_json_field(text, "url")
        self.assertEqual(result, "https://example.com:8080/path")


# ---------------------------------------------------------------------------
# Fix 5: Subagent dir auto-detection warns on failure
# ---------------------------------------------------------------------------
class TestFix5_SubagentDirWarning(unittest.TestCase):
    """When subagent dir auto-detection fails, a warning should be emitted to stderr."""

    def test_warning_when_no_subagents_dir_found(self):
        """Running extraction with no subagents dir should emit a note to stderr."""
        # Create a minimal fixture
        lines = [
            {"sessionId": "test", "timestamp": "2026-04-06T15:00:00Z",
             "message": {"role": "assistant", "content": [
                 {"type": "tool_use", "id": "tu_agent", "name": "Agent",
                  "input": {"description": "test", "prompt": "do something"}}
             ], "usage": {"input_tokens": 0, "output_tokens": 100,
                          "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}}},
        ]
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            for line in lines:
                f.write(json.dumps(line) + "\n")
            f.flush()
            # Capture stderr
            stderr_capture = io.StringIO()
            with redirect_stderr(stderr_capture):
                result = extract.extract_all_streaming(f.name, subagents_dir=None)
        os.unlink(f.name)
        # Should have at least one agent with no cost data
        agents_without_cost = [a for a in result["agents"] if a["estimated_cost_usd"] is None]
        if agents_without_cost:
            stderr_output = stderr_capture.getvalue()
            self.assertIn("subagent", stderr_output.lower(),
                          "No stderr warning about missing subagent cost data")


# ---------------------------------------------------------------------------
# Fix 6: Schema version in output
# ---------------------------------------------------------------------------
class TestFix6_SchemaVersion(unittest.TestCase):
    """Extraction output should include a schema_version field."""

    def test_schema_version_present(self):
        lines = [
            {"sessionId": "test", "timestamp": "2026-04-06T15:00:00Z"},
        ]
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            for line in lines:
                f.write(json.dumps(line) + "\n")
            f.flush()
            result = extract.extract_all_streaming(f.name)
        os.unlink(f.name)
        self.assertIn("schema_version", result,
                       "Output missing schema_version field")

    def test_schema_version_is_string(self):
        lines = [
            {"sessionId": "test", "timestamp": "2026-04-06T15:00:00Z"},
        ]
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            for line in lines:
                f.write(json.dumps(line) + "\n")
            f.flush()
            result = extract.extract_all_streaming(f.name)
        os.unlink(f.name)
        self.assertIsInstance(result.get("schema_version"), str)


if __name__ == "__main__":
    unittest.main(verbosity=2)
