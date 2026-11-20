from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
import json
import sys
from pathlib import Path


def read_call(path, name, count):
    text = path.read_text()
    prefix = name + "("
    if not text.startswith(prefix):
        raise ValueError(f"{path}:0: expected {prefix}")
    decoder = json.JSONDecoder()
    offset = len(prefix)
    arguments = []
    for index in range(count):
        while offset < len(text) and text[offset].isspace():
            offset += 1
        try:
            value, offset = decoder.raw_decode(text, offset)
        except json.JSONDecodeError as error:
            raise ValueError(f"{path}:{error.pos}: {error.msg}") from error
        arguments.append(value)
        while offset < len(text) and text[offset].isspace():
            offset += 1
        if index + 1 < count:
            if text[offset:offset + 1] != ",":
                raise ValueError(f"{path}:{offset}: expected argument separator")
            offset += 1
    if text[offset:].strip() != ");":
        raise ValueError(f"{path}:{offset}: expected end of snapshot call")
    return arguments


def trace(directory, origins, level="datapath"):
    entries, = read_call(directory / "index.js", "boson_index", 1)
    previous = None
    rows = []
    matched = 0
    for entry in entries:
        if entry["level"] != level:
            continue
        path, sequence, graph = load_snapshot(directory, entry)
        try:
            nodes = matching_nodes(graph, origins)
        except (KeyError, IndexError, TypeError, ValueError) as error:
            raise ValueError(f"{path}:0: invalid node/provenance columns: {error}") from error
        matched += len(nodes)
        properties = [{key: value for key, value in node.items() if key != "id"}
                      for node in nodes]
        if properties != previous:
            rows.append({"seq": sequence, "stage": entry["stage"],
                         "file": entry["file"], "nodes": nodes})
        previous = properties
    if not matched:
        raise ValueError(f"{directory / 'index.js'}:0: no provenance nodes match the requested origins")
    return rows


def load_snapshot(directory, entry):
    relative = Path(entry["file"])
    path = directory / relative
    if relative.is_absolute() or ".." in relative.parts or not path.resolve().is_relative_to(directory.resolve()):
        raise ValueError(f"{directory / 'index.js'}:0: stage path escapes archive")
    sequence, graph = read_call(path, "boson_snapshot", 2)
    if type(sequence) is not int or type(entry["seq"]) is not int or sequence < 0 or sequence != entry["seq"]:
        raise ValueError(f"{path}:0: snapshot sequence differs from index")
    return path, sequence, graph


def summarize(rows):
    summaries = []
    previous = None
    for row in rows:
        counts = Counter((node["kind"], node["width"]) for node in row["nodes"])
        if counts != previous:
            summaries.append({"seq": row["seq"], "stage": row["stage"], "file": row["file"],
                              "operators": [{"kind": kind, "width": width, "count": count}
                                            for (kind, width), count in sorted(counts.items())]})
        previous = counts
    return summaries


@dataclass(frozen=True)
class ConeQuery:
    name: str
    stage: str | None = None
    sequence: int | None = None
    level: str = "datapath_compiler"
    kind: str | None = None


