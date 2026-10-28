#!/usr/bin/env python3
"""Record how a boson-explore skill went, so partcl can improve it: what the agent
had to do off-script, what the skill had no method for, what guidance was wrong,
what inputs or coverage were missing, and whether the question got answered.

    F=<plugin>/feedback/skill_feedback.py
    $F init --skill boson-datapath-audit --question "why is the FMA adder path deep"
    $F add off_script --what "grep'd the netlist for MAJ chains" --why "no per-stage view"
    $F add missing_framework --what "DC netlist was ungrouped; could not label DW cells"
    $F add wrong_guidance --what "step 2 collect.tcl" --error "No path cells collected"
    $F add missing_input --what "no DC report_resources"
    $F coverage provenance=0.99 paired_endpoints=974 [--from-json split.json --pick label_balance,timing.paired]
    $F outcome partly --iterations 3 --note "split inconclusive; microbench pending"
    $F render >> REPORT.md          # the report's closing "Skill feedback" section
    $F share [--map name_map.json]  # skill_feedback.share/: anonymized copy + submit.tcl

Everything stays on this machine. `share` writes an anonymized copy and a Tcl file
that sends it with boson's `report_feedback` only when the user sources it.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import hmac
import json
import os
import re
import secrets
import subprocess
import sys
from pathlib import Path

SCHEMA = 1
KINDS = {
    "off_script": "Off-script actions",
    "missing_framework": "Missing framework",
    "wrong_guidance": "Guidance that was wrong or misleading",
    "missing_input": "Missing inputs or coverage gaps",
}
PLUGIN = Path(__file__).resolve().parents[1]
ANONYMIZER = PLUGIN / "skills" / "boson-netlist-debug" / "scripts" / "anonymize.py"
MAX_MESSAGE = 3800  # boson report_feedback caps the message at ~4 KB


def plugin_version() -> str:
    try:
        v = json.loads((PLUGIN / ".claude-plugin" / "plugin.json").read_text()).get("version", "?")
    except (OSError, ValueError):
        v = "?"
    try:
        sha = subprocess.run(["git", "-C", str(PLUGIN), "rev-parse", "--short", "HEAD"],
                             capture_output=True, text=True, timeout=10).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        sha = ""
    return f"{v}+{sha}" if sha else v


def load(path: Path) -> dict:
    if not path.exists():
        raise SystemExit(f"{path} not found; run `init` first")
    return json.loads(path.read_text())


def save(path: Path, fb: dict) -> None:
    fb["updated"] = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    path.write_text(json.dumps(fb, indent=1) + "\n")


def parse_value(v: str):
    for cast in (int, float):
        try:
            return cast(v)
        except ValueError:
            pass
    return {"yes": True, "true": True, "no": False, "false": False}.get(v.lower(), v)


def pick(obj, dotted: str):
    for part in dotted.split("."):
        if isinstance(obj, dict) and part in obj:
            obj = obj[part]
        elif isinstance(obj, list) and part.isdigit() and int(part) < len(obj):
            obj = obj[int(part)]
        else:
            return None
    return obj if not isinstance(obj, (dict, list)) else json.dumps(obj)[:200]


def render(fb: dict) -> str:
    o = ["## Skill feedback", "",
         f"Skill `{fb['skill']}` (plugin {fb['plugin_version']}). Question: {fb.get('question') or '-'}", ""]
    for i, (kind, title) in enumerate(KINDS.items(), 1):
        o.append(f"{i}. **{title}**")
        items = fb["items"].get(kind, [])
        if kind == "missing_input" and fb.get("coverage"):
            o.append("   - coverage: " + ", ".join(f"{k}={v}" for k, v in fb["coverage"].items()))
        if not items and not (kind == "missing_input" and fb.get("coverage")):
            o.append("   - none")
        for it in items:
            extra = "; ".join(f"{k}: {it[k]}" for k in ("why", "error") if it.get(k))
            o.append(f"   - {it['what']}" + (f" ({extra})" if extra else ""))
    out = fb.get("outcome") or {}
    o.append(f"5. **Outcome**: answered {out.get('answered', 'not recorded')}"
             + (f", {out['iterations']} iteration(s)" if out.get("iterations") is not None else "")
             + (f". {out['note']}" if out.get("note") else ""))
    o.append("")
    o.append("_Stored in skill_feedback.json on this machine. `skill_feedback.py share` writes an anonymized "
             "copy; nothing is sent unless you source the generated report_feedback script in boson._")
    return "\n".join(o)


# ---- anonymization ---------------------------------------------------------------
FREE_TEXT = ("question", "what", "why", "error", "note")
PATH_RE = re.compile(r"(?:[A-Za-z]:)?(?:~|\.{1,2})?(?:/[\w.\-+@]+){2,}")
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
HOST_RE = re.compile(r"\b[\w-]+(?:\.[\w-]+){2,}\b")
# identifiers that look like design names: hierarchy, buses, registers, mixed case/underscore
IDENT_RE = re.compile(r"\\?[A-Za-z_][\w$]*(?:[./\\][A-Za-z_][\w$]*|\[\d+(?::\d+)?\])+|\b[A-Za-z_]\w*_\w+\b")
# netlist-debug tokens (u3/c12/r4[7], add_o2, <path3>) are already anonymous
ND_TOKEN = re.compile(r"^(?:(?:top|clk\d+|in\d+|out\d+|io\d+|p\d+|m\d+|u\d+|r\d+|c\d+|w\d+|x\d+|[a-z]+_o\d+)(?:\[\d+(?::\d+)?\])*[/.]?)+$")
KEEP = re.compile(r"^(?:(?:email|path|host|id)_[0-9a-f]{6}|boson[\w-]*|report_\w+|get_\w+|set_\w+|compile_\w+|read_\w+|write_\w+|link_design|update_timing)$")


def plugin_vocabulary() -> set:
    """Identifiers the plugin's own skills and scripts use (script names, app variables,
    report fields). A word outside this set is treated as a possible design name."""
    words = set()
    for f in list(PLUGIN.glob("skills/*/SKILL.md")) + list(PLUGIN.glob("skills/*/scripts/*")) + \
            list(PLUGIN.glob("skills/*/references/*")) + [Path(__file__)]:
        try:
            words.update(re.findall(r"[A-Za-z_][\w.]*", f.read_text(errors="ignore")))
        except OSError:
            pass
    return words


VOCAB = None


def basic_scrub(text: str, salt: str, mapping: dict) -> str:
    """Paths, emails, hosts and design-like identifiers become salted tokens. Words the
    plugin itself uses (script names, report fields, boson commands) are kept; anything
    else with an underscore, hierarchy or a bus index is treated as a design name."""
    global VOCAB
    if VOCAB is None:
        VOCAB = plugin_vocabulary()

    def tok(kind, s):
        if s not in mapping:
            mapping[s] = f"{kind}_{hmac.new(salt.encode(), s.encode(), hashlib.sha256).hexdigest()[:6]}"
        return mapping[s]
    text = EMAIL_RE.sub(lambda m: tok("email", m.group(0)), text)
    text = PATH_RE.sub(lambda m: tok("path", m.group(0)), text)
    text = HOST_RE.sub(lambda m: m.group(0) if re.match(r"^\d+(\.\d+)+$", m.group(0)) else tok("host", m.group(0)), text)
    return IDENT_RE.sub(lambda m: m.group(0) if KEEP.match(m.group(0)) or ND_TOKEN.match(m.group(0))
                        or m.group(0) in VOCAB
                        else tok("id", m.group(0)), text)


def anonymize(fb: dict, name_map: Path | None, local_map: Path) -> tuple[dict, str]:
    def walk(o, fn):
        if isinstance(o, dict):
            return {k: (fn(v) if k in FREE_TEXT and isinstance(v, str) else walk(v, fn)) for k, v in o.items()}
        if isinstance(o, list):
            return [walk(x, fn) for x in o]
        return o

    method = "basic"
    if name_map and name_map.exists() and ANONYMIZER.exists():
        def encode(text):
            if not text.strip():
                return text
            r = subprocess.run([sys.executable, str(ANONYMIZER), "--map", str(name_map), "--encode", "-"],
                               input=text, capture_output=True, text=True, timeout=120)
            if r.returncode:
                raise SystemExit(f"anonymize.py --encode failed: {r.stderr.strip()}")
            return r.stdout[:-1] if r.stdout.endswith("\n") and not text.endswith("\n") else r.stdout
        fb = walk(fb, encode)
        method = "netlist-debug name map"
    # second pass in both cases: names the map has never seen (a partial netlist, a
    # name typed from memory) still look like design names and are tokenized here
    state = json.loads(local_map.read_text()) if local_map.exists() else {"salt": secrets.token_hex(16), "map": {}}
    fb = walk(fb, lambda s: basic_scrub(s, state["salt"], state["map"]))
    local_map.write_text(json.dumps(state, indent=1))
    os.chmod(local_map, 0o600)
    # coverage keys are ours, values are numbers/flags; drop free-form strings that could leak
    fb["coverage"] = {k: v for k, v in (fb.get("coverage") or {}).items()
                      if isinstance(v, (int, float, bool)) or re.fullmatch(r"[\w.%/+-]{1,24}", str(v))}
    fb["anonymized"] = method
    return fb, method


def compact(fb: dict) -> str:
    msg = json.dumps(fb, separators=(",", ":"))
    while len(msg) > MAX_MESSAGE:
        longest = max(((k, i) for k, v in fb["items"].items() for i in range(len(v))),
                      key=lambda ki: len(json.dumps(fb["items"][ki[0]][ki[1]])), default=None)
        if not longest:
            break
        it = fb["items"][longest[0]][longest[1]]
        for k in ("error", "why", "what"):
            if len(it.get(k, "")) > 100:
                it[k] = it[k][:80] + "..."
                break
        else:
            fb["items"][longest[0]].pop(longest[1])
            fb["truncated"] = True
        msg = json.dumps(fb, separators=(",", ":"))
    return msg


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-f", "--file", type=Path, default=Path("skill_feedback.json"))
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("init")
    p.add_argument("--skill", required=True)
    p.add_argument("--question", default="")
    p = sub.add_parser("add")
    p.add_argument("kind", choices=list(KINDS))
    p.add_argument("--what", required=True)
    p.add_argument("--why", default="")
    p.add_argument("--error", default="")
    p = sub.add_parser("coverage")
    p.add_argument("pairs", nargs="*", help="key=value")
    p.add_argument("--from-json", type=Path, help="a skill's JSON output")
    p.add_argument("--pick", default="", help="comma-separated dotted keys to copy from --from-json")
    p = sub.add_parser("outcome")
    p.add_argument("answered", choices=("yes", "partly", "no"))
    p.add_argument("--iterations", type=int)
    p.add_argument("--note", default="")
    sub.add_parser("render")
    p = sub.add_parser("share")
    p.add_argument("--map", type=Path, help="netlist-debug name_map.json (same tokens as a debug bundle)")
    a = ap.parse_args(argv)

    if a.cmd == "init":
        fb = {"schema": SCHEMA, "skill": a.skill, "plugin_version": plugin_version(), "question": a.question,
              "items": {k: [] for k in KINDS}, "coverage": {}, "outcome": None}
        save(a.file, fb)
        print(f"{a.file}: started for {a.skill}")
        return 0
    fb = load(a.file)
    if a.cmd == "add":
        fb["items"].setdefault(a.kind, []).append({k: v for k, v in (("what", a.what), ("why", a.why), ("error", a.error)) if v})
    elif a.cmd == "coverage":
        for kv in a.pairs:
            k, _, v = kv.partition("=")
            fb["coverage"][k] = parse_value(v)
        if a.from_json:
            data = json.loads(a.from_json.read_text())
            for key in filter(None, a.pick.split(",")):
                fb["coverage"][key] = pick(data, key)
    elif a.cmd == "outcome":
        fb["outcome"] = {"answered": a.answered, "iterations": a.iterations, "note": a.note}
    elif a.cmd == "render":
        print(render(fb))
        return 0
    elif a.cmd == "share":
        if not fb.get("outcome"):
            print("record the outcome first: skill_feedback.py outcome yes|partly|no", file=sys.stderr)
            return 1
        base = a.file.with_suffix("")
        anon, method = anonymize(json.loads(json.dumps(fb)), a.map, base.with_name(base.name + ".map.json"))
        msg = compact(anon)
        share = base.with_name(base.name + ".share")
        share.mkdir(exist_ok=True)
        out = share / "skill_feedback.anon.json"
        out.write_text(msg + "\n")
        if a.map and a.map.exists() and ANONYMIZER.exists():
            r = subprocess.run([sys.executable, str(ANONYMIZER), "--map", str(a.map), "--check", str(share)],
                               capture_output=True, text=True, timeout=120)
            if r.returncode:
                print(f"leak check failed on {share}; do not send. Edit the feedback and rerun share.\n{r.stdout}{r.stderr}",
                      file=sys.stderr)
                return 1
        tcl = share / "submit.tcl"
        tcl.write_text(
            "# Sends the anonymized skill feedback to partcl. Source in boson only if you agree to send it.\n"
            f"set fh [open [file join [file dirname [info script]] {out.name}]]\n"
            "set msg [string trim [read $fh]]\nclose $fh\n"
            f"report_feedback -category docs -message $msg -context \"skill={anon['skill']} plugin={anon['plugin_version']}\"\n")
        print(f"anonymized ({method}) -> {out}\n{msg}\n")
        print(f"To send it to partcl, the user sources {tcl} in boson (report_feedback prints the payload "
              "and asks before sending). Nothing has been sent.")
        if method == "basic":
            print("note: basic scrub only; with boson-netlist-debug installed, pass --map name_map.json so the "
                  "tokens match a debug bundle and the leak check runs.")
        return 0
    save(a.file, fb)
    return 0


if __name__ == "__main__":
    sys.exit(main())
