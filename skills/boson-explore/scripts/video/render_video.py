#!/usr/bin/env python3
"""Assemble a design-space-exploration GIF/MP4 from a finished sweep.

Left: a boson terminal replaying each design point's compile (time-lapse
elapsed timer, the point's real progress lines). Right: the parameter space
with evaluated points lit, the PPA scatter filling in, and the placement of
the point that just finished. Every number and image comes from <runs>/<tag>/.

    render_video.py --runs runs --gif demo/sweep.gif --mp4 demo/sweep.mp4
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).parent))
from lib import fonts, ppa_chart, placement_img  # noqa: E402
from lib.term import BG, DIM, FG, Term  # noqa: E402
import collect  # noqa: E402

INK = (242, 242, 238); INK2 = (195, 194, 183); MUTED = (137, 135, 129); RULE = (44, 44, 42)


class Layout:
    def __init__(self, supersample: float):
        self.S = supersample
        self.W, self.H = self.s(1600), self.s(900)
        self.TERM_W = self.s(860)
        self.RX = self.TERM_W + self.s(30)
        self.RW = self.W - self.RX - self.s(30)

    def s(self, v): return int(round(v * self.S))

    def font(self, sz, bold=False): return fonts.load("sans", self.s(sz), bold)


def fmt_int(n): return f"{int(n):,}"


def fmt_elapsed(sec):
    sec = int(sec); h, m, s = sec // 3600, (sec % 3600) // 60, sec % 60
    return f"{h}h {m:02d}m {s:02d}s" if h else f"{m}m {s:02d}s"


def fmt_cells(n):
    return f"{n / 1e6:.2f}M" if n >= 1e6 else (f"{n / 1e3:.1f}K" if n >= 1e3 else str(int(n)))


def fmt_area(um2):
    return f"{um2 / 1e6:.3f} mm²" if um2 >= 1e5 else f"{um2:,.0f} µm²"


def fmt_power(w):
    return f"{w:.2f} W" if w >= 1 else f"{w * 1e3:.1f} mW"


class Space:
    """The swept axes: index grid, header text, captions."""

    def __init__(self, space: dict):
        self.space = space
        self.axes = {k: [str(v) for v in vals] for k, vals in space["axes"].items()}
        self.param_axes = [a for a in self.axes if a != "period_ps"]
        self.periods = [int(float(p)) for p in self.axes.get("period_ps", [])]
        self.n = math.prod(len(v) for v in self.axes.values())
        self.cols = max(1, math.ceil(math.sqrt(self.n)))
        self.rows = math.ceil(self.n / self.cols)
        self.enc = ppa_chart.Encoding(space)

    def index(self, p) -> tuple[int, int]:
        i = 0
        for a, vals in self.axes.items():
            v = str(int(p["period_ps"])) if a == "period_ps" else str(p["params"].get(a))
            i = i * len(vals) + (vals.index(v) if v in vals else 0)
        return divmod(i, self.cols)

    def header_lines(self, width_chars=62) -> list[str]:
        parts = [f"{a} {{{', '.join(self.axes[a])}}}" for a in self.param_axes]
        if self.periods:
            parts.append(f"clock target {{{', '.join(f'{p / 1000:g}' for p in self.periods)} ns}}")
        text = " × ".join(parts) + f"  =  {self.n} configs"
        lines, cur = [], ""
        for tok in text.split(" × "):
            cand = tok if not cur else f"{cur} × {tok}"
            if len(cand) > width_chars and cur:
                lines.append(cur); cur = f"× {tok}"
            else:
                cur = cand
        lines.append(cur)
        return lines[:3]

    def caption(self, p) -> list[str]:
        head = " · ".join(self.enc.label(a, p["params"].get(a)) for a in self.param_axes) or p["tag"]
        out = [head, f"{p['period_ps'] / 1000:g} ns clock target",
               f"{fmt_int(p['cells'])} cells · {fmt_area(p['area_um2'])} std-cell area",
               f"WNS {p['wns_ns']:+.3f} ns → {p['fmax_ghz'] * 1000:.0f} MHz achieved"]
        if p.get("power_w"):
            out.append(f"{fmt_power(p['power_w'])} @ random toggle activity")
        if p.get("wall_s"):
            out.append(f"compile+place {fmt_elapsed(p['wall_s'])}")
        return out


class Scene:
    def __init__(self, L: Layout, sp: Space, points, thumbs, fps=10, version=None):
        self.L, self.sp, self.points, self.thumbs, self.fps = L, sp, points, thumbs, fps
        self.term = Term(L.TERM_W, L.H, size=L.s(14), pad=(L.s(18), L.s(16)), version=version)
        self.frames, self.durations = [], []
        xs = [p["area_um2"] / 1e6 for p in points]; ys = [p["fmax_ghz"] for p in points]
        pad = lambda lo, hi, f=0.12: (lo - (hi - lo) * f, hi + (hi - lo) * f)
        self.xlim = pad(0, max(xs)); self.ylim = pad(min(ys) * 0.85, max(ys) * 1.1)
        self.mhz = max(ys) < 1.0
        self.smax = max(p.get("power_w") or 0 for p in points) or 1.0
        self._chart_cache = {}

    def chart(self, done_pts, highlight, pareto):
        key = (tuple(p["tag"] for p in done_pts), highlight, pareto)
        if key not in self._chart_cache:
            self._chart_cache[key] = ppa_chart.render(done_pts, self.sp.enc, self.L.RW, self.L.s(400), highlight=highlight,
                                                      xlim=self.xlim, ylim=self.ylim, pareto=pareto, smax=self.smax,
                                                      fs=self.L.S, mhz=self.mhz)
        return self._chart_cache[key]

    def draw_space(self, dr, x, y, w, done_pts, active=None):
        L, sp = self.L, self.sp
        dr.text((x, y), sp.space["title"], font=L.font(17, True), fill=INK)
        yy = y + L.s(27)
        for line in sp.header_lines():
            dr.text((x, yy), line, font=L.font(12), fill=INK2); yy += L.s(18)
        dr.text((x, yy + L.s(3)), f"{len(done_pts)} evaluated", font=L.font(12, True), fill=MUTED)
        pitch = L.s(20) if sp.cols <= 6 else L.s(int(120 / sp.cols))
        gx, gy = x + w - sp.cols * pitch - L.s(6), y + L.s(4)
        lit = {sp.index(p): p for p in done_pts}
        act = sp.index(active) if active else None
        for i in range(sp.n):
            r, c = divmod(i, sp.cols)
            cx, cy = gx + c * pitch, gy + r * pitch
            if (r, c) == act:
                dr.ellipse([cx - L.s(6), cy - L.s(6), cx + L.s(6), cy + L.s(6)], fill=INK)
            elif (r, c) in lit:
                dr.ellipse([cx - L.s(5), cy - L.s(5), cx + L.s(5), cy + L.s(5)], fill=sp.enc.color_rgb(lit[(r, c)]))
            else:
                dr.ellipse([cx - L.s(2), cy - L.s(2), cx + L.s(2), cy + L.s(2)], fill=(58, 58, 56))

    def compose(self, lines, elapsed, done_pts, active=None, thumb=None, cap=None, highlight=None, pareto=False, final_text=None):
        L = self.L
        img = Image.new("RGB", (L.W, L.H), BG)
        img.paste(self.term.render(lines, cursor=True, elapsed=elapsed), (0, 0))
        dr = ImageDraw.Draw(img)
        dr.line([(L.TERM_W + L.s(8), L.s(20)), (L.TERM_W + L.s(8), L.H - L.s(20))], fill=RULE, width=L.s(1))
        self.draw_space(dr, L.RX, L.s(26), L.RW, done_pts, active)
        if done_pts:
            img.paste(self.chart(done_pts, highlight, pareto), (L.RX, L.s(140)))
        else:
            dr.text((L.RX + L.s(20), L.s(300)), "PPA space fills in as points finish", font=L.font(14), fill=MUTED)
        if thumb is not None:
            t = thumb.copy(); t.thumbnail((L.s(300), L.s(300)))
            img.paste(t, (L.RX, L.s(560)))
            dr.rectangle([L.RX - L.s(1), L.s(559), L.RX + t.width, L.s(560) + t.height], outline=(60, 60, 58))
        cap_x = L.RX + (L.s(320) if thumb is not None else 0)
        if cap:
            y = L.s(566)
            for i, line in enumerate(cap):
                dr.text((cap_x, y), line, font=L.font(14, i == 0), fill=INK if i < 2 else INK2); y += L.s(24) if i == 0 else L.s(22)
        if final_text:
            y = L.s(566)
            for i, line in enumerate(final_text):
                dr.text((cap_x, y), line, font=L.font(14, i == 0), fill=INK if i == 0 else INK2); y += L.s(25)
        return img

    def add(self, img, dur):
        self.frames.append(img); self.durations.append(dur)

    def typewriter(self, base_lines, text, done_pts, cps=60, **kw):
        n = max(1, int(len(text) / cps * self.fps))
        for i in range(1, n + 1):
            part = text[: int(len(text) * i / n)]
            self.add(self.compose(base_lines + [[("boson> ", FG), (part, FG)]], None, done_pts, **kw), 1 / self.fps)


def point_log_lines(p):
    """The point's real progress lines, lightly condensed to keep the terminal readable."""
    out = [[(l, DIM)] for l in p["compile_lines"]]
    for it in p["loop"]:
        out.append([(f"[layout-loop] iter {it['it']}/{it['of']}: WNS {it['wns_ps']:.1f} ps  area {int(it['area_um2'])} um^2  "
                     f"HPWL {int(it['hpwl_um'])} um  (+{it['t_s']:.1f}s)", DIM)])
    if not p["loop"] and not out:
        out.append([(f"place_design: {fmt_int(p['cells'])} cells placed", DIM)])
    if len(out) > 9:
        out = out[:2] + [[("  …", DIM)]] + out[-6:]
    qor = f"report_qor: WNS {p['wns_ns']:.3f} ns  ·  {fmt_int(p['cells'])} cells  ·  area {p['area_um2']:.0f} um^2"
    if p.get("power_w"):
        qor += f"  ·  {fmt_power(p['power_w'])}"
    out.append([(qor, FG)])
    out.append([(f"write_def: wrote {fmt_int(p['cells'])} placed component(s)", FG)])
    return out


