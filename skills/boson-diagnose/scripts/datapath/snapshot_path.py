import argparse
import json
from pathlib import Path

from datapath_audit import usable_slack
from snapshot_trace import load_snapshot, lookup, read_call


def snapshot(directory, sequence, level):
    entries, = read_call(directory / "index.js", "boson_index", 1)
    selected = [entry for entry in entries if entry["seq"] == sequence and entry["level"] == level]
    if len(selected) != 1:
        raise ValueError(f"{directory / 'index.js'}:0: expected one {level} snapshot at sequence {sequence}")
    return load_snapshot(directory, selected[0])[2]


def word_index(graph):
    nodes = graph["nodes"]
    provenance = graph["provenance"]
    if len(provenance["uid"]) != len(nodes["kind"]):
        raise ValueError("word snapshot UID and node columns have different lengths")
    words = {}
    for node, uid in enumerate(provenance["uid"]):
        words.setdefault(uid, []).append({
            "id": node, "kind": lookup(graph["kinds"], nodes["kind"][node])["name"],
            "width": lookup(nodes["width"], node), "detail": lookup(nodes["detail"], node),
        })
    return words


def join_path(mapped, words, path):
    names = mapped["nodes"]["name"]
    if len(set(names)) != len(names):
        raise ValueError("mapped snapshot has duplicate cell names")
    cells = {name: node for node, name in enumerate(names)}
    provenance = mapped["provenance"]
    rows = []
    for point in path["points"]:
        literal = point["point"]
        if "/" not in literal or not point.get("increment_ns"):
            continue
        cell, _ = literal.rsplit("/", 1)
        if cell not in cells:
            raise ValueError(f"timing point {literal!r} has no mapped snapshot cell")
        node = cells[cell]
        record_id = lookup(provenance["node"], node)
        record = {} if record_id == -1 else lookup(provenance["records"], record_id)
        rows.append({
            "point": literal, "cell": cell,
            "cell_type": lookup(mapped["kinds"], lookup(mapped["nodes"]["kind"], node))["name"],
            "increment_ps": point["increment_ns"] * 1000,
            "arrival_ps": point["arrival_ns"] * 1000,
            "origins": [lookup(provenance["strings"], origin) for origin in record.get("origins", [])],
            "words": words.get(record.get("uid"), []),
        })
    if not rows:
        raise ValueError("timing path has no nonzero cell-pin increments")
    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    parser.add_argument("--timing", type=Path, required=True)
    parser.add_argument("--mapped-seq", type=int, required=True)
    parser.add_argument("--word-seq", type=int, required=True)
    parser.add_argument("--path-index", type=int, default=0)
    args = parser.parse_args()
    try:
        paths = sorted(filter(usable_slack, json.loads(args.timing.read_text())["paths"]),
                       key=lambda path: path["slack_ns"])
        path = lookup(paths, args.path_index)
        rows = join_path(snapshot(args.directory, args.mapped_seq, "mapped"),
                         word_index(snapshot(args.directory, args.word_seq, "datapath")), path)
        result = {"startpoint": path["startpoint"], "endpoint": path["endpoint"],
                  "slack_ps": path["slack_ns"] * 1000, "cells": rows,
                  "word_matches": sum(bool(row["words"]) for row in rows),
                  "attribution": "UIDs identify origins, not operator boundaries or protected cones; snapshots may omit optimizer metadata."}
        print(json.dumps(result, indent=2))
    except (OSError, KeyError, TypeError, ValueError, IndexError) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
