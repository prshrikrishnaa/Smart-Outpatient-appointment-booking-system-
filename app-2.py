"""
app.py
Smart Outpatient Appointment Booking System - CINEMATIC EDITION

What's new in this build (on top of the Second Review build):
  - Cinematic movie-style opening (intro.py): hospital corridor -> overloaded
    OPD -> AI queue optimisation -> SMART OPD logo -> dashboard -> login.
    Click or press any key to skip it.
  - Premium dark teal + gold GUI that matches the intro (deep-black canvas,
    glass-like cards, gold hairlines, hover glow on tiles)
  - Animated brand panel on the login screen (pulsing medical cross,
    ECG line, scanner sweep, floating particles) and an ambient particle
    background behind every login / registration card
  - Dashboard stat tiles count up when a screen opens
  - "Replay Intro" button in the patient dashboard header

Everything from the Second Review build is unchanged: queue management,
waiting-time prediction, priority patients, hashed passwords, PDF slips.

Run:  python app.py
Requires:  pip install -r requirements.txt
Files:  app.py  database.py  payment.py  notify.py  homevisit_db.py  homevisit_ui.py  geo.py  models.py  pdf_slip.py  intro.py
"""

import math
import random
import threading
import time
import tkinter as tk

import customtkinter as ctk
from tkinter import messagebox, filedialog

# ----------------------------------------------------------------------
# Harmless Tk timing race: when a button's click handler rebuilds the screen
# (e.g. after booking, refresh, tab change) the old button is destroyed, and
# a delayed "focus" call that customtkinter had already queued for that button
# then fails with  TclError: invalid command name ".!ctkframe...!ctkcanvas".
# Nothing is wrong with the app - the widget is simply gone - so ignore it.
# ----------------------------------------------------------------------
_orig_canvas_focus = tk.Canvas.focus


def _safe_canvas_focus(self, *args):
    try:
        return _orig_canvas_focus(self, *args)
    except tk.TclError:
        return None


tk.Canvas.focus = _safe_canvas_focus
from datetime import datetime, timedelta
from database import Database
from models import Patient
from intro import CinematicIntro
import pdf_slip
import payment
import notify
import homevisit_ui
from opening_intro import OpeningIntro
from homevisit_ui import HomeVisitPatientMixin, HomeVisitAdminMixin, HomeVisitDoctorLoginFrame, HomeVisitDoctorDashboard

# ==========================================================
# THEME - cinematic dark teal + gold (same family as intro.py)
# ==========================================================
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

# NOTE: the old constant names are kept so the rest of the file needs no
# rewrite - NAVY is now the primary teal, BG_LIGHT / CARD_LIGHT are now the
# deep dark surfaces.
NAVY = "#14877f"          # primary teal (button fills, active tab)
NAVY_DARK = "#0d5c57"     # primary hover
TEAL_TXT = "#3fd8c8"      # teal for headings / outline buttons on dark
TEAL_BORDER = "#1d8f88"
GOLD = "#d8b45e"
GOLD_HOVER = "#e8c872"
GOLD_GLOW = "#1c2a22"     # hover tint for transparent gold link buttons
ON_GOLD = "#06181b"       # dark text that sits on gold fills
BG_DEEP = "#050d10"
BG_LIGHT = BG_DEEP        # app background
HEADER_BG = "#07161b"
CARD_LIGHT = "#0a1a20"    # card surface
CARD_HOVER = "#0e2229"
BORDER = "#14414a"
TEXT = "#e6faf7"
SOFT = "#9fc4c6"
SUCCESS = "#1f9d62"
WARN = "#c8913a"
DANGER = "#c0443a"
MUTED = "#7fa3a6"

STATUS_COLORS = {
    "Waiting": WARN,
    "In Consultation": NAVY,
    "Completed": SUCCESS,
    "No-Show": DANGER,
    "Cancelled": MUTED,
}

PRIORITY_BADGE = {
    "Emergency": ("🔴 Emergency", DANGER),
    "Senior Citizen": ("🟡 Senior Citizen", WARN),
    "Normal": ("🟢 Normal", SUCCESS),
}

# Restrained accent family for the icon-tile grids (teal / gold / slate)
TILE_BLUE = "#1f7fa8"
TILE_TEAL = "#14a89a"
TILE_PURPLE = "#4f6fb8"
TILE_ORANGE = "#c8913a"
TILE_PINK = "#b8586f"
TILE_GREEN = "#2f9a62"

TIME_SLOTS = ["09:00 AM", "10:00 AM", "11:00 AM", "12:00 PM",
              "02:00 PM", "03:00 PM", "04:00 PM", "05:00 PM"]


def _apply_theme_overrides():
    # Re-colours CustomTkinter's default widget theme so every entry, tab bar,
    # scrollbar, dropdown and switch - even ones with no explicit colour in
    # the code below - matches the cinematic palette.
    try:
        T = ctk.ThemeManager.theme

        def setv(widget, **vals):
            if widget in T:
                for key, val in vals.items():
                    T[widget][key] = [val, val]

        setv("CTkFrame", fg_color=CARD_LIGHT, top_fg_color=CARD_LIGHT, border_color=BORDER)
        setv("CTkEntry", fg_color="#0c222a", border_color="#17505a", text_color=TEXT,
             placeholder_text_color="#5f8689")
        setv("CTkButton", fg_color=NAVY, hover_color=NAVY_DARK, text_color="#ffffff")
        setv("CTkOptionMenu", fg_color=NAVY, button_color=NAVY_DARK, button_hover_color="#0a4743",
             text_color="#ffffff", dropdown_fg_color="#0c222a", dropdown_hover_color="#14414a",
             dropdown_text_color=TEXT)
        setv("CTkComboBox", fg_color="#0c222a", border_color="#17505a", button_color=NAVY,
             button_hover_color=NAVY_DARK, text_color=TEXT, dropdown_fg_color="#0c222a",
             dropdown_hover_color="#14414a", dropdown_text_color=TEXT)
        setv("CTkTabview", fg_color=CARD_LIGHT, border_color=BORDER,
             segmented_button_fg_color=HEADER_BG, segmented_button_selected_color=NAVY,
             segmented_button_selected_hover_color=NAVY_DARK,
             segmented_button_unselected_color=HEADER_BG,
             segmented_button_unselected_hover_color="#0f2a31", text_color=TEXT)
        setv("CTkScrollbar", button_color="#17505a", button_hover_color=NAVY)
        setv("CTkSwitch", progress_color=GOLD, button_color="#d9f3ef", button_hover_color="#ffffff")
        setv("CTkProgressBar", progress_color=GOLD, fg_color="#0c222a")
        setv("CTkLabel", text_color=TEXT)
        setv("CTkTextbox", fg_color="#0c222a", border_color="#17505a", text_color=TEXT)
    except Exception:
        pass  # purely cosmetic - never let theming break the app


_apply_theme_overrides()


# ==========================================================
# SHARED UI HELPERS
# ==========================================================
def card(parent, **kwargs):
    # every "panel" in the app looks consistent - dark glass surface,
    # rounded corners, thin teal border
    defaults = dict(fg_color=CARD_LIGHT, corner_radius=14, border_width=1,
                     border_color=BORDER)
    defaults.update(kwargs)
    return ctk.CTkFrame(parent, **defaults)


def gold_rule(parent):
    # thin gold hairline used under header bars
    line = ctk.CTkFrame(parent, fg_color="#8f7a3c", height=2, corner_radius=0)
    line.pack(fill="x")
    return line


def status_pill(parent, text, color):
    return ctk.CTkLabel(parent, text=f"  {text}  ", fg_color=color, text_color="white",
                         corner_radius=10, font=ctk.CTkFont(size=11, weight="bold"))


def _count_up(label, target, steps=26, delay=30):
    # animates a stat number 0 -> target; stops quietly if the widget is
    # destroyed (screen changed) and cancels its pending after() on destroy
    state = {"i": 0, "job": None}

    def cancel(_e=None):
        if state["job"] is not None:
            try:
                label.after_cancel(state["job"])
            except Exception:
                pass
            state["job"] = None

    def step():
        state["job"] = None
        try:
            if not label.winfo_exists():
                return
            state["i"] += 1
            u = min(1.0, state["i"] / steps)
            label.configure(text=str(int(round(target * u * u * (3 - 2 * u)))))
            if state["i"] < steps:
                state["job"] = label.after(delay, step)
        except tk.TclError:
            return

    try:
        label.bind("<Destroy>", cancel, add="+")
        state["job"] = label.after(120, step)
    except Exception:
        pass


def nav_tile(parent, *, icon, title, subtitle, color, command):
    # a single dashboard tile: colored rounded icon badge on top, title +
    # subtitle below, the whole card clickable, gold glow border on hover
    tile = card(parent, width=170, height=140)
    tile.pack_propagate(False)
    try:
        tile.configure(cursor="hand2")
    except Exception:
        pass  # cursor styling is cosmetic only - never let it break the build

    badge = ctk.CTkFrame(tile, fg_color=color, corner_radius=16, width=52, height=52)
    badge.pack(pady=(18, 8))
    badge.pack_propagate(False)
    ctk.CTkLabel(badge, text=icon, font=ctk.CTkFont(size=22), text_color="white").pack(expand=True)

    ctk.CTkLabel(tile, text=title, font=ctk.CTkFont(size=13, weight="bold"),
                 text_color=TEXT).pack()
    ctk.CTkLabel(tile, text=subtitle, font=ctk.CTkFont(size=10), text_color=MUTED).pack(pady=(1, 0))

    def on_enter(_e=None):
        try:
            tile.configure(border_color=GOLD, fg_color=CARD_HOVER)
        except tk.TclError:
            pass

    def on_leave(_e=None):
        def check():
            try:
                w = tile.winfo_containing(*tile.winfo_pointerxy())
                while w is not None:
                    if w is tile:
                        return  # pointer is still over the tile (or a child)
                    w = w.master
                tile.configure(border_color=BORDER, fg_color=CARD_LIGHT)
            except (tk.TclError, KeyError):
                pass
        try:
            tile.after(40, check)
        except tk.TclError:
            pass

    # make the whole card (and every child) clickable + hoverable
    for widget in (tile, badge, *tile.winfo_children(), *badge.winfo_children()):
        widget.bind("<Button-1>", lambda e: command())
        widget.bind("<Enter>", on_enter, add="+")
        widget.bind("<Leave>", on_leave, add="+")
    return tile


def stat_tile(parent, *, icon, value, label, color):
    # small stat card used at the top of dashboard grids; whole numbers count up
    tile = card(parent, height=78)
    tile.pack_propagate(False)
    row = ctk.CTkFrame(tile, fg_color="transparent")
    row.pack(expand=True, fill="both", padx=14, pady=10)
    badge = ctk.CTkFrame(row, fg_color=color, corner_radius=10, width=40, height=40)
    badge.pack(side="left")
    badge.pack_propagate(False)
    ctk.CTkLabel(badge, text=icon, font=ctk.CTkFont(size=16), text_color="white").pack(expand=True)
    text_col = ctk.CTkFrame(row, fg_color="transparent")
    text_col.pack(side="left", padx=(12, 0), anchor="center")

    try:
        target = int(value)
        shown = "0"
    except (TypeError, ValueError):
        target, shown = None, str(value)
    value_label = ctk.CTkLabel(text_col, text=shown, font=ctk.CTkFont(size=20, weight="bold"),
                               text_color=TEXT)
    value_label.pack(anchor="w")
    ctk.CTkLabel(text_col, text=label, font=ctk.CTkFont(size=10), text_color=MUTED).pack(anchor="w")
    if target is not None:
        _count_up(value_label, target)
    return tile


# ==========================================================
# ANIMATED CANVAS PANELS (login screens)
# ==========================================================
def _rgb(h):
    return tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))


_BG_RGB = _rgb(BG_DEEP)


def fade_hex(color_hex, a, bg=None):
    # blends a colour toward a background (deep black by default) - used instead of alpha
    a = max(0.0, min(1.0, a))
    c = _rgb(color_hex)
    b = _BG_RGB if bg is None else _rgb(bg)
    return "#%02x%02x%02x" % tuple(int(b[i] + (c[i] - b[i]) * a) for i in range(3))


def _ease(u):
    u = max(0.0, min(1.0, u))
    return u * u * (3 - 2 * u)


def _seg(t, a, b):
    return max(0.0, min(1.0, (t - a) / (b - a)))


class AmbientCanvas(tk.Canvas):
    """Base class: a canvas with ONE tracked after() loop that stops by itself
    when the widget is destroyed (screen change / window close)."""
    FPS = 24
    PARTICLES = 50

    def __init__(self, parent, bg=BG_DEEP, **kw):
        super().__init__(parent, bg=bg, highlightthickness=0, bd=0, **kw)
        self._bg = bg
        self._alive = True
        self._job = None
        self._t0 = time.perf_counter()
        self._seeds = [(random.random(), random.random(), random.random() * 6.283,
                        random.uniform(0.3, 1.0), random.choice((1, 1, 2, 2, 3)),
                        random.random() < 0.2) for _ in range(self.PARTICLES)]
        self.bind("<Destroy>", self._on_destroy, add="+")
        self._job = self.after(60, self._frame)

    def _on_destroy(self, event=None):
        if event is not None and event.widget is not self:
            return
        self._alive = False
        if self._job is not None:
            try:
                self.after_cancel(self._job)
            except Exception:
                pass
            self._job = None

    def _frame(self):
        self._job = None
        if not self._alive:
            return
        try:
            if not self.winfo_exists():
                return
            w, h = max(self.winfo_width(), 10), max(self.winfo_height(), 10)
            self.delete("all")
            self.draw(time.perf_counter() - self._t0, w, h)
        except tk.TclError:
            return
        self._job = self.after(int(1000 / self.FPS), self._frame)

    def draw_particles(self, t, w, h, strength=1.0):
        for sx, sy, ph, sp, sz, gold in self._seeds:
            x = (sx * w + math.sin(t * sp + ph) * 22) % w
            y = (sy * h - t * sp * 16) % h
            tw = 0.35 + 0.65 * (0.5 + 0.5 * math.sin(t * 1.6 * sp + ph * 2))
            col = GOLD if gold else TEAL_TXT
            r = sz * 0.7 + 0.4
            if sz >= 3:
                g = r * 2.8
                self.create_oval(x - g, y - g, x + g, y + g, fill=fade_hex(col, 0.14 * tw * strength), outline="")
            self.create_oval(x - r, y - r, x + r, y + r, fill=fade_hex(col, 0.75 * tw * strength), outline="")

    def draw(self, t, w, h):  # overridden
        pass


class AmbientBackground(AmbientCanvas):
    """Full-window drifting teal/gold particles + soft light behind a login card."""
    PARTICLES = 55

    def __init__(self, parent):
        super().__init__(parent)
        self.place(x=0, y=0, relwidth=1, relheight=1)

    def draw(self, t, w, h):
        fa = min(1.0, t / 1.2)
        for i, (ox, oy, rad, col) in enumerate(((0.25, 0.30, 0.34, TEAL_BORDER), (0.78, 0.72, 0.30, GOLD))):
            cx = w * (ox + 0.05 * math.sin(t * 0.15 + i))
            cy = h * (oy + 0.05 * math.cos(t * 0.12 + i * 2))
            for k, al in ((1.0, 0.025), (0.7, 0.035), (0.4, 0.05)):
                r = min(w, h) * rad * k
                self.create_oval(cx - r, cy - r, cx + r, cy + r, fill=fade_hex(col, al * fa), outline="")
        self.draw_particles(t, w, h, fa)


def _ecg(p):
    p %= 1.0
    if 0.42 < p < 0.45:
        return -(p - 0.42) / 0.03 * 0.3
    if 0.45 <= p < 0.48:
        return -0.3 + (p - 0.45) / 0.03 * 1.3
    if 0.48 <= p < 0.52:
        return 1.0 - (p - 0.48) / 0.04 * 1.5
    if 0.52 <= p < 0.55:
        return -0.5 + (p - 0.52) / 0.03 * 0.5
    if 0.65 < p < 0.75:
        return 0.18 * math.sin((p - 0.65) / 0.10 * math.pi)
    return 0.0


