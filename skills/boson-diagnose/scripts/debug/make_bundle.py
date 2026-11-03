#!/usr/bin/env python3
"""Build the shareable boson debug bundle, in two steps.

  1. prepare — anonymize every input and run the digests:
       make_bundle.py --work boson-debug-work --map name_map.json \\
           --netlist run/netlist.v --sdc run/out.sdc --timing run/timing.rpt --timing-json run/timing.json \\
           --qor run/qor.rpt --check-timing run/check_timing.rpt --log run/boson.log --journal run/decisions.jsonl \\
           [--rtl ...] [--liberty ...] [--literal ACME] [--pdk-node "7 nm"]
     (or --run-dir run). Writes boson-debug-work/anon/* and boson-debug-work/digests/*.
     Write REPORT.md from those anonymized files.

  2. bundle — same arguments plus --report REPORT.md:
       make_bundle.py ... --report REPORT.md [--include-netlist] [--journal-max-lines 200000]
     Re-anonymizes (same map, so tokens are stable), copies REPORT.md (passed
     through the anonymizer as a safety net), digests, anonymized reports, SDC,
     log and journal into boson-debug-bundle/, writes environment.json and
     MANIFEST.md, runs `anonymize.py --check` on the directory and on the
     tarball, and only then writes boson-debug-bundle.tar.gz.  Exit 1 if the
     check fails (no tarball is left behind).

Never in the bundle: name_map.json, RTL (harvested for names only), Liberty,
the raw netlist.  The anonymized netlist goes in only with --include-netlist:
it shows partcl the full structure (every cell and connection, under tokens),
which is the most useful debug artifact but also the most revealing about
the design's architecture.  Nothing is uploaded; the customer sends the
tarball themselves.
"""
from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import anonymize as an  # noqa: E402
import journal_digest as jd  # noqa: E402
import netlist_stats as ns  # noqa: E402
import timing_digest as td  # noqa: E402


def parser():
    ap = an.build_parser()
    ap.description = __doc__
    ap.add_argument("--work", type=Path, default=Path("boson-debug-work"))
    ap.add_argument("--bundle-dir", type=Path, default=Path("boson-debug-bundle"))
    ap.add_argument("--report", type=Path, help="REPORT.md (written from the anonymized work files)")
    ap.add_argument("--include-netlist", action="store_true", help="add the ANONYMIZED netlist (see trade-off above)")
    ap.add_argument("--journal-max-lines", type=int, default=200_000)
    ap.add_argument("--pdk-node", default=None, help='library family / node only, e.g. "7 nm" (never the library name)')
    ap.add_argument("--boson-bin", default=os.environ.get("BOSON_BIN", "boson"))
    ap.add_argument("--no-tar", action="store_true")
    return ap


def prepare(a) -> tuple[an.Mapper, dict]:
    anon = a.work / "anon"
    dig = a.work / "digests"
    if a.work.exists() and (a.work / "anon").exists():
        shutil.rmtree(anon)
    dig.mkdir(parents=True, exist_ok=True)
    a.out = anon
    if a.run_dir:
        f = an.discover(a.run_dir)
        print("discovered inputs (confirm these with the user):", file=sys.stderr)
        for k, v in f.items():
            print(f"  {k:13s} {v}", file=sys.stderr)
        a.netlist = a.netlist or (str(f["netlist"]) if f["netlist"] else None)
        a.journal = a.journal or (str(f["journal"]) if f["journal"] else None)
        for k in ("sdc", "timing", "timing_json", "qor", "check_timing", "log", "rtl"):
            if not getattr(a, k):
                setattr(a, k, [str(p) for p in f[k]] or None)
    m = an.Mapper.load(a.map) if a.map.exists() else an.Mapper()
    man = an.anonymize_inputs(a, m, anon)
    m.save(a.map)
    t_txt = [str(anon / x) for x in man.get("timing", [])]
    t_js = [str(anon / x) for x in man.get("timing_json", [])]
    qor = [str(anon / x) for x in man.get("qor", [])]
    ct = [str(anon / x) for x in man.get("check_timing", [])]
    net = str(anon / "netlist.v") if man.get("netlist") else None
    if t_txt or t_js or qor or ct:
        td.main([*sum((["--timing", x] for x in t_txt), []), *sum((["--timing-json", x] for x in t_js), []),
                 *sum((["--qor", x] for x in qor), []), *sum((["--check-timing", x] for x in ct), []),
                 *(["--netlist", net] if net and t_js else []),
                 "--out-md", str(dig / "timing_digest.md"), "--out-json", str(dig / "timing_digest.json")])
    if man.get("journal"):
        jd.main([str(anon / "decisions.jsonl"), *sum((["--timing", x] for x in t_txt), []),
                 *sum((["--timing-json", x] for x in t_js), []),
                 "--out-md", str(dig / "journal_digest.md"), "--out-json", str(dig / "journal_digest.json")])
    if net:
        lib_args = sum((["--liberty", x] for x in (a.liberty or [])), [])
        ns.main([net, *lib_args, *(["--map", str(a.map)] if lib_args else []),
                 "--out-md", str(dig / "netlist_stats.md"), "--out-json", str(dig / "netlist_stats.json")])
    env = environment(a, anon, man)
    (dig / "environment.json").write_text(json.dumps(env, indent=1))
    return m, man


