#!/usr/bin/env python3
"""Cross-provider discovery tests."""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import extract  # noqa: E402


class TestDiscoveryPriority(unittest.TestCase):
    def test_auto_prefers_newest_matching_provider(self):
        cwd = "/tmp/project"
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir)

            claude_sessions = home / ".claude" / "sessions"
            claude_projects = home / ".claude" / "projects" / cwd.replace("/", "-")
            claude_sessions.mkdir(parents=True)
            claude_projects.mkdir(parents=True)
            (claude_sessions / "100.json").write_text(json.dumps({"pid": 100, "sessionId": "claude-session", "cwd": cwd}))
            claude_transcript = claude_projects / "claude-session.jsonl"
            claude_transcript.write_text(
                '{"sessionId":"claude-session","cwd":"/tmp/project","timestamp":"2026-04-13T08:00:00Z","type":"session_start"}\n'
            )

            codex_dir = home / ".codex" / "sessions" / "2026" / "04" / "13"
            codex_dir.mkdir(parents=True)
            codex_transcript = codex_dir / "rollout-2026-04-13T08-00-01-codex.jsonl"
            codex_transcript.write_text(
                '{"timestamp":"2026-04-13T08:00:01Z","type":"session_meta","payload":{"id":"codex-session","timestamp":"2026-04-13T08:00:01Z","cwd":"/tmp/project","cli_version":"0.120.0"}}\n'
            )

            os.utime(claude_transcript, (1, 1))
            os.utime(codex_transcript, (2, 2))

            with patch.dict(os.environ, {"HOME": str(home)}):
                provider, transcript_path = extract.discover_current_session(provider="auto", cwd=cwd)

        self.assertEqual(provider, "codex")
        self.assertEqual(transcript_path, str(codex_transcript))


if __name__ == "__main__":
    unittest.main(verbosity=2)