class BrandPanel(AmbientCanvas):
    """Left-hand brand panel of the patient login: pulsing medical cross,
    rotating scanner rings, live ECG line, sweeping scan line, particles."""
    PARTICLES = 70

    def __init__(self, parent, width=440):
        super().__init__(parent, width=width)

    def draw(self, t, w, h):
        fa = min(1.0, t / 1.4)           # emerges from darkness on open
        cx, cy = w / 2.0, h * 0.34
        self.draw_particles(t, w, h, fa)

        # scan sweep
        sy = ((t * 0.10) % 1.0) * h
        for i in range(7):
            y1, y0 = sy - i * 6, sy - (i + 1) * 6
            if y0 >= 0:
                self.create_rectangle(0, y0, w, y1, fill=fade_hex(TEAL_TXT, 0.07 * (1 - i / 7.0) * fa), outline="")
        self.create_line(0, sy, w, sy, fill=fade_hex(TEAL_TXT, 0.35 * fa))

        # glow + rotating rings
        R = min(w, h) * 0.20
        for k, al in ((2.4, 0.04), (1.8, 0.07), (1.35, 0.10)):
            r = R * k
            self.create_oval(cx - r, cy - r, cx + r, cy + r, fill=fade_hex(TEAL_BORDER, al * fa), outline="")
        for rr, wd, ext, spd, col in ((R * 1.15, 3, 100, 70, TEAL_TXT), (R * 1.35, 1, 60, -110, GOLD),
                                      (R * 0.95, 2, 140, 95, TEAL_BORDER)):
            st = (t * spd) % 360
            for off in (0, 180):
                self.create_arc(cx - rr, cy - rr, cx + rr, cy + rr, start=(st + off) % 360, extent=ext,
                                style="arc", outline=fade_hex(col, fa), width=wd)
        # medical cross (gentle heartbeat pulse)
        pulse = 1 + 0.05 * max(0.0, math.sin(t * 2.4)) ** 3 * 4
        L, a = R * 0.62 * pulse, R * 0.62 * pulse * 0.26
        pts = [(-a, -L), (a, -L), (a, -a), (L, -a), (L, a), (a, a),
               (a, L), (-a, L), (-a, a), (-L, a), (-L, -a), (-a, -a)]
        flat = [v for px, py in pts for v in (cx + px, cy + py)]
        self.create_polygon(flat, fill=fade_hex("#d6faf6", 0.95 * fa), outline=fade_hex(TEAL_TXT, fa), width=2)

        # ECG line (scrolling), brighter toward the right
        base, amp = h * 0.56, 24
        pts, n = [], 70
        for i in range(n + 1):
            x = 30 + (w - 60) * i / n
            pts.extend((x, base - _ecg(i / n * 2.2 - t * 0.45) * amp))
        self.create_line(*pts, fill=fade_hex(GOLD, 0.22 * fa), width=6)
        self.create_line(*pts, fill=fade_hex(GOLD, 0.9 * fa), width=2)

        # title block
        ty = h * 0.67
        for dx, dy in ((-2, 0), (2, 0), (0, -2), (0, 2)):
            self.create_text(cx + dx, ty + dy, text="SMART OPD", font=("Segoe UI", 30, "bold"),
                             fill=fade_hex(TEAL_BORDER, 0.35 * fa))
        self.create_text(cx, ty, text="SMART OPD", font=("Segoe UI", 30, "bold"), fill=fade_hex("#d6faf6", fa))
        self.create_text(cx, ty + 36, text="Predict.  Organize.  Care.", font=("Segoe UI", 13),
                         fill=fade_hex(GOLD, fa))
        ln = 70 * min(1.0, max(0.0, (t - 0.6) / 1.0))
        self.create_line(cx - ln, ty + 62, cx + ln, ty + 62, fill=fade_hex(GOLD, 0.6 * fa))
        self.create_text(cx, h * 0.86, text="Predictive queue management for\nhassle-free hospital visits",
                         font=("Segoe UI", 11), fill=fade_hex(SOFT, 0.85 * fa), justify="center")

        # gold corner brackets
        c = 22
        for px, py, sx, sy in ((18, 18, 1, 1), (w - 18, 18, -1, 1), (18, h - 18, 1, -1), (w - 18, h - 18, -1, -1)):
            self.create_line(px, py + sy * c, px, py, px + sx * c, py, fill=fade_hex(GOLD, 0.7 * fa), width=2)
        # LIVE dot
        pr = 4 + 1.2 * math.sin(t * 5)
        self.create_oval(w - 78 - pr, 36 - pr, w - 78 + pr, 36 + pr, fill=fade_hex("#48e27e", fa), outline="")
        self.create_text(w - 66, 36, anchor="w", text="LIVE", font=("Segoe UI", 9, "bold"), fill=fade_hex("#48e27e", fa))


class LiveBadge(AmbientCanvas):
    """Header badge: pulsing green LIVE dot + running clock (same motif as the intro dashboard)."""
    PARTICLES = 0
    FPS = 8

    def __init__(self, parent, bg=HEADER_BG):
        super().__init__(parent, bg=bg, width=150, height=34)

    def draw(self, t, w, h):
        b, g, cy = self._bg, "#48e27e", h / 2.0
        ph = (t * 1.1) % 1.0
        pr, gr = 4.5 + 1.3 * math.sin(t * 5), 7 + 9 * ph
        self.create_oval(18 - gr, cy - gr, 18 + gr, cy + gr, outline=fade_hex(g, 0.5 * (1 - ph), b))
        self.create_oval(18 - pr, cy - pr, 18 + pr, cy + pr, fill=g, outline="")
        self.create_text(32, cy, anchor="w", text="LIVE", font=("Segoe UI", 9, "bold"), fill=g)
        self.create_text(w - 6, cy, anchor="e", text=time.strftime("%H:%M:%S"), font=("Consolas", 11),
                         fill=fade_hex(SOFT, 0.9, b))


class MiniLogo(AmbientCanvas):
    """Small animated Smart OPD mark for the header bars (rotating ring + pulsing cross)."""
    PARTICLES = 0
    FPS = 20

    def __init__(self, parent, bg=HEADER_BG, size=44):
        super().__init__(parent, bg=bg, width=size, height=size)

    def draw(self, t, w, h):
        cx, cy = w / 2.0, h / 2.0
        R = min(w, h) / 2.0 - 3
        st = (t * 90) % 360
        self.create_arc(cx - R, cy - R, cx + R, cy + R, start=st, extent=110, style="arc",
                        outline=TEAL_TXT, width=2)
        self.create_arc(cx - R, cy - R, cx + R, cy + R, start=(st + 180) % 360, extent=60, style="arc",
                        outline=GOLD, width=1)
        L = R * 0.55 * (1 + 0.24 * max(0.0, math.sin(t * 2.4)) ** 3)
        a = L * 0.28
        pts = [(-a, -L), (a, -L), (a, -a), (L, -a), (L, a), (a, a),
               (a, L), (-a, L), (-a, a), (-L, a), (-L, -a), (-a, -a)]
        self.create_polygon([v for px, py in pts for v in (cx + px, cy + py)], fill="#d6faf6",
                            outline=TEAL_TXT)


class StepTrack(AmbientCanvas):
    """3-step progress track for the booking wizard (done = teal, current = pulsing gold)."""
    PARTICLES = 0
    FPS = 12
    LABELS = ("Branch", "Department", "Doctor & Slot")

    def __init__(self, parent, step, bg=CARD_LIGHT):
        super().__init__(parent, bg=bg, width=420, height=52)
        self.step = step

    def draw(self, t, w, h):
        b = self._bg
        xs = [40, 210, 380]
        y = 14
        for i in range(2):
            done = (i + 1) < self.step
            self.create_line(xs[i] + 12, y, xs[i + 1] - 12, y, width=2,
                             fill=TEAL_BORDER if done else fade_hex(BORDER, 1.0, b))
        for i, x in enumerate(xs):
            n = i + 1
            if n < self.step:
                self.create_oval(x - 8, y - 8, x + 8, y + 8, fill=NAVY, outline=TEAL_TXT)
                self.create_line(x - 3, y, x - 1, y + 3, x + 4, y - 3, fill="white", width=2)
            elif n == self.step:
                pr = 9 + 3 * (0.5 + 0.5 * math.sin(t * 4))
                self.create_oval(x - pr, y - pr, x + pr, y + pr, outline=fade_hex(GOLD, 0.45, b))
                self.create_oval(x - 8, y - 8, x + 8, y + 8, fill=GOLD, outline="")
                self.create_text(x, y, text=str(n), font=("Segoe UI", 9, "bold"), fill=ON_GOLD)
            else:
                self.create_oval(x - 8, y - 8, x + 8, y + 8, fill=b, outline=BORDER)
                self.create_text(x, y, text=str(n), font=("Segoe UI", 9, "bold"), fill=MUTED)
            col = TEXT if n == self.step else (SOFT if n < self.step else MUTED)
            self.create_text(x, 38, text=self.LABELS[i], font=("Segoe UI", 9, "bold" if n == self.step else "normal"),
                             fill=col)


class WelcomeOverlay:
    """Short cinematic moment after a successful login: particles gather into a ring,
    WELCOME types in, then the real screen is revealed. Click / any key skips.
    One tracked after() job; calls then() exactly once."""
    DURATION = 2.4

    def __init__(self, root, title, subtitle, then):
        self.root, self.title, self.subtitle, self.then = root, title, subtitle, then
        self.done = False
        self.job = None
        self.keyb = None
        self.cv = tk.Canvas(root, bg=BG_DEEP, highlightthickness=0, bd=0)
        self.cv.place(x=0, y=0, relwidth=1, relheight=1)
        self.seeds = [(random.random(), random.random(), random.random() * 6.283,
                       random.uniform(0.3, 1.0), random.random() < 0.25) for _ in range(80)]
        self.t0 = time.perf_counter()
        self.cv.bind("<Button-1>", self.skip)
        self.cv.bind("<Destroy>", self._destroyed, add="+")
        self.keyb = root.bind("<Key>", self.skip, add="+")
        try:
            self.cv.focus_set()
        except tk.TclError:
            pass
        self.job = self.cv.after(16, self.frame)

    def skip(self, _e=None):
        self.finish()

    def _cleanup(self):
        if self.job is not None:
            try:
                self.cv.after_cancel(self.job)
            except Exception:
                pass
            self.job = None
        if self.keyb is not None:
            try:
                self.root.unbind("<Key>", self.keyb)
            except Exception:
                pass
            self.keyb = None

    def _destroyed(self, event=None):
        if event is not None and event.widget is not self.cv:
            return
        self.done = True
        self._cleanup()

    def finish(self):
        if self.done:
            return
        self.done = True
        self._cleanup()
        try:
            self.cv.destroy()
        except Exception:
            pass
        cb, self.then = self.then, None
        if cb is not None:
            try:
                if self.root.winfo_exists():
                    cb()
            except tk.TclError:
                pass

    def frame(self):
        self.job = None
        if self.done:
            return
        try:
            if not self.cv.winfo_exists():
                return
            t = time.perf_counter() - self.t0
            if t >= self.DURATION:
                self.finish()
                return
            self.draw(t)
        except tk.TclError:
            return
        self.job = self.cv.after(33, self.frame)

    def draw(self, t):
        cv = self.cv
        w, h = max(cv.winfo_width(), 200), max(cv.winfo_height(), 200)
        cv.delete("all")
        cx, cy = w / 2.0, h * 0.42
        fa = _ease(t / 0.35) * (1 - _ease(_seg(t, self.DURATION - 0.45, self.DURATION)))
        R = min(w, h) * 0.17
        u = _ease(_seg(t, 0.0, 1.2))
        # particles gather into a ring
        for i, (sx, sy, ph, sp, gold) in enumerate(self.seeds):
            ang = ph + t * 0.6 * sp
            tx, ty = cx + math.cos(ang) * R * 1.25, cy + math.sin(ang) * R * 1.25
            x = sx * w + (tx - sx * w) * u
            y = sy * h + (ty - sy * h) * u
            col = GOLD if gold else TEAL_TXT
            r = 1.6 if i % 3 else 2.4
            cv.create_oval(x - r, y - r, x + r, y + r, fill=fade_hex(col, 0.85 * fa), outline="")
        # glow + rotating arcs + pulsing cross
        for k, al in ((2.2, 0.04), (1.6, 0.07), (1.2, 0.10)):
            r = R * k * u
            if r > 1:
                cv.create_oval(cx - r, cy - r, cx + r, cy + r, fill=fade_hex(TEAL_BORDER, al * fa), outline="")
        for rr, wd, ext, spd, col in ((R * 1.0, 3, 110, 140, TEAL_TXT), (R * 1.22, 1, 60, -180, GOLD)):
            r = rr * u
            if r > 2:
                for off in (0, 180):
                    cv.create_arc(cx - r, cy - r, cx + r, cy + r, start=(t * spd + off) % 360, extent=ext,
                                  style="arc", outline=fade_hex(col, fa), width=wd)
        ca = _ease(_seg(t, 0.5, 1.1)) * fa
        L = R * 0.55 * (1 + 0.1 * max(0.0, math.sin(t * 5)) ** 3)
        a = L * 0.27
        pts = [(-a, -L), (a, -L), (a, -a), (L, -a), (L, a), (a, a),
               (a, L), (-a, L), (-a, a), (-L, a), (-L, -a), (-a, -a)]
        if ca > 0.02:
            cv.create_polygon([v for px, py in pts for v in (cx + px, cy + py)],
                              fill=fade_hex("#d6faf6", 0.95 * ca), outline=fade_hex(TEAL_TXT, ca), width=2)
        # typed title + gold subtitle
        size = 34 if len(self.title) <= 18 else 24
        n = int(len(self.title) * _seg(t, 0.6, 1.4))
        shown = self.title[:n]
        ty = cy + R * 1.75
        if shown:
            for dx, dy in ((-2, 0), (2, 0), (0, -2), (0, 2)):
                cv.create_text(cx + dx, ty + dy, text=shown, font=("Segoe UI", size, "bold"),
                               fill=fade_hex(TEAL_BORDER, 0.35 * fa))
            cv.create_text(cx, ty, text=shown, font=("Segoe UI", size, "bold"), fill=fade_hex("#d6faf6", fa))
        sa = _ease(_seg(t, 1.2, 1.7)) * fa
        if sa > 0.02:
            cv.create_text(cx, ty + size + 14, text=self.subtitle, font=("Segoe UI", 13), fill=fade_hex(GOLD, sa))
            ln = 90 * sa
            cv.create_line(cx - ln, ty + size + 38, cx + ln, ty + size + 38, fill=fade_hex(GOLD, 0.6 * sa))
        # one scan sweep
        if 0.15 < t < 1.3:
            sy = h * _seg(t, 0.15, 1.3)
            cv.create_line(0, sy, w, sy, fill=fade_hex(TEAL_TXT, 0.35 * fa), width=2)




