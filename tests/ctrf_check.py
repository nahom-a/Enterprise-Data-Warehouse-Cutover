#!/usr/bin/env python3
"""Validates CTRF JSON report from pytest run.
Prints OK only if the report shows exactly the expected number of tests (default 144),
all passed, none failed, skipped, pending, or other.
Any exception or unexpected result prints FAIL.
"""
import json
import sys


def main():
    try:
        if len(sys.argv) < 2:
            print("FAIL")
            sys.exit(1)

        path = sys.argv[1]
        expected_tests = int(sys.argv[2]) if len(sys.argv) > 2 else 144

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        results = data.get("results", {})
        summary = results.get("summary", {})

        tests = summary.get("tests", 0)
        passed = summary.get("passed", 0)
        failed = summary.get("failed", 0)
        skipped = summary.get("skipped", 0)
        pending = summary.get("pending", 0)
        other = summary.get("other", 0)

        if (
            tests == expected_tests
            and passed == expected_tests
            and failed == 0
            and skipped == 0
            and pending == 0
            and other == 0
        ):
            print("OK")
            sys.exit(0)
        else:
            print(f"FAIL: tests={tests}, passed={passed}, failed={failed}, skipped={skipped}", file=sys.stderr)
            print("FAIL")
            sys.exit(1)
    except Exception as e:
        print(f"FAIL: exception={e}", file=sys.stderr)
        print("FAIL")
        sys.exit(1)


if __name__ == "__main__":
    main()