def intro_text(space):
    libs = [Path(l).name for l in space["libs"]]; lefs = [Path(l).name for l in space["lefs"]]
    parts = [f"read_liberty {libs[0]}" if len(libs) == 1 else f"read_liberty {libs[0]} … ({len(libs)} libs)"]
    parts += [f"read_lef {l}" for l in lefs]
    return " ; ".join(parts)


def build(L, sp, points, thumbs, fps=10, secs_per_point=3.2, compute_note=None, version=None):
    sc = Scene(L, sp, points, thumbs, fps, version=version)
    lines = []
    sc.add(sc.compose(lines, None, []), 0.9)
    intro = intro_text(sp.space)
    sc.typewriter(lines, intro, [], cps=90)
    lines = lines + [[("boson> ", FG), (intro, FG)]]
    for l in (points[0].get("setup_lines") or [])[:2]:
        lines.append([(re.sub(r"(?<=\s)/\S+/(?=\S)", "", l), DIM)])   # show basenames, not the host's absolute paths
    sc.add(sc.compose(lines, None, []), 0.6)
    done = []
    for p in points:
        cmd = p["cmd"] or f"compile {sp.space['rtl']} -top {sp.space['top']}"
        prev = dict(thumb=thumbs.get(done[-1]["tag"]) if done else None, cap=sp.caption(done[-1]) if done else None,
                    highlight=done[-1]["tag"] if done else None)
        sc.typewriter(lines, cmd, done, cps=110, **prev)
        lines = lines + [[("boson> ", FG), (cmd, FG)]]
        plog = point_log_lines(p)
        nfr = int(secs_per_point * fps)
        wall = p.get("wall_s") or 0
        for i in range(nfr):
            frac = (i + 1) / nfr
            shown = plog[: int(len(plog) * frac)]
            sc.add(sc.compose(lines + shown, fmt_elapsed(wall * min(1.0, frac * 1.05)) if wall else None, done, active=p, **prev), 1 / fps)
        lines = lines + plog
        done = done + [p]
        for _ in range(int(0.8 * fps)):
            sc.add(sc.compose(lines, fmt_elapsed(wall) if wall else None, done, thumb=thumbs.get(p["tag"]), cap=sp.caption(p), highlight=p["tag"]), 1 / fps)
    total_s = sum(p.get("wall_s") or 0 for p in points)
    cells = [p["cells"] for p in points]
    span = fmt_cells(min(cells)) if min(cells) == max(cells) else f"{fmt_cells(min(cells))}–{fmt_cells(max(cells))}"
    final = [f"{len(points)} design point{'s' if len(points) != 1 else ''} · {span} cells each",
             compute_note or (f"{total_s / 3600:.1f} GPU-hours total" if total_s >= 3600 else f"{total_s / 60:.0f} min of compute total"),
             "each point: RTL→gates→place→STA→power",
             "one boson session per point · Pareto front shown"]
    lines = lines + [[("boson> ", FG), ("report_sweep -pareto", FG)]]
    for _ in range(int(4.0 * fps)):
        sc.add(sc.compose(lines, None, done, thumb=thumbs.get(points[-1]["tag"]), pareto=True, final_text=final), 1 / fps)
    return sc


