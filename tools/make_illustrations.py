# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 OpenLearn
"""Flat illustration set for the showcase quizzes.

No diffusion backend is reachable on this host, so the scenes are drawn from
primitives: one shared "nocturnal SOC" art direction, a motif per scene, a
radial glow behind it, a dot grid, grain and a vignette. Drawn at 2x and
downsampled for clean edges.
"""

from __future__ import annotations

import math
import os
import random

from PIL import Image, ImageDraw, ImageFilter

W, H = 1280, 720
SS = 2  # supersampling factor
OUT = "/workspace/openlearn-shots/illus"

BG_TOP = (11, 17, 33)
BG_BOTTOM = (4, 6, 13)
CYAN = (34, 211, 238)
VIOLET = (139, 92, 246)
TEAL = (20, 184, 166)
RED = (239, 68, 68)
AMBER = (245, 158, 11)
INK = (8, 11, 22)


def canvas(top=BG_TOP, bottom=BG_BOTTOM, accent=CYAN, glow_at=(0.5, 0.45), glow_size=0.75,
           glow_alpha=110, grid=True):
    """Background: vertical gradient, one radial glow, dot grid, grain."""
    width, height = W * SS, H * SS
    base = Image.new("RGB", (width, height), bottom)
    draw = ImageDraw.Draw(base)
    for y in range(height):
        ratio = y / height
        # Slight ease so the horizon of the gradient sits above the middle.
        eased = ratio ** 0.85
        colour = tuple(int(top[i] + (bottom[i] - top[i]) * eased) for i in range(3))
        draw.line((0, y, width, y), fill=colour)

    if grid:
        step = 46 * SS
        dots = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        dot = ImageDraw.Draw(dots)
        for x in range(0, width, step):
            for y in range(0, height, step):
                dot.ellipse((x, y, x + 2 * SS, y + 2 * SS), fill=(120, 150, 200, 26))
        base = Image.alpha_composite(base.convert("RGBA"), dots).convert("RGB")
        draw = ImageDraw.Draw(base)

    if glow_alpha:
        radius = int(min(width, height) * glow_size)
        cx, cy = int(width * glow_at[0]), int(height * glow_at[1])
        glow = Image.new("L", (radius * 2, radius * 2), 0)
        glow_draw = ImageDraw.Draw(glow)
        steps = 48
        for index in range(steps, 0, -1):
            ratio = index / steps
            value = int(glow_alpha * (1 - ratio) ** 1.7)
            box = (
                radius - int(radius * ratio),
                radius - int(radius * ratio),
                radius + int(radius * ratio),
                radius + int(radius * ratio),
            )
            glow_draw.ellipse(box, fill=value)
        glow = glow.filter(ImageFilter.GaussianBlur(28 * SS))
        halo = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        tint = Image.new("RGB", glow.size, accent)
        halo.paste(tint, (cx - radius, cy - radius), glow)
        base = Image.alpha_composite(base.convert("RGBA"), halo).convert("RGB")

    grain = Image.effect_noise((width, height), 14).convert("L")
    grain_layer = Image.new("RGBA", (width, height), (255, 255, 255, 0))
    grain_layer.putalpha(grain.point(lambda value: int(value * 0.06)))
    base = Image.alpha_composite(base.convert("RGBA"), grain_layer)
    return base


def scrim(image):
    """Darken the bottom edge so overlaid captions stay readable."""
    width, height = image.size
    mask = Image.new("L", (width, height), 0)
    draw = ImageDraw.Draw(mask)
    for index in range(int(height * 0.5)):
        y = height - index
        value = int(190 * (1 - index / (height * 0.5)) ** 1.4)
        draw.line((0, y, width, y), fill=value)
    dark = Image.new("RGBA", (width, height), (4, 6, 13, 255))
    dark.putalpha(mask)
    return Image.alpha_composite(image, dark)


