#!/usr/bin/env python3
"""
SMART OPD - Cinematic movie-style intro (module used by app.py)
----------------------------------------------------------------
Usage:   CinematicIntro(root, on_finish).start()
         on_finish() is called exactly once - after the film ends OR when
         the user clicks / presses a key to skip. All after() callbacks are
         tracked and cancelled before on_finish() runs.

Standalone test:  python intro.py

Design notes
 * One master clock (after() loop, ~30 fps). Every scene is a pure function
   of time, so scenes never leave stray callbacks behind.
 * Every after() id is tracked in a set and cancelled on skip / finish / close.
 * Edit SPEED to make the whole film faster (>1) or slower (<1).
"""
import math
import random
import time
import traceback
import tkinter as tk
from tkinter import font as tkfont

import customtkinter as ctk

FPS = 30
SPEED = 1.0

# ---------------------------------------------------------------- palette
BG = (2, 8, 10)
DASHBG = (4, 16, 21)
TEAL = (34, 206, 192)
TEAL_M = (20, 140, 142)
TEAL_D = (12, 78, 86)
GOLD = (216, 180, 98)
ICE = (216, 250, 246)
AMBER = (232, 164, 72)
GREEN = (72, 226, 126)
CEIL = (26, 72, 80)
FLOOR = (20, 60, 68)
WALL = (38, 98, 106)
SUN = (196, 228, 208)

# --------------------------------------------------------------- timeline
T2 = 1.8            # hospital reveal
T3 = T2 + 2.2       # data / patient system
T4 = T3 + 1.6       # chaos
TF0 = T4 + 1.5      # freeze start
TF1 = TF0 + 0.5     # freeze end
T5 = TF1            # AI activation
T6 = T5 + 2.8       # logo reveal
T7 = T6 + 5.0       # explosive transition -> dashboard
T8 = T7 + 2.6       # messages
TM2 = T8 + 2.0      # second message screen
TLOGIN = TM2 + 4.0  # hand over to login (welcome / credits screen stays 4 s)

SANS = "Segoe UI"
MONO = "Consolas"
SERIF = "Georgia"
SIGNS = ["+", "OPD", "X-RAY", "LAB", "ER", "PHARMACY"]
CARDS = [
    ("ACTIVE PATIENTS", "patients in hospital now"),
    ("QUEUE STATUS", "waiting in line"),
    ("AVERAGE WAIT TIME", "predicted by Smart OPD"),
    ("TODAY'S APPOINTMENTS", "of 120 booked slots"),
]


# ---------------------------------------------------------------- helpers
def clamp(v, lo=0.0, hi=1.0):
    return lo if v < lo else hi if v > hi else v


def seg(t, a, b):
    return clamp((t - a) / (b - a))


def ease(u):
    u = clamp(u)
    return u * u * (3.0 - 2.0 * u)


def lerp(a, b, u):
    return a + (b - a) * u


def mixc(c1, c2, u):
    return (lerp(c1[0], c2[0], u), lerp(c1[1], c2[1], u), lerp(c1[2], c2[2], u))


def hx(c):
    return "#%02x%02x%02x" % (int(c[0]), int(c[1]), int(c[2]))


def blend(c, a, bg=BG):
    a = clamp(a)
    return "#%02x%02x%02x" % (
        int(bg[0] + (c[0] - bg[0]) * a),
        int(bg[1] + (c[1] - bg[1]) * a),
        int(bg[2] + (c[2] - bg[2]) * a),
    )


def alive(w):
    try:
        return w is not None and bool(w.winfo_exists())
    except Exception:
        return False


class Particle:
    __slots__ = ("x0", "y0", "ph", "w", "sz", "gold", "order", "ring",
                 "ox", "oy", "ang", "cu", "cv", "card")

    def __init__(self, i, n):
        r = random.random
        self.x0, self.y0 = r(), r()
        self.ph = r() * 6.283
        self.w = 0.4 + r() * 0.9
        self.sz = random.choice((1, 1, 2, 2, 3))
        self.gold = r() < 0.2
        self.order = i / n
        self.ring = r() < 0.35
        self.ang = r() * 6.283
        if r() < 0.5:
            self.ox, self.oy = random.uniform(-1, 1), random.uniform(-0.26, 0.26)
        else:
            self.ox, self.oy = random.uniform(-0.26, 0.26), random.uniform(-1, 1)
        self.cu, self.cv = r(), r()
        self.card = i % 4


