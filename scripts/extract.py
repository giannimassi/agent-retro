#!/usr/bin/env python3
"""
Extract structured data from supported agent session transcripts.

Supported providers:
- Claude Code
- OpenAI Codex

Usage:
    python extract.py <session-jsonl-path> [--provider auto|claude|codex]
    python extract.py --discover-current [--provider auto|claude|codex]

Outputs JSON to stdout. Use --summary for a compact version that omits
individual tool call details. Use --metadata-only for cheap session verification.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from providers import claude, codex
from providers.common import (
    LITE_READ_BUF_SIZE,
    SCHEMA_VERSION,
    extract_json_field,
    parse_ts,
    read_head_tail,
    stream_jsonl,
)

PROVIDERS = {
    "claude": claude,
    "codex": codex,
}

# Preserve the Claude pricing exports for downstream users and tests.
PRICING_LAST_VERIFIED = claude.PRICING_LAST_VERIFIED
PRICE_PER_M = claude.PRICE_PER_M


def detect_provider(path):
    """Detect the transcript provider from the file header."""
    head, _, _ = read_head_tail(path)
    if claude.is_match(head):
        return "claude"
    if codex.is_match(head):
        return "codex"
    raise ValueError(f"Unable to detect transcript provider for {path}")


def resolve_provider(path, provider):
    return detect_provider(path) if provider == "auto" else provider


def discover_current_session(provider="auto", cwd=None):
    """Locate the most likely current session transcript for the working directory."""
    cwd = cwd or os.getcwd()

    if provider == "auto":
        candidates = []
        for provider_name, module in PROVIDERS.items():
            path = module.discover_current_session(cwd)
            if path:
                candidates.append((provider_name, path))
        if not candidates:
            raise FileNotFoundError(f"No supported session transcript found for cwd {cwd}")
        return max(candidates, key=lambda item: os.path.getmtime(item[1]))

    module = PROVIDERS[provider]
    path = module.discover_current_session(cwd)
    if not path:
        raise FileNotFoundError(f"No {provider} session transcript found for cwd {cwd}")
    return provider, path


def extract_metadata_lite(path, provider="auto"):
    resolved_provider = resolve_provider(path, provider)
    result = PROVIDERS[resolved_provider].extract_metadata_lite(path)
    result["provider"] = resolved_provider
    result["transcript_path"] = str(Path(path))
    return result


def extract_all_streaming(jsonl_path, subagents_dir=None, summary_mode=False, provider="auto"):
    resolved_provider = resolve_provider(jsonl_path, provider)
    result = PROVIDERS[resolved_provider].extract_all_streaming(
        jsonl_path,
        subagents_dir=subagents_dir,
        summary_mode=summary_mode,
    )
    result["provider"] = resolved_provider
    result["schema_version"] = SCHEMA_VERSION
    result["transcript_path"] = str(Path(jsonl_path))
    return result


def build_parser():
    parser = argparse.ArgumentParser(
        description="Extract structured data from Claude Code or Codex session transcripts.",
    )
    parser.add_argument(
        "jsonl_path",
        nargs="?",
        help="Path to the session JSONL transcript.",
    )
    parser.add_argument(
        "--provider",
        choices=("auto", "claude", "codex"),
        default="auto",
        help="Transcript provider. Defaults to auto-detection.",
    )
    parser.add_argument(
        "--discover-current",
        action="store_true",
        help="Discover the most recent transcript for the current working directory.",
    )
    parser.add_argument(
        "--cwd",
        help="Working directory to match when using --discover-current. Defaults to the current shell cwd.",
    )
    parser.add_argument(
        "--subagents-dir",
        help="Claude-only subagents directory used for subagent cost attribution.",
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Omit individual tool call listings and keep only aggregate counts.",
    )
    parser.add_argument(
        "--metadata-only",
        action="store_true",
        help="Read only lightweight metadata instead of full transcript extraction.",
    )
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.discover_current:
        provider_name, jsonl_path = discover_current_session(provider=args.provider, cwd=args.cwd)
    else:
        if not args.jsonl_path:
            parser.error("jsonl_path is required unless --discover-current is used")
        jsonl_path = args.jsonl_path
        provider_name = resolve_provider(jsonl_path, args.provider)

    if args.metadata_only:
        result = extract_metadata_lite(jsonl_path, provider=provider_name)
    else:
        result = extract_all_streaming(
            jsonl_path,
            subagents_dir=args.subagents_dir,
            summary_mode=args.summary,
            provider=provider_name,
        )

    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