def vignette(image, strength=150):
    width, height = image.size
    mask = Image.new("L", (width, height), 0)
    draw = ImageDraw.Draw(mask)
    steps = 40
    for index in range(steps):
        ratio = index / steps
        inset_x = int(width * 0.5 * ratio * 0.85)
        inset_y = int(height * 0.5 * ratio * 0.85)
        value = int(strength * (ratio ** 2))
        draw.ellipse(
            (inset_x, inset_y, width - inset_x, height - inset_y),
            outline=value,
            width=int(6 * SS) + 2,
        )
    mask = mask.filter(ImageFilter.GaussianBlur(40 * SS))
    dark = Image.new("RGBA", (width, height), (3, 5, 12, 255))
    dark.putalpha(mask)
    return Image.alpha_composite(image, dark)


def layer():
    return Image.new("RGBA", (W * SS, H * SS), (0, 0, 0, 0))


def glow_shape(base, shape, colour, blur=26, alpha=170):
    """Composite a coloured copy of `shape` blurred, behind the crisp shape."""
    halo = layer()
    halo.paste(Image.new("RGB", shape.size, colour), (0, 0), shape)
    halo = halo.filter(ImageFilter.GaussianBlur(blur * SS))
    if alpha < 255:
        faded = halo.getchannel("A").point(lambda value: int(value * alpha / 255))
        halo.putalpha(faded)
    return Image.alpha_composite(base, halo)


def merge(base, shape):
    return Image.alpha_composite(base, shape)


def soft_shadow(base, box, radius=30, alpha=120):
    shadow = layer()
    draw = ImageDraw.Draw(shadow)
    draw.rounded_rectangle(box, radius=radius * SS, fill=(0, 0, 0, alpha))
    shadow = shadow.filter(ImageFilter.GaussianBlur(18 * SS))
    return Image.alpha_composite(base, shadow)


# --------------------------------------------------------------------------- #
# Motifs                                                                      #
# --------------------------------------------------------------------------- #


def motif_key(draw, cx, cy, scale=1.0, colour=CYAN):
    """Padlock with a key in front."""
    s = scale
    body = (cx - 150 * s, cy - 40 * s, cx + 40 * s, cy + 170 * s)
    shackle = (cx - 110 * s, cy - 175 * s, cx + 0 * s, cy - 40 * s)
    draw.rounded_rectangle(body, radius=26 * s, fill=(18, 26, 47, 255), outline=colour + (255,),
                           width=int(7 * s))
    # The shackle has to land on the body, not float above it.
    draw.arc(shackle, 180, 360, fill=colour + (255,), width=int(7 * s))
    for arm_x in (cx - 110 * s, cx + 0 * s):
        draw.line((arm_x, cy - 100 * s, arm_x, cy - 40 * s), fill=colour + (255,), width=int(7 * s))
    draw.ellipse((cx - 78 * s, cy + 22 * s, cx - 32 * s, cy + 68 * s), fill=colour + (255,))
    draw.line((cx - 55 * s, cy + 60 * s, cx - 55 * s, cy + 112 * s), fill=colour + (255,),
              width=int(12 * s))

    # Key: round bow, shaft, two teeth.
    kx, ky = cx + 175 * s, cy + 65 * s
    draw.ellipse((kx - 62 * s, ky - 62 * s, kx + 62 * s, ky + 62 * s), outline=VIOLET + (255,),
                 width=int(10 * s))
    draw.ellipse((kx - 20 * s, ky - 20 * s, kx + 20 * s, ky + 20 * s), fill=VIOLET + (255,))
    draw.line((kx + 55 * s, ky, kx + 205 * s, ky), fill=VIOLET + (255,), width=int(16 * s))
    draw.line((kx + 150 * s, ky, kx + 150 * s, ky + 46 * s), fill=VIOLET + (255,), width=int(14 * s))
    draw.line((kx + 190 * s, ky, kx + 190 * s, ky + 32 * s), fill=VIOLET + (255,), width=int(14 * s))