class PaymentsMixin:
    """Payments tab for Admin (with UPI settings) and Staff (list + verify only).
    Needs self.app and self._branch_scope, like QueueStatsMixin."""

    def _build_payments_tab(self, tab, can_configure=False):
        db = self.app.db
        if can_configure:
            cfg = card(tab)
            cfg.pack(fill="x", padx=15, pady=(12, 8))
            ctk.CTkLabel(cfg, text="💳  UPI / GPay settings", font=ctk.CTkFont(size=14, weight="bold"),
                         text_color=TEAL_TXT).pack(anchor="w", padx=16, pady=(12, 2))
            ctk.CTkLabel(cfg, text="Open GPay > your profile > Bank account to find the exact UPI ID "
                                   "(example: 9345979867@okaxis). Complete the part after the @ below.",
                         text_color=MUTED, font=ctk.CTkFont(size=11), wraplength=760, justify="left"
                         ).pack(anchor="w", padx=16)
            row = ctk.CTkFrame(cfg, fg_color="transparent")
            row.pack(fill="x", padx=16, pady=(10, 4))
            self.pay_upi_entry = ctk.CTkEntry(row, placeholder_text="UPI ID", width=250, height=34)
            self.pay_upi_entry.pack(side="left", padx=(0, 8))
            self.pay_upi_entry.insert(0, db.get_setting("upi_id", payment.DEFAULT_UPI_ID))
            self.pay_handle_menu = ctk.CTkOptionMenu(
                row, values=["+ bank"] + payment.COMMON_HANDLES, width=95, height=34,
                fg_color=NAVY, button_color=NAVY_DARK, command=self._apply_upi_handle)
            self.pay_handle_menu.pack(side="left", padx=(0, 8))
            self.pay_name_entry = ctk.CTkEntry(row, placeholder_text="Payee name", width=210, height=34)
            self.pay_name_entry.pack(side="left", padx=(0, 8))
            self.pay_name_entry.insert(0, db.get_setting("payee_name", payment.DEFAULT_PAYEE))
            self.pay_fee_entry = ctk.CTkEntry(row, placeholder_text="Default fee (Rs.)", width=120, height=34)
            self.pay_fee_entry.pack(side="left", padx=(0, 8))
            self.pay_fee_entry.insert(0, db.get_setting("fee", str(payment.DEFAULT_FEE)))
            ctk.CTkLabel(cfg, text="Default fee is used for doctors who have no fee of their own. "
                                   "Set each doctor's fee in Manage Doctors.",
                         text_color=MUTED, font=ctk.CTkFont(size=11), wraplength=760, justify="left"
                         ).pack(anchor="w", padx=16)
            row2 = ctk.CTkFrame(cfg, fg_color="transparent")
            row2.pack(fill="x", padx=16, pady=(4, 12))
            self.pay_enabled = ctk.CTkSwitch(row2, text="Ask patients to pay while booking")
            if db.get_setting("payments_enabled", "1") == "1":
                self.pay_enabled.select()
            self.pay_enabled.pack(side="left", padx=(0, 16))
            ctk.CTkButton(row2, text="Save settings", width=130, height=32, fg_color=GOLD, hover_color=GOLD_HOVER,
                          text_color=ON_GOLD, command=self._save_payment_settings).pack(side="left")
            self.pay_status_label = ctk.CTkLabel(row2, text="", text_color=MUTED, font=ctk.CTkFont(size=11))
            self.pay_status_label.pack(side="left", padx=12)

        if can_configure:
            self._build_notify_card(tab)

        top = ctk.CTkFrame(tab, fg_color="transparent")
        top.pack(fill="x", padx=15, pady=(8, 0))
        ctk.CTkLabel(top, text="Recent payments", font=ctk.CTkFont(size=14, weight="bold"),
                     text_color=TEAL_TXT).pack(side="left")
        ctk.CTkButton(top, text="🔄 Refresh", width=110, fg_color=GOLD, hover_color=GOLD_HOVER,
                      text_color=ON_GOLD, command=self._refresh_payments).pack(side="right")
        self.payments_list = ctk.CTkScrollableFrame(tab, fg_color="transparent", height=240)
        self.payments_list.pack(fill="both", expand=True, padx=15, pady=(6, 15))
        self._refresh_payments()

    def _apply_upi_handle(self, handle):
        if not handle.startswith("@"):
            return
        base = self.pay_upi_entry.get().split("@")[0].strip()
        self.pay_upi_entry.delete(0, "end")
        self.pay_upi_entry.insert(0, base + handle)
        self.pay_handle_menu.set("+ bank")

    # ---- SMS / WhatsApp booking messages (Admin only) ----
    def _build_notify_card(self, tab):
        db = self.app.db
        ncfg = card(tab)
        ncfg.pack(fill="x", padx=15, pady=(0, 8))
        ctk.CTkLabel(ncfg, text="📱  Booking confirmation messages (SMS / WhatsApp)",
                     font=ctk.CTkFont(size=14, weight="bold"), text_color=TEAL_TXT
                     ).pack(anchor="w", padx=16, pady=(12, 2))
        ctk.CTkLabel(ncfg, text="After every booking the patient's registered mobile number gets a message. "
                                "'WhatsApp (my number)' is free: it uses WhatsApp Web in your browser (log in once "
                                "by scanning the QR, then do not touch the keyboard while it sends; "
                                "pip install pyautogui sends it automatically). Twilio options need an account "
                                "(Account SID, Auth Token, From number).",
                     text_color=MUTED, font=ctk.CTkFont(size=11), wraplength=760, justify="left"
                     ).pack(anchor="w", padx=16)
        r1 = ctk.CTkFrame(ncfg, fg_color="transparent")
        r1.pack(fill="x", padx=16, pady=(10, 4))
        self.notify_provider_menu = ctk.CTkOptionMenu(r1, values=notify.PROVIDERS, width=160, height=34,
                                                      fg_color=NAVY, button_color=NAVY_DARK)
        self.notify_provider_menu.pack(side="left", padx=(0, 8))
        self.notify_provider_menu.set(db.get_setting("notify_provider", "Off"))
        self.notify_sid_entry = ctk.CTkEntry(r1, placeholder_text="Twilio Account SID", width=250, height=34)
        self.notify_sid_entry.pack(side="left", padx=(0, 8))
        self.notify_sid_entry.insert(0, db.get_setting("notify_sid", ""))
        self.notify_token_entry = ctk.CTkEntry(r1, placeholder_text="Auth Token", show="*", width=170, height=34)
        self.notify_token_entry.pack(side="left", padx=(0, 8))
        self.notify_token_entry.insert(0, db.get_setting("notify_token", ""))
        self.notify_from_entry = ctk.CTkEntry(r1, placeholder_text="From  +14155238886", width=150, height=34)
        self.notify_from_entry.pack(side="left")
        self.notify_from_entry.insert(0, db.get_setting("notify_from", ""))
        self.notify_wait_entry = ctk.CTkEntry(r1, placeholder_text="Load wait (sec)", width=105, height=34)
        self.notify_wait_entry.pack(side="left", padx=(8, 0))
        self.notify_wait_entry.insert(0, db.get_setting("notify_wait", "18"))
        r2 = ctk.CTkFrame(ncfg, fg_color="transparent")
        r2.pack(fill="x", padx=16, pady=(4, 12))
        ctk.CTkButton(r2, text="Save", width=90, height=32, fg_color=GOLD, hover_color=GOLD_HOVER,
                      text_color=ON_GOLD, command=self._save_notify_settings).pack(side="left", padx=(0, 14))
        self.notify_test_entry = ctk.CTkEntry(r2, placeholder_text="Test mobile number", width=170, height=32)
        self.notify_test_entry.pack(side="left", padx=(0, 8))
        ctk.CTkButton(r2, text="Send test message", width=140, height=32, fg_color="transparent",
                      text_color=TEAL_TXT, border_width=1, border_color=TEAL_BORDER, hover_color="#0f2a31",
                      command=self._send_test_message).pack(side="left")
        self.notify_status_label = ctk.CTkLabel(r2, text="", text_color=MUTED, font=ctk.CTkFont(size=11),
                                                wraplength=330, justify="left")
        self.notify_status_label.pack(side="left", padx=12)

    def _save_notify_settings(self):
        db = self.app.db
        ok = (db.set_setting("notify_provider", self.notify_provider_menu.get())
              and db.set_setting("notify_sid", self.notify_sid_entry.get().strip())
              and db.set_setting("notify_token", self.notify_token_entry.get().strip())
              and db.set_setting("notify_from", self.notify_from_entry.get().strip())
              and db.set_setting("notify_wait", self.notify_wait_entry.get().strip() or "18"))
        if ok:
            self.notify_status_label.configure(text="Saved.", text_color=SUCCESS)
        else:
            self.notify_status_label.configure(text="Could not save.", text_color=DANGER)

    def _send_test_message(self):
        self._save_notify_settings()
        self.notify_status_label.configure(
            text="Sending... (WhatsApp Web takes ~20 s - do not touch the keyboard)", text_color=MUTED)
        result = []

        def work():
            result.append(notify.send_message(
                self.app.db, self.notify_test_entry.get(),
                "Smart OPD test message - your booking confirmations will arrive here."))

        threading.Thread(target=work, daemon=True).start()

        def poll():
            if not result:
                self.after(400, poll)
                return
            ok, info = result[0]
            self.notify_status_label.configure(
                text=("Done: " + str(info)) if ok else str(info),
                text_color=SUCCESS if ok else DANGER)

        self.after(400, poll)

    def _save_payment_settings(self):
        db = self.app.db
        upi = self.pay_upi_entry.get().strip()
        name = self.pay_name_entry.get().strip() or payment.DEFAULT_PAYEE
        try:
            fee = float(self.pay_fee_entry.get().strip())
            if fee < 0 or fee > 100000:
                raise ValueError
        except ValueError:
            messagebox.showerror("Input Error", "Enter the consultation fee as a number of rupees (0 = free).")
            return
        enabled = "1" if self.pay_enabled.get() else "0"
        ok = (db.set_setting("upi_id", upi) and db.set_setting("payee_name", name)
              and db.set_setting("fee", f"{fee:g}") and db.set_setting("payments_enabled", enabled))
        if not ok:
            messagebox.showerror("Error", "Could not save the payment settings.")
            return
        if payment.is_valid_upi_id(upi):
            msg, col = "Saved - QR payments are ready.", SUCCESS
        else:
            msg, col = "Saved - but the UPI ID is incomplete, patients will only see 'Pay at counter'.", WARN
        self.pay_status_label.configure(text=msg, text_color=col)

    def _refresh_payments(self):
        for w in self.payments_list.winfo_children():
            w.destroy()
        rows = self.app.db.get_payments(self._branch_scope)
        if not rows:
            ctk.CTkLabel(self.payments_list, text="No bookings yet.", text_color=MUTED).pack(pady=10)
            return
        colors = {"Verified": SUCCESS, "Paid - Unverified": WARN, "Pay at Counter": NAVY,
                  "Unpaid": DANGER, "Not Required": MUTED}
        for appt_id, patient, doctor, date, token, amount, method, ref, status in rows:
            r = card(self.payments_list, height=48)
            r.pack(fill="x", pady=4)
            r.pack_propagate(False)
            status_pill(r, status, colors.get(status, MUTED)).pack(side="left", padx=(12, 8))
            detail = f"Token {token:03d}  |  {patient}  |  Dr. {doctor}  |  {date}"
            if amount:
                detail += f"  |  Rs.{amount:.0f}"
            if ref:
                detail += f"  |  ref {ref}"
            ctk.CTkLabel(r, text=detail, anchor="w", font=ctk.CTkFont(size=12)).pack(side="left", padx=4)
            if status == "Paid - Unverified":
                ctk.CTkButton(r, text="Verify", width=80, height=28, fg_color=SUCCESS, hover_color="#166638",
                              command=lambda a=appt_id: self._verify_payment(a)).pack(side="right", padx=12)
            elif status in ("Pay at Counter", "Unpaid"):
                ctk.CTkButton(r, text="Mark Received", width=110, height=28, fg_color=NAVY, hover_color=NAVY_DARK,
                              command=lambda a=appt_id: self._receive_counter_payment(a)).pack(side="right", padx=12)

    def _verify_payment(self, appointment_id):
        ok, msg = self.app.db.verify_payment(appointment_id)
        if not ok:
            messagebox.showinfo("Payment", msg)
        self._refresh_payments()

    def _receive_counter_payment(self, appointment_id):
        try:
            default_fee = float(self.app.db.get_setting("fee", str(payment.DEFAULT_FEE)))
        except ValueError:
            default_fee = float(payment.DEFAULT_FEE)
        fee = self.app.db.get_appointment_fee(appointment_id, default_fee)
        if not messagebox.askyesno("Payment received", f"Mark Rs.{fee:.0f} as received at the counter?"):
            return
        ok, msg = self.app.db.record_counter_payment(appointment_id, fee)
        if not ok:
            messagebox.showinfo("Payment", msg)
        self._refresh_payments()

def generate_and_save_slip(**slip_kwargs):
    # shared by the booking-confirmation dialog and "My Appointments" —
    # asks where to save, builds the PDF (with its QR code), and reports
    # back with a friendly message either way
    token_number = slip_kwargs.get("token_number", 0)
    default_name = f"OPD_Token_{token_number:03d}.pdf"
    save_path = filedialog.asksaveasfilename(
        title="Save Appointment Slip",
        defaultextension=".pdf",
        initialfile=default_name,
        filetypes=[("PDF files", "*.pdf")],
    )
    if not save_path:
        return  # user cancelled the save dialog

    try:
        pdf_slip.generate_slip(save_path, **slip_kwargs)
        messagebox.showinfo("Slip Saved", f"Appointment slip saved to:\n{save_path}")
    except ImportError as e:
        messagebox.showerror("Missing Libraries", str(e))
    except Exception as e:
        messagebox.showerror("Error", f"Could not generate the PDF slip: {e}")


class ConfirmationDialog(ctk.CTkToplevel):
    # a custom modal used after booking, instead of a plain messagebox,
    # so the patient can download their PDF slip right from the popup
    def __init__(self, parent_app, *, patient, doctor_label, department, branch_name,
                 date_label, appointment_date, time_label, priority, token_number,
                 wait_minutes, ahead, payment_text=""):
        super().__init__(parent_app)
        self.title("Appointment Confirmed")
        self.geometry("380x560")
        self.resizable(False, False)
        self.configure(fg_color=BG_LIGHT)
        self.grab_set()  # modal — keeps focus until closed

        header = ctk.CTkFrame(self, fg_color=SUCCESS, corner_radius=0, height=70)
        header.pack(fill="x")
        header.pack_propagate(False)
        ctk.CTkLabel(header, text="✅  Appointment Confirmed", font=ctk.CTkFont(size=16, weight="bold"),
                     text_color="white").pack(pady=22)

        body = card(self)
        body.pack(fill="both", expand=True, padx=18, pady=18)

        def row(label, value):
            r = ctk.CTkFrame(body, fg_color="transparent")
            r.pack(fill="x", padx=16, pady=4)
            ctk.CTkLabel(r, text=label, text_color=MUTED, font=ctk.CTkFont(size=11)).pack(anchor="w")
            ctk.CTkLabel(r, text=value, font=ctk.CTkFont(size=13, weight="bold")).pack(anchor="w")

        row("Patient", f"{patient.name}  (Age {patient.age})")
        row("Doctor", f"{doctor_label}  —  {department}")
        row("Branch", branch_name)
        row("Date & Time", f"{date_label}  at  {time_label}")
        row("Priority", priority)
        if payment_text:
            row("Payment", payment_text)

        token_box = ctk.CTkFrame(body, fg_color=GOLD, corner_radius=10)
        token_box.pack(fill="x", padx=16, pady=(10, 6))
        ctk.CTkLabel(token_box, text="TOKEN NUMBER", text_color=ON_GOLD,
                     font=ctk.CTkFont(size=11, weight="bold")).pack(pady=(8, 0))
        ctk.CTkLabel(token_box, text=f"{token_number:03d}", text_color=ON_GOLD,
                     font=ctk.CTkFont(size=26, weight="bold")).pack(pady=(0, 8))

        ctk.CTkLabel(body, text=f"Estimated wait right now: {wait_minutes} min  "
                                 f"({ahead} patient(s) ahead of you)",
                     font=ctk.CTkFont(size=12), text_color=MUTED, wraplength=300
                     ).pack(padx=16, pady=(6, 12))

        ctk.CTkButton(body, text="⬇  Download PDF Slip", height=38, fg_color=NAVY, hover_color=NAVY_DARK,
                      command=lambda: generate_and_save_slip(
                          patient_name=patient.name, patient_age=patient.age,
                          token_number=token_number, doctor_name=doctor_label.replace("Dr. ", ""),
                          department=department, branch_name=branch_name,
                          appointment_date=appointment_date, appointment_time=time_label,
                          priority=priority, wait_minutes=wait_minutes, payment_text=payment_text)
                      ).pack(fill="x", padx=16, pady=(0, 8))

        ctk.CTkButton(body, text="Done", height=36, fg_color="transparent", text_color=TEAL_TXT,
                      border_width=1, border_color=TEAL_BORDER, command=self.destroy).pack(fill="x", padx=16)



# ==========================================================
# HOME VISIT PAYMENT DIALOG
# ==========================================================
def format_payment(status, method="", ref="", amount=0):
    """Return one human-readable payment line for dialogs, appointments and PDFs."""
    try:
        amount_text = f"Rs.{float(amount):.0f}"
    except (TypeError, ValueError):
        amount_text = "Rs.0"
    if status == "Verified":
        return amount_text + (" at counter" if method == "Counter" else " via UPI") + " - Verified"
    if status == "Paid - Unverified":
        return f"{amount_text} paid via UPI, ref {ref} (awaiting verification)"
    if status == "Pay at Counter":
        return "Pay at the counter on arrival"
    if status == "Pay on Visit":
        return "Pay cash/card to the doctor at the visit"
    if status == "No Charge":
        return "No consultation fee"
    return "Payment pending"


class QRScanCanvas(AmbientCanvas):
    """Black-on-white QR with a subtle animated scan line and corner brackets."""
    PARTICLES = 0
    FPS = 20

    def __init__(self, parent, pil_image, size=270):
        super().__init__(parent, bg=CARD_LIGHT, width=size, height=size)
        from PIL import ImageTk
        self._img = pil_image
        self._photo = ImageTk.PhotoImage(pil_image)

    def draw(self, t, w, h):
        iw, ih = self._img.size
        x0, y0 = (w - iw) / 2.0, (h - ih) / 2.0
        self.create_image(w / 2.0, h / 2.0, image=self._photo)
        sy = y0 + ((t * 0.55) % 1.0) * ih
        for i in range(6):
            a, b = sy - (i + 1) * 4, sy - i * 4
            if a > y0:
                self.create_rectangle(
                    x0, a, x0 + iw, b,
                    fill=fade_hex(GOLD, 0.10 * (1 - i / 6.0), "#ffffff"), outline=""
                )
        self.create_line(x0, sy, x0 + iw, sy, fill=GOLD, width=2)
        c, m = 22, 6
        for px, py, sx, sy2 in (
            (x0 - m, y0 - m, 1, 1), (x0 + iw + m, y0 - m, -1, 1),
            (x0 - m, y0 + ih + m, 1, -1), (x0 + iw + m, y0 + ih + m, -1, -1)
        ):
            self.create_line(px, py + sy2 * c, px, py, px + sx * c, py, fill=GOLD, width=3)


