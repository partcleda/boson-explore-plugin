import argparse
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


def trace(directory, origins):
    entries, = read_call(directory / "index.js", "boson_index", 1)
    previous = None
    rows = []
    matched = 0
    for entry in entries:
        if entry["level"] != "datapath":
            continue
        relative = Path(entry["file"])
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"{directory / 'index.js'}:0: stage path escapes archive")
        path = directory / relative
        sequence, graph = read_call(path, "boson_snapshot", 2)
        if sequence != entry["seq"]:
            raise ValueError(f"{path}:0: snapshot sequence differs from index")
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


def matching_nodes(graph, origins):
    columns = graph["nodes"]
    provenance = graph["provenance"]
    count = len(columns["kind"])
    for column in [columns["width"], columns["detail"], provenance["node"]]:
        if len(column) != count:
            raise ValueError("node and provenance columns have different lengths")
    selected = []
    for node, record in enumerate(provenance["node"]):
        if record is None:
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
    parser.add_argument("--origin", action="append", required=True,
                        help="literal substring of an origin label; repeat to match several locations")
    args = parser.parse_args()
    try:
        rows = trace(args.directory, args.origin)
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(2, f"{error}\n")
    json.dump(rows, sys.stdout, indent=2)
    print()


if __name__ == "__main__":
    main()