def motif_usb(draw, cx, cy, scale=1.0, colour=RED):
    s = scale
    body = (cx - 190 * s, cy - 60 * s, cx + 120 * s, cy + 60 * s)
    draw.rounded_rectangle(body, radius=18 * s, fill=(20, 24, 38, 255), outline=(200, 210, 230, 255),
                           width=int(6 * s))
    draw.rectangle((cx + 120 * s, cy - 32 * s, cx + 190 * s, cy + 32 * s), fill=(150, 160, 180, 255))
    draw.rectangle((cx + 132 * s, cy - 20 * s, cx + 150 * s, cy - 8 * s), fill=(60, 68, 88, 255))
    draw.rectangle((cx + 162 * s, cy + 6 * s, cx + 180 * s, cy + 18 * s), fill=(60, 68, 88, 255))
    # Warning triangle behind.
    tri = [(cx - 300 * s, cy + 190 * s), (cx - 150 * s, cy - 110 * s), (cx + 0 * s, cy + 190 * s)]
    draw.line(tri + [tri[0]], fill=colour + (255,), width=int(8 * s), joint="curve")
    draw.line((cx - 150 * s, cy + 20 * s, cx - 150 * s, cy + 110 * s), fill=colour + (255,),
              width=int(12 * s))
    draw.ellipse((cx - 158 * s, cy + 132 * s, cx - 142 * s, cy + 148 * s), fill=colour + (255,))


def motif_envelope(draw, cx, cy, scale=1.0, colour=RED):
    s = scale
    box = (cx - 230 * s, cy - 130 * s, cx + 90 * s, cy + 130 * s)
    draw.rounded_rectangle(box, radius=14 * s, fill=(20, 26, 44, 255), outline=(200, 210, 230, 255),
                           width=int(6 * s))
    draw.line((box[0], box[1], cx - 70 * s, cy + 5 * s), fill=(200, 210, 230, 255), width=int(5 * s))
    draw.line((box[2], box[1], cx - 70 * s, cy + 5 * s), fill=(200, 210, 230, 255), width=int(5 * s))
    # Fish hook coming out of the envelope.
    draw.line((cx - 70 * s, cy + 6 * s, cx + 110 * s, cy - 60 * s), fill=(220, 228, 245, 255),
              width=int(7 * s))
    draw.arc((cx + 40 * s, cy - 200 * s, cx + 210 * s, cy - 30 * s), 200, 20, fill=colour + (255,),
             width=int(9 * s))
    draw.line((cx + 122 * s, cy - 200 * s, cx + 122 * s, cy - 150 * s), fill=colour + (255,),
              width=int(9 * s))


def motif_server_clock(draw, cx, cy, scale=1.0, colour=AMBER):
    s = scale
    for index in range(3):
        top = cy - 190 * s + index * 130 * s
        draw.rounded_rectangle((cx - 260 * s, top, cx + 60 * s, top + 110 * s), radius=12 * s,
                               fill=(17, 24, 40, 255), outline=(120, 136, 170, 255), width=int(5 * s))
        for led in range(4):
            px = cx - 230 * s + led * 26 * s
            draw.ellipse((px, top + 46 * s, px + 12 * s, top + 58 * s), fill=colour + (255,))
        draw.line((cx + 20 * s, top + 30 * s, cx + 50 * s, top + 30 * s), fill=(120, 136, 170, 255),
                  width=int(4 * s))
        draw.line((cx + 20 * s, top + 60 * s, cx + 50 * s, top + 60 * s), fill=(120, 136, 170, 255),
                  width=int(4 * s))
    # Clock.
    clock_c = (cx + 200 * s, cy - 40 * s)
    radius = 120 * s
    draw.ellipse(
        (clock_c[0] - radius, clock_c[1] - radius, clock_c[0] + radius, clock_c[1] + radius),
        fill=(14, 19, 33, 255), outline=colour + (255,), width=int(8 * s),
    )
    draw.line((clock_c[0], clock_c[1], clock_c[0], clock_c[1] - 78 * s), fill=(230, 236, 248, 255),
              width=int(7 * s))
    draw.line((clock_c[0], clock_c[1], clock_c[0] + 54 * s, clock_c[1] + 30 * s), fill=colour + (255,),
              width=int(7 * s))