def environment(a, anon: Path, man: dict) -> dict:
    env = {"boson_version": None, "os": platform.system(), "os_release": None, "arch": platform.machine(),
           "cpu_count": os.cpu_count(), "ram_gb": None, "gpus": [], "python": platform.python_version(),
           "library": a.pdk_node or "not stated", "journal_app_vars": None}
    try:
        osr = dict(l.split("=", 1) for l in Path("/etc/os-release").read_text().splitlines() if "=" in l)
        env["os_release"] = f"{osr.get('ID', '').strip(chr(34))} {osr.get('VERSION_ID', '').strip(chr(34))}".strip()
    except OSError:
        pass
    try:
        kb = int(re.search(r"MemTotal:\s+(\d+)", Path("/proc/meminfo").read_text()).group(1))
        env["ram_gb"] = round(kb / 1024 / 1024)
    except (OSError, AttributeError):
        pass
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
                             capture_output=True, text=True, timeout=20).stdout
        env["gpus"] = [l.strip() for l in out.splitlines() if l.strip()]
    except (OSError, subprocess.SubprocessError):
        pass
    if man.get("journal"):
        with open(anon / "decisions.jsonl") as f:
            try:
                h = json.loads(f.readline())
                if h.get("kind") == "header":
                    env["boson_version"] = h.get("version")
                    env["journal_app_vars"] = h.get("app_vars")
            except json.JSONDecodeError:
                pass
    if not env["boson_version"]:
        for x in man.get("log", []):
            mm = re.search(r"boson v?(\d+\.\d+\.\d+(?: \(build \w+\))?)", (anon / x).read_text(errors="replace")[:20000])
            if mm:
                env["boson_version"] = mm.group(1)
                break
    if not env["boson_version"] and shutil.which(a.boson_bin):
        try:
            env["boson_version"] = subprocess.run([a.boson_bin, "--version"], capture_output=True, text=True,
                                                  timeout=30).stdout.strip().splitlines()[0]
        except (OSError, subprocess.SubprocessError, IndexError):
            pass
    return env


STRUCTURAL = ("header", "checkpoint", "compile_begin", "compile_end", "summary")
ALWAYS_DOMAINS = ("recipe", "constraints", "datapath", "clock_gating", "banking", "sequential")


def _decision_priority(r: dict, crit_objs: set) -> float | None:
    """None = drop; inf = always keep; else |timing impact| (larger kept first)."""
    score, _ = jd._impact_score(r.get("impact") or {})
    subj = r.get("subjects") or []
    if (r.get("domain") in ALWAYS_DOMAINS
            or any(isinstance(x, dict) and x.get("verdict") == "rolled_back" for x in r.get("alternatives") or [])
            or any(s in crit_objs or any(c.startswith(s + "_") or c.startswith(s + "/") for c in crit_objs) for s in subj[:20])):
        return float("inf")
    if abs(score) > jd.EPS or any(isinstance(x, dict) and x.get("verdict") == "rejected" for x in r.get("alternatives") or []):
        return abs(score)
    return None


def copy_journal(src: Path, dst: Path, max_lines: int, crit_objs: set) -> dict:
    """Copy the (anonymized) journal; above max_lines keep every structural record, messages (50 per id),
    and the highest-priority decisions, and record what was dropped."""
    n = sum(1 for _ in open(src))
    if n <= max_lines:
        shutil.copy(src, dst)
        return {"lines": n, "kept": n, "truncated": False}
    pr = []
    with open(src) as f:
        for line in f:
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if r.get("kind") == "decision":
                p = _decision_priority(r, crit_objs)
                if p is not None:
                    pr.append(p)
    budget = max(0, max_lines - 10_000)
    pr.sort(reverse=True)
    thr = pr[budget - 1] if 0 < budget <= len(pr) else (0.0 if pr else float("inf"))
    kept, dropped, per_msg, n_dec = 0, Counter(), Counter(), 0
    with open(src) as f, open(dst, "w") as o:
        for line in f:
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                dropped["unparsed"] += 1
                continue
            k = r.get("kind")
            if k in STRUCTURAL:
                keep = True
            elif k == "message":
                per_msg[r.get("id")] += 1
                keep = per_msg[r.get("id")] <= 50
            elif k == "decision":
                p = _decision_priority(r, crit_objs)
                keep = p is not None and p >= thr and n_dec < budget
                n_dec += keep
            else:
                keep = False
            if keep:
                o.write(line)
                kept += 1
            else:
                dropped[f"decision/{r.get('domain')}" if k == "decision" else str(k)] += 1
    return {"lines": n, "kept": kept, "truncated": True, "decision_priority_threshold": thr,
            "rule": "kept: header/checkpoint/compile/summary records; <=50 messages per id; decisions in "
                    f"{', '.join(ALWAYS_DOMAINS)}, rolled-back, or on reported-path objects; then decisions by |timing impact|",
            "dropped": dict(dropped.most_common())}