class PaymentDialog(ctk.CTkToplevel):
    """Shared payment dialog for normal OPD and Home Visit bookings.

    Online payment uses a standard UPI deep-link QR. The patient enters the
    12-digit UTR/reference after paying. The booking remains Paid - Unverified
    until Admin/Staff verifies it. No fake automatic bank confirmation is used.
    """

    def __init__(self, app, *, amount, doctor_label="", department="", on_done=None,
                 allow_counter=True, counter_text="Pay at counter instead",
                 note="OPD consultation", fallback_msg=""):
        super().__init__(app)
        self.app, self.amount, self.on_done = app, float(amount), on_done
        self._finished = False
        self.title("Secure Payment")
        self.configure(fg_color=BG_LIGHT)
        self.resizable(False, False)
        w, h = 800, 560
        try:
            x = app.winfo_rootx() + max(0, (app.winfo_width() - w) // 2)
            y = app.winfo_rooty() + max(0, (app.winfo_height() - h) // 2)
            self.geometry(f"{w}x{h}+{x}+{y}")
        except tk.TclError:
            self.geometry(f"{w}x{h}")
        self.transient(app)
        self.after(150, self._grab)

        db = app.db
        self.upi_id = db.get_setting("upi_id", payment.DEFAULT_UPI_ID).strip()
        self.payee = db.get_setting("payee_name", payment.DEFAULT_PAYEE).strip() or payment.DEFAULT_PAYEE
        self.configured = payment.is_valid_upi_id(self.upi_id)

        header = ctk.CTkFrame(self, fg_color=HEADER_BG, corner_radius=0, height=64)
        header.pack(fill="x")
        header.pack_propagate(False)
        gold_rule(self)
        MiniLogo(header, size=40).pack(side="left", padx=(20, 0))
        ctk.CTkLabel(header, text="Secure Payment",
                     font=ctk.CTkFont(size=19, weight="bold"), text_color="white").pack(side="left", padx=12)
        LiveBadge(header).pack(side="right", padx=14)

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=20, pady=16)

        left = card(body, width=310)
        left.pack(side="left", fill="y")
        left.pack_propagate(False)
        self.qr_widget = None
        qr_error = ""
        if self.configured:
            try:
                uri = payment.build_upi_uri(self.upi_id, self.payee, self.amount, note)
                self.qr_widget = QRScanCanvas(left, payment.make_qr_image(uri, 230), size=270)
                self.qr_widget.pack(padx=18, pady=(18, 6))
                ctk.CTkLabel(
                    left, text="Scan with GPay, PhonePe, Paytm\nor any UPI app",
                    text_color=SOFT, font=ctk.CTkFont(size=12), justify="center"
                ).pack(pady=(0, 6))
            except ImportError as e:
                qr_error = str(e)
            except Exception as e:
                qr_error = f"Could not create the QR code: {e}"
        else:
            qr_error = ("The QR cannot be shown because the hospital UPI ID is incomplete "
                        "(it needs the bank part after the @, e.g. 9345979867@okaxis).\n\n"
                        "Admin: Admin Portal > Payments > complete the UPI ID and press Save.")
        if self.qr_widget is None:
            ctk.CTkLabel(left, text="⚠", font=ctk.CTkFont(size=40), text_color=GOLD).pack(pady=(60, 8))
            ctk.CTkLabel(left, text=qr_error, text_color=SOFT, wraplength=260,
                         justify="center", font=ctk.CTkFont(size=12)).pack(padx=16)

        right = ctk.CTkFrame(body, fg_color="transparent")
        right.pack(side="left", fill="both", expand=True, padx=(18, 0))
        ctk.CTkLabel(right, text="Amount to pay", text_color=MUTED,
                     font=ctk.CTkFont(size=12)).pack(anchor="w")
        ctk.CTkLabel(right, text=f"₹ {self.amount:,.2f}", text_color=GOLD,
                     font=ctk.CTkFont(size=36, weight="bold")).pack(anchor="w")
        ctk.CTkLabel(right, text=f"{doctor_label}  -  {department}", text_color=SOFT,
                     font=ctk.CTkFont(size=12), wraplength=390).pack(anchor="w", pady=(0, 10))

        if self.qr_widget is not None:
            ctk.CTkLabel(right, text="Pay to:", text_color=MUTED,
                         font=ctk.CTkFont(size=11)).pack(anchor="w")
            line = ctk.CTkFrame(right, fg_color="transparent")
            line.pack(fill="x", pady=(0, 8))
            ctk.CTkLabel(line, text=f"{self.payee}   |   {self.upi_id}", text_color=TEXT,
                         font=ctk.CTkFont(size=12, weight="bold")).pack(side="left")
            ctk.CTkButton(line, text="Copy", width=52, height=24, fg_color="transparent",
                          text_color=TEAL_TXT, border_width=1, border_color=TEAL_BORDER,
                          hover_color="#0f2a31", command=self._copy_upi).pack(side="left", padx=8)
            ctk.CTkLabel(
                right,
                text="1. Scan the QR and pay the exact amount\n"
                     "2. Copy the 12-digit UPI reference / UTR\n"
                     "3. Enter it below and confirm",
                text_color=SOFT, justify="left", font=ctk.CTkFont(size=12)
            ).pack(anchor="w", pady=(0, 10))
            self.ref_entry = ctk.CTkEntry(right, placeholder_text="12-digit UPI reference / UTR", height=38)
            self.ref_entry.pack(fill="x")
            self.ref_entry.bind("<Return>", lambda e: self._confirm_upi())
            self.msg = ctk.CTkLabel(right, text="", text_color=DANGER,
                                    font=ctk.CTkFont(size=11), wraplength=390, justify="left")
            self.msg.pack(anchor="w", pady=(4, 6))
            ctk.CTkButton(
                right, text="✔  I have paid - Continue", height=40, fg_color=GOLD,
                hover_color=GOLD_HOVER, text_color=ON_GOLD,
                font=ctk.CTkFont(weight="bold"), command=self._confirm_upi
            ).pack(fill="x", pady=(0, 8))
        else:
            self.ref_entry = None
            self.msg = ctk.CTkLabel(
                right, text=fallback_msg or "You can still book and pay at the hospital/visit.",
                text_color=SOFT, wraplength=390, justify="left", font=ctk.CTkFont(size=12)
            )
            self.msg.pack(anchor="w", pady=(10, 14))

        if allow_counter:
            ctk.CTkButton(
                right, text=counter_text, height=36, fg_color="transparent",
                text_color=TEAL_TXT, border_width=1, border_color=TEAL_BORDER,
                hover_color="#0f2a31", command=lambda: self._finish("Counter", "")
            ).pack(fill="x", pady=(0, 6))
        ctk.CTkButton(right, text="Cancel", height=30, fg_color="transparent",
                      text_color=MUTED, hover_color="#0f2a31",
                      command=self.destroy).pack(fill="x")

    def _grab(self):
        try:
            if self.winfo_exists():
                self.grab_set()
                if self.ref_entry is not None:
                    self.ref_entry.focus_set()
        except tk.TclError:
            pass

    def _copy_upi(self):
        try:
            self.clipboard_clear()
            self.clipboard_append(self.upi_id)
            self.msg.configure(text="UPI ID copied.", text_color=SUCCESS)
        except tk.TclError:
            pass

    def _confirm_upi(self):
        ref = self.ref_entry.get().strip() if self.ref_entry is not None else ""
        if not payment.is_valid_utr(ref):
            self.msg.configure(
                text="Enter the 12-digit UPI reference number (digits only) shown in your payment app.",
                text_color=DANGER
            )
            return
        if self.app.db.payment_ref_exists(ref):
            self.msg.configure(text="This reference was already used for another booking.",
                               text_color=DANGER)
            return
        self._finish("UPI", ref)

    def _finish(self, method, ref):
        if self._finished:
            return
        self._finished = True
        cb, self.on_done = self.on_done, None
        try:
            self.grab_release()
        except tk.TclError:
            pass
        self.destroy()
        if cb is not None:
            cb(method, ref)


# Give the Home Visit module access to the existing theme/helpers.
homevisit_ui.bind(globals())

# ==========================================================
# MAIN APPLICATION SHELL
# ==========================================================
class OPDApp(ctk.CTk):
    def report_callback_exception(self, exc, val, tb):
        # Ignore only the "widget was already destroyed" errors (see note near the top of
        # this file); every other error is still printed so real bugs are never hidden.
        if isinstance(val, tk.TclError):
            msg = str(val)
            if "invalid command name" in msg or "bad window path name" in msg:
                return
        super().report_callback_exception(exc, val, tb)

    def __init__(self):
        super().__init__()
        self.title("Smart OPD Appointment Booking System")
        w, h = 1180, 760
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        w, h = min(w, sw - 60), min(h, sh - 100)
        self.geometry(f"{w}x{h}+{(sw - w) // 2}+{max(0, (sh - h) // 2 - 20)}")
        self.minsize(980, 640)
        self.configure(fg_color=BG_LIGHT)

        self.db = Database()

        # holds the logged-in patient object, or None if not logged in
        self.current_patient = None

        # holds the branch/department/doctor picked so far during booking
        self.selected_branch_id = None
        self.selected_branch_name = None
        self.selected_department = None
        # Home Visit doctor session
        self.current_hv_doctor = None

        self.container = ctk.CTkFrame(self, fg_color=BG_LIGHT)
        self.container.pack(fill="both", expand=True)

        # cinematic opening first; the login screen appears when it ends / is skipped
        self.intro = None
        self.after(150, self.play_intro)

    # ---------- navigation helpers ----------
    def _clear_container(self):
        for widget in self.container.winfo_children():
            widget.destroy()

    def _reveal(self, frames=14, delay=16):
        # cinematic screen change: a dark curtain with a glowing gold edge
        # sweeps away left -> right. One tracked after() job; it stops by
        # itself if the screen is replaced (curtain gets destroyed) mid-way.
        curtain = tk.Canvas(self.container, bg=BG_DEEP, highlightthickness=0, bd=0)
        curtain.place(x=0, y=0, relwidth=1, relheight=1)
        state = {"i": 0, "job": None}

        def stop(event=None):
            if event is not None and event.widget is not curtain:
                return
            if state["job"] is not None:
                try:
                    curtain.after_cancel(state["job"])
                except Exception:
                    pass
                state["job"] = None

        def step():
            state["job"] = None
            try:
                if not curtain.winfo_exists():
                    return
                state["i"] += 1
                u = min(1.0, state["i"] / frames)
                u = u * u * (3 - 2 * u)
                w, h = max(curtain.winfo_width(), 2), max(curtain.winfo_height(), 2)
                x = w * u
                curtain.delete("all")
                if u >= 1.0:
                    curtain.destroy()
                    return
                curtain.create_rectangle(x, 0, w, h, fill=BG_DEEP, outline="")
                for k, col in ((14, "#0b2a2d"), (8, "#124a4a"), (3, "#8f7a3c")):
                    curtain.create_rectangle(max(0, x - k), 0, x, h, fill=col, outline="")
                curtain.create_line(x, 0, x, h, fill=GOLD, width=2)
                state["job"] = curtain.after(delay, step)
            except tk.TclError:
                return

        curtain.bind("<Destroy>", stop, add="+")
        state["job"] = curtain.after(delay, step)

    def play_intro(self, on_done=None):
        # plays the cinematic intro on top of the current screen.
        # on_done runs when it finishes or the user skips (click / any key)
        if self.intro is not None or not self.winfo_exists():
            return

        def finished():
            self.intro = None
            (on_done or self.show_login_frame)()

        self.intro = CinematicIntro(self, finished)
        self.intro.start()

    def welcome_then(self, title, subtitle, then):
        # cinematic "welcome" moment after login, then the real screen
        if getattr(self, "_welcome", None) is not None:
            return

        def done():
            self._welcome = None
            then()

        self._welcome = WelcomeOverlay(self, title, subtitle, done)

    def replay_intro(self):
        self.play_intro(on_done=lambda: None)  # stay on the current screen afterwards

    def show_login_frame(self):
        self._clear_container()
        LoginFrame(self.container, self)
        self._reveal()

    def show_register_frame(self):
        self._clear_container()
        RegisterFrame(self.container, self)
        self._reveal()

    def show_admin_login_frame(self):
        self._clear_container()
        AdminLoginFrame(self.container, self)
        self._reveal()

    def show_admin_portal_frame(self):
        self._clear_container()
        AdminPortalFrame(self.container, self)
        self._reveal()

    def show_staff_login_frame(self):
        self._clear_container()
        StaffLoginFrame(self.container, self)
        self._reveal()

    def show_hv_doctor_login_frame(self):
        self._clear_container()
        HomeVisitDoctorLoginFrame(self.container, self)
        self._reveal()

    def show_hv_doctor_dashboard_frame(self):
        self._clear_container()
        HomeVisitDoctorDashboard(self.container, self)
        self._reveal()

    def hv_doctor_logout(self):
        self.current_hv_doctor = None
        self.show_login_frame()

    def show_staff_portal_frame(self, branch_id, branch_name):
        self._clear_container()
        StaffPortalFrame(self.container, self, branch_id, branch_name)
        self._reveal()

    def show_dashboard_frame(self, open_tab=None):
        self._clear_container()
        DashboardFrame(self.container, self, open_tab=open_tab)
        self._reveal()

    def logout(self):
        self.current_patient = None
        self.current_hv_doctor = None
        self.selected_branch_id = None
        self.selected_branch_name = None
        self.selected_department = None
        self.show_login_frame()


# ==========================================================
# PATIENT LOGIN  (+ link to Admin Login)
# ==========================================================
class LoginFrame(ctk.CTkFrame):
    def __init__(self, parent, app: OPDApp):
        super().__init__(parent, fg_color=BG_LIGHT)
        self.app = app
        self.pack(fill="both", expand=True)

        # split screen: animated cinematic brand panel on the left, form on the right
        BrandPanel(self, width=440).pack(side="left", fill="y")

        right = ctk.CTkFrame(self, fg_color=BG_LIGHT)
        right.pack(side="left", fill="both", expand=True)

        AmbientBackground(right)
        form = card(right, width=340)
        form.place(relx=0.5, rely=0.5, anchor="center")

        ctk.CTkLabel(form, text="Patient Login", font=ctk.CTkFont(size=22, weight="bold"),
                     text_color=TEAL_TXT).pack(pady=(35, 5), padx=40)
        ctk.CTkLabel(form, text="Welcome back — please sign in", font=ctk.CTkFont(size=12),
                     text_color=MUTED).pack(pady=(0, 20))

        self.username_entry = ctk.CTkEntry(form, placeholder_text="Username", width=280, height=38)
        self.username_entry.pack(pady=8, padx=40)

        self.password_entry = ctk.CTkEntry(form, placeholder_text="Password", show="*", width=280, height=38)
        self.password_entry.pack(pady=8, padx=40)
        self.password_entry.bind("<Return>", lambda e: self.handle_login())

        ctk.CTkButton(form, text="Login", width=280, height=40, fg_color=NAVY, hover_color=NAVY_DARK,
                      font=ctk.CTkFont(weight="bold"), command=self.handle_login).pack(pady=(20, 8), padx=40)
        ctk.CTkButton(form, text="New Patient? Register", width=280, fg_color="transparent",
                      text_color=TEAL_TXT, border_width=1, border_color=TEAL_BORDER,
                      command=self.app.show_register_frame).pack(pady=4, padx=40)

        link_row = ctk.CTkFrame(form, fg_color="transparent")
        link_row.pack(pady=(20, 30), padx=40)
        ctk.CTkButton(link_row, text="Admin Login", width=136, fg_color="transparent",
                      text_color=GOLD_HOVER, hover_color=GOLD_GLOW,
                      command=self.app.show_admin_login_frame).pack(side="left", padx=(0, 4))
        ctk.CTkButton(link_row, text="Staff Login", width=136, fg_color="transparent",
                      text_color=GOLD_HOVER, hover_color=GOLD_GLOW,
                      command=self.app.show_staff_login_frame).pack(side="left", padx=(4, 0))
        ctk.CTkButton(form, text="🏠 Home Visit Doctor Login", width=280,
                      fg_color="transparent", text_color=GOLD_HOVER, hover_color=GOLD_GLOW,
                      border_width=1, border_color="#8f6f32",
                      command=self.app.show_hv_doctor_login_frame).pack(pady=(0, 24), padx=40)

    def handle_login(self):
        username = self.username_entry.get().strip()
        password = self.password_entry.get().strip()

        if not username or not password:
            messagebox.showerror("Input Error", "Please enter both username and password.")
            return

        try:
            result = self.app.db.authenticate_patient(username, password)
            if result:
                # wrap the raw row into a Patient object (encapsulation)
                self.app.current_patient = Patient.from_row(result)
                self.app.welcome_then(f"WELCOME, {self.app.current_patient.name.upper()}",
                                      "Predict.  Organize.  Care.", self.app.show_dashboard_frame)
            else:
                messagebox.showerror("Login Failed", "Invalid username or password.")
        except Exception as e:
            messagebox.showerror("Error", f"Something went wrong: {e}")


# ==========================================================
# PATIENT REGISTRATION
# ==========================================================
class RegisterFrame(ctk.CTkFrame):
    def __init__(self, parent, app: OPDApp):
        super().__init__(parent, fg_color=BG_LIGHT)
        self.app = app
        self.pack(fill="both", expand=True)

        AmbientBackground(self)
        form = card(self, width=360)
        form.place(relx=0.5, rely=0.5, anchor="center")

        ctk.CTkLabel(form, text="Patient Registration", font=ctk.CTkFont(size=22, weight="bold"),
                     text_color=TEAL_TXT).pack(pady=(30, 20), padx=40)

        self.name_entry = ctk.CTkEntry(form, placeholder_text="Full Name", width=300, height=36)
        self.name_entry.pack(pady=6, padx=40)

        self.age_entry = ctk.CTkEntry(form, placeholder_text="Age", width=300, height=36)
        self.age_entry.pack(pady=6, padx=40)

        self.gender_menu = ctk.CTkOptionMenu(form, values=["Male", "Female", "Other"], width=300,
                                              fg_color=NAVY, button_color=NAVY_DARK)
        self.gender_menu.pack(pady=6, padx=40)

        self.contact_entry = ctk.CTkEntry(form, placeholder_text="Contact Number", width=300, height=36)
        self.contact_entry.pack(pady=6, padx=40)

        self.username_entry = ctk.CTkEntry(form, placeholder_text="Choose a Username", width=300, height=36)
        self.username_entry.pack(pady=6, padx=40)

        self.password_entry = ctk.CTkEntry(form, placeholder_text="Choose a Password", show="*",
                                            width=300, height=36)
        self.password_entry.pack(pady=6, padx=40)

        ctk.CTkLabel(form, text="Patients aged 60+ are automatically prioritised in the queue.",
                     font=ctk.CTkFont(size=11), text_color=MUTED, wraplength=300).pack(pady=(6, 0), padx=40)

        ctk.CTkButton(form, text="Register", width=300, height=40, fg_color=NAVY, hover_color=NAVY_DARK,
                      font=ctk.CTkFont(weight="bold"), command=self.handle_register).pack(pady=(16, 8), padx=40)

        ctk.CTkButton(form, text="Back to Login", width=300, fg_color="transparent",
                      text_color=TEAL_TXT, border_width=1, border_color=TEAL_BORDER,
                      command=self.app.show_login_frame).pack(pady=(4, 30), padx=40)

    def handle_register(self):
        name = self.name_entry.get().strip()
        age_text = self.age_entry.get().strip()
        gender = self.gender_menu.get()
        contact = self.contact_entry.get().strip()
        username = self.username_entry.get().strip()
        password = self.password_entry.get().strip()

        if not all([name, age_text, contact, username, password]):
            messagebox.showerror("Input Error", "Please fill in all fields.")
            return

        try:
            age = int(age_text)
            if age <= 0 or age > 120:
                raise ValueError("Age out of realistic range.")
        except ValueError:
            messagebox.showerror("Input Error", "Please enter a valid age (1-120).")
            return

        if not contact.isdigit() or len(contact) < 10:
            messagebox.showerror("Input Error", "Please enter a valid contact number.")
            return

        success, message = self.app.db.register_patient(name, age, gender, contact, username, password)
        if success:
            messagebox.showinfo("Success", message)
            self.app.show_login_frame()
        else:
            messagebox.showerror("Registration Failed", message)


# ==========================================================
# ADMIN LOGIN  (username: admin, password: 0000)
# ==========================================================
class AdminLoginFrame(ctk.CTkFrame):
    def __init__(self, parent, app: OPDApp):
        super().__init__(parent, fg_color=BG_LIGHT)
        self.app = app
        self.pack(fill="both", expand=True)

        AmbientBackground(self)
        form = card(self, width=340)
        form.place(relx=0.5, rely=0.5, anchor="center")

        ctk.CTkLabel(form, text="🔐", font=ctk.CTkFont(size=34)).pack(pady=(30, 0))
        ctk.CTkLabel(form, text="Admin Login", font=ctk.CTkFont(size=22, weight="bold"),
                     text_color=TEAL_TXT).pack(pady=(5, 20))

        self.username_entry = ctk.CTkEntry(form, placeholder_text="Admin Username", width=280, height=36)
        self.username_entry.pack(pady=8, padx=30)

        self.password_entry = ctk.CTkEntry(form, placeholder_text="Admin Password", show="*",
                                            width=280, height=36)
        self.password_entry.pack(pady=8, padx=30)
        self.password_entry.bind("<Return>", lambda e: self.handle_admin_login())

        ctk.CTkButton(form, text="Login", width=280, height=38, fg_color=GOLD, hover_color=GOLD_HOVER,
                      text_color=ON_GOLD, font=ctk.CTkFont(weight="bold"),
                      command=self.handle_admin_login).pack(pady=(20, 8), padx=30)

        ctk.CTkButton(form, text="Back", width=280, fg_color="transparent",
                      text_color=TEAL_TXT, border_width=1, border_color=TEAL_BORDER,
                      command=self.app.show_login_frame).pack(pady=(4, 30), padx=30)

    def handle_admin_login(self):
        username = self.username_entry.get().strip()
        password = self.password_entry.get().strip()

        if self.app.db.authenticate_admin(username, password):
            self.app.welcome_then("ADMIN CONSOLE", "Full control of the hospital network",
                                  self.app.show_admin_portal_frame)
        else:
            messagebox.showerror("Login Failed", "Invalid admin username or password.")


# ==========================================================
# ADMIN PORTAL — tabbed: Branches | Doctors | Queue Control | Live Stats
# ==========================================================
class QueueStatsMixin:
    """
    Shared queue-control and live-stats behaviour, used by both
    AdminPortalFrame (branch_scope = None -> sees every branch) and
    StaffPortalFrame (branch_scope = one branch_id -> sees only that
    branch). Whoever uses this mixin must set self.app and
    self._branch_scope before calling _build_queue_tab / _build_stats_tab.
    """

    # -------------------- Queue Control tab --------------------
    def _build_queue_tab(self, tab):
        # self._branch_scope is None for Admin (sees every doctor);
        # StaffPortalFrame sets it to its own branch_id before this runs,
        # so every method below is automatically scoped to that branch
        top = ctk.CTkFrame(tab, fg_color="transparent")
        top.pack(fill="x", padx=15, pady=15)

        self.queue_doctors_cache = self.app.db.get_all_doctors_with_branch(self._branch_scope)
        doctor_labels = [f"Dr. {d[1]} ({d[2]})" for d in self.queue_doctors_cache] or ["No doctors yet"]
        ctk.CTkLabel(top, text="Select Doctor:").pack(side="left", padx=(0, 8))
        self.queue_doctor_menu = ctk.CTkOptionMenu(top, values=doctor_labels, width=220,
                                                     fg_color=NAVY, button_color=NAVY_DARK,
                                                     command=lambda _: self._refresh_queue_list())
        self.queue_doctor_menu.pack(side="left", padx=(0, 8))

        ctk.CTkButton(top, text="🔄 Refresh Queue", width=140, fg_color=GOLD, hover_color=GOLD_HOVER,
                      text_color=ON_GOLD, command=self._refresh_queue_list).pack(side="left")

        # ---- Doctor delay adjustment — feeds the wait-time prediction ----
        delay_bar = card(tab)
        delay_bar.pack(fill="x", padx=15, pady=(0, 10))
        ctk.CTkLabel(delay_bar, text="⏱ Running Late?", font=ctk.CTkFont(weight="bold"),
                     text_color=TEAL_TXT).pack(side="left", padx=(14, 10), pady=10)
        self.delay_status_label = ctk.CTkLabel(delay_bar, text="", text_color=MUTED)
        self.delay_status_label.pack(side="left", padx=(0, 10))
        self.delay_entry = ctk.CTkEntry(delay_bar, placeholder_text="Delay in minutes", width=140, height=32)
        self.delay_entry.pack(side="left", padx=(0, 8))
        ctk.CTkButton(delay_bar, text="Report Delay", width=120, height=32, fg_color=WARN,
                      hover_color="#96600e", command=self._handle_set_delay).pack(side="left", padx=(0, 8))
        ctk.CTkButton(delay_bar, text="Clear Delay", width=110, height=32, fg_color="transparent",
                      text_color=TEAL_TXT, border_width=1, border_color=TEAL_BORDER,
                      command=self._handle_clear_delay).pack(side="left")

        self.queue_list = ctk.CTkScrollableFrame(tab, fg_color="transparent", height=290)
        self.queue_list.pack(fill="both", expand=True, padx=15, pady=(5, 15))
        self._refresh_queue_list()

    def _refresh_queue_doctor_menu(self):
        self.queue_doctors_cache = self.app.db.get_all_doctors_with_branch(self._branch_scope)
        labels = [f"Dr. {d[1]} ({d[2]})" for d in self.queue_doctors_cache] or ["No doctors yet"]
        self.queue_doctor_menu.configure(values=labels)
        self.queue_doctor_menu.set(labels[0])
        self._refresh_queue_list()

    def _get_selected_queue_doctor(self):
        label = self.queue_doctor_menu.get()
        for d in self.queue_doctors_cache:
            if f"Dr. {d[1]} ({d[2]})" == label:
                return d  # (doctor_id, name, department, branch_name, avg_min, delay_min, branch_id)
        return None

    def _handle_set_delay(self):
        doctor = self._get_selected_queue_doctor()
        if doctor is None:
            messagebox.showerror("Error", "Please select a doctor first.")
            return
        text = self.delay_entry.get().strip()
        try:
            minutes = int(text)
            if minutes < 0 or minutes > 240:
                raise ValueError
        except ValueError:
            messagebox.showerror("Input Error", "Enter a delay in minutes (0-240).")
            return
        success, message = self.app.db.set_doctor_delay(doctor[0], minutes)
        if success:
            self.delay_entry.delete(0, "end")
            self._refresh_queue_doctor_menu()
        else:
            messagebox.showerror("Error", message)

    def _handle_clear_delay(self):
        doctor = self._get_selected_queue_doctor()
        if doctor is None:
            return
        self.app.db.set_doctor_delay(doctor[0], 0)
        self._refresh_queue_doctor_menu()

    def _refresh_queue_list(self):
        for w in self.queue_list.winfo_children():
            w.destroy()

        if not self.queue_doctors_cache:
            ctk.CTkLabel(self.queue_list, text="Add a doctor first.", text_color=MUTED).pack(pady=10)
            return

        doctor = self._get_selected_queue_doctor()
        doctor_id = doctor[0] if doctor else None
        if doctor_id is None:
            return

        # reflect the doctor's current reported delay right above the queue
        current_delay = doctor[5]
        if current_delay > 0:
            self.delay_status_label.configure(
                text=f"Dr. {doctor[1]} is currently reported {current_delay} min late",
                text_color=WARN)
        else:
            self.delay_status_label.configure(text="No delay reported for this doctor", text_color=MUTED)

        queue = self.app.db.get_queue_for_doctor(doctor_id)
        if not queue:
            ctk.CTkLabel(self.queue_list, text="No patients currently in this doctor's queue.",
                         text_color=MUTED).pack(pady=10)
            return

        for appt_id, token, name, age, status, priority, appt_date, appt_time in queue:
            row = card(self.queue_list, height=56)
            row.pack(fill="x", pady=4)

            left = ctk.CTkFrame(row, fg_color="transparent")
            left.pack(side="left", fill="x", expand=True, padx=12, pady=8)
            badge_text, badge_color = PRIORITY_BADGE.get(priority, PRIORITY_BADGE["Normal"])
            top_line = ctk.CTkFrame(left, fg_color="transparent")
            top_line.pack(anchor="w", fill="x")
            ctk.CTkLabel(top_line, text=f"Token {token:03d}  —  {name} (Age {age})",
                         font=ctk.CTkFont(weight="bold")).pack(side="left")
            status_pill(top_line, badge_text, badge_color).pack(side="left", padx=(10, 0))
            ctk.CTkLabel(left, text=f"{appt_date}  {appt_time}   |   Status: {status}",
                         font=ctk.CTkFont(size=11), text_color=MUTED).pack(anchor="w")

            btns = ctk.CTkFrame(row, fg_color="transparent")
            btns.pack(side="right", padx=10)
            if status == "Waiting":
                ctk.CTkButton(btns, text="Start Consultation", width=140, height=28, fg_color=NAVY,
                              hover_color=NAVY_DARK,
                              command=lambda a=appt_id: self.handle_status_change(a, "In Consultation")
                              ).pack(side="left", padx=3)
                ctk.CTkButton(btns, text="No-Show", width=90, height=28, fg_color=DANGER,
                              hover_color="#96281b",
                              command=lambda a=appt_id: self.handle_status_change(a, "No-Show")
                              ).pack(side="left", padx=3)
            elif status == "In Consultation":
                ctk.CTkButton(btns, text="Mark Completed", width=140, height=28, fg_color=SUCCESS,
                              hover_color="#166638",
                              command=lambda a=appt_id: self.handle_status_change(a, "Completed")
                              ).pack(side="left", padx=3)

    def handle_status_change(self, appointment_id, new_status):
        success, message = self.app.db.update_appointment_status(appointment_id, new_status)
        if success:
            self._refresh_queue_list()
            self._refresh_stats()
        else:
            messagebox.showerror("Error", message)

    # -------------------- Live Stats tab --------------------
    def _build_stats_tab(self, tab):
        top = ctk.CTkFrame(tab, fg_color="transparent")
        top.pack(fill="x", padx=15, pady=15)
        self.total_label = ctk.CTkLabel(top, text="", font=ctk.CTkFont(size=16, weight="bold"),
                                         text_color=TEAL_TXT)
        self.total_label.pack(side="left")
        ctk.CTkButton(top, text="🔄 Refresh", width=110, fg_color=GOLD, hover_color=GOLD_HOVER,
                      text_color=ON_GOLD, command=self._refresh_stats).pack(side="right")

        ctk.CTkLabel(tab, text="Currently In Consultation", font=ctk.CTkFont(weight="bold"),
                     text_color=TEAL_TXT).pack(anchor="w", padx=15)
        self.consulting_frame = ctk.CTkScrollableFrame(tab, fg_color="transparent", height=260)
        self.consulting_frame.pack(fill="both", expand=True, padx=15, pady=(5, 15))
        self._refresh_stats()

    def _refresh_stats(self):
        total = self.app.db.get_total_active_patients(self._branch_scope)
        self.total_label.configure(text=f"🟢 Total active patients right now: {total}")

        for w in self.consulting_frame.winfo_children():
            w.destroy()

        consulting = self.app.db.get_currently_consulting(self._branch_scope)
        if not consulting:
            ctk.CTkLabel(self.consulting_frame, text="No patient currently consulting.",
                         text_color=MUTED).pack(pady=10)
            return

        for patient_name, age, doctor_name, branch_name, token in consulting:
            row = card(self.consulting_frame, height=42)
            row.pack(fill="x", pady=4)
            text = (f"Token {token:03d}  |  {patient_name} (Age {age})  |  "
                    f"with Dr. {doctor_name}  |  {branch_name}")
            ctk.CTkLabel(row, text=text, anchor="w").pack(side="left", padx=14, pady=8)






class AdminPortalFrame(HomeVisitAdminMixin, QueueStatsMixin, PaymentsMixin, ctk.CTkFrame):
    def __init__(self, parent, app: OPDApp):
        super().__init__(parent, fg_color=BG_LIGHT)
        self.app = app
        self._branch_scope = None  # Admin sees every branch — see QueueStatsMixin
        self.pack(fill="both", expand=True)

        # ---- header bar ----
        header = ctk.CTkFrame(self, fg_color=HEADER_BG, corner_radius=0, height=64)
        header.pack(fill="x")
        header.pack_propagate(False)
        gold_rule(self)
        MiniLogo(header).pack(side="left", padx=(22, 0))
        ctk.CTkLabel(header, text="Admin Portal", font=ctk.CTkFont(size=20, weight="bold"),
                     text_color="white").pack(side="left", padx=(12, 24))
        ctk.CTkButton(header, text="Logout", width=100, fg_color=GOLD, hover_color=GOLD_HOVER,
                      text_color=ON_GOLD, command=self.app.show_login_frame).pack(side="right", padx=24, pady=14)
        LiveBadge(header).pack(side="right", padx=(0, 6))

        body = ctk.CTkFrame(self, fg_color=BG_LIGHT)
        body.pack(fill="both", expand=True, padx=20, pady=16)

        self.tabs = ctk.CTkTabview(body, fg_color=CARD_LIGHT, segmented_button_selected_color=NAVY,
                                    segmented_button_selected_hover_color=NAVY_DARK)
        self.tabs.pack(fill="both", expand=True)
        self.tabs.add("🏠 Dashboard")
        self.tabs.add("🏢 Branches")
        self.tabs.add("🩺 Doctors")
        self.tabs.add("👥 Staff Accounts")
        self.tabs.add("📋 Queue Control")
        self.tabs.add("📊 Live Stats")
        self.tabs.add("🏠 Home Visit")
        self.tabs.add("💳 Payments")

        self._build_branches_tab(self.tabs.tab("🏢 Branches"))
        self._build_doctors_tab(self.tabs.tab("🩺 Doctors"))
        self._build_staff_tab(self.tabs.tab("👥 Staff Accounts"))
        self._build_queue_tab(self.tabs.tab("📋 Queue Control"))
        self._build_stats_tab(self.tabs.tab("📊 Live Stats"))
        self._build_homevisit_admin_tab(self.tabs.tab("🏠 Home Visit"))
        self._build_payments_tab(self.tabs.tab("💳 Payments"), can_configure=True)
        self._build_admin_dashboard_tab(self.tabs.tab("🏠 Dashboard"))
        self.tabs.set("🏠 Dashboard")

    # -------------------- Dashboard tab (icon-grid home screen) --------------------
    def _build_admin_dashboard_tab(self, tab):
        scroll = ctk.CTkScrollableFrame(tab, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=10, pady=10)

        ctk.CTkLabel(scroll, text="Welcome back, Admin", font=ctk.CTkFont(size=18, weight="bold"),
                     text_color=TEXT).pack(anchor="w", padx=6, pady=(4, 2))
        ctk.CTkLabel(scroll, text="A quick snapshot of the whole hospital network.",
                     font=ctk.CTkFont(size=12), text_color=MUTED).pack(anchor="w", padx=6, pady=(0, 16))

        stats_row = ctk.CTkFrame(scroll, fg_color="transparent")
        stats_row.pack(fill="x", padx=6, pady=(0, 20))
        for i in range(4):
            stats_row.grid_columnconfigure(i, weight=1)

        branches = self.app.db.get_all_branches()
        doctors = self.app.db.get_all_doctors_with_branch()
        staff = self.app.db.get_all_staff_with_branch()
        active = self.app.db.get_total_active_patients()

        stat_tile(stats_row, icon="🏢", value=len(branches), label="Branches", color=TILE_BLUE
                  ).grid(row=0, column=0, sticky="ew", padx=6)
        stat_tile(stats_row, icon="🩺", value=len(doctors), label="Doctors", color=TILE_TEAL
                  ).grid(row=0, column=1, sticky="ew", padx=6)
        stat_tile(stats_row, icon="👥", value=len(staff), label="Staff Accounts", color=TILE_PURPLE
                  ).grid(row=0, column=2, sticky="ew", padx=6)
        stat_tile(stats_row, icon="🩹", value=active, label="Patients In Queue", color=TILE_ORANGE
                  ).grid(row=0, column=3, sticky="ew", padx=6)

        ctk.CTkLabel(scroll, text="Manage", font=ctk.CTkFont(size=14, weight="bold"),
                     text_color=TEXT).pack(anchor="w", padx=6, pady=(4, 10))

        grid = ctk.CTkFrame(scroll, fg_color="transparent")
        grid.pack(fill="x", padx=6)

        tiles = [
            ("🏢", "Branches", "Add / view branches", TILE_BLUE, "🏢 Branches"),
            ("🩺", "Doctors", "Manage doctor roster", TILE_TEAL, "🩺 Doctors"),
            ("👥", "Staff Accounts", "Receptionist logins", TILE_PURPLE, "👥 Staff Accounts"),
            ("📋", "Queue Control", "Live patient queue", TILE_ORANGE, "📋 Queue Control"),
            ("📊", "Live Stats", "Network-wide stats", TILE_PINK, "📊 Live Stats"),
            ("💳", "Payments", "UPI QR & receipts", TILE_GREEN, "💳 Payments"),
        ]
        for i, (icon, title, subtitle, color, tab_name) in enumerate(tiles):
            t = nav_tile(grid, icon=icon, title=title, subtitle=subtitle, color=color,
                         command=lambda tn=tab_name: self.tabs.set(tn))
            t.grid(row=i // 5, column=i % 5, padx=8, pady=8)

    # -------------------- Branches tab --------------------
    def _build_branches_tab(self, tab):
        row = ctk.CTkFrame(tab, fg_color="transparent")
        row.pack(fill="x", padx=15, pady=15)
        self.branch_name_entry = ctk.CTkEntry(row, placeholder_text="Branch Name", width=260, height=36)
        self.branch_name_entry.pack(side="left", padx=(0, 10))
        ctk.CTkButton(row, text="+ Add Branch", width=140, fg_color=NAVY, hover_color=NAVY_DARK,
                      command=self.handle_add_branch).pack(side="left")

        ctk.CTkLabel(tab, text="Existing Branches", font=ctk.CTkFont(weight="bold"),
                     text_color=TEAL_TXT).pack(anchor="w", padx=15)
        self.branches_list = ctk.CTkScrollableFrame(tab, fg_color="transparent", height=280)
        self.branches_list.pack(fill="both", expand=True, padx=15, pady=(5, 15))
        self._refresh_branches_list()

    def _refresh_branches_list(self):
        for w in self.branches_list.winfo_children():
            w.destroy()
        branches = self.app.db.get_all_branches()
        if not branches:
            ctk.CTkLabel(self.branches_list, text="No branches added yet.", text_color=MUTED).pack(pady=10)
        for b_id, b_name in branches:
            row = card(self.branches_list, height=42)
            row.pack(fill="x", pady=4)
            ctk.CTkLabel(row, text=f"🏢  {b_name}", anchor="w").pack(side="left", padx=14, pady=8)

    def handle_add_branch(self):
        name = self.branch_name_entry.get().strip()
        if not name:
            messagebox.showerror("Input Error", "Please enter a branch name.")
            return
        success, message = self.app.db.add_branch(name)
        if success:
            messagebox.showinfo("Success", message)
            self.branch_name_entry.delete(0, "end")
            self._refresh_branches_list()
            self._refresh_doctor_branch_menu()
            self._refresh_staff_branch_menu()
        else:
            messagebox.showerror("Error", message)

    # -------------------- Doctors tab --------------------
    def _build_doctors_tab(self, tab):
        form = ctk.CTkFrame(tab, fg_color="transparent")
        form.pack(fill="x", padx=15, pady=15)

        self.branches_cache = self.app.db.get_all_branches()
        branch_labels = [b[1] for b in self.branches_cache] or ["Add a branch first"]
        self.doctor_branch_menu = ctk.CTkOptionMenu(form, values=branch_labels, width=160,
                                                      fg_color=NAVY, button_color=NAVY_DARK)
        self.doctor_branch_menu.pack(side="left", padx=(0, 8))

        self.doctor_name_entry = ctk.CTkEntry(form, placeholder_text="Doctor Name", width=150, height=36)
        self.doctor_name_entry.pack(side="left", padx=(0, 8))

        self.doctor_dept_entry = ctk.CTkEntry(form, placeholder_text="Department", width=130, height=36)
        self.doctor_dept_entry.pack(side="left", padx=(0, 8))

        self.doctor_avgmin_entry = ctk.CTkEntry(form, placeholder_text="Avg mins/patient", width=120, height=36)
        self.doctor_avgmin_entry.pack(side="left", padx=(0, 8))

        self.doctor_fee_entry = ctk.CTkEntry(form, placeholder_text="Fee (Rs.)", width=90, height=36)
        self.doctor_fee_entry.pack(side="left", padx=(0, 8))

        ctk.CTkButton(form, text="+ Add Doctor", width=120, fg_color=NAVY, hover_color=NAVY_DARK,
                      command=self.handle_add_doctor).pack(side="left")

        ctk.CTkLabel(tab, text="Existing Doctors  (avg. time is used for wait prediction; blank fee = default fee from Payments)",
                     font=ctk.CTkFont(weight="bold"), text_color=TEAL_TXT).pack(anchor="w", padx=15, pady=(6, 0))
        self.doctors_list = ctk.CTkScrollableFrame(tab, fg_color="transparent", height=260)
        self.doctors_list.pack(fill="both", expand=True, padx=15, pady=(5, 15))
        self._refresh_doctors_list()

    def _refresh_doctor_branch_menu(self):
        self.branches_cache = self.app.db.get_all_branches()
        labels = [b[1] for b in self.branches_cache] or ["Add a branch first"]
        self.doctor_branch_menu.configure(values=labels)
        self.doctor_branch_menu.set(labels[0])

    def _refresh_staff_branch_menu(self):
        # BUG FIX: this method didn't exist before, so the Staff Accounts
        # tab's branch dropdown was never updated after a branch was added —
        # it stayed stuck on "Add a branch first" and could never be changed.
        self.staff_branches_cache = self.app.db.get_all_branches()
        labels = [b[1] for b in self.staff_branches_cache] or ["Add a branch first"]
        self.staff_branch_menu.configure(values=labels)
        self.staff_branch_menu.set(labels[0])

    def _refresh_doctors_list(self):
        for w in self.doctors_list.winfo_children():
            w.destroy()
        doctors = self.app.db.get_all_doctors_with_branch()
        fees = self.app.db.get_doctor_fees()
        try:
            default_fee = float(self.app.db.get_setting("fee", str(payment.DEFAULT_FEE)))
        except ValueError:
            default_fee = float(payment.DEFAULT_FEE)
        if not doctors:
            ctk.CTkLabel(self.doctors_list, text="No doctors added yet.", text_color=MUTED).pack(pady=10)
        for doctor_id, name, dept, branch_name, avg_min, delay_min, b_id in doctors:
            row = card(self.doctors_list, height=48)
            row.pack(fill="x", pady=4)
            fee = fees.get(doctor_id)
            fee_text = f"₹{fee:g}" if fee is not None else f"₹{default_fee:g} (default)"
            text = (f"👨‍⚕️  Dr. {name}   |   {dept}   |   {branch_name}   |   ~{avg_min} min/patient"
                    f"   |   Fee {fee_text}")
            if delay_min > 0:
                text += f"   |   ⏱ {delay_min} min late"
            ctk.CTkLabel(row, text=text, anchor="w").pack(side="left", padx=14, pady=10)
            ctk.CTkButton(row, text="Delete", width=80, height=28, fg_color=DANGER, hover_color="#96281b",
                          command=lambda d=doctor_id, n=name: self.handle_delete_doctor(d, n)
                          ).pack(side="right", padx=10)
            ctk.CTkButton(row, text="Edit fee", width=80, height=28, fg_color=GOLD, hover_color=GOLD_HOVER,
                          text_color=ON_GOLD,
                          command=lambda d=doctor_id, n=name, f=fee: self.handle_edit_fee(d, n, f)
                          ).pack(side="right", padx=4)

    def handle_add_doctor(self):
        if not self.branches_cache:
            messagebox.showerror("Input Error", "Please add a branch first.")
            return

        name = self.doctor_name_entry.get().strip()
        dept = self.doctor_dept_entry.get().strip()
        branch_label = self.doctor_branch_menu.get()
        avg_text = self.doctor_avgmin_entry.get().strip() or "10"

        if not name or not dept:
            messagebox.showerror("Input Error", "Please enter doctor name and department.")
            return

        try:
            avg_minutes = int(avg_text)
            if avg_minutes <= 0 or avg_minutes > 120:
                raise ValueError
        except ValueError:
            messagebox.showerror("Input Error", "Average minutes per patient must be a number (1-120).")
            return

        branch_id = None
        for b_id, b_name in self.branches_cache:
            if b_name == branch_label:
                branch_id = b_id
                break
        if branch_id is None:
            messagebox.showerror("Input Error", "Please select a valid branch.")
            return

        fee_text = self.doctor_fee_entry.get().strip()
        fee = None            # blank -> doctor uses the default fee
        if fee_text:
            try:
                fee = float(fee_text)
                if fee < 0 or fee > 100000:
                    raise ValueError
            except ValueError:
                messagebox.showerror("Input Error", "Consultation fee must be a number of rupees (0 = free).")
                return

        success, message = self.app.db.add_doctor(name, dept, branch_id, avg_minutes, fee)
        if success:
            messagebox.showinfo("Success", message)
            self.doctor_name_entry.delete(0, "end")
            self.doctor_dept_entry.delete(0, "end")
            self.doctor_avgmin_entry.delete(0, "end")
            self.doctor_fee_entry.delete(0, "end")
            self._refresh_doctors_list()
            self._refresh_queue_doctor_menu()
        else:
            messagebox.showerror("Error", message)

    def handle_edit_fee(self, doctor_id, name, current_fee):
        shown = f"{current_fee:g}" if current_fee is not None else "default"
        dlg = ctk.CTkInputDialog(
            text=f"New consultation fee (Rs.) for Dr. {name}\n(currently: {shown}; leave blank to use the default fee)",
            title="Edit consultation fee")
        value = dlg.get_input()
        if value is None:            # dialog closed / cancelled
            return
        value = value.strip()
        fee = None
        if value:
            try:
                fee = float(value)
                if fee < 0 or fee > 100000:
                    raise ValueError
            except ValueError:
                messagebox.showerror("Input Error", "Consultation fee must be a number of rupees (0 = free).")
                return
        ok, msg = self.app.db.set_doctor_fee(doctor_id, fee)
        if not ok:
            messagebox.showerror("Error", msg)
        self._refresh_doctors_list()

    def handle_delete_doctor(self, doctor_id, name):
        confirm = messagebox.askyesno("Confirm Delete", f"Remove Dr. {name} from the system?")
        if not confirm:
            return
        success, message = self.app.db.delete_doctor(doctor_id)
        if success:
            messagebox.showinfo("Removed", message)
            self._refresh_doctors_list()
            self._refresh_queue_doctor_menu()
        else:
            messagebox.showerror("Cannot Delete", message)

    # -------------------- Staff Accounts tab (role-based access) --------------------
    def _build_staff_tab(self, tab):
        ctk.CTkLabel(tab, text="Create a receptionist account scoped to one branch — "
                               "that staff member will only see and manage that branch's queue.",
                     font=ctk.CTkFont(size=11), text_color=MUTED, wraplength=700
                     ).pack(anchor="w", padx=15, pady=(15, 5))

        form = ctk.CTkFrame(tab, fg_color="transparent")
        form.pack(fill="x", padx=15, pady=(0, 10))

        self.staff_branches_cache = self.app.db.get_all_branches()
        branch_labels = [b[1] for b in self.staff_branches_cache] or ["Add a branch first"]
        self.staff_branch_menu = ctk.CTkOptionMenu(form, values=branch_labels, width=160,
                                                     fg_color=NAVY, button_color=NAVY_DARK)
        self.staff_branch_menu.pack(side="left", padx=(0, 8))

        self.staff_username_entry = ctk.CTkEntry(form, placeholder_text="Staff Username", width=170, height=36)
        self.staff_username_entry.pack(side="left", padx=(0, 8))

        self.staff_password_entry = ctk.CTkEntry(form, placeholder_text="Staff Password", show="*",
                                                   width=170, height=36)
        self.staff_password_entry.pack(side="left", padx=(0, 8))

        ctk.CTkButton(form, text="+ Create Account", width=140, fg_color=NAVY, hover_color=NAVY_DARK,
                      command=self.handle_add_staff).pack(side="left")

        ctk.CTkLabel(tab, text="Existing Staff Accounts", font=ctk.CTkFont(weight="bold"),
                     text_color=TEAL_TXT).pack(anchor="w", padx=15, pady=(6, 0))
        self.staff_list = ctk.CTkScrollableFrame(tab, fg_color="transparent", height=240)
        self.staff_list.pack(fill="both", expand=True, padx=15, pady=(5, 15))
        self._refresh_staff_list()

    def _refresh_staff_list(self):
        for w in self.staff_list.winfo_children():
            w.destroy()
        staff = self.app.db.get_all_staff_with_branch()
        if not staff:
            ctk.CTkLabel(self.staff_list, text="No staff accounts yet.", text_color=MUTED).pack(pady=10)
        for staff_id, username, branch_name in staff:
            row = card(self.staff_list, height=44)
            row.pack(fill="x", pady=4)
            ctk.CTkLabel(row, text=f"👤  {username}   —   {branch_name}", anchor="w"
                          ).pack(side="left", padx=14, pady=8)
            ctk.CTkButton(row, text="Delete", width=80, height=28, fg_color=DANGER, hover_color="#96281b",
                          command=lambda s=staff_id: self.handle_delete_staff(s)).pack(side="right", padx=10)

    def handle_add_staff(self):
        if not self.staff_branches_cache:
            messagebox.showerror("Input Error", "Please add a branch first.")
            return
        username = self.staff_username_entry.get().strip()
        password = self.staff_password_entry.get().strip()
        branch_label = self.staff_branch_menu.get()

        if not username or not password:
            messagebox.showerror("Input Error", "Please enter a username and password.")
            return

        branch_id = None
        for b_id, b_name in self.staff_branches_cache:
            if b_name == branch_label:
                branch_id = b_id
                break
        if branch_id is None:
            messagebox.showerror("Input Error", "Please select a valid branch.")
            return

        success, message = self.app.db.add_staff(username, password, branch_id)
        if success:
            messagebox.showinfo("Success", message)
            self.staff_username_entry.delete(0, "end")
            self.staff_password_entry.delete(0, "end")
            self._refresh_staff_list()
        else:
            messagebox.showerror("Error", message)

    def handle_delete_staff(self, staff_id):
        confirm = messagebox.askyesno("Confirm Delete", "Remove this staff account?")
        if not confirm:
            return
        success, message = self.app.db.delete_staff(staff_id)
        if success:
            self._refresh_staff_list()
        else:
            messagebox.showerror("Error", message)


# ==========================================================
# STAFF LOGIN  &  STAFF PORTAL — branch-scoped receptionist access
# ==========================================================
class StaffLoginFrame(ctk.CTkFrame):
    def __init__(self, parent, app: OPDApp):
        super().__init__(parent, fg_color=BG_LIGHT)
        self.app = app
        self.pack(fill="both", expand=True)

        AmbientBackground(self)
        form = card(self, width=340)
        form.place(relx=0.5, rely=0.5, anchor="center")

        ctk.CTkLabel(form, text="🧑‍💼", font=ctk.CTkFont(size=34)).pack(pady=(30, 0))
        ctk.CTkLabel(form, text="Staff Login", font=ctk.CTkFont(size=22, weight="bold"),
                     text_color=TEAL_TXT).pack(pady=(5, 20))

        self.username_entry = ctk.CTkEntry(form, placeholder_text="Staff Username", width=280, height=36)
        self.username_entry.pack(pady=8, padx=30)

        self.password_entry = ctk.CTkEntry(form, placeholder_text="Staff Password", show="*",
                                            width=280, height=36)
        self.password_entry.pack(pady=8, padx=30)
        self.password_entry.bind("<Return>", lambda e: self.handle_staff_login())

        ctk.CTkButton(form, text="Login", width=280, height=38, fg_color=NAVY, hover_color=NAVY_DARK,
                      font=ctk.CTkFont(weight="bold"), command=self.handle_staff_login
                      ).pack(pady=(20, 8), padx=30)

        ctk.CTkButton(form, text="Back", width=280, fg_color="transparent",
                      text_color=TEAL_TXT, border_width=1, border_color=TEAL_BORDER,
                      command=self.app.show_login_frame).pack(pady=(4, 30), padx=30)

    def handle_staff_login(self):
        username = self.username_entry.get().strip()
        password = self.password_entry.get().strip()
        if not username or not password:
            messagebox.showerror("Input Error", "Please enter both username and password.")
            return
        result = self.app.db.authenticate_staff(username, password)
        if result:
            staff_id, branch_id, branch_name = result
            self.app.welcome_then(str(branch_name).upper(), "Branch queue desk",
                                  lambda: self.app.show_staff_portal_frame(branch_id, branch_name))
        else:
            messagebox.showerror("Login Failed", "Invalid staff username or password.")


class StaffPortalFrame(QueueStatsMixin, PaymentsMixin, ctk.CTkFrame):
    def __init__(self, parent, app: OPDApp, branch_id, branch_name):
        super().__init__(parent, fg_color=BG_LIGHT)
        self.app = app
        self._branch_scope = branch_id  # scopes every QueueStatsMixin method to this branch
        self.pack(fill="both", expand=True)

        header = ctk.CTkFrame(self, fg_color=HEADER_BG, corner_radius=0, height=64)
        header.pack(fill="x")
        header.pack_propagate(False)
        gold_rule(self)
        MiniLogo(header).pack(side="left", padx=(22, 0))
        ctk.CTkLabel(header, text=f"Staff Portal  -  {branch_name}",
                     font=ctk.CTkFont(size=18, weight="bold"), text_color="white"
                     ).pack(side="left", padx=(12, 24))
        ctk.CTkButton(header, text="Logout", width=100, fg_color=GOLD, hover_color=GOLD_HOVER,
                      text_color=ON_GOLD, command=self.app.show_login_frame).pack(side="right", padx=24, pady=14)
        LiveBadge(header).pack(side="right", padx=(0, 6))

        body = ctk.CTkFrame(self, fg_color=BG_LIGHT)
        body.pack(fill="both", expand=True, padx=20, pady=16)

        self.tabs = ctk.CTkTabview(body, fg_color=CARD_LIGHT, segmented_button_selected_color=NAVY,
                                    segmented_button_selected_hover_color=NAVY_DARK)
        self.tabs.pack(fill="both", expand=True)
        self.tabs.add("🏠 Dashboard")
        self.tabs.add("📋 Queue Control")
        self.tabs.add("📊 Branch Stats")
        self.tabs.add("💳 Payments")

        self._build_queue_tab(self.tabs.tab("📋 Queue Control"))
        self._build_stats_tab(self.tabs.tab("📊 Branch Stats"))
        self._build_payments_tab(self.tabs.tab("💳 Payments"), can_configure=False)
        self._build_staff_dashboard_tab(self.tabs.tab("🏠 Dashboard"), branch_name)
        self.tabs.set("🏠 Dashboard")

    # -------------------- Dashboard tab (icon-grid home screen) --------------------
    def _build_staff_dashboard_tab(self, tab, branch_name):
        wrap = ctk.CTkFrame(tab, fg_color="transparent")
        wrap.pack(fill="both", expand=True, padx=10, pady=10)

        ctk.CTkLabel(wrap, text=f"Welcome — {branch_name}", font=ctk.CTkFont(size=18, weight="bold"),
                     text_color=TEXT).pack(anchor="w", padx=6, pady=(4, 2))
        ctk.CTkLabel(wrap, text="Your branch's live queue at a glance.",
                     font=ctk.CTkFont(size=12), text_color=MUTED).pack(anchor="w", padx=6, pady=(0, 16))

        stats_row = ctk.CTkFrame(wrap, fg_color="transparent")
        stats_row.pack(fill="x", padx=6, pady=(0, 20))
        stats_row.grid_columnconfigure((0, 1), weight=1)

        active = self.app.db.get_total_active_patients(self._branch_scope)
        consulting = len(self.app.db.get_currently_consulting(self._branch_scope))

        stat_tile(stats_row, icon="🩹", value=active, label="Patients Waiting", color=TILE_ORANGE
                  ).grid(row=0, column=0, sticky="ew", padx=6)
        stat_tile(stats_row, icon="🔔", value=consulting, label="In Consultation Now", color=TILE_TEAL
                  ).grid(row=0, column=1, sticky="ew", padx=6)

        grid = ctk.CTkFrame(wrap, fg_color="transparent")
        grid.pack(fill="x", padx=6)
        nav_tile(grid, icon="📋", title="Queue Control", subtitle="Manage today's queue",
                  color=TILE_ORANGE, command=lambda: self.tabs.set("📋 Queue Control")
                  ).grid(row=0, column=0, padx=8, pady=8)
        nav_tile(grid, icon="📊", title="Branch Stats", subtitle="This branch's numbers",
                  color=TILE_PINK, command=lambda: self.tabs.set("📊 Branch Stats")
                  ).grid(row=0, column=1, padx=8, pady=8)
        nav_tile(grid, icon="💳", title="Payments", subtitle="Verify UPI / counter payments",
                  color=TILE_GREEN, command=lambda: self.tabs.set("💳 Payments")
                  ).grid(row=0, column=2, padx=8, pady=8)


# ==========================================================
# PATIENT DASHBOARD — tabbed shell: Overview | Book | My Appointments | Track Queue
# ==========================================================
class DashboardFrame(HomeVisitPatientMixin, ctk.CTkFrame):
    def __init__(self, parent, app: OPDApp, open_tab=None):
        super().__init__(parent, fg_color=BG_LIGHT)
        self.app = app
        self.pack(fill="both", expand=True)

        patient = self.app.current_patient

        # ---- header bar ----
        header = ctk.CTkFrame(self, fg_color=HEADER_BG, corner_radius=0, height=70)
        header.pack(fill="x")
        header.pack_propagate(False)
        gold_rule(self)

        MiniLogo(header).pack(side="left", padx=(22, 0))
        left = ctk.CTkFrame(header, fg_color="transparent")
        left.pack(side="left", padx=(12, 24))
        ctk.CTkLabel(left, text=f"{patient.name}", font=ctk.CTkFont(size=18, weight="bold"),
                     text_color="white").pack(anchor="w", pady=(12, 0))
        badge = "🟡 Senior Citizen priority" if patient.is_senior_citizen() else f"Age {patient.age}"
        ctk.CTkLabel(left, text=badge, font=ctk.CTkFont(size=12), text_color=SOFT).pack(anchor="w")

        right = ctk.CTkFrame(header, fg_color="transparent")
        right.pack(side="right", padx=24)
        LiveBadge(right).pack(side="left", padx=(0, 10), pady=18)
        ctk.CTkButton(right, text="▶  Replay Intro", width=120, fg_color="transparent",
                      text_color=TEAL_TXT, border_width=1, border_color=TEAL_BORDER,
                      hover_color="#0f2a31", command=self.app.replay_intro
                      ).pack(side="left", padx=(0, 12), pady=15)
        ctk.CTkButton(right, text="Logout", width=100, fg_color=GOLD, hover_color=GOLD_HOVER,
                      text_color=ON_GOLD, command=self.app.logout).pack(side="left", pady=15)

        body = ctk.CTkFrame(self, fg_color=BG_LIGHT)
        body.pack(fill="both", expand=True, padx=20, pady=16)

        self.tabs = ctk.CTkTabview(body, fg_color=CARD_LIGHT, segmented_button_selected_color=NAVY,
                                    segmented_button_selected_hover_color=NAVY_DARK)
        self.tabs.pack(fill="both", expand=True)
        self.tabs.add("🏠 Overview")
        self.tabs.add("📅 Book Appointment")
        self.tabs.add("🗂 My Appointments")
        self.tabs.add("🔔 Track Queue")
        self.tabs.add("🏠 Home Visit")
        self.tabs.add("🚑 My Home Visits")

        self._build_overview_tab(self.tabs.tab("🏠 Overview"))
        self._build_booking_tab(self.tabs.tab("📅 Book Appointment"))
        self._build_appointments_tab(self.tabs.tab("🗂 My Appointments"))
        self._build_track_tab(self.tabs.tab("🔔 Track Queue"))
        self._build_homevisit_tab(self.tabs.tab("🏠 Home Visit"))
        self._build_myhv_tab(self.tabs.tab("🚑 My Home Visits"))

        if open_tab:
            self.tabs.set(open_tab)

    # -------------------- Home Visit cinematic opening --------------------
    def _play_home_visit_intro(self):
        """Play the dedicated Home Visit opening before entering the booking screen."""
        if getattr(self, "_home_visit_intro_running", False):
            return
        self._home_visit_intro_running = True

        def finish():
            self._home_visit_intro_running = False
            try:
                self.tabs.set("🏠 Home Visit")
            except Exception:
                pass

        def skip():
            finish()

        try:
            self.home_visit_opening = OpeningIntro(
                self, on_finish=finish, on_skip=skip, show_skip_button=True
            )
            self.home_visit_opening.start()
        except Exception as exc:
            self._home_visit_intro_running = False
            try:
                self.tabs.set("🏠 Home Visit")
            except Exception:
                pass
            messagebox.showwarning(
                "Home Visit Intro",
                "The Home Visit intro could not start, so the booking screen was opened directly.\n\n" + str(exc)
            )

    # -------------------- Overview tab --------------------
    def _build_overview_tab(self, tab):
        appointments = self.app.db.get_appointments_for_patient(self.app.current_patient.patient_id)
        upcoming = [a for a in appointments if a[5] == "Waiting"]
        completed_count = len([a for a in appointments if a[5] == "Completed"])

        scroll_top = ctk.CTkFrame(tab, fg_color="transparent")
        scroll_top.pack(fill="x", padx=20, pady=(20, 0))
        scroll_top.grid_columnconfigure((0, 1, 2), weight=1)

        stat_tile(scroll_top, icon="📅", value=len(upcoming), label="Upcoming Appointments",
                  color=TILE_BLUE).grid(row=0, column=0, sticky="ew", padx=6)
        stat_tile(scroll_top, icon="✅", value=completed_count, label="Visits Completed",
                  color=TILE_GREEN).grid(row=0, column=1, sticky="ew", padx=6)
        stat_tile(scroll_top, icon="🗂", value=len(appointments), label="Total Bookings",
                  color=TILE_PURPLE).grid(row=0, column=2, sticky="ew", padx=6)

        quick_row = ctk.CTkFrame(tab, fg_color="transparent")
        quick_row.pack(fill="x", padx=14, pady=(16, 0))
        nav_tile(quick_row, icon="📅", title="Book Appointment", subtitle="Find a doctor & slot",
                  color=TILE_BLUE, command=lambda: self.tabs.set("📅 Book Appointment")
                  ).pack(side="left", padx=6)
        nav_tile(quick_row, icon="🗂", title="My Appointments", subtitle="View & manage bookings",
                  color=TILE_TEAL, command=lambda: self.tabs.set("🗂 My Appointments")
                  ).pack(side="left", padx=6)
        nav_tile(quick_row, icon="🔔", title="Track Queue", subtitle="Live wait estimate",
                  color=TILE_ORANGE, command=lambda: self.tabs.set("🔔 Track Queue")
                  ).pack(side="left", padx=6)
        nav_tile(quick_row, icon="🏠", title="Book Home Visit", subtitle="Doctor comes to you",
                  color=TILE_GREEN, command=self._play_home_visit_intro
                  ).pack(side="left", padx=6)

        ctk.CTkLabel(tab, text="Next Appointment", font=ctk.CTkFont(size=15, weight="bold"),
                     text_color=TEAL_TXT).pack(anchor="w", padx=20, pady=(10, 5))

        next_card = card(tab)
        next_card.pack(fill="x", padx=20, pady=(0, 20))
        if upcoming:
            (appt_id, doctor_name, dept, branch_name, token, status,
             appt_date, appt_time, priority, doctor_id) = upcoming[0]
            days_left = (datetime.strptime(appt_date, "%Y-%m-%d").date() - datetime.now().date()).days
            when_text = "Today" if days_left == 0 else f"in {days_left} day(s)"
            ctk.CTkLabel(next_card, text=f"Dr. {doctor_name}  ({dept})",
                         font=ctk.CTkFont(size=16, weight="bold")).pack(anchor="w", padx=16, pady=(14, 2))
            ctk.CTkLabel(next_card,
                         text=f"{appt_date} at {appt_time}  —  {when_text}   |   Token {token:03d}   |   {branch_name}",
                         text_color=MUTED).pack(anchor="w", padx=16, pady=(0, 14))
        else:
            ctk.CTkLabel(next_card, text="No upcoming appointments. Book one from the 'Book Appointment' tab.",
                         text_color=MUTED).pack(padx=16, pady=20)

        ctk.CTkButton(tab, text="+ Book a New Appointment", width=240, height=40, fg_color=NAVY,
                      hover_color=NAVY_DARK, font=ctk.CTkFont(weight="bold"),
                      command=lambda: self.tabs.set("📅 Book Appointment")).pack(padx=20, pady=(0, 10))

    # -------------------- Book Appointment tab (3-step wizard) --------------------
    def _build_booking_tab(self, tab):
        self.booking_tab = tab
        self.booking_step_frame = ctk.CTkFrame(tab, fg_color="transparent")
        self.booking_step_frame.pack(fill="both", expand=True)
        self._booking_step_branch()

    def _clear_booking_step(self):
        for w in self.booking_step_frame.winfo_children():
            w.destroy()

    def _booking_step_branch(self):
        self._clear_booking_step()
        f = self.booking_step_frame
        StepTrack(f, 1).pack(anchor="w", padx=20, pady=(14, 0))

        ctk.CTkLabel(f, text="Step 1 of 3 — Select Branch", font=ctk.CTkFont(size=16, weight="bold"),
                     text_color=TEAL_TXT).pack(anchor="w", padx=20, pady=(20, 10))

        self.branches = self.app.db.get_all_branches()
        if not self.branches:
            ctk.CTkLabel(f, text="No branches available. Please contact admin.", text_color=MUTED
                          ).pack(padx=20, pady=20)
            return

        branch_labels = [b[1] for b in self.branches]
        self.branch_menu = ctk.CTkOptionMenu(f, values=branch_labels, width=300, height=38,
                                              fg_color=NAVY, button_color=NAVY_DARK)
        self.branch_menu.pack(padx=20, pady=8, anchor="w")

        ctk.CTkButton(f, text="Next: Select Department  →", width=260, height=38, fg_color=NAVY,
                      hover_color=NAVY_DARK, command=self._handle_branch_next
                      ).pack(padx=20, pady=16, anchor="w")

    def _handle_branch_next(self):
        label = self.branch_menu.get()
        for b_id, b_name in self.branches:
            if b_name == label:
                self.app.selected_branch_id = b_id
                self.app.selected_branch_name = b_name
                break
        self._booking_step_department()

    def _booking_step_department(self):
        self._clear_booking_step()
        f = self.booking_step_frame
        StepTrack(f, 2).pack(anchor="w", padx=20, pady=(14, 0))

        ctk.CTkLabel(f, text=f"Branch: {self.app.selected_branch_name}",
                     text_color=MUTED).pack(anchor="w", padx=20, pady=(20, 0))
        ctk.CTkLabel(f, text="Step 2 of 3 — Select Department", font=ctk.CTkFont(size=16, weight="bold"),
                     text_color=TEAL_TXT).pack(anchor="w", padx=20, pady=(2, 10))

        departments = self.app.db.get_departments_by_branch(self.app.selected_branch_id)
        if not departments:
            ctk.CTkLabel(f, text="No departments available at this branch yet.", text_color=MUTED
                          ).pack(padx=20, pady=20)
            ctk.CTkButton(f, text="← Back", width=100, fg_color="transparent", text_color=TEAL_TXT,
                          border_width=1, border_color=TEAL_BORDER,
                          command=self._booking_step_branch).pack(padx=20, pady=10, anchor="w")
            return

        self.dept_menu = ctk.CTkOptionMenu(f, values=departments, width=300, height=38,
                                            fg_color=NAVY, button_color=NAVY_DARK)
        self.dept_menu.pack(padx=20, pady=8, anchor="w")

        row = ctk.CTkFrame(f, fg_color="transparent")
        row.pack(padx=20, pady=16, anchor="w")
        ctk.CTkButton(row, text="← Back", width=100, fg_color="transparent", text_color=TEAL_TXT,
                      border_width=1, border_color=TEAL_BORDER,
                      command=self._booking_step_branch).pack(side="left", padx=(0, 8))
        ctk.CTkButton(row, text="Next: Select Doctor  →", width=220, height=38, fg_color=NAVY,
                      hover_color=NAVY_DARK, command=self._handle_department_next).pack(side="left")

    def _handle_department_next(self):
        self.app.selected_department = self.dept_menu.get()
        self._booking_step_doctor()

    def _booking_step_doctor(self):
        self._clear_booking_step()
        f = self.booking_step_frame
        StepTrack(f, 3).pack(anchor="w", padx=20, pady=(14, 0))

        ctk.CTkLabel(f, text=f"Branch: {self.app.selected_branch_name}   |   "
                              f"Department: {self.app.selected_department}",
                     text_color=MUTED).pack(anchor="w", padx=20, pady=(20, 0))
        ctk.CTkLabel(f, text="Step 3 of 3 — Doctor, Date, Time & Priority",
                     font=ctk.CTkFont(size=16, weight="bold"), text_color=TEAL_TXT
                     ).pack(anchor="w", padx=20, pady=(2, 10))

        self.doctors = self.app.db.get_doctors_by_branch_and_department(
            self.app.selected_branch_id, self.app.selected_department)

        if not self.doctors:
            ctk.CTkLabel(f, text="No doctors available in this department.", text_color=MUTED
                          ).pack(padx=20, pady=20)
            ctk.CTkButton(f, text="← Back", width=100, fg_color="transparent", text_color=TEAL_TXT,
                          border_width=1, border_color=TEAL_BORDER,
                          command=self._booking_step_department).pack(padx=20, pady=10, anchor="w")
            return

        doctor_labels = [f"Dr. {d[1]}" for d in self.doctors]
        ctk.CTkLabel(f, text="Doctor").pack(anchor="w", padx=20)
        self.doctor_menu = ctk.CTkOptionMenu(f, values=doctor_labels, width=300, height=36,
                                              fg_color=NAVY, button_color=NAVY_DARK)
        self.doctor_menu.pack(padx=20, pady=(2, 10), anchor="w")

        today = datetime.now().date()
        self.date_options = [today + timedelta(days=i) for i in range(7)]
        date_labels = [d.strftime("%d-%b-%Y (%A)") for d in self.date_options]
        ctk.CTkLabel(f, text="Appointment Date").pack(anchor="w", padx=20)
        self.date_menu = ctk.CTkOptionMenu(f, values=date_labels, width=300, height=36,
                                            fg_color=NAVY, button_color=NAVY_DARK)
        self.date_menu.pack(padx=20, pady=(2, 10), anchor="w")

        ctk.CTkLabel(f, text="Appointment Time").pack(anchor="w", padx=20)
        self.time_menu = ctk.CTkOptionMenu(f, values=TIME_SLOTS, width=300, height=36,
                                            fg_color=NAVY, button_color=NAVY_DARK)
        self.time_menu.pack(padx=20, pady=(2, 10), anchor="w")

        # ---- priority: auto-suggested for senior citizens, editable ----
        patient = self.app.current_patient
        default_priority = "Senior Citizen" if patient.is_senior_citizen() else "Normal"
        ctk.CTkLabel(f, text="Priority").pack(anchor="w", padx=20)
        self.priority_menu = ctk.CTkOptionMenu(f, values=["Normal", "Senior Citizen", "Emergency"],
                                                width=300, height=36, fg_color=NAVY, button_color=NAVY_DARK)
        self.priority_menu.set(default_priority)
        self.priority_menu.pack(padx=20, pady=(2, 4), anchor="w")
        ctk.CTkLabel(f, text="Senior Citizen / Emergency patients are queued ahead of Normal patients.",
                     font=ctk.CTkFont(size=11), text_color=MUTED).pack(anchor="w", padx=20, pady=(0, 10))

        row = ctk.CTkFrame(f, fg_color="transparent")
        row.pack(padx=20, pady=10, anchor="w")
        ctk.CTkButton(row, text="← Back", width=100, fg_color="transparent", text_color=TEAL_TXT,
                      border_width=1, border_color=TEAL_BORDER,
                      command=self._booking_step_department).pack(side="left", padx=(0, 8))
        ctk.CTkButton(row, text="Confirm Booking", width=200, height=38, fg_color=GOLD,
                      hover_color=GOLD_HOVER, text_color=ON_GOLD, font=ctk.CTkFont(weight="bold"),
                      command=self._handle_booking_confirm).pack(side="left")

    def _handle_booking_confirm(self):
        try:
            doctor_label = self.doctor_menu.get()
            doctor_id, avg_min = None, 10
            for d_id, d_name, d_avg in self.doctors:
                if f"Dr. {d_name}" == doctor_label:
                    doctor_id, avg_min = d_id, d_avg
                    break
            if doctor_id is None:
                messagebox.showerror("Error", "Please select a valid doctor.")
                return

            selected_date_label = self.date_menu.get()
            selected_date = None
            for d in self.date_options:
                if d.strftime("%d-%b-%Y (%A)") == selected_date_label:
                    selected_date = d
                    break
            if selected_date is None:
                messagebox.showerror("Error", "Please select a valid appointment date.")
                return

            appointment_date = selected_date.strftime("%Y-%m-%d")
            appointment_time = self.time_menu.get()
            priority = self.priority_menu.get()

            fee = self._get_fee(doctor_id)
            department = self.app.selected_department

            def finalize(method, ref):
                # runs after the payment step (or straight away when there is no fee)
                try:
                    if method == "UPI":
                        status, paid = "Paid - Unverified", fee
                    elif method == "Counter":
                        status, paid = "Pay at Counter", 0.0
                    else:
                        status, paid = "Not Required", 0.0
                    success, result = self.app.db.book_appointment(
                        self.app.current_patient.patient_id, doctor_id, self.app.selected_branch_id,
                        appointment_date, appointment_time, priority, status, method, ref, paid)
                    if success:
                        ahead, wait_minutes = self.app.db.estimate_waiting_time(
                            doctor_id, appointment_date, result["token_number"], priority)
                        pay_text = format_payment(status, method, ref, paid)
                        notify.send_async(
                            self.app.db, self.app.db.get_patient_contact(self.app.current_patient.patient_id),
                            notify.opd_message(self.app.current_patient.name, doctor_label, department,
                                               self.app.selected_branch_name, selected_date_label,
                                               appointment_time, result["token_number"], wait_minutes, pay_text))
                        ConfirmationDialog(
                            self.app, patient=self.app.current_patient, doctor_label=doctor_label,
                            department=department, branch_name=self.app.selected_branch_name,
                            date_label=selected_date_label, appointment_date=appointment_date,
                            time_label=appointment_time, priority=priority,
                            token_number=result["token_number"], wait_minutes=wait_minutes, ahead=ahead,
                            payment_text=format_payment(status, method, ref, paid),
                        )
                        self.app.show_dashboard_frame(open_tab="🗂 My Appointments")
                    else:
                        messagebox.showerror("Booking Failed", str(result))
                except Exception as e:
                    messagebox.showerror("Error", f"Something went wrong: {e}")

            if fee > 0:
                PaymentDialog(self.app, amount=fee, doctor_label=doctor_label, department=department,
                              on_done=finalize)
            else:
                finalize("None", "")
        except Exception as e:
            messagebox.showerror("Error", f"Something went wrong: {e}")

    def _get_fee(self, doctor_id=None):
        # The doctor's own consultation fee (set in Admin > Manage Doctors); doctors without
        # one use the default fee from Admin > Payments. 0 when payments are switched off.
        db = self.app.db
        if db.get_setting("payments_enabled", "1") != "1":
            return 0.0
        try:
            default_fee = max(0.0, float(db.get_setting("fee", str(payment.DEFAULT_FEE))))
        except (TypeError, ValueError):
            default_fee = float(payment.DEFAULT_FEE)
        if doctor_id is None:
            return default_fee
        return max(0.0, db.get_doctor_fee(doctor_id, default_fee))


    # -------------------- My Appointments tab --------------------
    def _build_appointments_tab(self, tab):
        self.appointments_list_frame = ctk.CTkScrollableFrame(tab, fg_color="transparent")
        self.appointments_list_frame.pack(fill="both", expand=True, padx=15, pady=15)
        self._refresh_appointments_list()

    def _refresh_appointments_list(self):
        for w in self.appointments_list_frame.winfo_children():
            w.destroy()

        rows = self.app.db.get_appointments_for_patient(self.app.current_patient.patient_id)
        if not rows:
            ctk.CTkLabel(self.appointments_list_frame, text="No appointments booked yet.",
                         text_color=MUTED).pack(pady=20)
            return

        for (appt_id, doctor_name, department, branch_name, token, status,
             appointment_date, appointment_time, priority, doctor_id) in rows:
            row = card(self.appointments_list_frame)
            row.pack(fill="x", pady=5)

            left = ctk.CTkFrame(row, fg_color="transparent")
            left.pack(side="left", fill="x", expand=True, padx=14, pady=10)
            top_line = ctk.CTkFrame(left, fg_color="transparent")
            top_line.pack(anchor="w", fill="x")
            ctk.CTkLabel(top_line, text=f"Token {token:03d}  —  Dr. {doctor_name} ({department})",
                         font=ctk.CTkFont(weight="bold")).pack(side="left")
            status_pill(top_line, status, STATUS_COLORS.get(status, MUTED)).pack(side="left", padx=(10, 0))
            ctk.CTkLabel(left, text=f"{branch_name}   |   {appointment_date} at {appointment_time}   |   "
                                     f"Priority: {priority}",
                         font=ctk.CTkFont(size=11), text_color=MUTED).pack(anchor="w")

            if status == "Waiting":
                btns = ctk.CTkFrame(row, fg_color="transparent")
                btns.pack(side="right", padx=10)
                ctk.CTkButton(btns, text="Slip", width=60, height=28, fg_color=GOLD,
                              hover_color=GOLD_HOVER, text_color=ON_GOLD,
                              command=lambda a=appt_id, dn=doctor_name, dept=department, bn=branch_name,
                                             tok=token, ad=appointment_date, at=appointment_time,
                                             pr=priority: self._download_slip(a, dn, dept, bn, tok, ad, at, pr)
                              ).pack(side="left", padx=3)
                ctk.CTkButton(btns, text="Track", width=70, height=28, fg_color=NAVY, hover_color=NAVY_DARK,
                              command=lambda a=appt_id: self._open_track(a)).pack(side="left", padx=3)
                ctk.CTkButton(btns, text="Cancel", width=70, height=28, fg_color=DANGER,
                              hover_color="#96281b",
                              command=lambda a=appt_id: self._handle_cancel(a)).pack(side="left", padx=3)

    def _download_slip(self, appointment_id, doctor_name, department, branch_name,
                        token, appointment_date, appointment_time, priority):
        info = self.app.db.get_queue_position(appointment_id)
        wait_minutes = info["wait_minutes"] if info else None
        pay = self.app.db.get_payment_info(appointment_id)
        payment_text = format_payment(pay["status"], pay["method"], pay["ref"], pay["amount"]) if pay else None
        generate_and_save_slip(
            patient_name=self.app.current_patient.name, patient_age=self.app.current_patient.age,
            token_number=token, doctor_name=doctor_name, department=department,
            branch_name=branch_name, appointment_date=appointment_date,
            appointment_time=appointment_time, priority=priority, wait_minutes=wait_minutes,
            payment_text=payment_text)

    def _handle_cancel(self, appointment_id):
        confirm = messagebox.askyesno("Confirm Cancel", "Cancel this appointment?")
        if not confirm:
            return
        success, message = self.app.db.cancel_appointment(appointment_id)
        if success:
            messagebox.showinfo("Cancelled", message)
            self._refresh_appointments_list()
        else:
            messagebox.showerror("Cannot Cancel", message)

    def _open_track(self, appointment_id):
        self.tabs.set("🔔 Track Queue")
        self._load_track_appointment(appointment_id)

    # -------------------- Track Queue tab (waiting-time prediction) --------------------
    def _build_track_tab(self, tab):
        self.track_tab = tab
        ctk.CTkLabel(tab, text="Live Queue Position & Estimated Wait", font=ctk.CTkFont(size=16, weight="bold"),
                     text_color=TEAL_TXT).pack(anchor="w", padx=20, pady=(20, 5))

        top = ctk.CTkFrame(tab, fg_color="transparent")
        top.pack(fill="x", padx=20, pady=(0, 10))

        waiting = [a for a in self.app.db.get_appointments_for_patient(self.app.current_patient.patient_id)
                   if a[5] == "Waiting"]
        self.track_appointments = waiting
        labels = [f"Token {a[4]:03d} — Dr. {a[1]} — {a[6]}" for a in waiting] or ["No active appointments"]
        self.track_menu = ctk.CTkOptionMenu(top, values=labels, width=340, height=36,
                                             fg_color=NAVY, button_color=NAVY_DARK,
                                             command=lambda _: self._refresh_track())
        self.track_menu.pack(side="left", padx=(0, 8))
        ctk.CTkButton(top, text="🔄 Refresh", width=110, fg_color=GOLD, hover_color=GOLD_HOVER,
                      text_color=ON_GOLD, command=self._refresh_track).pack(side="left")

        self.track_result = card(tab)
        self.track_result.pack(fill="x", padx=20, pady=10)
        self._refresh_track()

    def _load_track_appointment(self, appointment_id):
        for i, a in enumerate(self.track_appointments):
            if a[0] == appointment_id:
                labels = self.track_menu.cget("values")
                if i < len(labels):
                    self.track_menu.set(labels[i])
                break
        self._refresh_track()

    def _refresh_track(self):
        for w in self.track_result.winfo_children():
            w.destroy()

        if not self.track_appointments:
            ctk.CTkLabel(self.track_result, text="You have no active appointments to track.",
                         text_color=MUTED).pack(padx=16, pady=20)
            return

        label = self.track_menu.get()
        selected = None
        labels = [f"Token {a[4]:03d} — Dr. {a[1]} — {a[6]}" for a in self.track_appointments]
        for a, lbl in zip(self.track_appointments, labels):
            if lbl == label:
                selected = a
                break
        if not selected:
            selected = self.track_appointments[0]

        appt_id = selected[0]
        info = self.app.db.get_queue_position(appt_id)
        if not info:
            ctk.CTkLabel(self.track_result, text="Could not load queue position.",
                         text_color=MUTED).pack(padx=16, pady=20)
            return

        ctk.CTkLabel(self.track_result, text=f"Token {selected[4]:03d}  —  Dr. {selected[1]} ({selected[2]})",
                     font=ctk.CTkFont(size=15, weight="bold")).pack(anchor="w", padx=16, pady=(16, 4))

        stats_row = ctk.CTkFrame(self.track_result, fg_color="transparent")
        stats_row.pack(fill="x", padx=16, pady=(4, 16))

        def mini_stat(text, value, color):
            c = ctk.CTkFrame(stats_row, fg_color=BG_LIGHT, corner_radius=10)
            c.pack(side="left", padx=6, pady=4, fill="both", expand=True)
            ctk.CTkLabel(c, text=value, font=ctk.CTkFont(size=22, weight="bold"), text_color=color
                         ).pack(pady=(10, 0))
            ctk.CTkLabel(c, text=text, font=ctk.CTkFont(size=11), text_color=MUTED).pack(pady=(0, 10))

        mini_stat("Patients Ahead of You", str(info["ahead"]), TEAL_TXT)
        mini_stat("Estimated Wait", f"{info['wait_minutes']} min", GOLD_HOVER)
        mini_stat("Recommended Arrival", "Now" if info["wait_minutes"] <= 15 else f"in {max(info['wait_minutes'] - 15, 0)} min",
                   SUCCESS)


if __name__ == "__main__":
    app = OPDApp()
    app.mainloop()
