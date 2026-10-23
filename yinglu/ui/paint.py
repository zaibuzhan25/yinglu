"""PIL 绘制工具：让 Tkinter 界面拥有抗锯齿圆角、渐变和阴影。"""
from __future__ import annotations

from typing import Callable

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageTk

FONT_REG = "C:/Windows/Fonts/msyh.ttc"
FONT_BOLD = "C:/Windows/Fonts/msyhbd.ttc"

# 调色板
BG_TOP = (13, 15, 21)
BG_BOTTOM = (8, 9, 13)
CARD = (20, 23, 31)
CARD_HI = (25, 29, 39)
BORDER = (35, 41, 54)
TEXT = (232, 237, 245)
MUTED = (143, 152, 171)
DIM = (98, 106, 124)
ACCENT = (255, 77, 94)
ACCENT_HI = (255, 112, 110)
ACCENT_LO = (238, 50, 78)
GREEN = (56, 211, 133)
PILL = (15, 18, 25)


def hexc(rgb: tuple[int, int, int]) -> str:
    return "#%02x%02x%02x" % rgb


def pil_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(FONT_BOLD if bold else FONT_REG, size)


class Painter:
    """在 2 倍分辨率上作画，最后缩小，得到平滑边缘。

    scale 会把所有坐标与字号整体放大，用于界面缩放。
    """

    S = 2

    def __init__(self, width: int, height: int, scale: float = 1.0):
        self.k = float(scale)
        self.width = int(round(width * self.k))
        self.height = int(round(height * self.k))
        self._layers: list[Callable[[ImageDraw.ImageDraw], None]] = []
        self._shadows: list[tuple] = []
        self._glows: list[tuple] = []
        self._base = self._gradient(self.width * self.S, self.height * self.S,
                                    BG_TOP, BG_BOTTOM)
        self._base_temp = None

    # ------------------------------------------------------------ helpers
    def _v(self, value: float) -> float:
        return value * self.k * self.S

    def _gradient(self, w: int, h: int, top, bottom) -> Image.Image:
        grad = Image.new("RGB", (1, h))
        px = grad.load()
        for y in range(h):
            t = y / max(1, h - 1)
            px[0, y] = (int(top[0] + (bottom[0] - top[0]) * t),
                        int(top[1] + (bottom[1] - top[1]) * t),
                        int(top[2] + (bottom[2] - top[2]) * t))
        return grad.resize((w, h), Image.Resampling.BILINEAR)

    def glow(self, cx, cy, rx, ry, color, alpha=26, blur=90):
        self._glows.append((cx, cy, rx, ry, color, alpha, blur))

    def shadow(self, x, y, w, h, radius, blur=18, dy=10, alpha=120):
        self._shadows.append((x, y, w, h, radius, blur, dy, alpha))

    def card(self, x, y, w, h, radius=14, fill=CARD, outline=BORDER,
             border=1, highlight=False):
        self.shadow(x, y, w, h, radius)
        v = self._v

        def _draw(d: ImageDraw.ImageDraw):
            d.rounded_rectangle([v(x), v(y), v(x + w) - 1, v(y + h) - 1],
                                radius=v(radius), fill=fill,
                                outline=outline, width=max(1, int(v(border))))
            if highlight:
                d.line([v(x + radius), v(y + 1), v(x + w - radius), v(y + 1)],
                       fill=(255, 255, 255), width=self.S)

        self._layers.append(_draw)

    def rounded(self, x, y, w, h, radius, fill, outline=None, width=1):
        v = self._v

        def _draw(d):
            d.rounded_rectangle([v(x), v(y), v(x + w) - 1, v(y + h) - 1],
                                radius=v(radius), fill=fill, outline=outline,
                                width=max(1, int(v(width))))

        self._layers.append(_draw)

    def gradient_rounded(self, x, y, w, h, radius, top, bottom, outline=None):
        size = (max(1, int(self._v(w))), max(1, int(self._v(h))))
        grad = self._gradient(size[0], size[1], top, bottom).convert("RGBA")
        mask = Image.new("L", size, 0)
        ImageDraw.Draw(mask).rounded_rectangle([0, 0, size[0] - 1, size[1] - 1],
                                               radius=self._v(radius), fill=255)

        def _draw(d: ImageDraw.ImageDraw):
            self._base_temp.paste(grad, (int(self._v(x)), int(self._v(y))), mask)
            if outline:
                d.rounded_rectangle([self._v(x), self._v(y),
                                     self._v(x + w) - 1, self._v(y + h) - 1],
                                    radius=self._v(radius), outline=outline,
                                    width=self.S)

        self._layers.append(_draw)

    def text(self, x, y, s, size, color=TEXT, bold=False, anchor="la", spacing=0.0):
        def _draw(d: ImageDraw.ImageDraw):
            font = pil_font(max(1, int(size * self.k * self.S)), bold)
            if not spacing:
                d.text((self._v(x), self._v(y)), s, font=font, fill=color, anchor=anchor)
                return
            cur = self._v(x)
            total = sum(d.textlength(ch, font=font) for ch in s) + \
                spacing * self.k * self.S * (len(s) - 1)
            if anchor[0] == "m":
                cur -= total / 2
            for ch in s:
                d.text((cur, self._v(y)), ch, font=font, fill=color,
                       anchor="l" + anchor[1])
                cur += d.textlength(ch, font=font) + spacing * self.k * self.S

        self._layers.append(_draw)

    def logo(self, x, y, size):
        v = self._v
        radius = size * 0.30

        def _draw(d: ImageDraw.ImageDraw):
            grad = self._gradient(int(v(size)), int(v(size)), ACCENT_HI, (226, 32, 74))
            mask = Image.new("L", (int(v(size)), int(v(size))), 0)
            ImageDraw.Draw(mask).rounded_rectangle(
                [0, 0, int(v(size)) - 1, int(v(size)) - 1], radius=v(radius), fill=255)
            self._base_temp.paste(grad, (int(v(x)), int(v(y))), mask)
            cx, cy, r = x + size / 2, y + size / 2, size * 0.20
            d.ellipse([v(cx - r), v(cy - r), v(cx + r), v(cy + r)],
                      fill=(255, 255, 255))
            r2 = r * 0.45
            d.ellipse([v(cx - r2), v(cy - r2), v(cx + r2), v(cy + r2)],
                      fill=(255, 77, 94))

        self._layers.append(_draw)

    # ------------------------------------------------------------ finish
    def finish(self) -> Image.Image:
        s = self.S
        v = self._v
        img = self._base.convert("RGBA")
        self._base_temp = img

        if self._glows:
            layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
            gd = ImageDraw.Draw(layer)
            for cx, cy, rx, ry, color, alpha, blur in self._glows:
                gd.ellipse([v(cx - rx), v(cy - ry), v(cx + rx), v(cy + ry)],
                           fill=(*color, alpha))
            layer = layer.filter(ImageFilter.GaussianBlur(v(blur) / 2))
            img = Image.alpha_composite(img, layer)
            self._base_temp = img

        if self._shadows:
            layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
            sd = ImageDraw.Draw(layer)
            for x, y, w, h, radius, blur, dy, alpha in self._shadows:
                sd.rounded_rectangle([v(x), v(y + dy), v(x + w), v(y + h + dy)],
                                     radius=v(radius), fill=(0, 0, 0, alpha))
            layer = layer.filter(ImageFilter.GaussianBlur(v(10)))
            img = Image.alpha_composite(img, layer)
            self._base_temp = img

        d = ImageDraw.Draw(img)
        for layer_fn in self._layers:
            layer_fn(d)
        return img.resize((self.width, self.height), Image.Resampling.LANCZOS)


