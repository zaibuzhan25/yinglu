"""主窗口背景：渐变、光晕、卡片、静态标题。"""
from __future__ import annotations

from PIL import Image

from .paint import (ACCENT, BORDER, CARD, CARD_HI, DIM, MUTED, Painter, TEXT)

W, H = 900, 640

LEFT_X, LEFT_W = 28, 396
CARD1_Y, CARD1_H = 96, 158
CARD2_Y, CARD2_H = 270, 200
RIGHT_X, RIGHT_W = 448, 424
PREVIEW_Y, PREVIEW_H = 96, 252
SETTINGS_Y, SETTINGS_H = 364, 148
RECORD_Y, RECORD_H = 528, 64


def build(scale: float = 1.0) -> Image.Image:
    p = Painter(W, H, scale)
    p.glow(150, 10, 360, 210, ACCENT, alpha=26, blur=110)
    p.glow(880, 660, 320, 220, (70, 96, 255), alpha=14, blur=130)
    p.glow(660, 560, 250, 90, ACCENT, alpha=34, blur=70)

    p.card(LEFT_X, CARD1_Y, LEFT_W, CARD1_H)
    p.card(LEFT_X, CARD2_Y, LEFT_W, CARD2_H)
    p.card(RIGHT_X, PREVIEW_Y, RIGHT_W, PREVIEW_H)
    p.card(RIGHT_X, SETTINGS_Y, RIGHT_W, SETTINGS_H)

    # 品牌
    p.logo(28, 24, 36)
    p.text(76, 21, "映录", 20, TEXT, True)
    p.text(77, 50, "YINGLU · SCREEN RECORDER", 8, DIM, True, spacing=1.4)

    # 卡片标题
    p.text(46, 110, "录制范围", 10, MUTED, True)
    p.text(46, 284, "声音", 10, MUTED, True)
    p.text(466, 378, "录制设置", 10, MUTED, True)

    # 设置项标签
    p.text(466, 400, "帧率", 10, TEXT)
    p.text(622, 400, "画质", 10, TEXT)
    p.text(466, 454, "倒计时", 10, TEXT)
    p.text(668, 454, "鼠标指针", 10, TEXT)

    # 界面缩放
    p.text(690, 32, "界面大小", 8.5, DIM)

    # 底部静态文字
    p.text(28, 484, "保存到", 8.5, DIM)
    p.text(28, 546, "最近一次", 8.5, DIM)
    p.text(28, 604, "F9 开始 / 停止      F10 暂停 / 继续", 9, DIM)

    # 分隔线
    p.rounded(28, 532, LEFT_W, 1, 0, (34, 40, 52))
    return p.finish()