def fanin(directory, query):
    entries, = read_call(directory / "index.js", "boson_index", 1)
    selected = [entry for entry in entries
                if entry["level"] == query.level and entry.get("main") is True and entry.get("probe") is False
                and (query.stage is None or entry["stage"] == query.stage)
                and (query.sequence is None or entry["seq"] == query.sequence)]
    if len(selected) != 1:
        sequences = [entry["seq"] for entry in selected]
        raise ValueError(f"{directory / 'index.js'}:0: expected one main snapshot; matching sequences {sequences}; select --seq")
    entry, = selected
    path, sequence, graph = load_snapshot(directory, entry)
    try:
        nodes = graph["nodes"]
        count = len(nodes["kind"])
        if any(len(nodes[key]) != count for key in ("width", "name")):
            raise ValueError("node columns have different lengths")
        kinds = [lookup(graph["kinds"], index) for index in nodes["kind"]]
        if any(not isinstance(kind["name"], str) or not isinstance(kind["class"], str) for kind in kinds):
            raise ValueError("kind names and classes must be strings")
        if any(not isinstance(name, str) for name in nodes["name"]):
            raise ValueError("node names must be strings")
        if any(type(width) is not int or width < 0 for width in nodes["width"]):
            raise ValueError("node widths must be nonnegative integers")
        edges = graph["edges"]
        if len(edges["src"]) != len(edges["dst"]):
            raise ValueError("edge columns have different lengths")
        operands = [[] for _ in range(count)]
        for source, target in zip(edges["src"], edges["dst"]):
            lookup(kinds, source)
            lookup(kinds, target)
            operands[target].append(source)
        roots = [node for node, name in enumerate(nodes["name"])
                 if name == query.name and (query.kind is None or kinds[node]["name"] == query.kind)]
        if len(roots) != 1:
            raise ValueError(f"expected one literal node-name match; got {roots}; select --kind")
        visited = set()
        pending = roots[:]
        cuts = {"input", "register", "memory", "blackbox"}
        while pending:
            node = pending.pop()
            if node in visited:
                continue
            visited.add(node)
            if kinds[node]["class"] not in cuts:
                pending.extend(operands[node])
        rows = [{"id": node, "kind": kinds[node]["name"], "name": nodes["name"][node],
                 "width": nodes["width"][node], "cut": kinds[node]["class"] in cuts,
                 "inputs": [] if kinds[node]["class"] in cuts else operands[node]}
                for node in sorted(visited)]
    except (KeyError, IndexError, TypeError, ValueError) as error:
        raise ValueError(f"{path}:0: invalid fanin graph: {error}") from error
    return {"seq": sequence, "stage": entry["stage"], "file": entry["file"], "root": roots[0],
            "node_count": len(rows), "bit_count": sum(row["width"] for row in rows),
            "kinds": dict(sorted(Counter(row["kind"] for row in rows).items())), "nodes": rows}


def matching_nodes(graph, origins):
    columns = graph["nodes"]
    provenance = graph["provenance"]
    count = len(columns["kind"])
    for column in [columns["width"], columns["detail"], provenance["node"]]:
        if len(column) != count:
            raise ValueError("node and provenance columns have different lengths")
    selected = []
    for node, record in enumerate(provenance["node"]):
        if record is None or (type(record) is int and record == -1):
            continue
        labels = [lookup(provenance["strings"], index)
                  for index in lookup(provenance["records"], record)["origins"]]
        if any(query in label for query in origins for label in labels):
            selected.append({"id": node, "kind": lookup(graph["kinds"], columns["kind"][node])["name"],
                             "width": columns["width"][node], "detail": columns["detail"][node],
                             "origins": labels})
    return selected


def lookup(column, index):
    if type(index) is not int or not 0 <= index < len(column):
        raise ValueError(f"invalid column index {index!r}")
    return column[index]


def main():
    parser = argparse.ArgumentParser(description="Trace recorded word-level node properties by RTL origin across an archived snapshot series.")
    parser.add_argument("directory", type=Path)
    root = parser.add_mutually_exclusive_group(required=True)
    root.add_argument("--origin", action="append", help="literal substring of an RTL-origin label")
    root.add_argument("--node-name", help="literal signal name for a combinational fanin cone")
    parser.add_argument("--level", help="snapshot level; defaults to datapath for origins, datapath_compiler for cones")
    parser.add_argument("--stage", help="pass name for a cone; repeated passes require --seq")
    parser.add_argument("--seq", type=int, help="exact snapshot sequence for a cone")
    parser.add_argument("--kind", help="disambiguate identical node names by operator kind")
    parser.add_argument("--summary", action="store_true", help="report changes in origin-matched operator counts and widths")
    args = parser.parse_args()
    if args.node_name is not None and args.stage is None and args.seq is None:
        parser.error("--node-name needs --stage or --seq")
    if args.origin is not None and any(value is not None for value in (args.stage, args.seq, args.kind)):
        parser.error("--stage, --seq and --kind require --node-name")
    if args.summary and args.origin is None:
        parser.error("--summary requires --origin")
    try:
        if args.node_name is not None:
            rows = fanin(args.directory, ConeQuery(args.node_name, args.stage, args.seq,
                         args.level or "datapath_compiler", args.kind))
        else:
            rows = trace(args.directory, args.origin, args.level or "datapath")
            if args.summary:
                rows = summarize(rows)
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(2, f"{error}\n")
    json.dump(rows, sys.stdout, indent=2)
    print()


if __name__ == "__main__":
    main()