def photo(img: Image.Image) -> ImageTk.PhotoImage:
    return ImageTk.PhotoImage(img)


def render_round_rect(w: int, h: int, radius: int, fill, bg,
                      outline=None, width: int = 1,
                      gradient=None) -> Image.Image:
    """生成带背景色的圆角小图（用于按钮/开关等）。"""
    S = 2
    img = Image.new("RGB", (w * S, h * S), bg)
    mask = Image.new("L", (w * S, h * S), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, w * S - 1, h * S - 1],
                                           radius=radius * S, fill=255)
    if gradient:
        top, bottom = gradient
        grad = Image.new("RGB", (1, h * S))
        px = grad.load()
        for yy in range(h * S):
            t = yy / max(1, h * S - 1)
            px[0, yy] = (int(top[0] + (bottom[0] - top[0]) * t),
                         int(top[1] + (bottom[1] - top[1]) * t),
                         int(top[2] + (bottom[2] - top[2]) * t))
        grad = grad.resize((w * S, h * S))
        img.paste(grad, (0, 0), mask)
    else:
        img.paste(Image.new("RGB", (w * S, h * S), fill), (0, 0), mask)
    if outline:
        d = ImageDraw.Draw(img)
        d.rounded_rectangle([0, 0, w * S - 1, h * S - 1], radius=radius * S,
                            outline=outline, width=width * S)
    return img.resize((w, h), Image.Resampling.LANCZOS)