def motif_logs(draw, cx, cy, scale=1.0, colour=CYAN):
    s = scale
    widths = [420, 360, 400, 300, 380, 250]
    for index, width in enumerate(widths):
        top = cy - 190 * s + index * 66 * s
        shade = 90 + index * 12
        draw.rounded_rectangle((cx - 260 * s, top, cx + (width - 260) * s, top + 26 * s), radius=13 * s,
                               fill=(min(shade, 190), min(shade + 20, 210), min(shade + 50, 235), 255))
    # Magnifier.
    mx, my = cx + 210 * s, cy + 120 * s
    radius = 110 * s
    draw.ellipse((mx - radius, my - radius, mx + radius, my + radius), fill=(10, 15, 28, 120),
                 outline=colour + (255,), width=int(10 * s))
    draw.line((mx + 78 * s, my + 78 * s, mx + 165 * s, my + 165 * s), fill=colour + (255,),
              width=int(16 * s))


def motif_disks(draw, cx, cy, scale=1.0, colour=TEAL):
    s = scale
    for index, dx in enumerate((-190, 60)):
        left = cx + dx * s
        draw.ellipse((left, cy - 150 * s, left + 170 * s, cy - 90 * s), fill=(18, 30, 40, 255),
                     outline=(200, 220, 235, 255), width=int(5 * s))
        draw.rectangle((left, cy - 120 * s, left + 170 * s, cy + 90 * s), fill=(18, 30, 40, 255))
        draw.ellipse((left, cy + 40 * s, left + 170 * s, cy + 100 * s), fill=(18, 30, 40, 255),
                     outline=(200, 220, 235, 255), width=int(5 * s))
        draw.line((left - 1 * s, cy - 120 * s, left - 1 * s, cy + 70 * s), fill=(200, 220, 235, 255),
                  width=int(5 * s))
        draw.line((left + 170 * s, cy - 120 * s, left + 170 * s, cy + 70 * s),
                  fill=(200, 220, 235, 255), width=int(5 * s))
    # Arrow between them.
    draw.line((cx + 10 * s, cy + 150 * s, cx + 200 * s, cy + 150 * s), fill=colour + (255,),
              width=int(9 * s))
    draw.line((cx + 160 * s, cy + 118 * s, cx + 200 * s, cy + 150 * s), fill=colour + (255,),
              width=int(9 * s))
    draw.line((cx + 160 * s, cy + 182 * s, cx + 200 * s, cy + 150 * s), fill=colour + (255,),
              width=int(9 * s))


def motif_soc(draw, cx, cy, scale=1.0, colour=CYAN):
    """Night shift: desk, monitor with a waveform, lit window with a moon."""
    s = scale
    # Window.
    draw.rounded_rectangle((cx - 520 * s, cy - 250 * s, cx - 250 * s, cy + 10 * s), radius=8 * s,
                           fill=(9, 14, 28, 255), outline=(90, 104, 138, 255), width=int(5 * s))
    draw.ellipse((cx - 420 * s, cy - 215 * s, cx - 360 * s, cy - 155 * s), fill=(226, 232, 245, 255))
    # Mullions: the frame has to read as a window, not as an anonymous box.
    draw.line((cx - 385 * s, cy - 250 * s, cx - 385 * s, cy + 10 * s), fill=(90, 104, 138, 255),
              width=int(5 * s))
    draw.line((cx - 520 * s, cy - 120 * s, cx - 250 * s, cy - 120 * s), fill=(90, 104, 138, 255),
              width=int(5 * s))
    for index in range(4):
        rain_x = cx - 480 * s + index * 26 * s
        draw.line((rain_x, cy - 220 * s + index * 14 * s, rain_x - 14 * s, cy - 160 * s + index * 14 * s),
                  fill=(90, 104, 138, 160), width=int(3 * s))
    # Monitor.
    draw.rounded_rectangle((cx - 190 * s, cy - 210 * s, cx + 330 * s, cy + 110 * s), radius=14 * s,
                           fill=(10, 15, 28, 255), outline=colour + (255,), width=int(6 * s))
    points = []
    for index in range(0, 60):
        x = cx - 170 * s + index * 8 * s
        y = cy - 60 * s + int(math.sin(index / 3.1) * 44 * s)
        points.append((x, y))
    draw.line(points, fill=colour + (255,), width=int(5 * s))
    draw.line((cx - 170 * s, cy + 60 * s, cx + 310 * s, cy + 60 * s), fill=(70, 84, 116, 255),
              width=int(4 * s))
    draw.line((cx + 70 * s, cy + 110 * s, cx + 70 * s, cy + 190 * s), fill=(120, 136, 170, 255),
              width=int(10 * s))
    draw.line((cx - 60 * s, cy + 200 * s, cx + 200 * s, cy + 200 * s), fill=(120, 136, 170, 255),
              width=int(10 * s))
    # Phone ringing.
    draw.rounded_rectangle((cx + 380 * s, cy + 20 * s, cx + 470 * s, cy + 170 * s), radius=12 * s,
                           fill=(16, 22, 40, 255), outline=AMBER + (255,), width=int(5 * s))
    for index, inset in enumerate((0, 18, 36)):
        draw.arc(
            (cx + 480 * s + inset * s, cy + 30 * s + inset * s, cx + 560 * s + inset * s,
             cy + 120 * s + inset * s),
            300, 60, fill=AMBER + (255,), width=int(5 * s),
        )


