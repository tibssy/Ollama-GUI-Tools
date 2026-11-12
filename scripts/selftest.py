#!/usr/bin/env python3
"""Run every tool with sample arguments. Uses only the standard library."""

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOOLS_DIR = ROOT / "tools"
NETWORK_TOOLS = {"web_search"}

SAMPLES = {
    "current_time": [
        ({}, "UTC"),
        ({"timezone": "America/New_York"}, "UTC-05:00"),
    ],
    "calculator": [
        ({"expression": "(2 + 3) * 4 / 2"}, "10"),
        ({"expression": "sqrt(2) ** 2"}, "2"),
        ({"expression": "-2 ** 2"}, "-4"),
        ({"expression": "2 ** 3 ** 2"}, "512"),
        ({"expression": "sin(pi / 2)"}, "1"),
    ],
    "unit_convert": [
        ({"value": 1, "from": "km", "to": "mi"}, "0.6213711922"),
        ({"value": 100, "from": "c", "to": "f"}, "212"),
        ({"value": 32, "from": "f", "to": "c"}, "0"),
        ({"value": 1, "from": "gib", "to": "gb"}, "1.073741824"),
        ({"value": 60, "from": "mph", "to": "km/h"}, "96.56064"),
    ],
    "web_search": [
        ({"query": "Ollama tool calling", "max_results": 3}, "http"),
    ],
}

ERROR_SAMPLES = {
    "calculator": [
        {"expression": "1 / 0"},
        {"expression": "2 +"},
        {"expression": "unknown(3)"},
    ],
    "unit_convert": [
        {"value": 1, "from": "km", "to": "kg"},
        {"value": 1, "from": "parsec", "to": "km"},
        {"value": -500, "from": "c", "to": "f"},
    ],
    "web_search": [
        {"query": ""},
    ],
}


def run_tool(path, args, timeout=10):
    completed = subprocess.run(
        [str(path)],
        input=json.dumps(args),
        text=True,
        capture_output=True,
        timeout=timeout,
    )
    output = completed.stdout.strip()
    if not output:
        raise RuntimeError(
            f"{path.parent.name}: no stdout (exit {completed.returncode}): "
            f"{completed.stderr.strip()[:300]}"
        )
    try:
        return json.loads(output)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{path.parent.name}: invalid JSON output: {output[:300]}") from exc


def main():
    failures = []
    tool_dirs = sorted(path for path in TOOLS_DIR.iterdir() if path.is_dir())
    if not tool_dirs:
        print("error: no tools found", file=sys.stderr)
        return 1

    for tool_dir in tool_dirs:
        tool_id = tool_dir.name
        run_path = tool_dir / "run"
        if not run_path.is_file():
            failures.append(f"{tool_id}: missing run")
            continue

        samples = SAMPLES.get(tool_id)
        if not samples:
            print(f"warning: {tool_id}: no sample arguments, skipped")
            continue

        if tool_id in NETWORK_TOOLS and os.environ.get("TOOLS_NETWORK_TESTS") != "1":
            print(f"skip: {tool_id} (network test; set TOOLS_NETWORK_TESTS=1)")
            continue

        for args, expected in samples:
            try:
                result = run_tool(run_path, args)
            except Exception as exc:
                failures.append(f"{tool_id} {args}: {exc}")
                continue
            if not result.get("success"):
                failures.append(f"{tool_id} {args}: {result.get('error', 'failed')}")
                continue
            text = str(result.get("result", ""))
            if expected not in text:
                failures.append(
                    f"{tool_id} {args}: expected '{expected}' in result, got '{text}'"
                )

        for args in ERROR_SAMPLES.get(tool_id, []):
            try:
                result = run_tool(run_path, args)
            except Exception as exc:
                failures.append(f"{tool_id} {args}: {exc}")
                continue
            if result.get("success"):
                failures.append(f"{tool_id} {args}: expected an error, got success")

        print(f"ok: {tool_id} ({len(samples)} samples)")

    if failures:
        print("\nfailures:", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        return 1

    print(f"\nall {len(tool_dirs)} tools passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