def bundle(a, m: an.Mapper, man: dict) -> int:
    anon, dig, b = a.work / "anon", a.work / "digests", a.bundle_dir
    if b.exists():
        shutil.rmtree(b)
    for sub in ("digests", "reports", "constraints", "logs", "journal"):
        (b / sub).mkdir(parents=True, exist_ok=True)
    # REPORT.md through the anonymizer (prose mode; backticked names strictly)
    with open(a.report) as f, open(b / "REPORT.md", "w") as o:
        for line in f:
            o.write(m.anon_text(line))
    for p in sorted(dig.iterdir()):
        if p.name != "environment.json":
            shutil.copy(p, b / "digests" / p.name)
    for k in ("timing", "timing_json", "qor", "check_timing"):
        for x in man.get(k, []):
            shutil.copy(anon / x, b / "reports" / x)
    for x in man.get("sdc", []):
        shutil.copy(anon / x, b / "constraints" / x)
    for x in man.get("log", []):
        shutil.copy(anon / x, b / "logs" / x)
    jinfo = None
    if man.get("journal"):
        crit = set()
        tdj = dig / "timing_digest.json"
        if tdj.exists():
            for pth in json.loads(tdj.read_text()).get("paths", []):
                crit.update(pth.get("objects", []))
        jinfo = copy_journal(anon / "decisions.jsonl", b / "journal" / "decisions.jsonl", a.journal_max_lines, crit)
        (b / "journal" / "truncation.json").write_text(json.dumps(jinfo, indent=1))
    else:
        shutil.rmtree(b / "journal")
    if a.include_netlist and man.get("netlist"):
        (b / "netlist").mkdir()
        shutil.copy(anon / "netlist.v", b / "netlist" / "netlist.v")
    shutil.copy(dig / "environment.json", b / "environment.json")
    for sub in ("reports", "constraints", "logs"):
        if not any((b / sub).iterdir()):
            (b / sub).rmdir()
    files = sorted(p for p in b.rglob("*") if p.is_file())
    lines = ["# boson debug bundle", "", "Anonymized: every design name is a token (top, u<N>, r<N>, w<N>, clk<N>, in<N>/out<N>, ...).",
             "The customer keeps the decoding map locally; ask questions using the tokens.", "",
             "| file | bytes |", "|---|---|"]
    lines += [f"| {p.relative_to(b)} | {p.stat().st_size:,} |" for p in files]
    lines += ["", "Not included: name map, RTL, Liberty, raw netlist" + ("" if a.include_netlist else ", anonymized netlist (not opted in)") + "."]
    if jinfo and jinfo.get("truncated"):
        lines.append(f"Journal truncated: kept {jinfo['kept']:,} of {jinfo['lines']:,} lines; see journal/truncation.json.")
    (b / "MANIFEST.md").write_text("\n".join(lines) + "\n")
    print(f"make_bundle: checking {b} ...", file=sys.stderr)
    if an.run_check(m, b) != 0:
        print("make_bundle: leak check FAILED - no tarball written. Fix and rerun.", file=sys.stderr)
        return 1
    if a.no_tar:
        return 0
    tgz = b.with_name(b.name + ".tar.gz")
    with tarfile.open(tgz, "w:gz") as t:
        for p in sorted(b.rglob("*")):
            ti = t.gettarinfo(str(p), arcname=str(Path(b.name) / p.relative_to(b)))
            ti.uid = ti.gid = 0
            ti.uname = ti.gname = ""
            ti.mtime = 0
            if p.is_file():
                with open(p, "rb") as fh:
                    t.addfile(ti, fh)
            else:
                t.addfile(ti)
    if an.run_check(m, tgz) != 0:
        tgz.unlink()
        return 1
    print(f"make_bundle: wrote {tgz} ({tgz.stat().st_size:,} bytes). Show the user MANIFEST.md and REPORT.md before they send it.",
          file=sys.stderr)
    return 0


def main(argv=None) -> int:
    a = parser().parse_args(argv)
    for d in (a.work, a.bundle_dir):
        if d.resolve() in a.map.resolve().parents:
            print(f"make_bundle: the name map must live outside {d}", file=sys.stderr)
            return 2
    m, man = prepare(a)
    if not a.report:
        print(f"make_bundle: prepared {a.work}/anon and {a.work}/digests. Write REPORT.md from those (anonymized names only), "
              f"then rerun with --report REPORT.md.", file=sys.stderr)
        return 0
    return bundle(a, m, man)


if __name__ == "__main__":
    raise SystemExit(main())