def motif_graph(draw, cx, cy, scale=1.0, colour=VIOLET):
    s = scale
    nodes = [
        (cx - 380 * s, cy - 60 * s),
        (cx - 190 * s, cy - 190 * s),
        (cx - 190 * s, cy + 80 * s),
        (cx + 10 * s, cy - 60 * s),
        (cx + 210 * s, cy + 60 * s),
        (cx + 400 * s, cy - 120 * s),
    ]
    edges = [(0, 1), (0, 2), (1, 3), (2, 3), (3, 4), (4, 5)]
    for a, b in edges:
        draw.line((nodes[a], nodes[b]), fill=(120, 140, 190, 200), width=int(5 * s))
    for index, (x, y) in enumerate(nodes):
        radius = 26 * s if index != 5 else 32 * s
        fill = colour + (255,) if index != 5 else RED + (255,)
        draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=fill)
    draw.line((nodes[5], (cx + 560 * s, cy - 230 * s)), fill=RED + (255,), width=int(7 * s))
    draw.line((cx + 500 * s, cy - 236 * s, cx + 560 * s, cy - 230 * s), fill=RED + (255,),
              width=int(7 * s))
    draw.line((cx + 528 * s, cy - 268 * s, cx + 560 * s, cy - 230 * s), fill=RED + (255,),
              width=int(7 * s))


def motif_phone(draw, cx, cy, scale=1.0, colour=AMBER):
    s = scale
    draw.rounded_rectangle((cx - 110 * s, cy - 230 * s, cx + 110 * s, cy + 210 * s), radius=26 * s,
                           fill=(14, 19, 34, 255), outline=(210, 220, 240, 255), width=int(6 * s))
    draw.rounded_rectangle((cx - 84 * s, cy - 150 * s, cx + 84 * s, cy + 130 * s), radius=12 * s,
                           fill=(18, 26, 46, 255), outline=colour + (255,), width=int(4 * s))
    draw.line((cx - 40 * s, cy + 190 * s, cx + 40 * s, cy + 190 * s), fill=(210, 220, 240, 255),
              width=int(6 * s))
    for index, inset in enumerate((0, 26, 52)):
        draw.arc(
            (cx - 150 * s - inset * s, cy - 300 * s - inset * s,
             cx + 150 * s + inset * s, cy + 280 * s + inset * s),
            200, 340, fill=colour + (150 - index * 30,), width=int(5 * s),
        )


