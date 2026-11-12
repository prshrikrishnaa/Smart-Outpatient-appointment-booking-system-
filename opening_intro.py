# =============================================================================
#   SMART OPD  -  3D-STYLE OPENING INTRO
#   Paste this whole block into app.py (above your existing intro code), or
#   keep it as opening_intro.py and:  from opening_intro import OpeningIntro
#
#   Needs:  pip install pillow numpy      (numpy is optional,
#           but it gives the real rotating 3D globe)
#
#   Everything is drawn from code - no image files needed.
# =============================================================================
import math
import os
import random
import sys
import time
import traceback
import tkinter as tk

from PIL import (Image, ImageChops, ImageDraw, ImageFilter, ImageFont,
                 ImageOps, ImageTk)

try:
    import numpy as np
except Exception:          # the globe falls back to a flat scrolling globe
    np = None


# =============================================================================
#  1.  CONFIGURATION  -  change everything important here
# =============================================================================
PROJECT_NAME        = "Home visit"
SUBTITLE            = "illam thedi maruthuvam"

INTRO_DURATION      = 10.0          # nominal length of the opening (seconds)
ANIMATION_SPEED     = 1.0           # 1.0 normal, 1.3 faster, 0.8 slower
TRANSITION_DURATION = 0.9           # seconds of the circular wipe into your ECG intro
TRANSITION_COLOR    = "#0b1220"     # set this to the first colour of your ECG scene
FPS                 = 60            # lower to 30 on very weak laptops

BG_TOP              = "#0a84ff"     # sky gradient (top)
BG_BOTTOM           = "#86e4ff"     # sky gradient (bottom)
SHOW_FRAME_GLOW     = True          # glowing cyan frame like the reference

MEDICAL_ELEMENT_COUNT = 12          # 1 - 12 orbiting objects
GLOBE_SIZE_RATIO    = 0.56          # globe diameter / window height at the start
TITLE_SIZE_RATIO    = 0.19          # title font height / window height
TITLE_FONT_FILES    = [             # first one found is used (put your own .ttf first)
  "assets/fonts/subtitle.ttf",
    "C:/Windows/Fonts/segoeuib.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "DejaVuSans-Bold.ttf",

]
SUBTITLE_FONT_FILES = [
      "assets/fonts/subtitle.ttf",
    "C:/Windows/Fonts/NirmalaB.ttf",
    "C:/Windows/Fonts/segoeuib.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "DejaVuSans-Bold.ttf",
]
SKIP_TEXT           = "SKIP INTRO  \u203a"
SHOW_SKIP_BUTTON    = True          # draws a SKIP INTRO button on the opening canvas

# ---- timeline (in "base seconds" of a 10 s intro; scaled by INTRO_DURATION) --
T_GLOBE   = 1.5      # globe pops in
T_EXIT    = 5.5      # non-staying objects fly away
T_SETTLE  = 5.9      # objects glide into the balanced composition
T_LOGO    = 6.2      # doctor-on-bike logo pops on the globe
T_TITLE   = 6.45     # SMART OPD letters shoot out
T_SUB     = 7.75     # subtitle reveal
T_TRANS   = 9.0      # circular wipe into the existing intro
LETTER_STAGGER = 0.055
LETTER_DUR     = 0.60

# (name, ring, radius multiplier, angular speed, start phase, enter time, stays?)
ITEMS = [
    ("doctor_m",    0, 1.00,  0.55, 0.00, 2.10, True),
    ("stethoscope", 1, 1.00, -0.62, 1.00, 2.50, True),
    ("calendar",    2, 1.00,  0.80, 2.00, 2.90, True),
    ("heart",       0, 1.00,  0.50, 3.30, 3.30, True),
    ("capsule",     1, 1.00, -0.70, 4.20, 3.60, False),
    ("doctor_f",    2, 1.00,  0.70, 5.20, 4.00, True),
    ("ambulance",   1, 1.00, -0.45, 0.40, 4.30, True),
    ("record",      0, 1.00,  0.60, 4.90, 4.60, True),
    ("syringe",     2, 1.00,  0.90, 0.90, 4.80, False),
    ("card",        0, 1.00, -0.50, 2.10, 5.00, False),
    ("home",        2, 1.00, -0.75, 3.10, 5.10, True),
    ("clock",       1, 1.00,  0.65, 5.70, 5.25, False),
]
# orbit rings: (tilt sine, roll degrees, radius multiplier)
RINGS = [(0.30, -16, 1.00), (0.36, 20, 1.10), (0.24, -4, 0.86)]
# final positions (fraction of width, height) of the objects that stay
ANCHORS = [(0.14, 0.20), (0.86, 0.20), (0.07, 0.44), (0.93, 0.44),
           (0.16, 0.64), (0.84, 0.64), (0.08, 0.86), (0.92, 0.86)]


# =============================================================================
#  2.  SMALL HELPERS
# =============================================================================
def clamp(v, a=0.0, b=1.0):
    return a if v < a else b if v > b else v


def lerp(a, b, t):
    return a + (b - a) * t


def prog(t, a, b):
    return clamp((t - a) / (b - a)) if b > a else 1.0


def ease_out(t):
    return 1 - (1 - t) ** 3


def ease_in(t):
    return t ** 3


def ease_io(t):
    return t * t * (3 - 2 * t)


def ease_back(t, s=1.70158):
    t -= 1
    return 1 + (s + 1) * t ** 3 + s * t ** 2


def hex_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _base_dirs():
    dirs = [os.getcwd()]
    try:
        dirs.append(os.path.dirname(os.path.abspath(__file__)))
    except Exception:
        pass
    try:
        dirs.append(os.path.dirname(os.path.abspath(sys.argv[0])))
    except Exception:
        pass
    return dirs


def resolve_path(path):
    if os.path.isabs(path):
        return path if os.path.exists(path) else None
    for b in _base_dirs():
        p = os.path.join(b, path)
        if os.path.exists(p):
            return p
    return None


