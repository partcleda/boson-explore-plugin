"""Terminal-look renderer: dark surface, mint boson banner, monospace body,
block cursor, optional elapsed timer in the corner. Everything is drawn with
PIL so frames compose straight into the video canvas."""
from PIL import Image, ImageDraw

from . import fonts

BG = (19, 19, 19)
FG = (215, 215, 210)
DIM = (140, 140, 135)
MINT = (60, 214, 156)
BANNER = [
    "   ___   ___  ___  ___  _  _ ",
    "  | _ ) / _ \\/ __|/ _ \\| \\| |",
    "  | _ \\| (_) \\__ \\ (_) | .` |",
    "  |___/ \\___/|___/\\___/|_|\\_|",
]


class Term:
    def __init__(self, w, h, size=17, pad=(16, 14), version=None):
        self.w, self.h, self.pad = w, h, pad
        self.font = fonts.load("mono", size)
        self.bold = fonts.load("mono", size, bold=True)
        self.cw = self.font.getlength("M")
        self.lh = int(size * 1.55)
        self.rows = (h - 2 * pad[1]) // self.lh
        self.cols = int((w - 2 * pad[0]) // self.cw)
        self.version = version

    def wrap(self, runs):
        """Split a list of (text, colour) runs into display rows of <= self.cols chars."""
        rows, cur, used = [], [], 0
        for text, colour in runs:
            while text:
                room = self.cols - used
                if room <= 0:
                    rows.append(cur); cur, used = [], 0; room = self.cols
                chunk, text = text[:room], text[room:]
                cur.append((chunk, colour)); used += len(chunk)
        rows.append(cur)
        return rows

    def render(self, lines, cursor=True, elapsed=None):
        """lines: list of str, or list of run-lists [(text, colour), ...]. colour None = bold white."""
        img = Image.new("RGB", (self.w, self.h), BG)
        dr = ImageDraw.Draw(img)
        y = self.pad[1] + 6
        x0 = self.pad[0]
        head = [[(b, MINT)] for b in BANNER]
        tail = f"{self.version} GPU-accelerated EDA toolkit" if self.version else "GPU-accelerated EDA toolkit"
        head.append([("  boson ", None), (tail, DIM)])
        head.append([("", FG)])
        body = []
        for l in lines:
            runs = l if isinstance(l, list) else [(l, FG)]
            body.extend(self.wrap(runs))
        avail = self.rows - len(head) - 1
        if len(body) > avail:
            body = body[-avail:]
        for runs in head + body:
            x = x0
            for text, colour in runs:
                if colour is None:
                    dr.text((x, y), text, font=self.bold, fill=(245, 245, 240)); x += self.bold.getlength(text)
                else:
                    dr.text((x, y), text, font=self.font, fill=colour); x += self.font.getlength(text)
            y += self.lh
        if cursor:
            dr.rectangle([x0, y + 2, x0 + self.cw, y + self.lh - 4], fill=(200, 200, 200))
        if elapsed is not None:
            t = f"elapsed  {elapsed}"
            tw = self.bold.getlength(t)
            dr.text((self.w - self.pad[0] - tw, self.h - self.pad[1] - self.lh), t, font=self.bold, fill=(70, 230, 120))
        return img