def motif_contained(draw, cx, cy, scale=1.0, colour=TEAL):
    s = scale
    # Machine boxed by a dashed containment square.
    draw.rounded_rectangle((cx - 120 * s, cy - 110 * s, cx + 120 * s, cy + 90 * s), radius=12 * s,
                           fill=(16, 30, 34, 255), outline=(200, 226, 230, 255), width=int(5 * s))
    draw.rectangle((cx - 70 * s, cy - 150 * s, cx + 70 * s, cy - 110 * s), fill=(16, 30, 34, 255),
                   outline=(200, 226, 230, 255), width=int(5 * s))
    dash, gap = 26 * s, 18 * s
    left, top, right, bottom = cx - 260 * s, cy - 230 * s, cx + 260 * s, cy + 210 * s
    x = left
    while x < right:
        draw.line((x, top, min(x + dash, right), top), fill=colour + (255,), width=int(6 * s))
        draw.line((x, bottom, min(x + dash, right), bottom), fill=colour + (255,), width=int(6 * s))
        x += dash + gap
    y = top
    while y < bottom:
        draw.line((left, y, left, min(y + dash, bottom)), fill=colour + (255,), width=int(6 * s))
        draw.line((right, y, right, min(y + dash, bottom)), fill=colour + (255,), width=int(6 * s))
        y += dash + gap


def motif_room(draw, cx, cy, scale=1.0, colour=VIOLET):
    s = scale
    # Screen at the back with a chart.
    draw.rounded_rectangle((cx - 240 * s, cy - 230 * s, cx + 240 * s, cy - 40 * s), radius=10 * s,
                           fill=(12, 17, 32, 255), outline=colour + (255,), width=int(5 * s))
    bars = [60, 120, 90, 160, 110]
    for index, height in enumerate(bars):
        left = cx - 200 * s + index * 80 * s
        draw.rectangle((left, cy - 60 * s - height * s, left + 48 * s, cy - 60 * s),
                       fill=colour + (200,))
    # Table and chairs.
    draw.ellipse((cx - 260 * s, cy + 40 * s, cx + 260 * s, cy + 210 * s), fill=(20, 26, 44, 255),
                 outline=(150, 165, 200, 255), width=int(5 * s))
    for angle in (200, 250, 290, 340):
        rad = math.radians(angle)
        px = cx + math.cos(rad) * 320 * s
        py = cy + 130 * s + math.sin(rad) * 130 * s
        draw.ellipse((px - 34 * s, py - 34 * s, px + 34 * s, py + 34 * s), fill=(190, 200, 225, 255))


def motif_chair(draw, cx, cy, scale=1.0, colour=(120, 140, 180)):
    s = scale
    draw.polygon(
        [(cx - 60 * s, cy + 120 * s), (cx + 60 * s, cy + 120 * s), (cx + 110 * s, cy + 250 * s),
         (cx - 110 * s, cy + 250 * s)],
        fill=(16, 21, 36, 255),
    )
    draw.rounded_rectangle((cx - 70 * s, cy - 160 * s, cx + 70 * s, cy + 110 * s), radius=16 * s,
                           fill=(16, 21, 36, 255), outline=colour + (255,), width=int(5 * s))
    draw.line((cx, cy + 250 * s, cx, cy + 300 * s), fill=colour + (255,), width=int(8 * s))


def motif_sunrise(draw, cx, cy, scale=1.0, colour=AMBER):
    s = scale
    draw.ellipse((cx - 150 * s, cy - 130 * s, cx + 150 * s, cy + 170 * s), fill=colour + (255,))
    for index in range(12):
        angle = math.radians(index * 30)
        x1 = cx + math.cos(angle) * 210 * s
        y1 = cy + 20 * s + math.sin(angle) * 210 * s
        x2 = cx + math.cos(angle) * 300 * s
        y2 = cy + 20 * s + math.sin(angle) * 300 * s
        draw.line((x1, y1, x2, y2), fill=colour + (200,), width=int(7 * s))
    draw.rectangle((0, cy + 170 * s, W * SS, H * SS), fill=(9, 12, 24, 255))



