#!/usr/bin/env python3
"""Tests for the Codex transcript adapter."""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import extract  # noqa: E402


FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


class TestCodexMetadata(unittest.TestCase):
    def setUp(self):
        self.fixture = str(FIXTURES_DIR / "codex_session.jsonl")
        self.meta = extract.extract_metadata_lite(self.fixture)

    def test_provider_detected(self):
        self.assertEqual(self.meta["provider"], "codex")

    def test_session_id_extracted(self):
        self.assertEqual(self.meta["session_id"], "019d881b-b082-7d91-9c06-25bcae39c50a")

    def test_first_prompt_extracted(self):
        self.assertEqual(self.meta["first_prompt"], "please review the repo and add a brief plan")


class TestCodexExtraction(unittest.TestCase):
    def setUp(self):
        self.fixture = str(FIXTURES_DIR / "codex_session.jsonl")
        self.result = extract.extract_all_streaming(self.fixture)

    def test_provider_set(self):
        self.assertEqual(self.result["provider"], "codex")

    def test_tool_counts(self):
        counts = self.result["tools"]["counts"]
        self.assertEqual(counts.get("exec_command", 0), 1)
        self.assertEqual(counts.get("spawn_agent", 0), 1)
        self.assertEqual(counts.get("apply_patch", 0), 1)

    def test_files_tracked_from_apply_patch(self):
        self.assertEqual(self.result["files"]["written"], ["docs/retro.md"])
        self.assertEqual(self.result["files"]["edited"], ["src/app.py"])

    def test_conversation_arc_preserved(self):
        roles = [message["role"] for message in self.result["conversation_arc"]]
        self.assertIn("user", roles)
        self.assertIn("assistant", roles)

    def test_token_mapping(self):
        total = self.result["tokens"]["total"]
        self.assertEqual(total["input_tokens"], 2400)
        self.assertEqual(total["cache_read_input_tokens"], 1800)
        self.assertEqual(total["output_tokens"], 320)
        self.assertEqual(total["reasoning_output_tokens"], 40)
        self.assertIsNone(self.result["tokens"]["estimated_cost_usd"])

    def test_exec_command_result_sizes_prefer_raw_output(self):
        exec_stats = self.result["tool_result_sizes"]["exec_command"]
        self.assertEqual(exec_stats["total_bytes"], len("## main\n".encode("utf-8")))

    def test_spawn_agent_recorded(self):
        self.assertEqual(len(self.result["agents"]), 1)
        self.assertEqual(self.result["agents"][0]["type"], "explorer")


class TestDiscovery(unittest.TestCase):
    def test_codex_current_session_discovery(self):
        fixture = FIXTURES_DIR / "codex_session.jsonl"
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir)
            target_dir = home / ".codex" / "sessions" / "2026" / "04" / "13"
            target_dir.mkdir(parents=True)
            target_file = target_dir / "rollout-2026-04-13T18-30-09-test.jsonl"
            target_file.write_text(fixture.read_text())

            with patch.dict(os.environ, {"HOME": str(home)}):
                provider, transcript_path = extract.discover_current_session(
                    provider="auto",
                    cwd="/home/test/dev/myproject",
                )

        self.assertEqual(provider, "codex")
        self.assertEqual(transcript_path, str(target_file))


if __name__ == "__main__":
    unittest.main(verbosity=2)
