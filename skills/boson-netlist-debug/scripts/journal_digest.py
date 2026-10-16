#!/usr/bin/env python3
"""Stream a boson decision journal (decision_log_file, schema 1) and summarise
what boson decided, where QoR moved, and which decisions look suspicious.

    journal_digest.py anon/decisions.jsonl [--timing anon/timing_1.rpt] [--timing-json anon/timing_1.json] \\
        [--top 15] [--out-md journal_digest.md] [--out-json journal_digest.json]

Run it on the ANONYMIZED journal.  Streams: memory is bounded by the number
of distinct subjects, not by the journal length.  Unknown kinds, domains,
actions and metrics are handled generically.  See
../references/journal-schema.md for the record format.

Flags it raises (each with journal seq numbers):
- stage checkpoints that lost WNS/TNS or grew area without a WNS gain
- shipped decisions with the worst negative impact (WNS/TNS/slack down,
  area/power up with no timing gain)
- decisions with a rolled-back or rejected outcome, and setup/hold repairs
  that kept the original design
- flip-flopping: the same subject+action changing its choice back and forth,
  or repeatedly acted on with no net gain (e.g. upsize, upsize, downsize)
- a rejected alternative whose own metrics beat the chosen option on timing
- hold repair on paths with small or negative setup margin
- decisions touching objects on the reported critical paths
- probe (what-if) decisions vs shipped, and probe wins that never shipped
- warnings/errors grouped by message ID
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _bdlib import better_direction, fmt, md_table, num, open_text  # noqa: E402

EPS = 1e-6
TIMING_KEYS = ("wns_ns", "tns_ns", "slack_ns", "setup_slack_ns", "worst_slack_ns")
ROLLBACK_RE = re.compile(r"roll(?:ed)?[_ ]?back|revert|undo|keep_original|kept the design as it was|discard", re.I)


def _impact_score(impact: dict) -> tuple[float, dict]:
    """Timing delta in 'goodness' units (positive = better); falls back to any metric."""
    deltas = {}
    for k, v in (impact or {}).items():
        if isinstance(v, dict):
            d = num(v.get("delta"))
            if d is None and num(v.get("after")) is not None and num(v.get("before")) is not None:
                d = num(v["after"]) - num(v["before"])
        else:
            d = num(v)
        if d is not None:
            deltas[k] = d
    t = None
    for k in TIMING_KEYS:
        if k in deltas:
            t = deltas[k] * better_direction(k)
            break
    if t is None:
        for k, d in deltas.items():
            if better_direction(k) == 1:
                t = d
                break
    return (t if t is not None else 0.0), deltas


def _alt_beats_chosen(rec: dict) -> list[dict]:
    """Rejected alternatives whose metrics are better on timing than the chosen option's."""
    alts = rec.get("alternatives") or []
    chosen = rec.get("chosen")
    cm = None
    for a in alts:
        if isinstance(a, dict) and (a.get("verdict") == "chosen" or (chosen is not None and a.get("option") == chosen)):
            cm = a.get("metrics") or {}
    if not cm:
        return []
    out = []
    for a in alts:
        if not isinstance(a, dict) or a.get("verdict") not in ("rejected", "skipped"):
            continue
        am = a.get("metrics") or {}
        for k in list(am):
            dirn = better_direction(k)
            if k.startswith(("wns", "tns", "slack", "delay", "arrival", "fmax")) and dirn:
                av, cv = num(am.get(k)), num(cm.get(k))
                if av is not None and cv is not None and (av - cv) * dirn > EPS:
                    out.append({"option": a.get("option"), "metric": k, "alternative": av, "chosen": cv,
                                "why": a.get("why")})
                    break
    return out


def load_critical(text_files, json_files) -> dict:
    """objects on reported paths -> path ids (P1.. by slack order, as timing_digest numbers them)."""
    try:
        import timing_digest as td
    except ImportError:
        return {}
    d = td.digest(text_files, json_files, [], [], None)
    obj = defaultdict(set)
    for a in d["paths"]:
        for o in a["objects"]:
            obj[o].add(a["id"])
            obj[re.sub(r"/[^/]+$", "", o)].add(a["id"]) if "/" in o else None
    return {"objects": obj, "paths": {a["id"]: {"slack_ns": a["slack_ns"], "start": a["startpoint"], "end": a["endpoint"]}
                                       for a in d["paths"]}}