# ================================================================== APP
class CinematicIntro:
    def __init__(self, root, on_finish):
        self.root = root
        self.on_finish = on_finish
        self._key_bind = None
        self.root.update_idletasks()
        w0 = max(int(root.winfo_width()), 800)
        h0 = max(int(root.winfo_height()), 450)
        self.cv = tk.Canvas(self.root, bg=hx(BG), highlightthickness=0, bd=0)
        self.cv.place(x=0, y=0, relwidth=1, relheight=1)

        # state
        self._ids = set()
        self.finished = False
        self.closed = False
        self.tm = 0.0          # motion clock (stops in freeze)
        self.cam_z = 0.0
        self.W, self.H = w0, h0
        self.lcx = self.lcy = self.L0 = 0.0
        self.F = 600.0
        self.vx = self.vy = 0.0
        self.people = []
        self.people_ready = False

        self._make_fonts(h0)
        self._make_world()

    def start(self):
        self._key_bind = self.root.bind("<Key>", self.on_skip, add="+")
        self.cv.bind("<Button-1>", self.on_skip)
        self.cv.bind("<Destroy>", self._on_cv_destroy, add="+")
        self.cv.focus_set()
        self.t0 = self.last = time.perf_counter()
        self.sched(30, self.tick)

    def _on_cv_destroy(self, event=None):
        # window closed mid-intro: make sure nothing keeps running
        if event is not None and event.widget is not self.cv:
            return
        self.closed = True
        self.cancel_all()

    # ------------------------------------------------------------ setup
    def _make_fonts(self, h0):
        def mk(fam, px, weight="normal", slant="roman"):
            return tkfont.Font(root=self.root, family=fam, size=-int(px), weight=weight, slant=slant)
        px = int(h0 * 0.088)
        self.f_title = mk(SANS, px, "bold")
        self.f_tag = mk(SANS, h0 * 0.026)
        self.f_hud = mk(MONO, 19)
        self.f_hud_b = mk(MONO, 19, "bold")
        self.f_small = mk(SANS, 12, "bold")
        self.f_chip = mk(MONO, 15, "bold")
        self.f_num = mk(SANS, 46, "bold")
        self.f_unit = mk(SANS, 18)
        self.f_hdr = mk(SANS, 22, "bold")
        self.f_phase = mk(MONO, 21, "bold")
        self.f_msg = mk(SERIF, 34, "normal", "italic")
        self.f_msg2 = mk(SERIF, 36)
        self.f_wel = mk(SANS, 15, "bold")
        self.f_big = mk(SANS, 38, "bold")
        self.hud_cw = max(8, self.f_hud.measure("0"))
        spacing = int(px * 0.2)
        self.title = "SMART OPD"
        self.title_ws = [self.f_title.measure(c) for c in self.title]
        self.title_xs = []
        x = 0
        for w in self.title_ws:
            self.title_xs.append(x)
            x += w + spacing
        self.title_total = x - spacing

    def _make_world(self):
        self.parts = [Particle(i, 150) for i in range(150)]
        n = 20
        self.nodes = []
        for i in range(n):
            row, col = divmod(i, 10)
            self.nodes.append(dict(
                u=random.uniform(0.40, 0.94), v=random.uniform(0.16, 0.80),
                ou=0.14 + col * (0.72 / 9), ov=0.70 + row * 0.075,
                t0=T3 + 0.3 + i * 0.07, ph=random.random() * 6.28,
                w=random.uniform(0.8, 1.6)))
        self.extras = [dict(u=random.random(), v=random.uniform(0.12, 0.88),
                            t0=T4 + random.random() * 1.2, ph=random.random() * 6.28,
                            w=random.uniform(1.0, 2.4)) for _ in range(40)]
        self.edges = []
        for i in range(n - 1):
            self.edges.append((i, i + 1, 0 if i % 10 != 9 else 1))
        for i in range(0, n, 2):
            self.edges.append((i, (i + 5) % n, 1))
        for i in range(0, n, 3):
            self.edges.append((i, (i + 7) % n, 2))
        self.tickets = [dict(u=random.uniform(0.44, 0.78), v=random.uniform(0.18, 0.80),
                             t0=T4 + 0.15 + i * 0.2) for i in range(5)]
        self.rays = [random.random() * 6.28 for _ in range(16)]
        self.bar_seed = [[random.random() * 6.28 for _ in range(12)] for _ in range(4)]

    # -------------------------------------------------- after() tracking
    def sched(self, ms, fn):
        if self.closed:
            return None
        holder = []

        def run():
            if holder:
                self._ids.discard(holder[0])
            if self.closed:
                return
            fn()

        aid = self.root.after(max(1, int(ms)), run)
        holder.append(aid)
        self._ids.add(aid)
        return aid

    def cancel_all(self):
        for aid in list(self._ids):
            try:
                self.root.after_cancel(aid)
            except Exception:
                pass
        self._ids.clear()

    # ------------------------------------------------------ flow control
    def on_skip(self, _event=None):
        if not self.finished:
            self.finish(skipped=True)

    def finish(self, skipped=False):
        if self.finished:
            return
        self.finished = True
        self.cancel_all()
        if self._key_bind is not None:
            try:
                self.root.unbind("<Key>", self._key_bind)
            except Exception:
                pass
            self._key_bind = None
        if alive(self.cv):
            try:
                self.cv.unbind("<Button-1>")
                self.cv.destroy()
            except Exception:
                pass
        cb, self.on_finish = self.on_finish, None
        if cb is not None and alive(self.root):
            cb()

    # --------------------------------------------------------- master tick
    def tick(self):
        if self.finished or not alive(self.cv):
            return
        t0 = time.perf_counter()
        dt = min(t0 - self.last, 0.1)
        self.last = t0
        t = (t0 - self.t0) * SPEED
        rate = 0.0 if TF0 <= t < TF1 else (2.4 if T4 <= t < TF0 else 1.0)
        self.tm += dt * SPEED * rate
        self.cam_z += dt * SPEED * self.cam_speed(t)
        try:
            self.render(t)
        except tk.TclError:
            self.finish(skipped=True)
            return
        except Exception:
            traceback.print_exc()
            self.finish(skipped=True)
            return
        if t >= TLOGIN:
            self.finish()
            return
        spent = (time.perf_counter() - t0) * 1000.0
        self.sched(max(1, 1000.0 / FPS - spent), self.tick)

    def cam_speed(self, t):
        if t < T2:
            return 0.0
        if t < T3:
            return 0.4 + 1.2 * ease(seg(t, T2, T3))
        if t < T4:
            return 1.6 + 0.9 * ease(seg(t, T3, T4))
        if t < TF0:
            return 2.5 + 6.0 * ease(seg(t, T4, T4 + 0.9))
        if t < TF1:
            return 0.0
        return 0.5

    def dim(self, t):
        d = 1.0 - 0.86 * ease(seg(t, TF0, TF0 + 0.1))
        d += 0.86 * ease(seg(t, TF1, TF1 + 0.9))
        return d

    def card_rect(self, i, W, H):
        cw = W * 0.205
        gap = W * 0.016
        total = 4 * cw + 3 * gap
        x0 = (W - total) / 2 + i * (cw + gap)
        y0 = H * 0.27
        return x0, y0, x0 + cw, y0 + H * 0.36

    # ================================================================ RENDER
    def render(self, t):
        cv = self.cv
        W = max(int(cv.winfo_width()), 320)
        H = max(int(cv.winfo_height()), 240)
        cv.delete("all")
        self.W, self.H = W, H
        cx, cy = W / 2.0, H / 2.0
        self.lcx, self.lcy, self.L0 = cx, cy - 0.07 * H, 0.085 * H
        dim = self.dim(t)

        chaos_run = ease(seg(t, T4, T4 + 0.8)) if t < TF0 else 0.0
        amp = 1.5 + 9.0 * chaos_run
        self.F = H * 0.95
        self.vx = cx + math.sin(self.cam_z * 1.7) * amp * 1.4
        self.vy = cy * 0.96 + math.sin(self.cam_z * 3.1) * amp

        # corridor ------------------------------------------------------
        ca = ease(seg(t, T2, T2 + 1.5))
        if t > T5:
            ca = lerp(ca, 0.16, ease(seg(t, T5, T5 + 0.6)))
        if t > T6:
            ca *= 1 - ease(seg(t, T6, T6 + 0.9))
        if t >= T2 and ca * dim > 0.02:
            self.draw_corridor(t, ca * dim)

        if t >= T4 and not self.people_ready:
            self.spawn_people()
        if self.people_ready:
            self.draw_people(t, dim * (1 - ease(seg(t, T5, T5 + 0.5))))
        if T4 <= t < TF0:
            self.draw_speed_lines(t)

        if t >= T3 and t < T6 + 1.1:
            self.draw_net(t, dim)
            self.draw_tickets(t, dim)
            self.draw_hud(t, dim)
            self.draw_counter(t, dim)

        if T7 - 0.01 <= t < TM2:
            da = 1 - 0.88 * ease(seg(t, T8 - 0.3, T8 + 0.5))
            da *= 1 - ease(seg(t, TM2 - 0.5, TM2))
            self.draw_dash(t, da)

        self.draw_scanner(t)
        self.draw_logo(t)
        self.draw_particles(t, dim)
        self.draw_wave(t)
        self.draw_msgs(t)

        # freeze flash
        if TF0 <= t < TF0 + 0.12:
            f = 1 - seg(t, TF0, TF0 + 0.12)
            cv.create_rectangle(0, 0, W, H, fill=blend(ICE, 0.28 * f), outline="")

        # cinematic letterbox
        bh = H * 0.075 * ease(seg(t, T2 - 0.4, T2 + 0.8)) * (1 - ease(seg(t, T7, T7 + 0.6)))
        if bh > 0.5:
            cv.create_rectangle(0, 0, W, bh, fill="#000000", outline="")
            cv.create_rectangle(0, H - bh, W, H, fill="#000000", outline="")

        if t < T2 + 1.0:
            self.draw_intro(t)

    # ------------------------------------------------------------ SCENE 1
    def draw_intro(self, t):
        cv = self.cv
        cx, cy, H = self.W / 2.0, self.H / 2.0, self.H
        fa = 1 - ease(seg(t, T2 - 0.1, T2 + 0.9))
        if fa <= 0.01:
            return
        ap = ease(seg(t, 0.4, 1.2)) * fa
        pulse = 0.5 + 0.5 * math.sin(t * 2.2)
        if ap > 0.01:
            for r, al in ((46, 0.05), (28, 0.10), (16, 0.20), (8, 0.45)):
                rr = r * (0.9 + 0.15 * pulse)
                cv.create_oval(cx - rr, cy - rr, cx + rr, cy + rr, fill=blend(TEAL, al * ap), outline="")
            cv.create_oval(cx - 2.5, cy - 2.5, cx + 2.5, cy + 2.5, fill=blend(ICE, ap), outline="")
        # vertical heartbeat pulses (lub-dub), then it stops
        for b0, amp in ((1.0, 1.0), (1.28, 0.65)):
            d = seg(t, b0, b0 + 0.45)
            if 0 < d < 1:
                h = H * 0.2 * amp * math.sin(math.pi * d)
                cv.create_line(cx, cy - h, cx, cy + h, fill=blend(TEAL, 0.25 * fa), width=9)
                cv.create_line(cx, cy - h, cx, cy + h, fill=blend(ICE, 0.9 * fa * (1 - 0.5 * d)), width=2)
                r = 12 + 110 * d
                cv.create_oval(cx - r, cy - r, cx + r, cy + r, outline=blend(TEAL, 0.5 * (1 - d) * fa), width=1)

    # ------------------------------------------------------------ SCENE 2
    def proj(self, X, Y, z):
        s = self.F / z
        return self.vx + X * s, self.vy + Y * s

    def draw_corridor(self, t, A):
        cv = self.cv
        D, N, F = 3.0, 14, self.F
        cz = self.cam_z
        k0 = max(0, int(cz // D))
        proj = self.proj
        for k in range(k0 + N, k0 - 1, -1):
            z0 = k * D - cz
            z1 = z0 + D
            if z1 < 0.5:
                continue
            z0c = max(z0, 0.5)
            f = clamp(z0c / (D * N))
            on = ease(seg(t, T2 + 0.16 * k, T2 + 0.16 * k + 0.5))
            fog = 1 - 0.72 * f
            base = A * fog * (0.22 + 0.78 * on) * (1.0 if k % 2 == 0 else 0.86)
            s0 = F / z0c
            # surfaces
            for col, pts in (
                (CEIL, [*proj(-1, -0.9, z0c), *proj(1, -0.9, z0c), *proj(1, -0.9, z1), *proj(-1, -0.9, z1)]),
                (FLOOR, [*proj(-1, 0.9, z0c), *proj(1, 0.9, z0c), *proj(1, 0.9, z1), *proj(-1, 0.9, z1)]),
                (WALL, [*proj(-1, -0.9, z0c), *proj(-1, -0.9, z1), *proj(-1, 0.9, z1), *proj(-1, 0.9, z0c)]),
                (WALL, [*proj(1, -0.9, z0c), *proj(1, -0.9, z1), *proj(1, 0.9, z1), *proj(1, 0.9, z0c)]),
            ):
                c = blend(col, base)
                cv.create_polygon(pts, fill=c, outline=c)
            lw = int(clamp(0.012 * s0, 1, 4))
            gl = blend(GOLD, 0.55 * on * A * fog)
            for side in (-1, 1):
                cv.create_line(*proj(side, -0.3, z0c), *proj(side, -0.3, z1), fill=gl, width=lw)
                cv.create_line(*proj(side * 0.95, 0.9, z0c), *proj(side * 0.95, 0.9, z1),
                               fill=blend(TEAL, 0.8 * on * A * fog), width=int(clamp(0.02 * s0, 1, 5)))
            # ceiling light + floor reflection
            lz0, lz1 = z0 + 0.9, z0 + 2.1
            if lz1 > 0.55 and on > 0.01:
                lz0 = max(lz0, 0.55)
                for hw, dz, al in ((0.5, 0.25, 0.10), (0.3, 0.0, 0.95)):
                    za, zb = max(lz0 - dz, 0.55), lz1 + dz
                    c = blend(ICE if al > 0.5 else TEAL, al * on * A * fog)
                    cv.create_polygon([*proj(-hw, -0.9, za), *proj(hw, -0.9, za),
                                       *proj(hw, -0.9, zb), *proj(-hw, -0.9, zb)], fill=c, outline="")
                rz0, rz1 = max(z0 + 0.6, 0.55), z0 + 2.5
                if rz1 > rz0:
                    cv.create_polygon([*proj(-0.28, 0.9, rz0), *proj(0.28, 0.9, rz0),
                                       *proj(0.28, 0.9, rz1), *proj(-0.28, 0.9, rz1)],
                                      fill=blend(TEAL, 0.30 * on * A * fog), outline="")
            # doorways + medical signs
            for side, cond, za, zb in ((-1, k % 2 == 0, 0.7, 1.9), (1, k % 2 == 1 and k % 3 != 0, 1.0, 2.3)):
                if not cond:
                    continue
                zA, zB = max(z0 + za, 0.55), z0 + zb
                if zB <= 0.6 or zB <= zA:
                    continue
                zm = (zA + zB) / 2
                s = F / zm
                leave = t > T4 + 0.5 and side == -1 and k % 4 == 0
                ec = AMBER if leave else TEAL_M
                dc = A * fog
                cv.create_polygon([*proj(side, -0.2, zA), *proj(side, -0.2, zB),
                                   *proj(side, 0.9, zB), *proj(side, 0.9, zA)],
                                  fill=blend((3, 12, 16), dc), outline=blend(ec, dc * (0.35 + 0.65 * on)),
                                  width=2 if s > 60 else 1)
                cv.create_polygon([*proj(side, -0.1, zA + 0.12), *proj(side, -0.1, zB - 0.12),
                                   *proj(side, 0.8, zB - 0.12), *proj(side, 0.8, zA + 0.12)],
                                  fill=blend((24, 76, 86), 0.35 * dc * on), outline="")
                cv.create_polygon([*proj(side, -0.62, zA), *proj(side, -0.62, zB),
                                   *proj(side, -0.38, zB), *proj(side, -0.38, zA)],
                                  fill=blend((8, 28, 34), dc), outline=blend(GOLD, 0.5 * dc * on))
                size = int(clamp(0.1 * s, 0, 28))
                if size >= 7 and dc * on > 0.1:
                    x, y = proj(side, -0.5, zm)
                    cv.create_text(x, y, text=SIGNS[k % len(SIGNS)], font=(SANS, -size, "bold"),
                                   fill=blend(GOLD if k % 3 == 0 else ICE, dc * on))
                lsize = int(clamp(0.075 * s, 0, 20))
                if leave and lsize >= 7:
                    x, y = proj(side, 0.3, zm)
                    cv.create_text(x, y, text="DOCTOR\nON LEAVE", font=(SANS, -lsize, "bold"),
                                   fill=blend(AMBER, dc), justify="center")
        # sunlit atmosphere at the end of the corridor (Ghibli-ish haze + rays)
        vx, vy, H = self.vx, self.vy, self.H
        for r, al in ((0.30 * H, 0.05), (0.20 * H, 0.08), (0.12 * H, 0.12), (0.06 * H, 0.20), (0.025 * H, 0.40)):
            cv.create_oval(vx - r, vy - r, vx + r, vy + r, fill=blend(SUN, al * A), outline="")
        for j in range(5):
            a1 = math.radians(25 + j * 32)
            a2 = a1 + 0.12
            R = self.W
            cv.create_polygon([vx, vy, vx + math.cos(a1) * R, vy + math.sin(a1) * R,
                               vx + math.cos(a2) * R, vy + math.sin(a2) * R],
                              fill=blend((120, 200, 190), 0.035 * A * (0.6 + 0.4 * math.sin(self.tm * 0.5 + j))),
                              outline="")

    def spawn_people(self):
        self.people_ready = True
        cz = self.cam_z
        for i in range(22):  # single-file appointment queue
            self.people.append(dict(x=0.42 + random.random() * 0.1, z=cz + 2.0 + i * 0.8,
                                    t0=T4 + 0.1 + i * 0.05, ph=random.random() * 6.28,
                                    w=random.uniform(1.5, 3.2)))
        k_now = int(cz // 3.0)
        for k in range(k_now + 1, k_now + 12):  # crowds waiting at doctors' doors
            if k % 4 == 0:
                for j in range(3):
                    self.people.append(dict(x=-0.62 - 0.12 * j, z=k * 3.0 + 1.3 + 0.35 * (j - 1),
                                            t0=T4 + 0.2 + random.random() * 0.8,
                                            ph=random.random() * 6.28, w=random.uniform(1.5, 3.2)))

    def draw_people(self, t, dim):
        if dim < 0.02:
            return
        cv, F = self.cv, self.F
        vis = []
        for p in self.people:
            z = p["z"] - self.cam_z
            if 0.7 < z < 24 and t >= p["t0"]:
                vis.append((z, p))
        vis.sort(key=lambda e: -e[0])
        for z, p in vis:
            s = F / z
            a = dim * (1 - 0.7 * clamp(z / 24)) * ease(seg(t, p["t0"], p["t0"] + 0.3))
            bx, by = self.proj(p["x"], 0.9, z)
            bx += math.sin(self.tm * p["w"] + p["ph"]) * 0.025 * s
            bw, bh, r = 0.17 * s, 0.78 * s, 0.095 * s
            cv.create_oval(bx - bw, by - bh, bx + bw, by - 0.02 * s, fill=blend((5, 20, 25), a),
                           outline=blend(TEAL_M, a * 0.7))
            hy = by - bh - r * 0.9
            cv.create_oval(bx - r, hy - r, bx + r, hy + r, fill=blend((5, 20, 25), a),
                           outline=blend(TEAL_M, a * 0.7))

    def draw_speed_lines(self, t):
        cv = self.cv
        chaos = ease(seg(t, T4, T4 + 1.0))
        for i, a0 in enumerate(self.rays):
            ph = (self.tm * 1.8 + i * 0.37) % 1.0
            r0 = 0.15 * self.W + ph * 0.6 * self.W
            r1 = r0 * 1.18
            cv.create_line(self.vx + math.cos(a0) * r0, self.vy + math.sin(a0) * r0 * 0.7,
                           self.vx + math.cos(a0) * r1, self.vy + math.sin(a0) * r1 * 0.7,
                           fill=blend(TEAL, 0.35 * (1 - ph) * chaos), width=1)

    # ------------------------------------------------------------ SCENE 3-5
    def draw_net(self, t, dim):
        cv, W, H = self.cv, self.W, self.H
        chaos = ease(seg(t, T4, T4 + 1.0))
        reorg = ease(seg(t, T5 + 1.4, T5 + 2.5))
        merge = ease(seg(t, T6, T6 + 0.9))
        gone = 1 - ease(seg(t, T6 + 0.5, T6 + 1.0))
        if gone <= 0.01:
            return
        pos = []
        amp = (4 + 26 * chaos) * (1 - 0.9 * reorg)
        for nd in self.nodes:
            x = nd["u"] * W + math.sin(self.tm * nd["w"] + nd["ph"]) * amp
            y = nd["v"] * H + math.cos(self.tm * nd["w"] * 1.3 + nd["ph"]) * amp * 0.8
            x, y = lerp(x, nd["ou"] * W, reorg), lerp(y, nd["ov"] * H, reorg)
            x, y = lerp(x, self.lcx, merge), lerp(y, self.lcy, merge)
            pos.append((x, y, ease(seg(t, nd["t0"], nd["t0"] + 0.4)) * gone * dim))
        for a, b, kind in self.edges:
            xa, ya, aa = pos[a]
            xb, yb, ab = pos[b]
            st = max(self.nodes[a]["t0"], self.nodes[b]["t0"]) + 0.2
            pr = ease(seg(t, st, st + 0.6))
            if pr <= 0:
                continue
            fk = 1.0 if kind == 0 else (1 - reorg if kind == 1 else chaos * (1 - reorg))
            al = min(aa, ab) * fk * pr
            if al < 0.03:
                continue
            cv.create_line(xa, ya, lerp(xa, xb, pr), lerp(ya, yb, pr), fill=blend(TEAL, 0.55 * al), width=1)
            if pr > 0.99 and al > 0.2:
                q = (self.tm * 0.45 + a * 0.173) % 1.0
                px, py = lerp(xa, xb, q), lerp(ya, yb, q)
                cv.create_oval(px - 2, py - 2, px + 2, py + 2, fill=blend(ICE, 0.9 * al), outline="")
        col = mixc(TEAL, ICE, reorg * 0.6)
        for x, y, al in pos:
            if al < 0.02:
                continue
            r = 4 + 1.5 * reorg
            cv.create_oval(x - r * 3, y - r * 3, x + r * 3, y + r * 3, fill=blend(col, 0.10 * al), outline="")
            cv.create_oval(x - r * 2, y - r * 2, x + r * 2, y + r * 2, fill=blend(col, 0.22 * al), outline="")
            cv.create_oval(x - r, y - r, x + r, y + r, fill=blend(col, al), outline="")
            if reorg > 0.05:
                cv.create_oval(x - r - 3, y - r - 3, x + r + 3, y + r + 3,
                               outline=blend(GOLD, 0.7 * reorg * al), width=1)
        if t >= T4:
            fade_x = (1 - ease(seg(t, T5 + 0.9, T5 + 1.6))) * gone * dim
            if fade_x > 0.02:
                for e in self.extras:
                    al = ease(seg(t, e["t0"], e["t0"] + 0.3)) * chaos * fade_x
                    if al < 0.03:
                        continue
                    x = e["u"] * W + math.sin(self.tm * e["w"] + e["ph"]) * 34
                    y = e["v"] * H + math.cos(self.tm * e["w"] * 1.2 + e["ph"]) * 28
                    cv.create_oval(x - 2, y - 2, x + 2, y + 2, fill=blend(TEAL, 0.6 * al), outline="")

    def draw_tickets(self, t, dim):
        cv, W, H = self.cv, self.W, self.H
        gone = 1 - ease(seg(t, T6, T6 + 0.6))
        if t < T4 or gone <= 0.01:
            return
        chaos = ease(seg(t, T4, T4 + 1.0))
        reorg = ease(seg(t, T5 + 1.4, T5 + 2.5))
        for i, tk in enumerate(self.tickets):
            al = ease(seg(t, tk["t0"], tk["t0"] + 0.25)) * gone * dim
            if al < 0.02:
                continue
            amp = (6 + 18 * chaos) * (1 - reorg)
            x = tk["u"] * W + math.sin(self.tm * 2.1 + i * 1.7) * amp
            y = tk["v"] * H + math.cos(self.tm * 1.7 + i * 2.3) * amp
            x, y = lerp(x, 0.84 * W, reorg), lerp(y, (0.22 + 0.085 * i) * H, reorg)
            hot = int(self.tm * 5 + i * 3) % 6 == 0 and reorg < 0.5
            cv.create_rectangle(x - 76, y - 16, x + 76, y + 16, fill=blend((6, 26, 32), al),
                                outline=blend(AMBER if hot else TEAL, al))
            cv.create_text(x, y, text="QUEUE #%03d" % (41 + i), font=self.f_chip, fill=blend(ICE, al))
            if reorg > 0.3:
                cv.create_line(x - 76, y - 16, x - 76, y + 16, fill=blend(GOLD, reorg * al), width=3)

    def draw_counter(self, t, dim):
        if not (T4 + 0.3 <= t < T5 + 0.5):
            return
        al = dim * (1 - ease(seg(t, T5, T5 + 0.4)))
        blink = 0.55 + 0.45 * math.sin(self.tm * 7)
        n = 127 + int(215 * seg(t, T4, TF0))
        self.cv.create_text(self.W * 0.94, self.H * 0.14, anchor="e", text="WAITING  %d" % n,
                            font=self.f_chip, fill=blend(AMBER, al * blink))

    def draw_hud(self, t, dim):
        W, H, cv, cw = self.W, self.H, self.cv, self.hud_cw
        ha = ease(seg(t, T3, T3 + 0.5)) * (1 - ease(seg(t, T5 + 0.2, T5 + 0.8))) * dim
        if ha <= 0.02:
            return
        x0, y0, lh = W * 0.06, H * 0.26, H * 0.085
        left, top, right, bot = x0 - 22, y0 - 52, x0 + cw * 27, y0 + lh * 3 + 46
        cv.create_rectangle(left, top, right, bot, outline=blend(TEAL_D, ha), fill=blend((4, 16, 20), ha * 0.8))
        c = 18
        for px, py, sx, sy in ((left, top, 1, 1), (right, top, -1, 1), (left, bot, 1, -1), (right, bot, -1, -1)):
            cv.create_line(px, py + sy * c, px, py, px + sx * c, py, fill=blend(GOLD, ha), width=2)
        cv.create_text(x0, y0 - 30, anchor="w", text="OPD TELEMETRY", font=self.f_small, fill=blend(GOLD, ha * 0.9))
        cs = ease(seg(t, T4, TF0))
        for i, lab in enumerate(("PATIENTS", "DOCTORS", "APPOINTMENTS", "QUEUE")):
            ts = T3 + 0.2 + 0.4 * i
            y = y0 + lh * i
            left_txt = (lab + " ").ljust(18, ".")
            n = int(len(left_txt) * seg(t, ts, ts + 0.35))
            if n > 0:
                cv.create_text(x0, y, anchor="w", text=left_txt[:n], font=self.f_hud, fill=blend(TEAL, ha * 0.85))
            if t < ts + 0.3:
                continue
            q = ease(seg(t, ts + 0.3, ts + 1.5))
            col = ICE
            if i == 0:
                val = str(int(127 * q + 60 * cs))
            elif i == 1:
                val = "%02d" % int(round(8 * q - 3 * cs))
            elif i == 2:
                val = str(int(94 * q + 47 * cs))
            elif cs > 0.35:
                val, col = "OVERLOAD", AMBER
            else:
                val = "ACTIVE"[:int(math.ceil(6 * q))]
            cv.create_text(x0 + cw * 19, y, anchor="w", text=val, font=self.f_hud_b, fill=blend(col, ha))

    def draw_scanner(self, t):
        sa = ease(seg(t, T5 + 0.1, T5 + 0.7)) * (1 - ease(seg(t, T6 + 0.2, T6 + 0.8)))
        if sa <= 0.02:
            return
        cv, W, H = self.cv, self.W, self.H
        cx, cy = W / 2.0, H / 2.0 - 0.04 * H
        R = 0.19 * H * (0.6 + 0.4 * sa)
        # sweeping horizontal scan line across the whole screen
        if T5 + 0.15 <= t < T6:
            p = ((t - T5 - 0.15) % 1.3) / 1.3
            y = ease(p) * H
            for i in range(8):
                y1, y0 = y - i * 6, y - (i + 1) * 6
                if y0 < 0:
                    break
                cv.create_rectangle(0, y0, W, y1, fill=blend(TEAL, 0.16 * (1 - i / 8.0) * sa), outline="")
            cv.create_line(0, y, W, y, fill=blend(ICE, 0.85 * sa), width=2)
        # radar wedge and rings
        cv.create_arc(cx - R, cy - R, cx + R, cy + R, start=(-t * 200) % 360, extent=60,
                      style="pieslice", fill=blend(TEAL, 0.07 * sa), outline="")
        for rr, col, al in ((R, TEAL_D, 0.9), (R * 0.56, TEAL_D, 0.7)):
            cv.create_oval(cx - rr, cy - rr, cx + rr, cy + rr, outline=blend(col, al * sa), width=1)
        for rr, w, ext, spd, col in ((R, 3, 100, 140, TEAL), (R * 0.78, 2, 60, -210, GOLD),
                                     (R * 0.56, 2, 140, 180, TEAL), (R * 1.12, 1, 30, -90, ICE)):
            st = (t * spd) % 360
            for off in (0, 180):
                cv.create_arc(cx - rr, cy - rr, cx + rr, cy + rr, start=(st + off) % 360, extent=ext,
                              style="arc", outline=blend(col, sa), width=w)
        for i in range(48):
            a = i * math.pi / 24
            r0, r1 = R * 1.0, R * (1.07 if i % 4 else 1.14)
            cv.create_line(cx + math.cos(a) * r0, cy + math.sin(a) * r0,
                           cx + math.cos(a) * r1, cy + math.sin(a) * r1, fill=blend(TEAL_M, 0.7 * sa))
        cv.create_line(cx - R * 1.3, cy, cx + R * 1.3, cy, fill=blend(TEAL_D, sa))
        cv.create_line(cx, cy - R * 1.3, cx, cy + R * 1.3, fill=blend(TEAL_D, sa))
        pr = 0.5 + 0.5 * math.sin(t * 6)
        for rr, al in ((14, 0.15), (9, 0.35), (4, 1.0)):
            r2 = rr * (0.85 + 0.3 * pr)
            cv.create_oval(cx - r2, cy - r2, cx + r2, cy + r2, fill=blend(ICE if al > 0.9 else TEAL, al * sa), outline="")
        # phrases
        for i, txt in enumerate(("ANALYZING PATIENT FLOW...", "PREDICTING WAIT TIMES...", "OPTIMIZING QUEUE...")):
            ps = T5 + 0.2 + 0.65 * i
            if not (ps <= t < ps + 0.65):
                continue
            al = ease(seg(t, ps, ps + 0.15)) * (1 - ease(seg(t, ps + 0.55, ps + 0.65)))
            n = int(len(txt) * seg(t, ps, ps + 0.4))
            shown = txt[:n] + ("_" if n < len(txt) else "")
            cv.create_text(W / 2.0, H * 0.87, text=shown, font=self.f_phase, fill=blend(ICE, al))

    # ------------------------------------------------------------ SCENE 6
    def draw_logo(self, t):
        if t < T6 + 1.0:
            return
        la = 1 - ease(seg(t, T7 + 0.25, T7 + 0.9))
        if la <= 0.02:
            return
        cv, W, H = self.cv, self.W, self.H
        lcx, lcy = self.lcx, self.lcy
        sc = 1 + 0.4 * ease(seg(t, T7, T7 + 0.9))
        L = self.L0 * sc
        pulse = ease(seg(t, T7 - 0.5, T7))
        ca = ease(seg(t, T6 + 1.1, T6 + 1.8)) * la
        # light rays
        for i in range(14):
            ang = i * 2 * math.pi / 14 + t * 0.08
            r0, r1 = 1.9 * L, 1.9 * L + W * 0.35
            cv.create_line(lcx + math.cos(ang) * r0, lcy + math.sin(ang) * r0 * 0.8,
                           lcx + math.cos(ang) * r1, lcy + math.sin(ang) * r1 * 0.8,
                           fill=blend(TEAL, 0.12 * ca * (0.5 + 0.5 * math.sin(i * 2.3 + t))), width=1)
        def plus(scale):
            hl = L * scale
            aw = 0.26 * hl
            pts = [(-aw, -hl), (aw, -hl), (aw, -aw), (hl, -aw), (hl, aw), (aw, aw),
                   (aw, hl), (-aw, hl), (-aw, aw), (-hl, aw), (-hl, -aw), (-aw, -aw)]
            out = []
            for px, py in pts:
                out.extend((lcx + px, lcy + py))
            return out

        if ca > 0.01:
            for sca, al in ((1.7, 0.05), (1.45, 0.08), (1.25, 0.12)):
                cv.create_polygon(plus(sca), fill=blend(TEAL, al * ca * (1 + 1.5 * pulse)), outline="")
            cv.create_polygon(plus(1.0), fill=blend(ICE, 0.95 * ca), outline=blend(TEAL, ca), width=2)
        rr = 1.62 * L
        ext = 360 * ease(seg(t, T6 + 1.6, T6 + 2.5))
        if ext > 1:
            cv.create_arc(lcx - rr, lcy - rr, lcx + rr, lcy + rr, start=90, extent=ext, style="arc",
                          outline=blend(TEAL, la * (0.8 + 0.2 * pulse)), width=3)
        ext2 = 360 * ease(seg(t, T6 + 1.9, T6 + 2.8))
        if ext2 > 1:
            r2 = 1.82 * L
            cv.create_arc(lcx - r2, lcy - r2, lcx + r2, lcy + r2, start=90, extent=-ext2, style="arc",
                          outline=blend(GOLD, 0.8 * la), width=1)
        if ext > 300:
            for k in range(4):
                ang = k * math.pi / 2
                gx, gy = lcx + math.cos(ang) * rr, lcy + math.sin(ang) * rr
                cv.create_oval(gx - 4, gy - 4, gx + 4, gy + 4, fill=blend(GOLD, la), outline="")
        # SMART OPD letter by letter
        ty = lcy + 1.62 * self.L0 + 0.08 * H + self.f_title.metrics("linespace") * 0.35
        x_start = W / 2.0 - self.title_total / 2.0
        for i, ch in enumerate(self.title):
            ts = T6 + 1.7 + 0.07 * i
            al = ease(seg(t, ts, ts + 0.25)) * la
            if al < 0.02 or ch == " ":
                continue
            x = x_start + self.title_xs[i] + self.title_ws[i] / 2.0
            y = ty + 6 * (1 - ease(seg(t, ts, ts + 0.25)))
            for dx, dy in ((-2, 0), (2, 0), (0, -2), (0, 2)):
                cv.create_text(x + dx, y + dy, text=ch, font=self.f_title, fill=blend(TEAL, 0.35 * al))
            cv.create_text(x, y, text=ch, font=self.f_title, fill=blend(ICE, al))
        ta = ease(seg(t, T6 + 2.5, T6 + 3.1)) * la
        if ta > 0.02:
            y2 = ty + self.f_title.metrics("linespace") * 0.8
            cv.create_text(W / 2.0, y2, text="Predict.  Organize.  Care.", font=self.f_tag, fill=blend(GOLD, ta))
            ln = W * 0.12 * ta
            cv.create_line(W / 2.0 - 140 - ln, y2, W / 2.0 - 140, y2, fill=blend(GOLD, 0.6 * ta))
            cv.create_line(W / 2.0 + 140, y2, W / 2.0 + 140 + ln, y2, fill=blend(GOLD, 0.6 * ta))

    def draw_particles(self, t, dim):
        fade = 1 - ease(seg(t, T7 + 1.3, T7 + 2.4))
        if fade <= 0.01:
            return
        cv, W, H, L = self.cv, self.W, self.H, self.L0
        cx, cy = W / 2.0, H / 2.0
        sp = 0.04 + 0.96 * ease(seg(t, 1.0, T3))
        rot = 0.2 * self.tm * (1 - sp)
        cr, sr = math.cos(rot), math.sin(rot)
        for p in self.parts:
            vis = ease(seg(t, 0.25 + p.order * 1.3, 0.8 + p.order * 1.3))
            if vis <= 0.01:
                continue
            dx = (p.x0 - 0.5) * W * 1.05 * sp
            dy = (p.y0 - 0.5) * H * 1.05 * sp
            x = cx + dx * cr - dy * sr + math.sin(self.tm * p.w + p.ph) * (5 + 28 * sp)
            y = cy + dx * sr + dy * cr + math.cos(self.tm * p.w * 0.8 + p.ph) * (5 + 18 * sp)
            u = ease(seg(t, T6 + 0.5 * p.order, T6 + 0.9 + 0.5 * p.order))
            if u > 0:
                if p.ring:
                    tx, ty = self.lcx + math.cos(p.ang) * 1.62 * L, self.lcy + math.sin(p.ang) * 1.62 * L
                else:
                    tx, ty = self.lcx + p.ox * L, self.lcy + p.oy * L
                x, y = lerp(x, tx, u), lerp(y, ty, u)
                if t > T7:
                    u2 = ease(seg(t, T7 + 0.1, T7 + 0.9 + 0.5 * p.order))
                    if u2 > 0:
                        x0, y0, x1, y1 = self.card_rect(p.card, W, H)
                        x = lerp(x, x0 + p.cu * (x1 - x0), u2)
                        y = lerp(y, y0 + p.cv * (y1 - y0), u2)
            tw = 0.65 + 0.35 * math.sin(self.tm * 2.0 * p.w + p.ph * 3)
            al = vis * dim * fade * (0.5 + 0.5 * u) * tw
            if al < 0.03:
                continue
            col = GOLD if p.gold else TEAL
            r = p.sz * 0.75 + 0.4
            if p.sz >= 3 and al > 0.25:
                g = r * 2.6
                cv.create_oval(x - g, y - g, x + g, y + g, fill=blend(col, 0.2 * al), outline="")
            cv.create_oval(x - r, y - r, x + r, y + r, fill=blend(ICE if u > 0.9 else col, al), outline="")

    # ------------------------------------------------------------ SCENE 7
    def draw_wave(self, t):
        d = t - T7
        if d < 0 or d > 2.0:
            return
        cv = self.cv
        lcx, lcy, H = self.lcx, self.lcy, self.H
        if d < 0.45:
            f = 1 - d / 0.45
            for r, al in ((0.30 * H, 0.10), (0.18 * H, 0.22), (0.09 * H, 0.45)):
                rr = r * (1 + 2.5 * d)
                cv.create_oval(lcx - rr, lcy - rr, lcx + rr, lcy + rr, fill=blend(ICE, al * f), outline="")
        r = d * self.W * 1.15
        for off, wid, al in ((0, 4, 0.9), (26, 2, 0.5), (60, 1, 0.3)):
            rr = r - off
            if rr > 2:
                cv.create_oval(lcx - rr, lcy - rr, lcx + rr, lcy + rr,
                               outline=blend(ICE if off == 0 else TEAL, al * (1 - seg(d, 1.0, 2.0))), width=wid)

    def draw_dash(self, t, da):
        if da <= 0.01:
            return
        cv, W, H = self.cv, self.W, self.H
        r = (t - T7) * W * 1.15
        if r >= math.hypot(W, H) * 0.95:
            cv.create_rectangle(0, 0, W, H, fill=blend(DASHBG, da), outline="")
        elif r > 2:
            cv.create_oval(self.lcx - r, self.lcy - r, self.lcx + r, self.lcy + r,
                           fill=blend(DASHBG, da), outline="")
        xl = self.card_rect(0, W, H)[0]
        xr = self.card_rect(3, W, H)[2]
        ha = ease(seg(t, T7 + 0.55, T7 + 1.1)) * da
        if ha > 0.02:
            hy = H * 0.115
            cv.create_text(xl, hy, anchor="w", text="SMART OPD", font=self.f_hdr, fill=blend(ICE, ha))
            cv.create_text(xl, hy + 24, anchor="w", text="HOSPITAL MANAGEMENT SYSTEM", font=self.f_small,
                           fill=blend(GOLD, ha * 0.9))
            cv.create_line(xl, H * 0.17, xr, H * 0.17, fill=blend(TEAL_D, ha))
            cv.create_line(xl, H * 0.17, xl + 90, H * 0.17, fill=blend(GOLD, ha), width=2)
            cv.create_text(xr, hy, anchor="e", text=time.strftime("%H:%M:%S"), font=self.f_chip,
                           fill=blend(ICE, ha * 0.9))
            lx = xr - 140
            ph = (t * 1.2) % 1.0
            pr = 5 + 1.5 * math.sin(t * 5)
            gr = 8 + 10 * ph
            cv.create_oval(lx - gr, hy - gr, lx + gr, hy + gr, outline=blend(GREEN, 0.5 * (1 - ph) * ha, DASHBG))
            cv.create_oval(lx - pr, hy - pr, lx + pr, hy + pr, fill=blend(GREEN, ha, DASHBG), outline="")
            cv.create_text(lx + 16, hy, anchor="w", text="LIVE", font=self.f_small, fill=blend(GREEN, ha, DASHBG))
        targets = (127, 18, 12, 94)
        for i, (title, sub) in enumerate(CARDS):
            ca = ease(seg(t, T7 + 0.45 + 0.14 * i, T7 + 1.0 + 0.14 * i)) * da
            if ca < 0.02:
                continue
            x0, y0, x1, y1 = self.card_rect(i, W, H)
            ch = 10
            cv.create_polygon([x0 + ch, y0, x1, y0, x1, y1 - ch, x1 - ch, y1, x0, y1, x0, y0 + ch],
                              fill=blend((7, 26, 32), ca), outline=blend(TEAL_M, ca))
            cv.create_line(x0 + ch, y0, x0 + ch + 54, y0, fill=blend(GOLD, ca), width=2)
            cv.create_text(x0 + 18, y0 + 24, anchor="w", text=title, font=self.f_small, fill=blend(TEAL, ca))
            q = ease(seg(t, T7 + 0.8 + 0.14 * i, T7 + 2.2 + 0.14 * i))
            if i == 1:
                word = "ACTIVE"[:int(math.ceil(6 * q))]
                cv.create_text(x0 + 18, y0 + 86, anchor="w", text=word, font=self.f_big, fill=blend(ICE, ca))
                subtxt = "%d %s" % (int(targets[1] * q), sub)
            else:
                cv.create_text(x0 + 18, y0 + 86, anchor="w", text=str(int(targets[i] * q)),
                               font=self.f_num, fill=blend(ICE, ca))
                if i == 2:
                    nw = self.f_num.measure(str(int(targets[i] * q)))
                    cv.create_text(x0 + 24 + nw, y0 + 98, anchor="w", text="min", font=self.f_unit,
                                   fill=blend(GOLD, ca))
                subtxt = sub
            cv.create_text(x0 + 18, y0 + 132, anchor="w", text=subtxt, font=self.f_small,
                           fill=blend(TEAL_M, ca))
            bw = (x1 - x0 - 36) / 12.0
            for k in range(12):
                hh = (0.25 + 0.75 * abs(math.sin(k * 1.7 + self.bar_seed[i][k]))) * \
                     (0.6 + 0.4 * math.sin(self.tm * 1.5 + k * 0.6)) * 48 * q
                bx = x0 + 18 + k * bw
                if hh > 1:
                    cv.create_rectangle(bx, y1 - 18 - hh, bx + bw * 0.62, y1 - 18,
                                        fill=blend(GOLD if k == 7 else TEAL, ca * 0.55), outline="")
        fa = ease(seg(t, T7 + 1.2, T7 + 1.8)) * da
        if fa > 0.02:
            py0, py1 = H * 0.71, H * 0.89
            cv.create_rectangle(xl, py0, xr, py1, outline=blend(TEAL_D, fa), fill=blend((6, 22, 28), fa))
            cv.create_text(xl + 16, py0 + 18, anchor="w", text="PATIENT FLOW  -  LIVE", font=self.f_small,
                           fill=blend(TEAL, fa))
            npts = int(48 * seg(t, T7 + 1.3, T7 + 2.6))
            pts = []
            for k in range(npts):
                xx = xl + 14 + (xr - xl - 28) * k / 47.0
                v = 0.5 + 0.28 * math.sin(k * 0.33 + self.tm * 1.2) + 0.14 * math.sin(k * 0.8 + self.tm * 0.7)
                pts.extend((xx, py1 - 14 - (py1 - py0 - 44) * v))
            if len(pts) >= 4:
                cv.create_line(*pts, fill=blend(TEAL, fa), width=2, smooth=True)

    # ------------------------------------------------------------ SCENE 8
    def draw_msgs(self, t):
        if t < T8:
            return
        cv, W, H = self.cv, self.W, self.H
        out = 1 - ease(seg(t, TLOGIN - 0.6, TLOGIN))
        if t < TM2:
            m = ease(seg(t, T8 + 0.2, T8 + 0.9)) * (1 - ease(seg(t, TM2 - 0.5, TM2)))
            if m > 0.02:
                ln = W * 0.10 * m
                cv.create_line(W / 2.0 - ln, H * 0.43, W / 2.0 + ln, H * 0.43, fill=blend(GOLD, 0.8 * m))
                cv.create_text(W / 2.0, H * 0.5, text="மருத்துவம் மக்களுக்கான சேவை",
                               font=self.f_msg, fill=blend(ICE, m))
                ma = ease(seg(t, T8 + 0.9, T8 + 1.5)) * (1 - ease(seg(t, TM2 - 0.5, TM2)))
                if ma > 0.02:
                    cv.create_text(W / 2.0, H * 0.5 + 72, text="\u2014 CM சி. ஜோசப் விஜய்",
                                   font=self.f_msg, fill=blend(GOLD, ma))
            return
        a1 = ease(seg(t, TM2 + 0.1, TM2 + 0.7)) * out
        if a1 > 0.02:
            cv.create_text(W / 2.0, H * 0.36, text="Medical care is a service for the people,",
                           font=self.f_msg2, fill=blend(ICE, a1))
            cv.create_text(W / 2.0, H * 0.36 + 52, text="not a corporate business.",
                           font=self.f_msg2, fill=blend(ICE, a1))
            cv.create_text(W / 2.0, H * 0.36 + 102, text="\u2014 CM C. Joseph Vijay.",
                           font=self.f_msg2, fill=blend(GOLD, a1))
        a2 = ease(seg(t, TM2 + 1.0, TM2 + 1.6)) * out
        if a2 > 0.02:
            ln = W * 0.08 * a2
            cv.create_line(W / 2.0 - ln, H * 0.585, W / 2.0 + ln, H * 0.585, fill=blend(GOLD, 0.7 * a2))
            cv.create_text(W / 2.0, H * 0.63, text="W E L C O M E   T O", font=self.f_wel, fill=blend(GOLD, a2))
            cv.create_text(W / 2.0, H * 0.71, text="Smart Hospital Management System",
                           font=self.f_big, fill=blend(GOLD, a2))
            cv.create_text(W / 2.0, H * 0.75, text="By Shafir Ahamed J",
                           font=self.f_big, fill=blend(GOLD, a2))
            cv.create_text(W / 2.0, H * 0.79, text=" Shri Krishnaa PR",
                           font=self.f_big, fill=blend(GOLD, a2))
            cv.create_text(W / 2.0, H * 0.83, text="Kailash R",
                           font=self.f_big, fill=blend(GOLD, a2))
            cv.create_text(W / 2.0, H * 0.87, text="Yogesh VS",
                           font=self.f_big, fill=blend(GOLD, a2))

if __name__ == "__main__":
    _root = ctk.CTk()
    _root.geometry("1280x720")
    _root.configure(fg_color=hx(BG))

    def _done():
        ctk.CTkLabel(_root, text="Intro finished", font=ctk.CTkFont(size=28)).place(relx=.5, rely=.5, anchor="center")

    CinematicIntro(_root, _done).start()
    _root.mainloop()
