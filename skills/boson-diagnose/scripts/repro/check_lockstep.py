#!/usr/bin/env python3
import argparse
import json
import re
from pathlib import Path


SUMMARY = re.compile(r"^SIMEQ checked ([0-9]+) cycles, ([0-9]+) mismatches$", re.MULTILINE)


def check_summary(text, expected_cycles):
    if expected_cycles <= 0:
        raise ValueError("expected cycles must be positive")
    matches = list(SUMMARY.finditer(text))
    if len(matches) != 1:
        raise ValueError(f"expected one completion summary, found {len(matches)}")
    cycles, mismatches = map(int, matches[0].groups())
    if cycles != expected_cycles:
        raise ValueError(f"checked {cycles} cycles, expected {expected_cycles}")
    if mismatches:
        raise ValueError(f"found {mismatches} mismatches")
    return {"checked_cycles": cycles, "mismatches": mismatches}


def main():
    parser = argparse.ArgumentParser(description="Check bounded lockstep simulation completion and mismatches.")
    parser.add_argument("--expected-cycles", required=True, type=int)
    parser.add_argument("logs", nargs="+", type=Path)
    args = parser.parse_args()
    if args.expected_cycles <= 0:
        parser.error("--expected-cycles must be positive")
    failed = False
    for path in args.logs:
        result = {"log": str(path), "check": "bounded_simulation"}
        try:
            result.update(check_summary(path.read_text(encoding="utf-8"), args.expected_cycles))
            result["passed"] = True
        except UnicodeDecodeError as error:
            result.update(passed=False, reason=f"invalid UTF-8 at byte {error.start}")
        except (OSError, ValueError) as error:
            result.update(passed=False, reason=str(error))
        failed |= not result["passed"]
        print(json.dumps(result, sort_keys=True))
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
