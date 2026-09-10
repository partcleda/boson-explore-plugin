"""Render one sweep point's placement (a boson-written DEF) as a thumbnail.

Synthesis flattens the design, so the honest per-cell attribute left is the
library cell each instance maps to. Cells are coloured by FUNCTION class at
matched luminance, so hue (not brightness) separates them: combinational
logic is the teal fabric, flip-flops the blue accent, buffers/inverters the
dim mesh; hard macros (SRAMs etc.) are drawn as orange squares at their
placed spot. The frame is cropped to the placed cells, not the reserved die.

The class regexes default to patterns that cover sky130 (`sky130_fd_sc_hd__dfxtp_1`)
and ASAP7/boson-style (`DFFHQNx1_ASAP7_75t_R`, `BUFx2`) names; override them
for another library."""
import re
import numpy as np
from PIL import Image, ImageDraw

from .defplot import parse_def, lef_sizes

COMB = np.array([36, 118, 104], np.float64)   # teal fabric   (luma ~92)
SEQ = np.array([70, 128, 214], np.float64)    # flops, blue   (luma ~113)
BUF = np.array([58, 60, 68], np.float64)      # buffers, dim  (luma ~60)
MACRO_C = (233, 110, 60)
BG = (17, 17, 17)

DEFAULT_SEQ_RE = r"(__dfxtp|__dfrtp|__dfstp|__dfbbn|__dfxbp|__dlxtp|__dlrtp|__dlxbp|__sdf|__edfxtp|__dlclkp|^DFF|^DHL|^DLL|^SDF|^ICG|LATCH)"
DEFAULT_BUF_RE = r"(__buf_|__inv_|__clkbuf_|__clkinv_|__clkdlybuf|__conb_|__einvp|__einvn|^BUF|^INV|^HB\d|^TIE)"
DEFAULT_MACRO_RE = r"(sram|SRAM|_ram_|^RAM|macro)"


def make_classifier(seq_re=DEFAULT_SEQ_RE, buf_re=DEFAULT_BUF_RE, macro_re=DEFAULT_MACRO_RE):
    seq, buf, macro = re.compile(seq_re), re.compile(buf_re), re.compile(macro_re)

    def cls(ref):
        if macro.search(ref): return "macro"
        if seq.search(ref): return "seq"
        if buf.search(ref): return "buf"
        return "comb"
    return cls


COL = {"comb": COMB, "seq": SEQ, "buf": BUF, "macro": COMB}


def render(def_path, lef_paths, width_px=520, sizes=None, margin_um=3.0, classifier=None):
    d = parse_def(def_path)
    sizes = sizes or lef_sizes(lef_paths)
    cls = classifier or make_classifier()
    n = len(d["names"]); x, y = d["x"], d["y"]
    kinds = [cls(c) for c in d["cells"]]
    counts = {k: kinds.count(k) for k in ("seq", "comb", "buf", "macro")}
    if n:
        # 0.3-99.7 percentile drops a few sparse outliers so the dense block fills the frame
        x0, x1 = np.percentile(x, 0.3) - margin_um, np.percentile(x, 99.7) + margin_um
        y0, y1 = np.percentile(y, 0.3) - margin_um, np.percentile(y, 99.7) + margin_um
    else:
        x0, y0, x1, y1 = d["die"]
    if x1 <= x0: x1 = x0 + 1.0
    if y1 <= y0: y1 = y0 + 1.0
    W = width_px; H = max(1, int(round(W * (y1 - y0) / (x1 - x0))))
    sx = W / (x1 - x0); sy = H / (y1 - y0)
    acc = np.zeros((H, W, 3)); cnt = np.zeros((H, W))
    wh = np.array([sizes.get(c, (0.5, 0.5)) for c in d["cells"]]) if n else np.zeros((0, 2))
    for i in range(n):
        if kinds[i] == "macro": continue
        px0 = int(np.clip((x[i] - x0) * sx, 0, W - 1)); py0 = int(np.clip((y[i] - y0) * sy, 0, H - 1))
        px1 = int(np.clip((x[i] + wh[i, 0] - x0) * sx, 0, W - 1)); py1 = int(np.clip((y[i] + wh[i, 1] - y0) * sy, 0, H - 1))
        acc[py0:py1 + 1, px0:px1 + 1] += COL[kinds[i]]; cnt[py0:py1 + 1, px0:px1 + 1] += 1
    img = np.array(BG, float)[None, None, :] * np.ones((H, W, 1)); m = cnt > 0
    img[m] = acc[m] / cnt[m][:, None]
    pim = Image.fromarray(np.clip(img, 0, 255).astype(np.uint8)[::-1])   # DEF y grows upward
    dr = ImageDraw.Draw(pim); r = max(3, int(W / 130))
    for c, xx, yy in zip(d["cells"], x, y):
        if cls(c) == "macro":
            px = (xx - x0) * sx; py = H - (yy - y0) * sy
            dr.rectangle([px - r, py - r, px + r, py + r], fill=MACRO_C, outline=BG)
    return pim, dict(cells=n, die=d["die"], placed_box=(round(x1 - x0, 1), round(y1 - y0, 1)), **counts)
