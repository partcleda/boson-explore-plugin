#!/usr/bin/env python3
import argparse
import gzip
import json
import math
import re
import sys
from pathlib import Path

PREFIX = re.compile(r"^(?:\d{4}-\d\d-\d\dT[\d:.]+Z )?partcl_timing_profile \+(\S+)s (.*)$")
COMPILE = re.compile(r"\[synth_profile\] compile=(\S+)s(?:\s|$)")


def nonnegative(value, source, line):
    try:
        number = float(value)
    except ValueError:
        raise ValueError(f"{source}:{line}: invalid duration {value!r}") from None
    if not math.isfinite(number) or number < 0:
        raise ValueError(f"{source}:{line}: invalid duration {value!r}")
    return number


def summarize(lines, source):
    stages = {}
    compiles = []
    for line_number, line in enumerate(lines, 1):
        completion = COMPILE.search(line)
        if completion:
            compiles.append(1000 * nonnegative(completion[1], source, line_number))
        match = PREFIX.match(line.rstrip("\r\n"))
        if not match:
            continue
        payload = match[2].replace("\\t", "\t")
        if "\t" not in payload:
            continue
        elapsed = nonnegative(match[1], source, line_number)
        label, duration = payload.rsplit("\t", 1)
        if re.match(r"[A-Za-z_][A-Za-z0-9_]*=", duration):
            continue
        measured = re.fullmatch(r"(\S+) ms(?:\s+.*)?", duration)
        if not label or not measured:
            raise ValueError(f"{source}:{line_number}: malformed timing phase")
        label = re.split(r" (?=[A-Za-z_][A-Za-z0-9_]*=)", label, maxsplit=1)[0]
        milliseconds = nonnegative(measured[1], source, line_number)
        stage = stages.setdefault(label, dict(label=label, calls=0, total_ms=0.0,
                                             max_ms=0.0, first_s=elapsed, last_s=elapsed))
        stage["calls"] += 1
        stage["total_ms"] += milliseconds
        stage["max_ms"] = max(stage["max_ms"], milliseconds)
        stage["first_s"] = min(stage["first_s"], elapsed)
        stage["last_s"] = max(stage["last_s"], elapsed)
    if not stages:
        raise ValueError(f"{source}: no timing phase records")
    return dict(source=str(source), aggregation="inclusive by label; totals overlap",
                compile_completions=len(compiles),
                reported_compile_ms=sum(compiles) if compiles else None,
                stages=sorted(stages.values(), key=lambda stage: (-stage["total_ms"], stage["label"])))


def main(argv=None):
    parser = argparse.ArgumentParser(description="Summarize boson timing-profile phases from a plain or gzipped log.")
    parser.add_argument("log", type=Path)
    args = parser.parse_args(argv)
    opener = gzip.open if args.log.suffix == ".gz" else open
    try:
        with opener(args.log, "rt", encoding="utf-8") as lines:
            report = summarize(lines, args.log)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    json.dump(report, sys.stdout, indent=2, allow_nan=False)
    print()


if __name__ == "__main__":
    main()