def _touches(subject: str, crit: dict) -> set:
    objs = crit.get("objects") or {}
    hits = set(objs.get(subject, set()))
    s = subject.rstrip("/")
    if not hits:
        # operator subjects (u1/add_o3) own cells named u1/add_o3_gs12 etc.
        for o, ids in objs.items():
            if o.startswith(s + "_") or o.startswith(s + "/"):
                hits |= ids
    return hits


CAP = 2000             # examples kept per finding list (counts are exact)
MAX_SUBJECTS = 300_000  # distinct (subject, action family) histories tracked for flip-flop detection
_tie = [0]


def _keep(heap: list, item: dict, key: float, n: int = 200) -> None:
    """Bounded best-n by ascending key (most negative = most interesting)."""
    import heapq
    _tie[0] += 1
    entry = (-key, _tie[0], item)          # max-heap on key via negation: evict the least interesting
    if len(heap) < n:
        heapq.heappush(heap, entry)
    elif entry[0] < heap[0][0]:
        pass
    else:
        heapq.heapreplace(heap, entry)


def digest(path: Path, crit: dict, top: int = 15) -> dict:
    header, compile_end, summary = None, None, None
    checkpoints, worst, rolled, alt_better, hold_flags, crit_hits, probe_wins = [], [], [], [], [], [], []
    counts = Counter()
    counts_probe = Counter()
    per_stage = defaultdict(lambda: {"decisions": 0, "t_first": None, "t_last": None})
    subj_hist: dict = {}  # (subject, domain/action family) -> [(seq, action, chosen, score)]
    n_worst = n_rolled = n_alt = n_hold = n_crit = n_probe = subjects_untracked = 0
    messages = defaultdict(lambda: {"count": 0, "severity": None, "examples": []})
    kinds = Counter()
    progress_tail = []
    n_lines = bad_lines = 0
    with open_text(path) as f:
        for line in f:
            n_lines += 1
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                bad_lines += 1
                continue
            if not isinstance(r, dict):
                bad_lines += 1
                continue
            k = r.get("kind", "?")
            kinds[k] += 1
            if k == "header":
                header = r
            elif k == "compile_end":
                compile_end = r
            elif k == "summary":
                summary = r
            elif k == "checkpoint":
                checkpoints.append({"seq": r.get("seq"), "t_s": r.get("t_s"), "stage": r.get("stage"),
                                    "label": r.get("label"), "metrics": r.get("metrics") or {}})
            elif k == "progress":
                progress_tail.append(r.get("text"))
                progress_tail = progress_tail[-15:]
            elif k == "message":
                m = messages[r.get("id") or "?"]
                m["count"] += 1
                m["severity"] = r.get("severity")
                if len(m["examples"]) < 3:
                    m["examples"].append({"seq": r.get("seq"), "text": r.get("text")})
            elif k == "decision":
                dom, act = r.get("domain", "?"), r.get("action", "?")
                key = f"{dom}/{act}"
                probe = bool(r.get("probe"))
                (counts_probe if probe else counts)[key] += 1
                st = per_stage[r.get("stage") or "?"]
                st["decisions"] += 1
                t = num(r.get("t_s"))
                st["t_first"] = t if st["t_first"] is None else st["t_first"]
                st["t_last"] = t if t is not None else st["t_last"]
                score, deltas = _impact_score(r.get("impact") or {})
                brief = {"seq": r.get("seq"), "stage": r.get("stage"), "pass": r.get("pass"), "key": key,
                         "subjects": (r.get("subjects") or [])[:5], "n_subjects": len(r.get("subjects") or []),
                         "chosen": r.get("chosen"), "reason": r.get("reason"), "deltas": deltas, "score": score,
                         "inputs": r.get("inputs"), "probe": probe}
                if probe:
                    if score > EPS:
                        _keep(probe_wins, brief, -score)
                        n_probe += 1
                    continue
                area_d = next((v for kk, v in deltas.items() if kk.startswith(("area", "power"))), None)
                if score < -EPS or (area_d is not None and area_d > EPS and score <= EPS and any(
                        kk in deltas for kk in TIMING_KEYS)):
                    _keep(worst, brief, score)
                    n_worst += 1
                txt = " ".join(str(x) for x in (r.get("chosen"), r.get("reason"), act) if x)
                if ROLLBACK_RE.search(txt) or any(isinstance(a, dict) and a.get("verdict") == "rolled_back"
                                                  for a in r.get("alternatives") or []):
                    b = dict(brief)
                    b["alternatives"] = [{"option": a.get("option"), "verdict": a.get("verdict"), "why": a.get("why"),
                                          "metrics": a.get("metrics")} for a in r.get("alternatives") or [] if isinstance(a, dict)]
                    if len(rolled) < CAP:
                        rolled.append(b)
                    n_rolled += 1
                ab = _alt_beats_chosen(r)
                if ab:
                    b = dict(brief)
                    b["better_alternatives"] = ab
                    if len(alt_better) < CAP:
                        alt_better.append(b)
                    n_alt += 1
                if dom == "hold_repair":
                    inp = r.get("inputs") or {}
                    sm = next((num(v) for kk, v in inp.items() if "setup" in kk and num(v) is not None), None)
                    if score < -EPS or (sm is not None and sm < 0.05):
                        b = dict(brief)
                        b["setup_margin_ns"] = sm
                        if len(hold_flags) < CAP:
                            hold_flags.append(b)
                        n_hold += 1
                family = re.sub(r"^(up|down)", "", act) if dom in ("sizing", "vt") else act
                for s in r.get("subjects") or []:
                    if isinstance(s, str):
                        hk = (s, f"{dom}/{family}")
                        hist = subj_hist.get(hk)
                        if hist is None and len(subj_hist) < MAX_SUBJECTS:
                            hist = subj_hist[hk] = []
                        elif hist is None:
                            subjects_untracked += 1
                        if hist is not None and len(hist) < 64:
                            hist.append((r.get("seq"), act, r.get("chosen"), score))
                        if crit:
                            hits = _touches(s, crit)
                            if hits:
                                b = dict(brief)
                                b["paths"] = sorted(hits)
                                if len(crit_hits) < CAP:
                                    crit_hits.append(b)
                                n_crit += 1
    flips = []
    for (s, fam), h in subj_hist.items():
        if len(h) < 2:
            continue
        choices = [c for _, _, c, _ in h]
        acts = [a for _, a, _, _ in h]
        reverted = any(choices[i] in choices[:i - 1] for i in range(2, len(choices)) if choices[i] is not None)
        direction_flip = len(set(acts)) > 1 and any(a.startswith("up") for a in acts) and any(a.startswith("down") for a in acts)
        net = sum(sc for *_, sc in h)
        if reverted or direction_flip or (len(h) >= 3 and net <= EPS):
            flips.append({"subject": s, "family": fam, "n": len(h), "seqs": [q for q, *_ in h][:12],
                          "actions": acts[:12], "choices": choices[:12], "net_timing_gain": net,
                          "pattern": "reverted to an earlier choice" if reverted else (
                              "up/down oscillation" if direction_flip else "repeated with no net gain")})
    flips.sort(key=lambda x: (-x["n"], x["net_timing_gain"]))
    worst = [b for _, _, b in sorted(worst, key=lambda t: -t[0])]
    probe_wins = [b for _, _, b in sorted(probe_wins, key=lambda t: -t[0])]
    # checkpoint deltas
    cp_rows = []
    prev = None
    for c in checkpoints:
        m = c["metrics"]
        row = {"seq": c["seq"], "t_s": c["t_s"], "stage": c["stage"], "label": c["label"],
               **{k: (v if isinstance(v, int) and not isinstance(v, bool) else num(v)) for k, v in m.items()}}
        if prev:
            for k, v in m.items():
                a, b = num(v), num(prev["metrics"].get(k))
                if a is not None and b is not None:
                    row[f"d_{k}"] = a - b
        flags = []
        if row.get("d_wns_ns") is not None and row["d_wns_ns"] < -EPS:
            flags.append("WNS lost")
        if row.get("d_tns_ns") is not None and row["d_tns_ns"] < -EPS:
            flags.append("TNS lost")
        if row.get("d_area_um2") is not None and row["d_area_um2"] > EPS and (row.get("d_wns_ns") or 0) <= EPS:
            flags.append("area up, no WNS gain")
        if row.get("d_violating_endpoints") is not None and row["d_violating_endpoints"] > 0:
            flags.append("more violating endpoints")
        row["flags"] = flags
        cp_rows.append(row)
        prev = c
    msgs = sorted(({"id": k, **v} for k, v in messages.items()),
                  key=lambda m: ({"error": 0, "warning": 1}.get(str(m["severity"]).lower(), 2), -m["count"]))
    return {
        "lines": n_lines, "unparsed_lines": bad_lines, "kinds": dict(kinds),
        "complete": compile_end is not None, "closed": summary is not None,
        "header": {k: header.get(k) for k in ("schema", "tool", "version", "app_vars")} if header else None,
        "compile": {"elapsed_s": compile_end.get("elapsed_s"), "counts": compile_end.get("counts")} if compile_end else None,
        "counts_shipped": dict(counts.most_common()), "counts_probe": dict(counts_probe.most_common()),
        "stages": {k: v for k, v in per_stage.items()},
        "checkpoints": cp_rows,
        "worst_decisions": worst[:top], "n_worst": n_worst,
        "rolled_back": rolled[:top], "n_rolled_back": n_rolled,
        "alternative_beat_chosen": alt_better[:top], "n_alternative_beat_chosen": n_alt,
        "hold_on_tight_setup": hold_flags[:top], "n_hold_on_tight_setup": n_hold,
        "flip_flops": flips[:top], "n_flip_flops": len(flips), "subject_decisions_untracked": subjects_untracked,
        "critical_path_decisions": crit_hits[: top * 3], "n_critical_path_decisions": n_crit,
        "critical_paths": (crit or {}).get("paths"),
        "probe_wins_not_shipped": probe_wins[:top], "n_probe_wins": n_probe,
        "messages": msgs, "progress_tail": progress_tail,
    }