def write(sc, out_gif, out_mp4, gif_scale, mp4_scale):
    L = sc.L

    def scaled(scale):
        if scale == 1.0: return sc.frames
        w = int(L.W * scale) & ~1; h = int(L.H * scale) & ~1
        return [f.resize((w, h), Image.LANCZOS) for f in sc.frames]

    if out_gif:
        frames = scaled(gif_scale)
        pal = [f.quantize(colors=255, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE) for f in frames]
        pal[0].save(out_gif, save_all=True, append_images=pal[1:], duration=[int(d * 1000) for d in sc.durations], loop=0, optimize=True, disposal=1)
        print(f"[viz] gif {out_gif} {Path(out_gif).stat().st_size / 1e6:.1f} MB, {len(frames)} frames {frames[0].size}", file=sys.stderr)
    if out_mp4:
        try:
            import imageio_ffmpeg
        except ImportError:
            print("[viz] mp4 skipped: pip install imageio-ffmpeg", file=sys.stderr); return
        import subprocess
        frames = scaled(mp4_scale)
        ff = imageio_ffmpeg.get_ffmpeg_exe()
        p = subprocess.Popen([ff, "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{frames[0].width}x{frames[0].height}",
                              "-r", str(sc.fps), "-i", "-", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18", "-movflags", "+faststart", out_mp4],
                             stdin=subprocess.PIPE)
        for f, d in zip(frames, sc.durations):
            for _ in range(max(1, round(d * sc.fps))):
                p.stdin.write(f.tobytes())
        p.stdin.close(); p.wait()
        print(f"[viz] mp4 {out_mp4} {Path(out_mp4).stat().st_size / 1e6:.1f} MB {frames[0].size}", file=sys.stderr)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--runs", type=Path, default=Path("runs"))
    ap.add_argument("--gif", default=None); ap.add_argument("--mp4", default=None)
    ap.add_argument("--order", nargs="*", default=None, help="Explicit tag order (default: by cell count, ascending)")
    ap.add_argument("--fps", type=int, default=10)
    ap.add_argument("--secs-per-point", type=float, default=3.2)
    ap.add_argument("--supersample", type=float, default=2.0, help="Render scale (2 = 3200x1800 native)")
    ap.add_argument("--gif-scale", type=float, default=0.5); ap.add_argument("--mp4-scale", type=float, default=0.6)
    ap.add_argument("--thumb-px", type=int, default=900)
    ap.add_argument("--compute-note", default=None, help="Closing line 2, e.g. '18.9 GPU-hours on one RTX 6000 Ada'")
    ap.add_argument("--still", default=None, help="Also save the final frame as PNG here")
    a = ap.parse_args()
    if not (a.gif or a.mp4 or a.still):
        ap.error("give at least one of --gif / --mp4 / --still")

    rows = collect.main(a.runs)
    space = json.loads((a.runs / "space.json").read_text())
    pts = [r for r in rows if r["done"] and r.get("wns_ns") is not None and r.get("cells") and r.get("area_um2")]
    if a.order:
        by = {r["tag"]: r for r in pts}; pts = [by[t] for t in a.order if t in by]
    else:
        pts.sort(key=lambda r: (r["cells"], -r["period_ps"]))
    if not pts:
        sys.exit("[viz] no finished points with timing data under " + str(a.runs))
    thumbs = {}
    for p in pts:
        png = a.runs / p["tag"] / "placement.png"
        if not png.exists() and p["has_def"] and space["lefs"]:
            img, st = placement_img.render(str(a.runs / p["tag"] / "design.def"), space["lefs"], a.thumb_px)
            img.save(png); print(f"[viz] placement {p['tag']}: {st}", file=sys.stderr)
        if png.exists():
            thumbs[p["tag"]] = Image.open(png).convert("RGB")
    version = next((p.get("boson_version") for p in pts if p.get("boson_version")), None)
    L = Layout(a.supersample); sp = Space(space)
    sc = build(L, sp, pts, thumbs, fps=a.fps, secs_per_point=a.secs_per_point, compute_note=a.compute_note, version=version)
    write(sc, a.gif, a.mp4, a.gif_scale, a.mp4_scale)
    if a.still:
        sc.frames[-1].save(a.still); print(f"[viz] still {a.still}", file=sys.stderr)


if __name__ == "__main__":
    main()