def load_font(files, size):
    for f in files:
        for p in ([f] if os.path.isabs(f) else [f] + [os.path.join(b, f) for b in _base_dirs()]):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                continue
    for name in ("DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf", "arialbd.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            pass
    try:
        return ImageFont.load_default(size)
    except Exception:
        return ImageFont.load_default()


# =============================================================================
#  4.  PROCEDURAL ARTWORK (all drawn with Pillow, nothing external)
# =============================================================================
SPR = 160           # base sprite size in px
SS = 3              # supersampling
K = SS * SPR / 100.0


def _new():
    im = Image.new("RGBA", (SPR * SS, SPR * SS), (0, 0, 0, 0))
    return im, ImageDraw.Draw(im)


def _k(*v):
    return [x * K for x in v]


def _pline(d, pts, w, fill):
    pp = [(x * K, y * K) for x, y in pts]
    d.line(pp, fill=fill, width=int(w * K), joint="curve")
    r = w * K / 2
    for x, y in (pp[0], pp[-1]):
        d.ellipse([x - r, y - r, x + r, y + r], fill=fill)


def _overlay(im, fn):
    ov = Image.new("RGBA", im.size, (0, 0, 0, 0))
    fn(ImageDraw.Draw(ov))
    return Image.alpha_composite(im, ov)


def _sticker(im):
    """downscale + glossy white outline + soft shadow (gives the 3D 'sticker' look)"""
    inner = int(SPR * 0.86)
    im = im.resize((inner, inner), Image.LANCZOS)
    canvas = Image.new("RGBA", (SPR, SPR), (0, 0, 0, 0))
    canvas.paste(im, ((SPR - inner) // 2, (SPR - inner) // 2))
    im = canvas
    a = im.split()[3]
    outline = a.filter(ImageFilter.MaxFilter(7))
    shadow = Image.new("RGBA", im.size, (5, 45, 120, 0))
    shadow.putalpha(outline.filter(ImageFilter.GaussianBlur(4)).point(lambda v: int(v * 0.45)))
    shadow = ImageChops.offset(shadow, 0, 5)
    white = Image.new("RGBA", im.size, (255, 255, 255, 255))
    white.putalpha(outline)
    out = Image.new("RGBA", im.size, (0, 0, 0, 0))
    for layer in (shadow, white, im):
        out = Image.alpha_composite(out, layer)
    return out


def spr_stethoscope():
    im, d = _new()
    dark = (38, 54, 84, 255)
    _pline(d, [(30, 14), (30, 40), (40, 60), (50, 66)], 5, dark)
    _pline(d, [(70, 14), (70, 40), (60, 60), (50, 66)], 5, dark)
    _pline(d, [(50, 66), (50, 74)], 5, dark)
    for x in (30, 70):
        d.ellipse(_k(x - 5, 9, x + 5, 20), fill=(205, 215, 230, 255), outline=dark, width=int(1.5 * K))
    d.ellipse(_k(35, 70, 65, 100), fill=(190, 205, 225, 255), outline=dark, width=int(2 * K))
    d.ellipse(_k(43, 78, 57, 92), fill=(20, 170, 190, 255))
    return _sticker(im)


def spr_doctor(female):
    im, d = _new()
    skin = (255, 214, 172, 255)
    line = (160, 185, 215, 255)
    hair = (95, 55, 35, 255) if female else (35, 28, 28, 255)
    scrub = (240, 100, 150, 255) if female else (30, 170, 205, 255)
    if female:
        d.rounded_rectangle(_k(26, 28, 74, 66), radius=14 * K, fill=hair)
        d.ellipse(_k(41, 4, 59, 22), fill=hair)
    d.rounded_rectangle(_k(16, 58, 84, 98), radius=14 * K, fill=(255, 255, 255, 255),
                        outline=line, width=int(1.6 * K))
    d.polygon(_k(40, 58, 60, 58, 50, 78), fill=scrub)
    d.rectangle(_k(45, 50, 55, 62), fill=skin)
    d.ellipse(_k(31, 14, 69, 56), fill=skin)
    if female:
        d.chord(_k(29, 11, 71, 53), 185, 355, fill=hair)
    else:
        d.chord(_k(30, 11, 70, 49), 185, 355, fill=hair)
    d.ellipse(_k(41, 36, 46, 41), fill=(40, 40, 60, 255))
    d.ellipse(_k(54, 36, 59, 41), fill=(40, 40, 60, 255))
    d.arc(_k(43, 40, 57, 51), 20, 160, fill=(170, 70, 60, 255), width=int(1.8 * K))
    _pline(d, [(36, 60), (39, 78), (50, 87), (61, 78), (64, 60)], 2.6, (40, 56, 84, 255))
    d.ellipse(_k(45, 86, 55, 96), fill=(200, 210, 225, 255), outline=(40, 56, 84, 255), width=int(1.4 * K))
    d.rectangle(_k(68, 76, 72, 86), fill=(230, 60, 70, 255))
    d.rectangle(_k(65, 79, 75, 83), fill=(230, 60, 70, 255))
    return _sticker(im)


def spr_capsule():
    im, d = _new()
    red, white = (232, 55, 70, 255), (250, 250, 252, 255)
    d.rounded_rectangle(_k(8, 36, 92, 64), radius=14 * K, fill=red)
    half = Image.new("RGBA", im.size, (0, 0, 0, 0))
    ImageDraw.Draw(half).rectangle(_k(50, 36, 92, 64), fill=white)
    mask = Image.new("L", im.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle(_k(8, 36, 92, 64), radius=14 * K, fill=255)
    half.putalpha(ImageChops.multiply(half.split()[3], mask))
    im = Image.alpha_composite(im, half)
    im = _overlay(im, lambda o: o.rounded_rectangle(_k(14, 40, 86, 46), radius=3 * K, fill=(255, 255, 255, 110)))
    im = im.rotate(40, resample=Image.BICUBIC)
    return _sticker(im)


def spr_syringe():
    im, d = _new()
    glass, edge = (228, 242, 255, 255), (80, 110, 150, 255)
    d.rounded_rectangle(_k(22, 42, 70, 58), radius=3 * K, fill=glass, outline=edge, width=int(1.6 * K))
    d.rectangle(_k(25, 45, 55, 55), fill=(40, 160, 255, 255))
    for x in (32, 40, 48, 56, 64):
        d.line(_k(x, 42, x, 46), fill=edge, width=int(1.2 * K))
    d.polygon(_k(22, 44, 13, 48, 13, 52, 22, 56), fill=(200, 210, 225, 255), outline=edge)
    d.line(_k(13, 50, 2, 50), fill=(170, 180, 195, 255), width=int(1.8 * K))
    d.rectangle(_k(68, 36, 72, 64), fill=(120, 135, 160, 255))
    d.rectangle(_k(72, 48, 88, 52), fill=(150, 165, 185, 255))
    d.rectangle(_k(88, 40, 92, 60), fill=(100, 115, 140, 255))
    im = im.rotate(45, resample=Image.BICUBIC)
    return _sticker(im)


def spr_calendar():
    im, d = _new()
    d.rounded_rectangle(_k(16, 18, 84, 88), radius=9 * K, fill=(255, 255, 255, 255),
                        outline=(120, 150, 190, 255), width=int(2 * K))
    d.rounded_rectangle(_k(16, 18, 84, 38), radius=9 * K, fill=(235, 60, 70, 255))
    d.rectangle(_k(16, 30, 84, 38), fill=(235, 60, 70, 255))
    for x in (34, 66):
        d.rounded_rectangle(_k(x - 3, 10, x + 3, 26), radius=3 * K, fill=(70, 80, 110, 255))
    for r in range(3):
        for c in range(4):
            x, y = 24 + c * 15, 46 + r * 13
            d.rounded_rectangle(_k(x, y, x + 9, y + 8), radius=2 * K, fill=(205, 222, 245, 255))
    d.ellipse(_k(56, 58, 84, 86), fill=(40, 190, 110, 255), outline=(255, 255, 255, 255), width=int(2 * K))
    _pline(d, [(63, 72), (68, 77), (77, 66)], 3.2, (255, 255, 255, 255))
    return _sticker(im)


def spr_card():
    W = SPR * SS
    base = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    grad = ImageOps.colorize(Image.linear_gradient("L").resize((W, W)), black=(30, 110, 245), white=(125, 70, 225))
    mask = Image.new("L", (W, W), 0)
    ImageDraw.Draw(mask).rounded_rectangle(_k(14, 30, 86, 72), radius=7 * K, fill=255)
    base.paste(grad, (0, 0), mask)
    d = ImageDraw.Draw(base)
    d.rectangle(_k(14, 36, 86, 42), fill=(20, 30, 70, 255))
    d.rounded_rectangle(_k(21, 46, 35, 57), radius=3 * K, fill=(255, 214, 90, 255))
    for i in range(4):
        d.rounded_rectangle(_k(21 + i * 13, 64, 21 + i * 13 + 9, 67), radius=1 * K, fill=(235, 240, 255, 255))
    d.ellipse(_k(64, 56, 75, 67), fill=(235, 60, 70, 255))
    d.ellipse(_k(71, 56, 82, 67), fill=(255, 190, 40, 255))
    base = base.rotate(14, resample=Image.BICUBIC)
    return _sticker(base)


def spr_home():
    im, d = _new()
    d.rectangle(_k(22, 48, 78, 90), fill=(255, 255, 255, 255), outline=(120, 150, 190, 255), width=int(1.6 * K))
    d.rectangle(_k(66, 22, 75, 40), fill=(180, 80, 70, 255))
    d.polygon(_k(11, 52, 50, 15, 89, 52), fill=(232, 66, 78, 255), outline=(160, 40, 55, 255))
    d.rectangle(_k(44, 33, 56, 37), fill=(255, 255, 255, 255))
    d.rectangle(_k(48, 29, 52, 41), fill=(255, 255, 255, 255))
    d.rounded_rectangle(_k(43, 62, 57, 90), radius=3 * K, fill=(45, 130, 235, 255))
    d.rectangle(_k(28, 57, 38, 68), fill=(170, 220, 255, 255), outline=(120, 150, 190, 255))
    d.rectangle(_k(62, 57, 72, 68), fill=(170, 220, 255, 255), outline=(120, 150, 190, 255))
    d.rectangle(_k(65, 61, 69, 64), fill=(230, 60, 70, 255))
    d.rectangle(_k(66.5, 59, 68, 66), fill=(230, 60, 70, 255))
    return _sticker(im)


def spr_ambulance():
    im, d = _new()
    gray = (120, 145, 180, 255)
    d.rounded_rectangle(_k(8, 34, 74, 74), radius=6 * K, fill=(255, 255, 255, 255), outline=gray, width=int(1.6 * K))
    d.polygon(_k(72, 44, 72, 74, 94, 74, 94, 56, 84, 44), fill=(255, 255, 255, 255), outline=gray)
    d.polygon(_k(76, 48, 76, 58, 90, 58, 84, 48), fill=(150, 215, 255, 255))
    d.rectangle(_k(9, 62, 93, 67), fill=(230, 60, 70, 255))
    d.rectangle(_k(27, 42, 41, 48), fill=(230, 60, 70, 255))
    d.rectangle(_k(31, 38, 37, 52), fill=(230, 60, 70, 255))
    d.rounded_rectangle(_k(38, 27, 50, 34), radius=2 * K, fill=(60, 130, 255, 255))
    for cx in (26, 80):
        d.ellipse(_k(cx - 10, 66, cx + 10, 86), fill=(40, 50, 70, 255))
        d.ellipse(_k(cx - 4, 72, cx + 4, 80), fill=(190, 200, 215, 255))
    return _sticker(im)


def spr_heart():
    im, d = _new()
    pts = []
    for i in range(120):
        t = 2 * math.pi * i / 120
        x = 16 * math.sin(t) ** 3
        y = -(13 * math.cos(t) - 5 * math.cos(2 * t) - 2 * math.cos(3 * t) - math.cos(4 * t))
        pts.append(((50 + x * 2.7) * K, (40 + y * 2.7) * K))
    d.polygon(pts, fill=(235, 50, 72, 255), outline=(170, 20, 45, 255), width=int(2 * K))
    im = _overlay(im, lambda o: o.ellipse(_k(20, 18, 42, 36), fill=(255, 255, 255, 110)))
    d = ImageDraw.Draw(im)
    _pline(d, [(18, 52), (36, 52), (42, 40), (49, 66), (57, 30), (63, 52), (82, 52)], 3.4, (255, 255, 255, 255))
    return _sticker(im)


def spr_record():
    im, d = _new()
    d.rounded_rectangle(_k(20, 14, 80, 92), radius=6 * K, fill=(165, 112, 70, 255))
    d.rounded_rectangle(_k(26, 24, 74, 86), radius=3 * K, fill=(255, 255, 255, 255))
    d.rounded_rectangle(_k(38, 8, 62, 24), radius=4 * K, fill=(185, 195, 210, 255), outline=(110, 125, 150, 255), width=int(1.5 * K))
    d.rectangle(_k(44, 33, 56, 37), fill=(230, 60, 70, 255))
    d.rectangle(_k(48, 29, 52, 41), fill=(230, 60, 70, 255))
    for i in range(4):
        d.rounded_rectangle(_k(32, 48 + i * 9, 68 - (i % 2) * 12, 51 + i * 9), radius=1.5 * K, fill=(190, 205, 228, 255))
    return _sticker(im)


def spr_clock():
    im, d = _new()
    d.ellipse(_k(12, 12, 88, 88), fill=(255, 255, 255, 255), outline=(30, 130, 235, 255), width=int(5 * K))
    for i in range(12):
        a = math.radians(i * 30)
        d.line(_k(50 + 31 * math.cos(a), 50 + 31 * math.sin(a), 50 + 35 * math.cos(a), 50 + 35 * math.sin(a)),
               fill=(70, 90, 130, 255), width=int(2 * K))
    _pline(d, [(50, 50), (50, 24)], 3.4, (35, 50, 85, 255))
    _pline(d, [(50, 50), (66, 58)], 3.8, (230, 60, 70, 255))
    d.ellipse(_k(46, 46, 54, 54), fill=(35, 50, 85, 255))
    return _sticker(im)


SPRITE_BUILDERS = {
    "stethoscope": spr_stethoscope, "doctor_m": lambda: spr_doctor(False),
    "doctor_f": lambda: spr_doctor(True), "capsule": spr_capsule, "syringe": spr_syringe,
    "calendar": spr_calendar, "card": spr_card, "home": spr_home, "ambulance": spr_ambulance,
    "heart": spr_heart, "record": spr_record, "clock": spr_clock,
}


# ---------------------------------------------------------------- LOGO -------
LOGO_PX = 420


def _ik(a, b, l1, l2, bend):
    dx, dy = b[0] - a[0], b[1] - a[1]
    d = max(abs(l1 - l2) + 0.01, min(math.hypot(dx, dy), l1 + l2 - 0.01))
    base = math.atan2(dy, dx)
    ca = (l1 * l1 + d * d - l2 * l2) / (2 * l1 * d)
    ang = base + bend * math.acos(max(-1.0, min(1.0, ca)))
    return a[0] + l1 * math.cos(ang), a[1] + l1 * math.sin(ang)


def _rider(i, f):
    """Doctor in white coat pedalling a bike. Design space 400x400, frame i of 12."""
    W = int(400 * f)
    im = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    P = lambda x, y: (x * f, y * f)

    def line(pts, w, fill):
        pp = [P(*p) for p in pts]
        d.line(pp, fill=fill, width=int(w * f), joint="curve")
        r = w * f / 2
        for x, y in (pp[0], pp[-1]):
            d.ellipse([x - r, y - r, x + r, y + r], fill=fill)

    def circ(c, r, fill=None, outline=None, w=0):
        x, y = P(*c)
        R = r * f
        d.ellipse([x - R, y - R, x + R, y + R], fill=fill, outline=outline, width=int(w * f))

    theta, wang = math.radians(i * 30), math.radians(i * 15)
    rear, front, crank, seat, head = (100, 300), (300, 300), (170, 305), (145, 222), (268, 235)
    hip, shoulder, hand = (150, 212), (192, 152), (276, 205)
    skin, coat, coat_edge = (255, 214, 172, 255), (252, 253, 255, 255), (150, 175, 210, 255)
    red = (228, 50, 62, 255)

    # doctor's bag on the rear rack ("home visit")
    line([(70, 250), (128, 250)], 4, (90, 100, 120, 255))
    line([(80, 250), (100, 300)], 3, (90, 100, 120, 255))
    d.rounded_rectangle([*P(76, 212), *P(118, 250)], radius=7 * f, fill=(120, 76, 44, 255), outline=(70, 42, 24, 255), width=int(2 * f))
    d.rectangle([*P(91, 226), *P(103, 231)], fill=(255, 255, 255, 255))
    d.rectangle([*P(95, 222), *P(99, 235)], fill=(255, 255, 255, 255))

    for c in (rear, front):                                   # wheels
        circ(c, 55, outline=(25, 35, 55, 255), w=9)
        circ(c, 46, outline=(215, 225, 240, 255), w=2)
        for s in range(8):
            a = wang + s * math.pi / 4
            line([c, (c[0] + 46 * math.cos(a), c[1] + 46 * math.sin(a))], 1.6, (200, 210, 225, 255))
        circ(c, 6, fill=(60, 70, 90, 255))

    p_near = (crank[0] + 30 * math.cos(theta), crank[1] + 30 * math.sin(theta))
    p_far = (crank[0] - 30 * math.cos(theta), crank[1] - 30 * math.sin(theta))

    def leg(pedal, col):
        knee = _ik(hip, pedal, 63, 63, -1)
        line([hip, knee], 25, col)
        line([knee, pedal], 21, col)
        d.rounded_rectangle([*P(pedal[0] - 9, pedal[1] - 6), *P(pedal[0] + 19, pedal[1] + 8)], radius=6 * f, fill=(28, 34, 50, 255))
        d.rectangle([*P(pedal[0] - 8, pedal[1] + 6), *P(pedal[0] + 18, pedal[1] + 8)], fill=(235, 238, 245, 255))

    line([crank, p_far], 5, (110, 120, 140, 255))             # far side
    leg(p_far, (22, 40, 78, 255))

    for seg in ([rear, crank], [rear, seat], [seat, crank], [seat, head], [crank, head]):
        line(seg, 7, red)                                     # frame
    line([head, front], 6, red)
    line([head, (262, 205)], 6, (40, 50, 70, 255))
    line([(262, 205), (284, 203)], 6, (40, 50, 70, 255))
    line([(128, 217), (162, 217)], 9, (40, 46, 62, 255))      # saddle
    circ(crank, 13, fill=(80, 92, 115, 255))

    line([crank, p_near], 5, (150, 160, 180, 255))            # near side
    line([hip, shoulder], 58, coat_edge)                      # torso
    line([hip, shoulder], 52, coat)
    leg(p_near, (31, 58, 104, 255))
    line([(198, 148), (187, 170), (172, 190)], 3, (40, 56, 84, 255))
    circ((171, 192), 6, fill=(205, 215, 230, 255), outline=(40, 56, 84, 255), w=2)
    d.rectangle([*P(156, 176), *P(162, 186)], fill=(228, 50, 62, 255))   # red cross on pocket
    d.rectangle([*P(153, 179), *P(165, 183)], fill=(228, 50, 62, 255))

    elbow = _ik(shoulder, hand, 52, 52, 1)                    # arm
    line([shoulder, elbow], 24, coat_edge)
    line([elbow, hand], 22, coat_edge)
    line([shoulder, elbow], 20, coat)
    line([elbow, hand], 18, coat)
    circ(hand, 10, fill=skin)

    line([(200, 142), (206, 128)], 20, skin)                  # head
    circ((196, 119), 6, fill=(240, 190, 150, 255))
    circ((212, 116), 27, fill=skin)
    d.chord([*P(185, 89), *P(239, 143)], 200, 340, fill=(20, 170, 190, 255))
    d.rectangle([*P(206, 96), *P(218, 100)], fill=(255, 255, 255, 255))
    d.rectangle([*P(210, 92), *P(214, 104)], fill=(255, 255, 255, 255))
    circ((222, 116), 3, fill=(35, 35, 55, 255))
    d.line([*P(216, 108), *P(228, 107)], fill=(60, 40, 30, 255), width=int(2.4 * f))
    d.ellipse([*P(222, 123), *P(236, 128)], fill=(60, 40, 30, 255))
    d.arc([*P(216, 122), *P(234, 136)], 25, 155, fill=(165, 70, 60, 255), width=int(2 * f))
    return im


def make_logo_frames(n=12):
    SSL = 2
    f = LOGO_PX / 400.0 * SSL
    W = int(400 * f)
    cm = Image.new("L", (W, W), 0)
    ImageDraw.Draw(cm).ellipse([20 * f, 20 * f, 380 * f, 380 * f], fill=255)
    base = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    bd = ImageDraw.Draw(base)
    bd.ellipse([2 * f, 2 * f, 398 * f, 398 * f], fill=(10, 52, 125, 255))
    bd.ellipse([8 * f, 8 * f, 392 * f, 392 * f], fill=(255, 255, 255, 255))
    grad = ImageOps.colorize(Image.linear_gradient("L").resize((W, W)), black=(24, 120, 235), white=(135, 222, 255))
    base.paste(grad, (0, 0), cm.resize((W, W)))
    bd = ImageDraw.Draw(base)
    for cx, cy, s in ((105, 78, 1.0), (305, 66, 0.8)):          # little clouds
        for dx, dy, r in ((-20, 4, 15), (0, -6, 20), (22, 4, 15), (4, 8, 16)):
            bd.ellipse([(cx + (dx - r) * s) * f, (cy + (dy - r) * s) * f,
                        (cx + (dx + r) * s) * f, (cy + (dy + r) * s) * f], fill=(255, 255, 255, 255))
    for cx, cy, s in ((200, 52, 12), (318, 112, 9), (86, 128, 8)):   # medical crosses
        bd.rectangle([(cx - s) * f, (cy - s / 3) * f, (cx + s) * f, (cy + s / 3) * f], fill=(255, 255, 255, 255))
        bd.rectangle([(cx - s / 3) * f, (cy - s) * f, (cx + s / 3) * f, (cy + s) * f], fill=(255, 255, 255, 255))
    road = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    ImageDraw.Draw(road).rectangle([0, 346 * f, W, W], fill=(26, 44, 92, 255))
    base = Image.composite(road, base, ImageChops.multiply(road.split()[3], cm))
    base = Image.alpha_composite(base, Image.new("RGBA", (W, W), (0, 0, 0, 0)))

    frames = []
    rs = 0.86
    for i in range(n):
        fr = base.copy()
        dash = Image.new("RGBA", (W, W), (0, 0, 0, 0))
        dd = ImageDraw.Draw(dash)
        off = -(i / n) * 56
        x = off - 56
        while x < 460:
            dd.rectangle([x * f, 366 * f, (x + 28) * f, 372 * f], fill=(255, 255, 255, 235))
            x += 56
        dash.putalpha(ImageChops.multiply(dash.split()[3], cm))
        fr = Image.alpha_composite(fr, dash)
        rider = _rider(i, f)
        rw = int(W * rs)
        rider = rider.resize((rw, rw), Image.LANCZOS)
        ra = rider.split()[3].filter(ImageFilter.MaxFilter(5))
        halo = Image.new("RGBA", rider.size, (255, 255, 255, 255))
        halo.putalpha(ra)
        px, py = int(28 * f), int(40 * f)
        fr.alpha_composite(halo, (px, py))
        fr.alpha_composite(rider, (px, py))
        frames.append(fr.resize((LOGO_PX, LOGO_PX), Image.LANCZOS))
    return frames


# ---------------------------------------------------------------- GLOBE ------
TEX_W, TEX_H = 1024, 512


def make_globe_texture():
    tex = Image.new("RGB", (TEX_W, TEX_H), (20, 100, 210))
    d = ImageDraw.Draw(tex)
    for y in range(TEX_H):
        s = int(26 * math.sin(math.pi * y / TEX_H))
        d.line([(0, y), (TEX_W, y)], fill=(16 + s, 96 + s, 206 + min(30, s)))
    rnd = random.Random(11)
    for (land, count) in (((52, 176, 98), 9), ((38, 146, 82), 9)):
        for _ in range(count):
            cx = rnd.randint(0, TEX_W)
            cy = rnd.randint(int(TEX_H * 0.22), int(TEX_H * 0.78))
            for _b in range(rnd.randint(5, 9)):
                rx, ry = rnd.randint(22, 80), rnd.randint(14, 44)
                ox, oy = rnd.randint(-70, 70), rnd.randint(-36, 36)
                for wrap in (-TEX_W, 0, TEX_W):
                    d.ellipse([cx + ox - rx + wrap, cy + oy - ry, cx + ox + rx + wrap, cy + oy + ry], fill=land)
    d.rectangle([0, 0, TEX_W, 20], fill=(240, 248, 255))
    d.rectangle([0, TEX_H - 20, TEX_W, TEX_H], fill=(240, 248, 255))
    for _ in range(26):                                        # thin clouds
        cx, cy = rnd.randint(0, TEX_W), rnd.randint(40, TEX_H - 40)
        rx, ry = rnd.randint(30, 90), rnd.randint(5, 11)
        for wrap in (-TEX_W, 0, TEX_W):
            d.ellipse([cx - rx + wrap, cy - ry, cx + rx + wrap, cy + ry], fill=(226, 242, 253))
    for _ in range(14):                                        # hospital crosses
        cx, cy = rnd.randint(0, TEX_W), rnd.randint(70, TEX_H - 70)
        for wrap in (-TEX_W, 0, TEX_W):
            d.rectangle([cx - 11 + wrap, cy - 4, cx + 11 + wrap, cy + 4], fill=(255, 255, 255))
            d.rectangle([cx - 4 + wrap, cy - 11, cx + 4 + wrap, cy + 11], fill=(255, 255, 255))
            d.rectangle([cx - 6 + wrap, cy - 2, cx + 6 + wrap, cy + 2], fill=(235, 55, 70))
            d.rectangle([cx - 2 + wrap, cy - 6, cx + 2 + wrap, cy + 6], fill=(235, 55, 70))
    return tex


class GlobeRenderer:
    """Real-time rotating sphere. With numpy: true spherical mapping. Without: flat scroll."""

    def __init__(self, size):
        self.S = S = int(size)
        self.tex = make_globe_texture()
        if np is not None:
            t = np.asarray(self.tex.convert("RGBA"), dtype=np.uint8).copy()
            self.tex32 = t.view(np.uint32).reshape(-1)
            ys, xs = np.mgrid[0:S, 0:S].astype(np.float32)
            nx = (xs + 0.5) / S * 2 - 1
            ny = 1 - (ys + 0.5) / S * 2
            r2 = nx * nx + ny * ny
            nz = np.sqrt(np.clip(1 - r2, 0, 1))
            lat = np.arcsin(np.clip(ny, -1, 1))
            lon = np.arctan2(nx, nz)
            self.vrow = (((0.5 - lat / np.pi) * (TEX_H - 1)).astype(np.int32)) * TEX_W
            self.ucoord = ((lon / (2 * np.pi) + 0.5) * TEX_W).astype(np.float32)
            light = np.array([-0.45, 0.55, 0.70], dtype=np.float32)
            light /= np.linalg.norm(light)
            dot = np.clip(nx * light[0] + ny * light[1] + nz * light[2], 0, 1)
            self.shade = ((0.42 + 0.68 * dot) * 256).astype(np.uint16)[..., None]
            rim = np.clip(1 - nz, 0, 1) ** 2.4
            spec = np.clip(dot, 0, 1) ** 30 * 0.38
            add = (rim[..., None] * np.array([120, 205, 255], dtype=np.float32) * 0.75 + spec[..., None] * 255)
            self.add = add.astype(np.uint16)
            self.alpha = (np.clip((1 - np.sqrt(r2)) * S * 0.5, 0, 1) * 255).astype(np.uint8)
            self.out = np.empty((S, S, 4), dtype=np.uint8)
        else:
            yy, xx = Image.new("L", (S, S), 0), None
            m = Image.new("L", (S * 3, S * 3), 0)
            ImageDraw.Draw(m).ellipse([0, 0, S * 3 - 1, S * 3 - 1], fill=255)
            self.mask = m.resize((S, S), Image.LANCZOS)
            rg = ImageOps.invert(Image.radial_gradient("L")).resize((S, S))
            self.shade_img = ImageOps.colorize(rg, black=(0, 25, 80), white=(255, 255, 255)).convert("RGBA")
            self.tex_wide = self.tex

    def render(self, lon_deg):
        S = self.S
        if np is not None:
            shift = int(lon_deg / 360.0 * TEX_W)
            u = (self.ucoord.astype(np.int32) + shift) % TEX_W
            px = self.tex32[self.vrow + u].view(np.uint8).reshape(S, S, 4)
            rgb = (px[..., :3].astype(np.uint16) * self.shade) >> 8
            rgb = np.minimum(rgb + self.add, 255)
            self.out[..., :3] = rgb
            self.out[..., 3] = self.alpha
            return Image.fromarray(self.out, "RGBA")
        shift = int(lon_deg / 360.0 * TEX_W)
        t = ImageChops.offset(self.tex, shift, 0).crop((TEX_W // 2 - TEX_H // 2, 0, TEX_W // 2 + TEX_H // 2, TEX_H))
        t = t.resize((S, S), Image.BILINEAR).convert("RGBA")
        t = ImageChops.multiply(t, self.shade_img)
        t.putalpha(self.mask)
        return t


# =============================================================================
#  5.  THE OPENING CANVAS
# =============================================================================
class OpeningIntro(tk.Canvas):
    """
    Usage inside app.py (see bottom of this file for the full example):

        self.opening = OpeningIntro(root,
                                    on_finish=self.start_existing_intro,   # -> your ECG intro
                                    on_skip=self.open_login_screen)        # -> Skip / Esc
        self.opening.start()
    """

    def __init__(self, master, on_finish=None, on_skip=None, show_skip_button=SHOW_SKIP_BUTTON):
        super().__init__(master, bg=BG_BOTTOM, highlightthickness=0, bd=0)
        self.on_finish, self.on_skip = on_finish, on_skip
        self.show_skip_button = show_skip_button
        self._alive, self._running = True, False
        self._job = self._resize_job = None
        self.W = self.H = 0
        self._cache = {}
        self._vis, self._last_img = {}, {}
        self._sprites = None
        self._logo_frames = None
        self.orb = 0.0
        self.globe_lon = 0.0
        self._gphoto, self._gsize = None, 0
        self._hphoto, self._hq = None, 0
        self._impact_done = self._logo_burst_done = False
        self._trans_start = None
        self.particles = []
        self.bind("<Configure>", self._on_configure)
        self.bind("<Escape>", self._on_escape)
        self.winfo_toplevel().bind("<Escape>", self._on_escape, add="+")

    # ---------------------------------------------------------- lifecycle ---
    def start(self):
        if not self.winfo_manager():
            self.place(x=0, y=0, relwidth=1, relheight=1)
        self.update()
        top = self.winfo_toplevel()
        self.W = self.winfo_width() if self.winfo_width() > 100 else top.winfo_width()
        self.H = self.winfo_height() if self.winfo_height() > 100 else top.winfo_height()
        self.W, self.H = max(self.W, 320), max(self.H, 240)
        self._make_bg()                       # sky is visible instantly - never a blank screen
        self.bg_id = self.create_image(0, 0, anchor="nw", image=self.bg_photo)
        self.update()
        self._build_static_assets()
        self._build_size_assets()
        self._create_items()
        self._init_timing()
        self.focus_set()
        self._t0 = self._last = time.perf_counter()
        self._running = True
        self._tick()

    def stop(self):
        self._running = False
        if self._job is not None:
            try:
                self.after_cancel(self._job)
            except Exception:
                pass
            self._job = None

    def skip(self):
        """Skip button / Esc:  stop animation -> open login."""
        if not self._alive or getattr(self, "_skipped", False):
            return
        self._skipped = True
        self.stop()
        cb = self.on_skip
        if cb:
            cb()
        self.after(60, self._safe_destroy)

    def _on_escape(self, _e=None):
        if self._alive and self._running:
            self.skip()

    def _finish(self):
        self.stop()
        cb = self.on_finish
        if cb:
            cb()          # build/show your ECG scene NOW (it must be above this canvas)
        self.after(80, self._safe_destroy)

    def _safe_destroy(self):
        if self._alive:
            self._alive = False
            try:
                self.destroy()
            except Exception:
                pass

    def _init_timing(self):
        self.t_impact = T_TITLE + (len([c for c in PROJECT_NAME if c != " "]) - 1) * LETTER_STAGGER + LETTER_DUR

    # ------------------------------------------------------------- assets ---
    def _make_bg(self):
        W, H = self.W, self.H
        g = ImageOps.colorize(Image.linear_gradient("L").resize((W, H)),
                              black=hex_rgb(BG_TOP), white=hex_rgb(BG_BOTTOM)).convert("RGBA")
        glow = ImageOps.invert(Image.radial_gradient("L")).resize((W, H)).point(lambda v: int(v * 0.40))
        white = Image.new("RGBA", (W, H), (235, 250, 255, 255))
        white.putalpha(glow)
        g = Image.alpha_composite(g, white)
        self.bg_img = g
        self.bg_photo = ImageTk.PhotoImage(g.convert("RGB"))

    def _build_static_assets(self):
        n = max(1, min(MEDICAL_ELEMENT_COUNT, len(ITEMS)))
        self.items = []
        stay_i = 0
        for idx, (name, ring, rmul, spd, ph, enter, stay) in enumerate(ITEMS[:n]):
            anchor = None
            if stay and stay_i < len(ANCHORS):
                anchor, stay_i = ANCHORS[stay_i], stay_i + 1
            elif stay:
                stay = False
            self.items.append(dict(name=name, ring=ring, rmul=rmul, spd=spd, ph=ph, enter=enter,
                                   stay=stay, anchor=anchor, idx=idx, front=None, exit_off=(idx % 4) * 0.12))
        self._sprites = {nm: SPRITE_BUILDERS[nm]() for nm in {i["name"] for i in self.items}}
        self._logo_frames = make_logo_frames(12)

    def _build_size_assets(self):
        W, H = self.W, self.H
        self._cache.clear()
        self.unit = H / 720.0
        self.item_px = 0.17 * H
        self.orbit_a = min(0.44 * W, 0.62 * H)
        self.G0 = GLOBE_SIZE_RATIO * H
        self.G_F = 0.46 * H
        self.G_FINAL_CY = 0.36
        self.title_cy = 0.735 * H
        self._make_bg()
        # globe
        self.globe = GlobeRenderer(int(clamp(self.G0 * 0.80, 200, 380)))
        halo = Image.new("RGBA", (256, 256), (205, 240, 255, 0))
        halo.putalpha(ImageOps.invert(Image.radial_gradient("L")).point(lambda v: int(v * 0.60)))
        self.halo_img = halo
        # clouds
        rnd = random.Random(5)
        self.clouds = []
        for i in range(6):
            cw, ch = int(W * rnd.uniform(0.26, 0.46)), int(H * rnd.uniform(0.14, 0.24))
            im = Image.new("RGBA", (cw, ch), (255, 255, 255, 0))
            cd = ImageDraw.Draw(im)
            for _ in range(7):
                rx, ry = rnd.uniform(0.14, 0.26) * cw, rnd.uniform(0.28, 0.46) * ch
                x, y = rnd.uniform(0.2, 0.8) * cw, rnd.uniform(0.45, 0.65) * ch
                cd.ellipse([x - rx, y - ry, x + rx, y + ry], fill=(255, 255, 255, 215))
            im = im.filter(ImageFilter.GaussianBlur(ch * 0.06))
            self.clouds.append(dict(img=im, x=rnd.uniform(-0.2, 1.0) * W, y=rnd.uniform(0.05, 0.85) * H,
                                    v=rnd.uniform(8, 22) * (1 + i * 0.25) * self.unit, photo=None, id=None))
        self._build_title()
        self._build_subtitle()

    def _build_title(self):
        W, H = self.W, self.H
        text = PROJECT_NAME
        fs = max(20, int(TITLE_SIZE_RATIO * H))
        for _ in range(2):
            font = load_font(TITLE_FONT_FILES, fs)
            track = fs * 0.03
            advs = [font.getlength(c) if c != " " else fs * 0.32 for c in text]
            total = sum(advs) + track * (len(text) - 1)
            limit = 0.86 * W
            if total <= limit:
                break
            fs = int(fs * limit / total)
        asc, desc = font.getmetrics()
        pad = int(fs * 0.22)
        Hh = asc + desc + 2 * pad
        sw, depth = max(3, int(fs * 0.055)), max(4, int(fs * 0.085))
        Wt = int(total + 2 * pad)
        title = Image.new("RGBA", (Wt, Hh), (0, 0, 0, 0))
        self.letters = []
        cur = float(pad)
        for ch, adv in zip(text, advs):
            if ch != " ":
                Wl = int(adv + 2 * pad)
                li = self._render_letter(ch, font, fs, pad, Wl, Hh, asc, sw, depth)
                x = int(cur - pad)
                title.alpha_composite(li, (x, 0)) if x >= 0 and x + Wl <= Wt else title.paste(li, (x, 0), li)
                self.letters.append(dict(img=li, off=x + Wl / 2 - Wt / 2))
            cur += adv + track
        self.title_img = title
        self.sweep_frames = self._make_sweep(title, 16)

    @staticmethod
    def _render_letter(ch, font, fs, pad, W, H, asc, sw, depth):
        x, y = pad, pad + asc
        sh = Image.new("L", (W, H), 0)
        ImageDraw.Draw(sh).text((x, y + depth + 6), ch, font=font, fill=255, anchor="ls", stroke_width=sw)
        sh = sh.filter(ImageFilter.GaussianBlur(fs * 0.04))
        im = Image.new("RGBA", (W, H), (4, 30, 90, 0))
        im.putalpha(sh.point(lambda v: int(v * 0.5)))
        d = ImageDraw.Draw(im)
        for k in range(depth, 0, -1):
            d.text((x, y + k), ch, font=font, fill=(8, 70, 170, 255), anchor="ls",
                   stroke_width=sw, stroke_fill=(6, 44, 120, 255))
        d.text((x, y), ch, font=font, fill=(255, 255, 255, 255), anchor="ls",
               stroke_width=sw, stroke_fill=(6, 38, 102, 255))
        mask = Image.new("L", (W, H), 0)
        ImageDraw.Draw(mask).text((x, y), ch, font=font, fill=255, anchor="ls")
        grad = ImageOps.colorize(Image.linear_gradient("L").resize((W, H)),
                                 black=(255, 255, 255), white=(255, 196, 40))
        im.paste(grad, (0, 0), mask)
        return im

    @staticmethod
    def _make_sweep(img, n):
        W, H = img.size
        alpha = img.split()[3]
        frames = []
        for i in range(n):
            p = i / (n - 1)
            cx = lerp(-0.25 * W, 1.25 * W, p)
            band = Image.new("L", (W, H), 0)
            bw, sk = W * 0.07, H * 0.5
            ImageDraw.Draw(band).polygon([(cx - bw + sk, 0), (cx + bw + sk, 0), (cx + bw - sk, H), (cx - bw - sk, H)], fill=255)
            band = band.filter(ImageFilter.GaussianBlur(H * 0.035))
            a = ImageChops.multiply(band, alpha).point(lambda v: int(v * 0.9))
            white = Image.new("RGBA", (W, H), (255, 255, 255, 0))
            white.putalpha(a)
            frames.append(Image.alpha_composite(img, white))
        return frames

    def _build_subtitle(self):
        W, H = self.W, self.H
        fs = max(12, int(0.044 * H))
        for _ in range(2):
            font = load_font(SUBTITLE_FONT_FILES, fs)
            tw = font.getlength(SUBTITLE)
            if tw + fs * 2.2 <= 0.88 * W:
                break
            fs = int(fs * 0.88 * W / (tw + fs * 2.2))
        asc, desc = font.getmetrics()
        px, py = int(fs * 1.1), int(fs * 0.5)
        w, h = int(tw + 2 * px), int(asc + desc + 2 * py)
        im = Image.new("RGBA", (w + 8, h + 8), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        d.rounded_rectangle([4, 4, w + 3, h + 3], radius=h // 2, fill=(6, 50, 145, 215), outline=(255, 255, 255, 235), width=2)
        d.text((4 + px + 1, 4 + py + asc + 2), SUBTITLE, font=font, fill=(0, 20, 70, 255), anchor="ls")
        d.text((4 + px, 4 + py + asc), SUBTITLE, font=font, fill=(255, 255, 255, 255), anchor="ls")
        self.sub_img = im

    # ------------------------------------------------------------ canvas ---
    def _create_items(self):
        W, H = self.W, self.H
        self._rings_back, self._rings_front = [], []
        for _ in RINGS:
            self._rings_back.append(self.create_line(0, 0, 0, 0, fill="#c9efff", width=2, smooth=True, state="hidden"))
        for c in self.clouds:
            c["photo"] = ImageTk.PhotoImage(c["img"])
            c["id"] = self.create_image(c["x"], c["y"], image=c["photo"], anchor="w")
        # ambient sparkles
        rnd = random.Random(3)
        self.dots = []
        for _ in range(34):
            r = rnd.uniform(1.5, 4.5) * self.unit
            iid = self.create_oval(0, 0, 0, 0, fill=rnd.choice(["#ffffff", "#d7f4ff", "#fff6c4"]), outline="")
            self.dots.append(dict(id=iid, x=rnd.uniform(0, W), y=rnd.uniform(0, H), vy=rnd.uniform(12, 40) * self.unit,
                                  r=r, ph=rnd.uniform(0, 6.28), born=rnd.uniform(0.0, 1.6)))
        for r in self._rings_back:
            self.tag_raise(r)
        for it in self.items:
            it["id"] = self.create_image(-999, -999, state="hidden")
        self.halo_id = self.create_image(-999, -999, state="hidden")
        self.globe_id = self.create_image(-999, -999, state="hidden")
        for _ in RINGS:
            self._rings_front.append(self.create_line(0, 0, 0, 0, fill="#e6f8ff", width=2, smooth=True, state="hidden"))
        self.logo_id = self.create_image(-999, -999, state="hidden")
        self.letter_ids = [self.create_image(-999, -999, state="hidden") for _ in self.letters]
        self.title_id = self.create_image(-999, -999, state="hidden")
        self.sub_id = self.create_image(-999, -999, state="hidden")
        self.conf = []
        palette = ["#ffffff", "#ffd23f", "#ff5c8a", "#5ad1ff", "#ff7a3d", "#7dff9a", "#ffffff"]
        for _ in range(110):
            self.conf.append(dict(id=self.create_polygon(0, 0, 0, 0, 0, 0, 0, 0, fill=random.choice(palette), outline="", state="hidden"),
                                  alive=False))
        self.shock = [self.create_oval(0, 0, 0, 0, outline="#ffffff", width=4, state="hidden"),
                      self.create_oval(0, 0, 0, 0, outline="#bdf1ff", width=2, state="hidden")]
        self.iris = self.create_oval(0, 0, 0, 0, fill=TRANSITION_COLOR, outline="#ffffff", width=6, state="hidden")
        if SHOW_FRAME_GLOW:
            self.frame_a = self.create_rectangle(0, 0, 0, 0, outline="#38c6ff", width=8)
            self.frame_b = self.create_rectangle(0, 0, 0, 0, outline="#c8f4ff", width=2)
        if self.show_skip_button:
            self._create_skip()
        self._layout_static()

    def _create_skip(self):
        self.skip_rect = self.create_rectangle(0, 0, 0, 0, fill="#0a3a8f", outline="#ffffff", width=2, tags="skip")
        self.skip_txt = self.create_text(0, 0, text=SKIP_TEXT, fill="#ffffff", font=("Segoe UI", 10, "bold"), tags="skip")
        self.tag_bind("skip", "<Button-1>", lambda e: self.skip())
        self.tag_bind("skip", "<Enter>", lambda e: (self.itemconfigure(self.skip_rect, fill="#1f6bff"), self.config(cursor="hand2")))
        self.tag_bind("skip", "<Leave>", lambda e: (self.itemconfigure(self.skip_rect, fill="#0a3a8f"), self.config(cursor="")))

    def _layout_static(self):
        W, H = self.W, self.H
        if SHOW_FRAME_GLOW:
            self.coords(self.frame_a, 6, 6, W - 6, H - 6)
            self.coords(self.frame_b, 12, 12, W - 12, H - 12)
        if self.show_skip_button:
            bw, bh = 150, 34
            self.coords(self.skip_rect, W - 24 - bw, H - 24 - bh, W - 24, H - 24)
            self.coords(self.skip_txt, W - 24 - bw / 2, H - 24 - bh / 2)
            self.tag_raise("skip")

    def _on_configure(self, e):
        if e.width < 100 or e.height < 100 or not self._running:
            return
        if abs(e.width - self.W) < 8 and abs(e.height - self.H) < 8:
            return
        self.W, self.H = e.width, e.height
        if self._resize_job:
            self.after_cancel(self._resize_job)
        self._resize_job = self.after(180, self._rebuild)

    def _rebuild(self):
        self._resize_job = None
        if not self._alive:
            return
        try:
            old_ids = [c["id"] for c in self.clouds]
            self._build_size_assets()
            self.itemconfigure(self.bg_id, image=self.bg_photo)
            for iid in old_ids:
                self.delete(iid)
            for c in self.clouds:
                c["photo"] = ImageTk.PhotoImage(c["img"])
                c["id"] = self.create_image(c["x"], c["y"], image=c["photo"], anchor="w")
                self.tag_lower(c["id"], self.halo_id)
            self.tag_lower(self.bg_id)
            self._gphoto = self._hphoto = None
            self._hq = self._gsize = 0
            self._last_img.clear()
            self._layout_static()
        except Exception:
            traceback.print_exc()

    # -------------------------------------------------------- draw helpers ---
    def _put(self, iid, photo, x, y):
        if not self._vis.get(iid):
            self.itemconfigure(iid, state="normal")
            self._vis[iid] = True
        if self._last_img.get(iid) is not photo:
            self.itemconfigure(iid, image=photo)
            self._last_img[iid] = photo
        self.coords(iid, x, y)

    def _hide(self, iid):
        if self._vis.get(iid) is not False:
            self.itemconfigure(iid, state="hidden")
            self._vis[iid] = False

    def _cached(self, key, build):
        p = self._cache.get(key)
        if p is None:
            if len(self._cache) > 2200:
                self._cache.clear()
                self._last_img.clear()
            p = ImageTk.PhotoImage(build())
            self._cache[key] = p
        return p

    def _sprite_photo(self, name, size, ang, squash):
        q = max(8, int(size / 4) * 4)
        a = int(round(ang / 6.0)) * 6
        s = round(squash * 10) / 10.0

        def build():
            im = self._sprites[name].resize((max(2, int(q * s)), q), Image.BILINEAR, reducing_gap=2.0)
            return im.rotate(a, resample=Image.BILINEAR, expand=True) if a else im

        return self._cached(("s", name, q, a, s), build)

    # -------------------------------------------------------------- frame ---
    def _tick(self):
        if not self._running or not self._alive:
            return
        t_start = time.perf_counter()
        real = t_start - self._t0
        dt = min(t_start - self._last, 0.05)
        self._last = t_start
        scale = ANIMATION_SPEED * 10.0 / INTRO_DURATION
        t, dtb = real * scale, dt * scale
        try:
            self._frame(t, dtb, real)
        except tk.TclError:
            return
        except Exception:
            traceback.print_exc()          # never freeze the demo: fall through to the next scene
            self._finish()
            return
        if not self._running:
            return
        spent = (time.perf_counter() - t_start) * 1000
        self._job = self.after(max(1, int(1000.0 / FPS - spent)), self._tick)

    def _proj(self, ring, a, th, cx, cy):
        st, roll, rm = RINGS[ring]
        x = a * rm * math.cos(th)
        s = math.sin(th)
        y = a * rm * s * st
        z = a * rm * s * math.sqrt(1 - st * st)
        r = math.radians(roll)
        xr, yr = x * math.cos(r) - y * math.sin(r), x * math.sin(r) + y * math.cos(r)
        D = 4.0 * self.orbit_a
        ps = D / (D - z)
        return cx + xr * ps, cy + yr * ps, z, ps

    def _frame(self, t, dtb, real):
        W, H = self.W, self.H
        cx = W / 2.0
        u = self.unit

        # --- clocks -----------------------------------------------------------
        energy = ease_io(prog(t, 3.6, 5.3))
        calm = ease_io(prog(t, 5.7, 6.8))
        self.orb += dtb * (1 + 0.9 * energy) * (1 - 0.75 * calm)
        self.globe_lon = (self.globe_lon + dtb * (20 + 34 * energy)) % 360

        # --- impact shake ------------------------------------------------------
        sx = sy = 0.0
        if t >= self.t_impact:
            sp = prog(t, self.t_impact, self.t_impact + 0.45)
            sx = (1 - sp) ** 2 * 11 * u * math.sin(sp * 42)
            sy = (1 - sp) ** 2 * 7 * u * math.cos(sp * 37)

        # --- globe -------------------------------------------------------------
        pop = ease_back(prog(t, T_GLOBE, T_GLOBE + 0.9))
        m = ease_io(prog(t, T_SETTLE, T_SETTLE + 0.9))
        gcy = lerp(0.5 * H, self.G_FINAL_CY * H, m) + 7 * u * math.sin(t * 1.3) * (1 - m)
        gsize = lerp(self.G0, self.G_F, m) * pop
        gx, gy = cx + sx, gcy + sy

        # --- clouds & sparkles ---------------------------------------------------
        for c in self.clouds:
            c["x"] -= c["v"] * dtb
            cw = c["img"].width
            if c["x"] < -cw:
                c["x"] = W + 20
            if c["id"] is not None:
                self.coords(c["id"], c["x"], c["y"])
        for d in self.dots:
            life = prog(t, d["born"], d["born"] + 0.8)
            d["y"] -= d["vy"] * dtb
            if d["y"] < -10:
                d["y"], d["x"] = H + 10, random.uniform(0, W)
            r = d["r"] * life * (0.7 + 0.3 * math.sin(t * 4 + d["ph"]))
            self.coords(d["id"], d["x"] - r, d["y"] - r, d["x"] + r, d["y"] + r)

        # --- orbit rings -----------------------------------------------------------
        for ri in range(len(RINGS)):
            vis = prog(t, 1.8 + ri * 0.35, 2.7 + ri * 0.35) * (1 - prog(t, 5.3, 6.1))
            if vis < 0.03:
                self._hide(self._rings_back[ri]); self._hide(self._rings_front[ri])
                continue
            a = self.orbit_a * (0.35 + 0.65 * ease_out(vis))
            for front, iid in ((False, self._rings_back[ri]), (True, self._rings_front[ri])):
                pts = []
                for k in range(29):
                    th = (0 if front else math.pi) + math.pi * k / 28
                    px, py, _z, _p = self._proj(ri, a, th, gx, gy)
                    pts += [px, py]
                self.coords(iid, *pts)
                self.itemconfigure(iid, width=1 + 2.5 * vis * (1 + 0.5 * energy))
                if not self._vis.get(iid):
                    self.itemconfigure(iid, state="normal"); self._vis[iid] = True

        # --- globe halo + globe ------------------------------------------------------
        if gsize > 6:
            hq = int(gsize * (1.75 + 0.06 * math.sin(t * 3)) / 12) * 12
            if hq != self._hq or self._hphoto is None:
                self._hphoto = ImageTk.PhotoImage(self.halo_img.resize((hq, hq), Image.BILINEAR))
                self._hq = hq
            self._put(self.halo_id, self._hphoto, gx, gy)
            gq = max(8, int(gsize / 4) * 4)
            img = self.globe.render(self.globe_lon)
            if gq != self.globe.S:
                img = img.resize((gq, gq), Image.BILINEAR)
            if self._gphoto is None or self._gsize != gq:
                self._gphoto = ImageTk.PhotoImage(img)
                self._gsize = gq
                self._last_img.pop(self.globe_id, None)
            else:
                self._gphoto.paste(img)
            self._put(self.globe_id, self._gphoto, gx, gy)
        else:
            self._hide(self.halo_id); self._hide(self.globe_id)

        # --- orbiting medical objects --------------------------------------------------
        order = []
        for it in self.items:
            if t < it["enter"]:
                self._hide(it["id"]); continue
            pe = prog(t, it["enter"], it["enter"] + 0.85)
            sc = ease_back(pe)
            rf = lerp(0.30, 1.0, ease_out(prog(t, it["enter"], it["enter"] + 1.1)))
            if not it["stay"]:
                x0 = T_EXIT + it["exit_off"]
                ex = prog(t, x0, x0 + 0.65)
                if ex >= 1:
                    self._hide(it["id"]); continue
                sc *= 1 - ease_in(ex)
                rf *= 1 + 0.7 * ease_in(ex)
            th = it["ph"] + it["spd"] * self.orb
            px, py, z, ps = self._proj(it["ring"], self.orbit_a * it["rmul"] * rf, th, gx, gy)
            front = z > 0
            if it["stay"] and t >= T_SETTLE:
                e = ease_io(prog(t, T_SETTLE + it["idx"] * 0.05, T_SETTLE + 0.95 + it["idx"] * 0.05))
                ax, ay = it["anchor"][0] * W, it["anchor"][1] * H
                bob = 7 * u * math.sin(t * 2.0 + it["ph"]) * e
                px, py = lerp(px, ax, e) + sx * 0.5, lerp(py, ay, e) + bob
                ps = lerp(ps, 0.98, e)
                front = front or e > 0.3
            size = self.item_px * ps * sc
            if size < 8:
                self._hide(it["id"]); continue
            ang = 14 * math.sin(t * 1.5 + it["ph"] * 1.7)
            squash = 0.78 + 0.22 * math.cos(t * 1.25 + it["ph"]) ** 2
            self._put(it["id"], self._sprite_photo(it["name"], size, ang, squash), px, py)
            if it["front"] is not front:
                it["front"] = front
                (self.tag_raise if front else self.tag_lower)(it["id"], self.globe_id)
            order.append((z, it))

        # --- doctor-on-bike logo ---------------------------------------------------------
        if t >= T_LOGO:
            lp = ease_back(prog(t, T_LOGO, T_LOGO + 0.75))
            lsize = max(8, int(self.G_F * 0.84 * lp / 6) * 6)
            fi = int((t - T_LOGO) * 14) % 12
            ph = self._cached(("logo", fi, lsize),
                              lambda: self._logo_frames[fi].resize((lsize, lsize), Image.LANCZOS))
            self._put(self.logo_id, ph, gx, gy + 3 * u * math.sin(t * 3.2))
            if not self._logo_burst_done:
                self._logo_burst_done = True
                self._burst(gx, gy, 34, 0.55)
        else:
            self._hide(self.logo_id)

        # --- title letters / full title --------------------------------------------------
        tcy = self.title_cy + sy
        if t < T_TITLE:
            for iid in self.letter_ids:
                self._hide(iid)
            self._hide(self.title_id)
        elif t < self.t_impact + 0.02:
            self._hide(self.title_id)
            for i, L in enumerate(self.letters):
                st = T_TITLE + i * LETTER_STAGGER
                p = prog(t, st, st + LETTER_DUR)
                if p <= 0:
                    self._hide(self.letter_ids[i]); continue
                pe = ease_out(p)
                x = lerp(gx, cx + L["off"], pe) + sx
                y = lerp(gcy, self.title_cy, pe) - 0.16 * H * math.sin(math.pi * pe) + sy
                sc = lerp(0.18, 1.0, ease_back(p))
                q = max(0.1, round(sc * 20) / 20.0)
                li = L["img"]
                ph = self._cached(("L", i, q), lambda li=li, q=q: li.resize((max(2, int(li.width * q)), max(2, int(li.height * q))), Image.BILINEAR))
                self._put(self.letter_ids[i], ph, x, y)
            for iid in self.letter_ids:
                self.tag_raise(iid)
        else:
            for iid in self.letter_ids:
                self._hide(iid)
            if not self._impact_done:
                self._impact_done = True
                self._burst(cx, self.title_cy, 90, 1.0)
            ip = prog(t, self.t_impact, self.t_impact + 0.35)
            punch = 1 + 0.08 * math.sin(math.pi * ip)
            sw0 = self.t_impact + 0.30
            fy = tcy + 2.5 * u * math.sin(t * 2.2)
            if t >= sw0 and prog(t, sw0, sw0 + 0.9) < 1:
                fi = int(prog(t, sw0, sw0 + 0.9) * 15)
                ph = self._cached(("sw", fi), lambda: self.sweep_frames[fi].copy())
            else:
                q = round(punch * 50) / 50.0
                ph = self._cached(("T", q), lambda: self.title_img.resize(
                    (int(self.title_img.width * q), int(self.title_img.height * q)), Image.BILINEAR) if q != 1 else self.title_img.copy())
            self._put(self.title_id, ph, cx + sx, fy)
            self.tag_raise(self.title_id)

        # --- subtitle -------------------------------------------------------------------
        sp = prog(t, T_SUB, T_SUB + 0.75)
        if sp > 0:
            step = int(ease_out(sp) * 28)
            w_full = self.sub_img.width

            def build_sub(step=step):
                cw = max(2, int(w_full * step / 28))
                x0 = (w_full - cw) // 2
                return self.sub_img.crop((x0, 0, x0 + cw, self.sub_img.height))

            ph = self._cached(("sub", step), build_sub)
            y = 0.885 * H + (1 - ease_out(sp)) * 18 * u
            self._put(self.sub_id, ph, cx, y)
            self.tag_raise(self.sub_id)
        else:
            self._hide(self.sub_id)

        # --- confetti & shockwave ------------------------------------------------------------
        self._update_particles(dtb, u)
        if t >= self.t_impact:
            sp2 = prog(t, self.t_impact, self.t_impact + 0.7)
            for k, iid in enumerate(self.shock):
                r = lerp(0.10 * H, 0.95 * max(W, H) * (0.55 + 0.2 * k), ease_out(sp2)) 
                if sp2 >= 1:
                    self._hide(iid); continue
                self.coords(iid, cx - r, self.title_cy - r * 0.55, cx + r, self.title_cy + r * 0.55)
                self.itemconfigure(iid, width=max(1, int((6 - 5 * sp2) * (1 - 0.4 * k))))
                if not self._vis.get(iid):
                    self.itemconfigure(iid, state="normal"); self._vis[iid] = True
                self.tag_raise(iid)
        for c in self.conf:
            if c["alive"]:
                self.tag_raise(c["id"])

        # --- ordered chrome stays on top -------------------------------------------------------
        if SHOW_FRAME_GLOW:
            self.tag_raise(self.frame_a); self.tag_raise(self.frame_b)

        # --- transition into the existing ECG intro --------------------------------------------
        if t >= T_TRANS:
            if self._trans_start is None:
                self._trans_start = real
            tp = prog(real - self._trans_start, 0, TRANSITION_DURATION)
            r = ease_in(tp) * math.hypot(W, H) * 0.56 + 1
            self.coords(self.iris, W / 2 - r, H / 2 - r, W / 2 + r, H / 2 + r)
            if not self._vis.get(self.iris):
                self.itemconfigure(self.iris, state="normal"); self._vis[self.iris] = True
            self.tag_raise(self.iris)
            if self.show_skip_button:
                self.tag_raise("skip")
            if tp >= 1:
                self._finish()
                return
        elif self.show_skip_button:
            self.tag_raise("skip")

    # ----------------------------------------------------------- particles ---
    def _burst(self, x, y, n, power):
        free = [p for p in self.conf if not p["alive"]]
        for p in free[:n]:
            a = random.uniform(0, math.tau)
            sp = random.uniform(180, 620) * power * self.unit
            p.update(alive=True, x=x, y=y, vx=math.cos(a) * sp, vy=math.sin(a) * sp - 260 * self.unit * power,
                     ang=random.uniform(0, 6.28), va=random.uniform(-9, 9),
                     w=random.uniform(5, 11) * self.unit, h=random.uniform(3, 6) * self.unit,
                     life=random.uniform(1.2, 2.2))

    def _update_particles(self, dt, u):
        for p in self.conf:
            if not p["alive"]:
                continue
            p["life"] -= dt
            if p["life"] <= 0 or p["y"] > self.H + 30:
                p["alive"] = False
                self.itemconfigure(p["id"], state="hidden")
                continue
            p["vy"] += 900 * u * dt
            p["vx"] *= 1 - 1.6 * dt
            p["x"] += p["vx"] * dt
            p["y"] += p["vy"] * dt
            p["ang"] += p["va"] * dt
            c, s = math.cos(p["ang"]), math.sin(p["ang"])
            w, h = p["w"], p["h"] * (0.35 + 0.65 * abs(math.sin(p["ang"] * 1.7)))
            pts = []
            for dx, dy in ((-w, -h), (w, -h), (w, h), (-w, h)):
                pts += [p["x"] + dx * c - dy * s, p["y"] + dx * s + dy * c]
            self.coords(p["id"], *pts)
            self.itemconfigure(p["id"], state="normal")


# =============================================================================
#  6.  HOW TO CONNECT IT TO YOUR EXISTING app.py
# =============================================================================
#
#   class App(ctk.CTk):
#       def __init__(self):
#           super().__init__()
#           ...                                  # your existing window setup
#           self.show_opening()
#
#       # ---- NEW: opening -> your existing intro --------------------------------
#       def show_opening(self):
#           self.opening = OpeningIntro(self,
#                                       on_finish=self.start_existing_intro,
#                                       on_skip=self.skip_all_intro)
#           self.opening.start()
#
#       def start_existing_intro(self):
#           # build / show your CURRENT intro (ECG -> hospital -> patient/doctor ->
#           # booking -> payment -> confirmation) exactly as you do today.
#           # IMPORTANT: create it AFTER the opening (or call .lift()) so it sits on top;
#           # the opening canvas destroys itself 80 ms later => no blank frame.
#           self.intro_screen = YourExistingIntro(self, on_done=self.finish_all_intro)
#
#       def finish_all_intro(self):                 # called when your LAST intro scene ends
#           self.open_login_screen()
#
#       def skip_all_intro(self):                   # Skip button / Esc (opening scene)
#           self.open_login_screen()
#
#   In your EXISTING skip button / Esc handler keep:
#           <stop your animation>; self.open_login_screen()
#
#   (OpeningIntro already binds Esc itself while it is on screen.)


# =============================================================================
#  7.  STANDALONE TEST RUNNER  -  only runs when you execute THIS file directly
#      (python opening_intro.py).  Ignored when imported / pasted into app.py.
# =============================================================================
if __name__ == "__main__":
    root = tk.Tk()
    root.title("SMART OPD - opening intro test")
    root.geometry("1280x720")
    root.configure(bg=TRANSITION_COLOR)

    def _next_scene():
        # stand-in for your ECG intro: a dark frame so you can see the hand-over
        f = tk.Frame(root, bg=TRANSITION_COLOR)
        f.place(x=0, y=0, relwidth=1, relheight=1)
        tk.Label(f, text="Your existing ECG intro starts here", bg=TRANSITION_COLOR,
                 fg="white", font=("Segoe UI", 22, "bold")).place(relx=0.5, rely=0.5, anchor="center")
        root.after(2500, root.destroy)

    def _skipped():
        print("Skipped -> open Login screen here")
        root.after(300, root.destroy)

    intro = OpeningIntro(root, on_finish=_next_scene, on_skip=_skipped)
    root.after(300, intro.start)       # small delay so the window is fully drawn first
    root.mainloop()
