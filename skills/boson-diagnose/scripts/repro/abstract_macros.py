#!/usr/bin/env python3
import argparse
import hashlib
import json
import os
from pathlib import Path
import tempfile


def cut_macros(design, top):
    module = design["modules"][top]
    ports = module["ports"]
    signature = []
    for instance, cell in sorted(list(module["cells"].items())):
        definition = design["modules"].get(cell["type"])
        if not definition or not str(definition.get("attributes", {}).get("blackbox", "0")).endswith("1"):
            continue
        pins = []
        for pin, bits in sorted(cell["connections"].items()):
            if not bits:
                continue
            direction = definition["ports"][pin]["direction"]
            if direction not in ("input", "output"):
                raise ValueError(f"unsupported direction at {instance}/{pin}: {direction}")
            if direction == "output" and any(type(bit) is not int for bit in bits):
                raise ValueError(f"macro output {instance}/{pin} has no wire")
            name = "macro_" + hashlib.sha256((instance + "\0" + pin).encode()).hexdigest()[:24]
            if name in ports:
                raise ValueError(f"abstraction port already exists: {name}")
            ports[name] = {"direction": "input" if direction == "output" else "output", "bits": bits}
            pins.append([pin, direction, len(bits), name])
        signature.append([instance, cell["type"], pins])
        del module["cells"][instance]
    if not signature:
        raise ValueError("no declared blackbox instances to abstract")
    design["modules"] = {top: module}
    return signature


def main():
    parser = argparse.ArgumentParser(description="Cut matching Yosys blackboxes into common inputs and observed outputs.")
    parser.add_argument("original", type=Path)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--top", required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error(f"output already exists: {args.output}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".macro-cut-", dir=args.output.parent) as scratch:
        previous = None
        for label, path in [("original", args.original), ("candidate", args.candidate)]:
            with path.open() as source:
                design = json.load(source)
            signature = cut_macros(design, args.top)
            if previous is not None and signature != previous:
                raise ValueError("blackbox instances, types or connected port signatures differ")
            previous = signature
            with (Path(scratch) / f"{label}.json").open("w") as output:
                json.dump(design, output)
            del design
        manifest = {"top": args.top, "instances": len(previous), "ports": sum(len(pins) for _, _, pins in previous), "signature": previous}
        (Path(scratch) / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        os.rename(scratch, args.output)
    print(json.dumps({"output": str(args.output), "instances": manifest["instances"], "ports": manifest["ports"]}))


if __name__ == "__main__":
    main()
