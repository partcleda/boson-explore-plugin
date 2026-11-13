#!/usr/bin/env python3
import argparse
import itertools
import json
from pathlib import Path


def compare_stages(baseline, candidate, level):
    left = load_stages(baseline, level)
    right = load_stages(candidate, level)
    if not left and not right:
        raise ValueError(f"no main-flow stages at level {level} in either snapshot directory")
    matched = 0
    difference = None
    for position, (old, new) in enumerate(itertools.zip_longest(left, right)):
        if old == new:
            matched += 1
            continue
        difference = {
            "position": position,
            "baseline": describe(old),
            "candidate": describe(new),
        }
        break
    return {
        "level": level,
        "baseline_stages": len(left),
        "candidate_stages": len(right),
        "matched_prefix": matched,
        "equal": difference is None,
        "first_difference": difference,
    }


def load_stages(directory, level):
    directory = directory.resolve()
    index, = read_call(directory / "index.js", "boson_index")
    stages = []
    for entry in index:
        if not entry["main"] or entry["probe"]:
            continue
        if level != "all" and entry["level"] != level:
            continue
        path = (directory / entry["file"]).resolve()
        if not path.is_relative_to(directory):
            raise ValueError(f"{directory / 'index.js'}: stage path leaves snapshot directory: {entry['file']}")
        sequence, graph = read_call(path, "boson_snapshot")
        if sequence != entry["seq"] or graph["stage"] != entry["stage"]:
            raise ValueError(f"{path}: stage identity differs from index")
        stages.append(graph)
    return stages


def read_call(path, function):
    text = path.read_text(encoding="utf-8")
    prefix = function + "("
    if not text.startswith(prefix):
        raise ValueError(f"{path}: expected {function} at offset 0")
    decoder = json.JSONDecoder()
    position = len(prefix)
    arguments = []
    while True:
        position = skip_space(text, position)
        try:
            argument, position = decoder.raw_decode(text, position)
        except json.JSONDecodeError as error:
            raise ValueError(f"{path}: {error.msg} at offset {error.pos}") from error
        arguments.append(argument)
        position = skip_space(text, position)
        if text[position:position + 1] == ",":
            position += 1
            continue
        if text[position:].strip() != ");":
            raise ValueError(f"{path}: expected end of call at offset {position}")
        return arguments


def skip_space(text, position):
    while position < len(text) and text[position].isspace():
        position += 1
    return position


def describe(stage):
    if stage is None:
        return None
    return {
        "stage": stage["stage"],
        "level": stage["level"],
        "nodes": {name: len(values) for name, values in stage["nodes"].items()},
    }


def main():
    parser = argparse.ArgumentParser(description="Compare main-flow graph snapshots and locate the first changed stage.")
    parser.add_argument("baseline", type=Path)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("--level", choices=["datapath", "gates", "aig", "mapped", "all"], default="datapath")
    args = parser.parse_args()
    try:
        result = compare_stages(args.baseline, args.candidate, args.level)
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(2, f"snapshot_stages: {error}\n")
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