def _subj(b):
    s = ", ".join(f"`{x}`" for x in b["subjects"])
    return s + (f" (+{b['n_subjects'] - len(b['subjects'])})" if b["n_subjects"] > len(b["subjects"]) else "")


def _d(b):
    return ", ".join(f"{k} {v:+.4g}" for k, v in b["deltas"].items()) or "–"


def to_md(d: dict) -> str:
    o = ["# Decision journal digest", ""]
    h = d["header"] or {}
    o.append(f"- boson {h.get('version', '?')}, journal schema {h.get('schema', '?')}; {d['lines']:,} lines "
             f"({', '.join(f'{k} {v:,}' for k, v in sorted(d['kinds'].items()))}); unparsed {d['unparsed_lines']}")
    o.append(f"- compile_end present: {d['complete']} (absent = the run was killed or is still running; "
             f"summary record present: {d['closed']})")
    if d["compile"]:
        o.append(f"- compile elapsed: {fmt(d['compile']['elapsed_s'])} s")
    if h.get("app_vars"):
        o.append("- app var overrides: " + ", ".join(f"`{k}={v}`" for k, v in h["app_vars"].items()))
    o.append("")
    o.append("## Stage-by-stage QoR (checkpoints)")
    cols = ["wns_ns", "tns_ns", "area_um2", "cells", "violating_endpoints"]
    o.append(md_table(["seq", "stage / label", *cols, "ΔWNS", "ΔTNS", "Δarea", "flags"],
                      [[r["seq"], f"{r['stage']} / {r['label']}", *[r.get(c) for c in cols], r.get("d_wns_ns"),
                        r.get("d_tns_ns"), r.get("d_area_um2"), ", ".join(r["flags"])] for r in d["checkpoints"]]))
    o.append("## Decision counts (shipped / probe)")
    keys = sorted(set(d["counts_shipped"]) | set(d["counts_probe"]), key=lambda k: -(d["counts_shipped"].get(k, 0) + d["counts_probe"].get(k, 0)))
    o.append(md_table(["domain/action", "shipped", "probe"], [[k, d["counts_shipped"].get(k, 0), d["counts_probe"].get(k, 0)] for k in keys]))
    o.append("## Decisions per stage")
    o.append(md_table(["stage", "decisions", "t first", "t last"],
                      [[k, v["decisions"], v["t_first"], v["t_last"]] for k, v in d["stages"].items()]))
    o.append(f"## Worst-impact shipped decisions ({d['n_worst']} total)")
    o.append(md_table(["seq", "stage", "domain/action", "subjects", "chosen", "impact", "reason"],
                      [[b["seq"], b["stage"] or "", b["key"], _subj(b), str(b["chosen"]), _d(b), b["reason"] or ""] for b in d["worst_decisions"]]))
    o.append(f"## Rolled back / kept original ({d['n_rolled_back']})")
    o.append(md_table(["seq", "domain/action", "subjects", "chosen", "alternatives"],
                      [[b["seq"], b["key"], _subj(b), str(b["chosen"]),
                        "; ".join(f"{a['option']}={a['verdict']} ({a.get('why') or ''})" for a in b["alternatives"])]
                       for b in d["rolled_back"]]))
    o.append(f"## A rejected alternative was better on timing ({d['n_alternative_beat_chosen']})")
    o.append(md_table(["seq", "domain/action", "subjects", "chosen", "better alternative"],
                      [[b["seq"], b["key"], _subj(b), str(b["chosen"]),
                        "; ".join(f"{x['option']}: {x['metric']} {x['alternative']} vs {x['chosen']} ({x.get('why') or ''})" for x in b["better_alternatives"])]
                       for b in d["alternative_beat_chosen"]]))
    o.append(f"## Hold repair on tight setup ({d['n_hold_on_tight_setup']})")
    o.append(md_table(["seq", "action", "subjects", "setup margin", "impact"],
                      [[b["seq"], b["key"], _subj(b), b["setup_margin_ns"], _d(b)] for b in d["hold_on_tight_setup"]]))
    o.append(f"## Flip-flopping / no-gain repetition ({d['n_flip_flops']})")
    o.append(md_table(["subject", "family", "n", "pattern", "seqs", "choices", "net timing gain"],
                      [[f"`{x['subject']}`", x["family"], x["n"], x["pattern"], ",".join(map(str, x["seqs"])),
                        " → ".join(str(c) for c in x["choices"]), x["net_timing_gain"]] for x in d["flip_flops"]]))
    o.append(f"## Decisions on reported critical paths ({d['n_critical_path_decisions']})")
    if d["critical_paths"] is None:
        o.append("_no timing report given (--timing / --timing-json)_\n")
    else:
        o.append(md_table(["seq", "paths", "domain/action", "subjects", "chosen", "impact"],
                          [[b["seq"], ",".join(b["paths"]), b["key"], _subj(b), str(b["chosen"]), _d(b)] for b in d["critical_path_decisions"]]))
    o.append(f"## Probe (what-if) decisions that improved timing ({d['n_probe_wins']}) — not in the shipped netlist")
    o.append(md_table(["seq", "domain/action", "subjects", "chosen", "impact"],
                      [[b["seq"], b["key"], _subj(b), str(b["chosen"]), _d(b)] for b in d["probe_wins_not_shipped"]]))
    o.append("## Messages by ID")
    o.append(md_table(["id", "severity", "count", "examples"],
                      [[m["id"], str(m["severity"]), m["count"], " / ".join(f"[{e['seq']}] {e['text']}" for e in m["examples"])] for m in d["messages"]]))
    if d["progress_tail"]:
        o.append("## Last progress lines")
        o.append("```\n" + "\n".join(str(x) for x in d["progress_tail"]) + "\n```")
    return "\n".join(o)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("journal")
    ap.add_argument("--timing", action="append", default=[])
    ap.add_argument("--timing-json", action="append", default=[])
    ap.add_argument("--top", type=int, default=15)
    ap.add_argument("--out-md"); ap.add_argument("--out-json")
    a = ap.parse_args(argv)
    crit = load_critical(a.timing, a.timing_json) if (a.timing or a.timing_json) else {}
    d = digest(Path(a.journal), crit, a.top)
    md = to_md(d)
    if a.out_md:
        Path(a.out_md).write_text(md)
    else:
        print(md)
    if a.out_json:
        Path(a.out_json).write_text(json.dumps(d, indent=1, default=lambda x: sorted(x) if isinstance(x, set) else str(x)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