def motif_2fa(draw, cx, cy, scale=1.0, colour=TEAL):
    """Shield + phone showing a six-digit code."""
    s = scale
    shield = [
        (cx - 250 * s, cy - 230 * s), (cx + 40 * s, cy - 230 * s), (cx + 40 * s, cy + 40 * s),
        (cx - 105 * s, cy + 200 * s), (cx - 250 * s, cy + 40 * s),
    ]
    draw.line(shield + [shield[0]], fill=colour + (255,), width=int(7 * s), joint="curve")
    draw.rounded_rectangle((cx - 70 * s, cy - 120 * s, cx + 250 * s, cy + 250 * s), radius=26 * s,
                           fill=(12, 20, 26, 255), outline=(214, 232, 236, 255), width=int(6 * s))
    for index in range(6):
        left = cx - 34 * s + (index % 3) * 92 * s
        top = cy - 46 * s + (index // 3) * 96 * s
        draw.rounded_rectangle((left, top, left + 62 * s, top + 62 * s), radius=10 * s,
                               fill=(20, 44, 48, 255), outline=colour + (200,), width=int(3 * s))
        draw.ellipse((left + 27 * s, top + 27 * s, left + 35 * s, top + 35 * s), fill=colour + (255,))


def motif_laptop_lock(draw, cx, cy, scale=1.0, colour=CYAN):
    """Laptop with an encrypted-disk lockdown badge."""
    s = scale
    draw.rounded_rectangle((cx - 330 * s, cy - 250 * s, cx + 330 * s, cy + 110 * s), radius=16 * s,
                           fill=(13, 19, 33, 255), outline=(206, 216, 236, 255), width=int(6 * s))
    draw.rounded_rectangle((cx - 300 * s, cy - 220 * s, cx + 300 * s, cy + 80 * s), radius=8 * s,
                           fill=(17, 24, 42, 255), outline=(90, 104, 138, 255), width=int(4 * s))
    draw.polygon(
        [(cx - 420 * s, cy + 110 * s), (cx + 420 * s, cy + 110 * s), (cx + 360 * s, cy + 168 * s),
         (cx - 360 * s, cy + 168 * s)],
        fill=(28, 36, 56, 255), outline=(206, 216, 236, 255),
    )
    # Lock badge.
    draw.rounded_rectangle((cx - 90 * s, cy - 60 * s, cx + 90 * s, cy + 70 * s), radius=18 * s,
                           fill=(10, 15, 28, 255), outline=colour + (255,), width=int(7 * s))
    draw.arc((cx - 60 * s, cy - 130 * s, cx + 60 * s, cy - 20 * s), 180, 360, fill=colour + (255,),
             width=int(7 * s))
    for arm_x in (cx - 60 * s, cx + 60 * s):
        draw.line((arm_x, cy - 75 * s, arm_x, cy - 55 * s), fill=colour + (255,), width=int(7 * s))
    draw.ellipse((cx - 16 * s, cy - 12 * s, cx + 16 * s, cy + 20 * s), fill=colour + (255,))


def motif_radar(draw, cx, cy, scale=1.0, colour=VIOLET):
    """Lateral movement: radar rings, a sweep and a hostile dot."""
    s = scale
    for index, radius in enumerate((150, 250, 350)):
        draw.ellipse((cx - radius * s, cy - radius * s, cx + radius * s, cy + radius * s),
                     outline=(120, 140, 190, 150 - index * 30), width=int(5 * s))
    draw.line((cx - 380 * s, cy, cx + 380 * s, cy), fill=(90, 104, 138, 120), width=int(3 * s))
    draw.line((cx, cy - 380 * s, cx, cy + 380 * s), fill=(90, 104, 138, 120), width=int(3 * s))
    # Sweep wedge.
    draw.pieslice((cx - 350 * s, cy - 350 * s, cx + 350 * s, cy + 350 * s), 300, 350,
                  fill=colour + (60,))
    draw.line((cx, cy, cx + 300 * s, cy - 175 * s), fill=colour + (220,), width=int(5 * s))
    draw.ellipse((cx - 12 * s, cy - 12 * s, cx + 12 * s, cy + 12 * s), fill=(220, 230, 250, 255))
    # Hostile dot.
    hx, hy = cx + 190 * s, cy + 150 * s
    draw.ellipse((hx - 20 * s, hy - 20 * s, hx + 20 * s, hy + 20 * s), fill=RED + (255,))
    draw.ellipse((hx - 46 * s, hy - 46 * s, hx + 46 * s, hy + 46 * s), outline=RED + (170,),
                 width=int(4 * s))


def motif_bad_dawn(draw, cx, cy, scale=1.0, colour=(120, 140, 180)):
    """Cold dawn after a failed containment."""
    s = scale
    draw.ellipse((cx - 130 * s, cy - 120 * s, cx + 130 * s, cy + 140 * s), fill=colour + (255,))
    draw.rectangle((0, cy + 140 * s, W * SS, H * SS), fill=(9, 12, 24, 255))
    # Downward trend arrow over the horizon.
    draw.line((cx - 260 * s, cy + 210 * s, cx + 240 * s, cy + 300 * s), fill=RED + (255,),
              width=int(7 * s))
    draw.line((cx + 240 * s, cy + 300 * s, cx + 170 * s, cy + 300 * s), fill=RED + (255,),
              width=int(7 * s))
    draw.line((cx + 240 * s, cy + 300 * s, cx + 250 * s, cy + 235 * s), fill=RED + (255,),
              width=int(7 * s))


# --------------------------------------------------------------------------- #
# Scenes                                                                      #
# --------------------------------------------------------------------------- #


def scene(motif, colour, name, accent_glow=None, glow_at=(0.5, 0.42), scale=1.18,
          motif_at=(0.5, 0.47), vignette_strength=170, top=BG_TOP, bottom=BG_BOTTOM,
          grid=True):
    base = canvas(top=top, bottom=bottom, accent=accent_glow or colour, glow_at=glow_at, grid=grid)
    shape = layer()
    draw = ImageDraw.Draw(shape)
    motif(draw, int(W * SS * motif_at[0]), int(H * SS * motif_at[1]), scale, colour)
    base = glow_shape(base, shape.getchannel("A").point(lambda v: v), colour, blur=30, alpha=90)
    base = merge(base, shape)
    base = vignette(base, vignette_strength)
    base = scrim(base)
    image = base.convert("RGB").resize((W, H), Image.LANCZOS)
    path = os.path.join(OUT, f"{name}.jpg")
    image.save(path, "JPEG", quality=88, optimize=True)
    size = os.path.getsize(path)
    print(f"{name:22} {size // 1024:4} KB")
    return path


def main():
    os.makedirs(OUT, exist_ok=True)
    random.seed(7)
    # Swipe deck: one illustration per statement.
    scene(motif_key, CYAN, "swipe-password")
    scene(motif_usb, RED, "swipe-usb", accent_glow=AMBER, glow_at=(0.45, 0.4), scale=1.05)
    scene(motif_2fa, TEAL, "swipe-2fa", glow_at=(0.45, 0.45), scale=1.0)
    scene(motif_envelope, RED, "swipe-phishing", glow_at=(0.5, 0.45), scale=1.05)
    scene(motif_laptop_lock, CYAN, "swipe-disk", glow_at=(0.5, 0.45), scale=0.95)
    scene(motif_server_clock, AMBER, "swipe-patch", glow_at=(0.5, 0.4), scale=1.0)
    scene(motif_logs, CYAN, "swipe-logs", glow_at=(0.45, 0.4), scale=1.0)
    scene(motif_disks, TEAL, "swipe-backup", glow_at=(0.5, 0.45), scale=1.05)
    # Story nodes.
    scene(motif_soc, CYAN, "story-start", glow_at=(0.45, 0.4), scale=1.0)
    scene(motif_graph, VIOLET, "story-analyse", glow_at=(0.5, 0.45), scale=1.0)
    scene(motif_phone, AMBER, "story-escalation", glow_at=(0.5, 0.4), scale=1.05)
    scene(motif_radar, VIOLET, "story-surveillance", glow_at=(0.5, 0.45), scale=0.95)
    # Endings.
    scene(motif_contained, TEAL, "ending-contained", glow_at=(0.5, 0.45), scale=1.0)
    scene(motif_room, VIOLET, "ending-report", glow_at=(0.5, 0.35), scale=1.0)
    scene(motif_bad_dawn, RED, "ending-exfiltration", glow_at=(0.5, 0.3), grid=False, scale=1.0)
    scene(motif_chair, (110, 130, 175), "ending-death", glow_at=(0.5, 0.35),
          vignette_strength=210, scale=1.0)
    scene(motif_sunrise, AMBER, "ending-victory", glow_at=(0.5, 0.35), grid=False, scale=1.0)


if __name__ == "__main__":
    main()
