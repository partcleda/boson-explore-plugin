"""PPA scatter on the dark surface, rendered to a PIL image.

x = standard-cell area (mm²), y = achieved clock (1/(period - WNS)), marker
size = total power, hue = the sweep's `color_by` axis, marker shape = its
`marker_by` axis. Hues are the validated dark categorical palette in fixed
slot order (the first three slots validate all-pairs for scatter forms; past
three, prefer a marker axis or split the sweep rather than more colours)."""
import io
import sys
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from PIL import Image

SURF = "#131313"; INK = "#f2f2ee"; INK2 = "#c3c2b7"; MUTED = "#898781"; GRID = "#2c2c2a"; AXIS = "#383835"
DARK_SLOTS = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"]
MARKERS = ["o", "s", "D", "^", "v", "P", "X"]

plt.rcParams.update({"font.family": "DejaVu Sans", "text.color": INK, "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2,
                     "axes.edgecolor": AXIS, "axes.facecolor": SURF, "figure.facecolor": SURF, "grid.color": GRID})


def fmax_ghz(period_ps, wns_ns):
    return 1000.0 / (period_ps - 1000.0 * wns_ns)


class Encoding:
    """Maps a sweep's categorical axes onto colour slots and marker shapes."""

    def __init__(self, space):
        self.space = space
        self.color_by = space.get("color_by")
        self.marker_by = space.get("marker_by")
        axes = space["axes"]
        self.color_vals = [str(v) for v in axes.get(self.color_by, [])] if self.color_by else []
        self.marker_vals = [str(v) for v in axes.get(self.marker_by, [])] if self.marker_by else []
        if len(self.color_vals) > 3:
            print(f"[viz] warning: color_by axis {self.color_by!r} has {len(self.color_vals)} values; only the first "
                  f"three palette slots validate all-pairs on a scatter — consider a marker axis instead", file=sys.stderr)
        self.labels = space.get("labels", {})

    def label(self, axis, value):
        return self.labels.get(axis, {}).get(str(value), f"{axis}={value}")

    def color(self, p):
        if not self.color_by: return DARK_SLOTS[0]
        v = str(p["params"].get(self.color_by))
        return DARK_SLOTS[self.color_vals.index(v) % len(DARK_SLOTS)] if v in self.color_vals else INK2

    def color_rgb(self, p):
        h = self.color(p).lstrip("#"); return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))

    def marker(self, p):
        if not self.marker_by: return "o"
        v = str(p["params"].get(self.marker_by))
        return MARKERS[self.marker_vals.index(v) % len(MARKERS)] if v in self.marker_vals else "o"

    def legend_handles(self, fs):
        h = []
        for i, v in enumerate(self.color_vals):
            h.append(Line2D([], [], marker="s", color=SURF, markerfacecolor=DARK_SLOTS[i % len(DARK_SLOTS)], markersize=9 * fs,
                            linestyle="none", label=self.label(self.color_by, v)))
        for i, v in enumerate(self.marker_vals):
            h.append(Line2D([], [], marker=MARKERS[i % len(MARKERS)], color=SURF, markerfacecolor=INK2, markersize=8 * fs,
                            linestyle="none", label=self.label(self.marker_by, v)))
        return h


def render(points, enc, w_px, h_px, dpi=100, highlight=None, xlim=None, ylim=None, pareto=False, smax=None, fs=1.0, mhz=False):
    """points: rows from summary.json (params, area_um2, period_ps, wns_ns, power_w, tag).
    fs scales fonts/marks so the chart stays proportional at higher render resolutions."""
    fig, ax = plt.subplots(figsize=(w_px / dpi, h_px / dpi), dpi=dpi)
    ax.grid(True, linewidth=1 * fs, alpha=1.0); ax.set_axisbelow(True)
    ax.tick_params(labelsize=9 * fs, width=fs, length=3.5 * fs)
    for s in ("top", "right"): ax.spines[s].set_visible(False)
    for s in ("left", "bottom"): ax.spines[s].set_linewidth(fs)
    yscale = 1000.0 if mhz else 1.0
    xs = [p["area_um2"] / 1e6 for p in points]
    ys = [fmax_ghz(p["period_ps"], p["wns_ns"]) * yscale for p in points]
    pw = np.array([p.get("power_w") or 0.0 for p in points]); smax = smax or (pw.max() if len(pw) else 1.0)
    for p, x, y, pwr in zip(points, xs, ys, pw):
        size = (60 + 340 * (pwr / smax if smax else 0)) * fs * fs
        hl = highlight == p["tag"]
        ax.scatter([x], [y], s=size, marker=enc.marker(p), c=enc.color(p), edgecolors=SURF, linewidths=2 * fs, zorder=3 + hl)
        if hl:
            ax.scatter([x], [y], s=size * 2.6, marker=enc.marker(p), facecolors="none", edgecolors=INK, linewidths=1.5 * fs, zorder=5)
    if pareto and len(points) > 1:
        idx = np.argsort(xs); best = -1; px, py = [], []
        for i in idx:
            if ys[i] > best: best = ys[i]; px.append(xs[i]); py.append(ys[i])
        ax.step(px, py, where="post", color=INK2, linewidth=1.2 * fs, alpha=0.7, zorder=2)
    ax.set_xlabel("standard-cell area (mm²)", fontsize=10 * fs)
    ax.set_ylabel("achieved clock (MHz)" if mhz else "achieved clock (GHz)", fontsize=10 * fs)
    if xlim: ax.set_xlim(*xlim)
    if ylim: ax.set_ylim(ylim[0] * yscale, ylim[1] * yscale)
    handles = enc.legend_handles(fs)
    if handles:
        ax.legend(handles=handles, loc="upper center", bbox_to_anchor=(0.5, -0.16), frameon=False, ncol=min(5, len(handles)),
                  fontsize=9 * fs, labelcolor=INK2, handletextpad=0.3, columnspacing=1.2)
    fig.tight_layout(pad=0.6, rect=(0, 0.04, 1, 1))
    buf = io.BytesIO(); fig.savefig(buf, format="png", facecolor=SURF); plt.close(fig)
    buf.seek(0); return Image.open(buf).convert("RGB")
