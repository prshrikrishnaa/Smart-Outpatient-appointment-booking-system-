"""
homevisit_ui.py
All CustomTkinter screens of the Home Visit feature:

  HomeVisitPatientMixin     -> 2 new tabs in the patient dashboard
                                 "🏠 Home Visit"      (location -> branch -> doctor -> slot -> payment)
                                 "🚑 My Home Visits"  (status tracking + accept/decline messages)
  HomeVisitAdminMixin       -> 1 new tab in the Admin Portal ("🏠 Home Visit") holding
                                 Branch Management / Home Visit Doctors / Monitoring
  HomeVisitDoctorLoginFrame -> separate "Home Visit Doctor Login"
  HomeVisitDoctorDashboard  -> separate sidebar-style dashboard (requests, accept/decline,
                               on-the-way/arrived/complete, schedule, availability & leave)

It re-uses the look of app.py (colours, card(), nav_tile(), stat_tile(), PaymentDialog ...).
app.py calls  homevisit_ui.bind(globals())  once, which hands those shared names to this
module - that avoids a circular import and keeps app.py's own code unchanged.
"""

import notify
import threading
import tkinter as tk
import webbrowser
from datetime import datetime, timedelta
from tkinter import messagebox

import customtkinter as ctk

import geo
from homevisit_db import (HV_FLOW, ST_ACCEPTED, ST_ARRIVED, ST_CANCELLED, ST_DECLINED, ST_DONE,
                          ST_ON_WAY, ST_WAITING, WEEKDAY_NAMES, HV_TIME_SLOTS)

# ---- names supplied by app.py through bind() -------------------------------------------
card = gold_rule = status_pill = nav_tile = stat_tile = None
MiniLogo = LiveBadge = AmbientBackground = PaymentDialog = None
NAVY = NAVY_DARK = TEAL_TXT = TEAL_BORDER = GOLD = GOLD_HOVER = GOLD_GLOW = ON_GOLD = None
BG_LIGHT = HEADER_BG = CARD_LIGHT = CARD_HOVER = BORDER = TEXT = SOFT = None
SUCCESS = WARN = DANGER = MUTED = None
TILE_BLUE = TILE_TEAL = TILE_PURPLE = TILE_ORANGE = TILE_PINK = TILE_GREEN = None

_SHARED = ("card", "gold_rule", "status_pill", "nav_tile", "stat_tile", "MiniLogo", "LiveBadge",
           "AmbientBackground", "PaymentDialog", "NAVY", "NAVY_DARK", "TEAL_TXT", "TEAL_BORDER", "GOLD",
           "GOLD_HOVER", "GOLD_GLOW", "ON_GOLD", "BG_LIGHT", "HEADER_BG", "CARD_LIGHT", "CARD_HOVER",
           "BORDER", "TEXT", "SOFT", "SUCCESS", "WARN", "DANGER", "MUTED", "TILE_BLUE", "TILE_TEAL",
           "TILE_PURPLE", "TILE_ORANGE", "TILE_PINK", "TILE_GREEN")

# the doctor dashboard deliberately looks different from the patient app: warm amber accent + sidebar
HV_ACCENT = "#e08a3c"
HV_ACCENT_HOVER = "#f0a055"
HV_HEADER = "#17100a"
HV_SIDEBAR = "#120c07"

HV_TAB = "🏠 Home Visit"
HV_MY_TAB = "🚑 My Home Visits"
ADMIN_HV_TAB = "🏠 Home Visit"


def bind(ns):
    """Called once from app.py: copies the shared theme/helpers into this module."""
    g = globals()
    for name in _SHARED:
        g[name] = ns[name]


# ==========================================================
# small shared helpers
# ==========================================================
def status_color(status):
    return {ST_WAITING: WARN, ST_ACCEPTED: NAVY, ST_ON_WAY: TILE_BLUE, ST_ARRIVED: TILE_PURPLE,
            ST_DONE: SUCCESS, ST_DECLINED: DANGER, ST_CANCELLED: MUTED}.get(status, MUTED)


def fmt_date(iso, with_day=False):
    try:
        d = datetime.strptime(iso, "%Y-%m-%d")
        return d.strftime("%d-%b-%Y (%A)" if with_day else "%d-%b-%Y")
    except (TypeError, ValueError):
        return str(iso)


def money(v):
    return f"₹{float(v):,.0f}"


def hv_payment_text(a):
    st = a["payment_status"]
    # hv_appointments has no 'amount_paid' column (only the OPD 'appointments'
    # table does). For Home Visits the amount paid is the booking's total_fee.
    a = dict(a)
    a.setdefault("amount_paid", a.get("total_fee", 0))
    if st == "Paid - Unverified":
        return f"{money(a['amount_paid'])} paid via UPI (ref {a['payment_ref']}) - awaiting verification"
    if st == "Verified":
        return f"Paid {money(a['amount_paid'])} " + ("in cash at the visit" if a["payment_method"] == "Cash"
                                                     else "via UPI - verified")
    if st == "Pay on Visit":
        return f"Pay {money(a['total_fee'])} to the doctor at the visit"
    if st == "Refund Due":
        return f"Refund of {money(a['amount_paid'])} is due - the hospital will process it"
    if st == "Refunded":
        return f"{money(a['amount_paid'])} refunded"
    return "No fee"


def run_in_background(widget, func, on_done):
    """Runs func() in a thread so the window never freezes (network calls can take seconds).
    on_done(result, error) runs back on the Tk thread; it is skipped if the widget is gone."""
    box = {}

    def work():
        try:
            box["ok"] = func()
        except Exception as e:  # noqa - always report, never crash the thread silently
            box["err"] = e

    threading.Thread(target=work, daemon=True).start()

    def poll():
        try:
            if not widget.winfo_exists():
                return
            if "ok" in box or "err" in box:
                on_done(box.get("ok"), box.get("err"))
            else:
                widget.after(120, poll)
        except tk.TclError:
            return

    try:
        widget.after(120, poll)
    except tk.TclError:
        pass


def hover_border(frame, hot=None):
    """gold border glow while the mouse is anywhere over a card (same effect as the dashboard tiles)"""
    hot = hot or GOLD

    def enter(_e=None):
        try:
            frame.configure(border_color=hot)
        except tk.TclError:
            pass

    def leave(_e=None):
        def check():
            try:
                w = frame.winfo_containing(*frame.winfo_pointerxy())
                while w is not None:
                    if w is frame:
                        return
                    w = w.master
                frame.configure(border_color=BORDER)
            except (tk.TclError, KeyError):
                pass
        try:
            frame.after(40, check)
        except tk.TclError:
            pass

    def walk(w):
        try:
            w.bind("<Enter>", enter, add="+")
            w.bind("<Leave>", leave, add="+")
        except Exception:
            pass
        for c in w.winfo_children():
            walk(c)

    walk(frame)


def ghost_button(parent, text, command, width=110, **kw):
    return ctk.CTkButton(parent, text=text, width=width, fg_color="transparent", text_color=TEAL_TXT,
                         border_width=1, border_color=TEAL_BORDER, hover_color="#0f2a31", command=command, **kw)


def gold_button(parent, text, command, width=200, height=38, **kw):
    return ctk.CTkButton(parent, text=text, width=width, height=height, fg_color=GOLD, hover_color=GOLD_HOVER,
                         text_color=ON_GOLD, font=ctk.CTkFont(weight="bold"), command=command, **kw)


def progress_chips(parent, a, bg=None):
    """Payment Completed -> Waiting -> Accepted -> On The Way -> Arrived -> Completed, as chips."""
    short = {"Payment Completed": "Payment Done", "Request Placed": "Request Placed", ST_WAITING: "Awaiting Doctor",
             ST_ACCEPTED: "Accepted", ST_ON_WAY: "On The Way", ST_ARRIVED: "Arrived", ST_DONE: "Completed"}
    steps = list(HV_FLOW)
    if a["payment_method"] != "UPI":
        steps[0] = "Request Placed"
    status = a["status"]
    closed = status in (ST_DECLINED, ST_CANCELLED)
    current = 1 if closed else (steps.index(status) if status in steps else 1)
    row = ctk.CTkFrame(parent, fg_color=bg or "transparent")
    for i, s in enumerate(steps):
        if closed:
            fg, tc = ("#16303a", MUTED) if i > 1 else (NAVY_DARK, "white")
            txt = short[s]
        elif i < current:
            fg, tc, txt = NAVY, "white", "✓ " + short[s]
        elif i == current:
            fg, tc, txt = GOLD, ON_GOLD, short[s]
        else:
            fg, tc, txt = "#16303a", MUTED, short[s]
        ctk.CTkLabel(row, text=f"  {txt}  ", fg_color=fg, text_color=tc, corner_radius=10,
                     font=ctk.CTkFont(size=11, weight="bold" if i == current else "normal")
                     ).pack(side="left", padx=(0, 3), pady=2)
        if i < len(steps) - 1:
            ctk.CTkLabel(row, text="›", text_color=MUTED).pack(side="left", padx=(0, 3))
    return row


def accepted_message(a):
    return (f"✅ Your Home Visit has been accepted by Dr. {a['doctor_name']}.\n\n"
            f"Date: {fmt_date(a['appointment_date'], True)}\nTime: {a['appointment_time']}\n"
            f"Doctor: Dr. {a['doctor_name']} ({a['specialization']})\nBranch: {a['branch_name']}")


def declined_message(a):
    msg = (f"❌ Your Home Visit request was declined by Dr. {a['doctor_name']}.\n\n"
           f"Reason: {a['decline_reason'] or 'Not given'}")
    if a["payment_status"] in ("Refund Due", "Refunded"):
        msg += "\n\nYour online payment will be refunded by the hospital."
    return msg


class _DateField:
    """DD/MM/YYYY parsing used by the leave form."""

    @staticmethod
    def parse(text):
        t = (text or "").strip().replace("-", "/").replace(".", "/")
        return datetime.strptime(t, "%d/%m/%Y").date()


# ==========================================================
# PATIENT SIDE
# ==========================================================
class HomeVisitConfirmDialog(ctk.CTkToplevel):
    def __init__(self, app, a_info):
        super().__init__(app)
        self.title("Home Visit Request Sent")
        self.geometry("420x520")
        self.resizable(False, False)
        self.configure(fg_color=BG_LIGHT)
        try:
            self.transient(app)
            self.after(150, lambda: self.winfo_exists() and self.grab_set())
        except tk.TclError:
            pass
        head = ctk.CTkFrame(self, fg_color=SUCCESS, corner_radius=0, height=70)
        head.pack(fill="x")
        head.pack_propagate(False)
        ctk.CTkLabel(head, text="✅  Home Visit Request Sent", font=ctk.CTkFont(size=17, weight="bold"),
                     text_color="white").pack(pady=22)
        body = card(self)
        body.pack(fill="both", expand=True, padx=18, pady=18)

        def row(label, value):
            r = ctk.CTkFrame(body, fg_color="transparent")
            r.pack(fill="x", padx=16, pady=4)
            ctk.CTkLabel(r, text=label, text_color=MUTED, font=ctk.CTkFont(size=11)).pack(anchor="w")
            ctk.CTkLabel(r, text=value, font=ctk.CTkFont(size=13, weight="bold"), wraplength=330,
                         justify="left").pack(anchor="w")

        row("Request No.", f"HV-{a_info['id']:04d}")
        row("👨‍⚕️ Doctor", f"Dr. {a_info['doctor_name']}  -  {a_info['specialization']}")
        row("🏥 Branch", a_info["branch_name"])
        row("📅 Date & 🕐 Time", f"{fmt_date(a_info['date'], True)}  at  {a_info['time']}")
        row("📍 Address", a_info["address"])
        row("💳 Payment", a_info["payment_text"])
        box = ctk.CTkFrame(body, fg_color=GOLD, corner_radius=10)
        box.pack(fill="x", padx=16, pady=(12, 8))
        ctk.CTkLabel(box, text="STATUS", text_color=ON_GOLD, font=ctk.CTkFont(size=11, weight="bold")
                     ).pack(pady=(8, 0))
        ctk.CTkLabel(box, text="Waiting for Doctor Response", text_color=ON_GOLD,
                     font=ctk.CTkFont(size=15, weight="bold")).pack(pady=(0, 8))
        ctk.CTkLabel(body, text="You will be notified here as soon as the doctor accepts or declines.",
                     text_color=MUTED, font=ctk.CTkFont(size=11), wraplength=340).pack(pady=(0, 8))
        ghost_button(body, "Done", self.destroy, width=120).pack(pady=(0, 14))


class HomeVisitPatientMixin:
    """Mixed into DashboardFrame (see app.py)."""

    STEP_LABELS = ("📍 Location", "🏥 Branch", "👨‍⚕️ Doctor", "📅 Date & Time", "💳 Payment")

    # ---------------------------------------------------------------- tab 1: booking wizard
    def _build_homevisit_tab(self, tab):
        self.hv_state = {}
        self._hv_token = 0
        self._hv_chips = []
        self.hv_step_frame = ctk.CTkScrollableFrame(tab, fg_color="transparent")
        self.hv_step_frame.pack(fill="both", expand=True)
        self._hv_step_location()

    def _hv_clear(self):
        self._hv_token += 1                       # invalidates any background job from the old step
        for w in self.hv_step_frame.winfo_children():
            w.destroy()
        self._hv_chips = []

    def _hv_bg(self, func, on_done):
        token = self._hv_token

        def done(res, err):
            if token == self._hv_token:           # ignore results that arrive after the user moved on
                on_done(res, err)
        run_in_background(self.hv_step_frame, func, done)

    def _hv_stepper(self, current):
        row = ctk.CTkFrame(self.hv_step_frame, fg_color="transparent")
        row.pack(anchor="w", padx=20, pady=(14, 0))
        self._hv_chips = []
        for i, label in enumerate(self.STEP_LABELS):
            chip = ctk.CTkLabel(row, text=f"  {label}  ", corner_radius=10, font=ctk.CTkFont(size=11))
            chip.pack(side="left", padx=(0, 4))
            self._hv_chips.append(chip)
        self._hv_paint_stepper(current)

    def _hv_paint_stepper(self, current):
        for i, chip in enumerate(self._hv_chips):
            try:
                if i < current:
                    chip.configure(fg_color=NAVY, text_color="white")
                elif i == current:
                    chip.configure(fg_color=GOLD, text_color=ON_GOLD, font=ctk.CTkFont(size=11, weight="bold"))
                else:
                    chip.configure(fg_color="#16303a", text_color=MUTED)
            except tk.TclError:
                pass

    # ---------------- step 1: location ----------------
    def _hv_step_location(self):
        self._hv_clear()
        f = self.hv_step_frame
        self.hv_state = {}
        self._hv_stepper(0)
        ctk.CTkLabel(f, text="📍 Home Visit Location", font=ctk.CTkFont(size=20, weight="bold"),
                     text_color=TEAL_TXT).pack(anchor="w", padx=20, pady=(16, 2))
        ctk.CTkLabel(f, text="A doctor will come to your home instead of you going to the hospital. Tell us where "
                             "you are and we will pick the nearest SRM branch for you automatically.",
                     text_color=MUTED, wraplength=760, justify="left").pack(anchor="w", padx=20, pady=(0, 12))

        tiles = ctk.CTkFrame(f, fg_color="transparent")
        tiles.pack(anchor="w", padx=14)
        nav_tile(tiles, icon="📍", title="Use Current Location", subtitle="Detect automatically",
                 color=TILE_BLUE, command=self._hv_use_current_location).pack(side="left", padx=6)
        nav_tile(tiles, icon="✏️", title="Enter Address", subtitle="Type your home address",
                 color=TILE_ORANGE, command=self._hv_show_manual_form).pack(side="left", padx=6)

        self.hv_box = ctk.CTkFrame(f, fg_color="transparent")
        self.hv_box.pack(fill="x", padx=20, pady=(14, 20))

    def _hv_box_clear(self):
        self._hv_token += 1
        for w in self.hv_box.winfo_children():
            w.destroy()

    def _hv_loading(self, text):
        self._hv_box_clear()
        c = card(self.hv_box)
        c.pack(fill="x")
        lbl = ctk.CTkLabel(c, text=f"⏳  {text}", font=ctk.CTkFont(size=14), text_color=GOLD_HOVER)
        lbl.pack(padx=20, pady=22, anchor="w")
        state = {"n": 0}

        def tick():
            try:
                if not lbl.winfo_exists():
                    return
                state["n"] = (state["n"] + 1) % 4
                lbl.configure(text=f"⏳  {text}" + "." * state["n"])
                lbl.after(400, tick)
            except tk.TclError:
                return
        lbl.after(400, tick)

    def _hv_message(self, text, color=None, icon="⚠️", manual_button=True):
        color = color or DANGER
        self._hv_box_clear()
        c = card(self.hv_box, border_color=color)
        c.pack(fill="x")
        ctk.CTkLabel(c, text=f"{icon}  {text}", text_color=TEXT, wraplength=700, justify="left",
                     font=ctk.CTkFont(size=13)).pack(anchor="w", padx=20, pady=(18, 10))
        row = ctk.CTkFrame(c, fg_color="transparent")
        row.pack(anchor="w", padx=20, pady=(0, 16))
        if manual_button:
            gold_button(row, "✏️  Enter Address Manually", self._hv_show_manual_form, width=230).pack(side="left")
        ghost_button(row, "↻ Try Current Location Again", self._hv_use_current_location, width=210
                     ).pack(side="left", padx=8)

    def _hv_use_current_location(self):
        self._hv_paint_stepper(0)
        self._hv_loading("Detecting your location")

        def job():
            loc = geo.detect_current_location()
            addr = {"display": "", "city": ""}
            try:
                addr = geo.reverse_geocode(loc["lat"], loc["lon"])
            except geo.LocationError:
                pass                                   # address text is optional - coordinates are enough
            return loc, addr

        def done(res, err):
            if err is not None:
                if isinstance(err, geo.LocationError):
                    self._hv_message(str(err) + "\n\nYou can type your address instead.")
                else:
                    self._hv_message("Something went wrong while detecting your location. "
                                     "Please enter your address manually.")
                return
            loc, addr = res
            self._hv_resolve(loc["lat"], loc["lon"], loc["source"], addr["display"], addr["city"],
                             loc["approximate"])
        self._hv_bg(job, done)

    def _hv_show_manual_form(self):
        self._hv_paint_stepper(0)
        self._hv_box_clear()
        c = card(self.hv_box)
        c.pack(fill="x")
        ctk.CTkLabel(c, text="✏️  Enter your home address", font=ctk.CTkFont(size=14, weight="bold"),
                     text_color=TEAL_TXT).pack(anchor="w", padx=20, pady=(16, 2))
        ctk.CTkLabel(c, text="House no., street, area, city.  (Or type coordinates like  10.9385, 78.7501)",
                     text_color=MUTED, font=ctk.CTkFont(size=11)).pack(anchor="w", padx=20)
        entry = ctk.CTkEntry(c, placeholder_text="e.g. 12 Gandhi Street, Anna Nagar, Madurai", width=560, height=40)
        entry.pack(anchor="w", padx=20, pady=(8, 4))
        msg = ctk.CTkLabel(c, text="", text_color=DANGER, wraplength=640, justify="left",
                           font=ctk.CTkFont(size=12))
        msg.pack(anchor="w", padx=20)
        btn = gold_button(c, "🔎  Find My Branch", lambda: submit(), width=200)
        btn.pack(anchor="w", padx=20, pady=(6, 16))
        entry.bind("<Return>", lambda e: submit())
        entry.focus_set()

        def submit():
            text = entry.get().strip()
            if len(text) < 4:
                msg.configure(text="Please type your address (or coordinates).", text_color=DANGER)
                return
            msg.configure(text="⏳ Looking up your address...", text_color=GOLD_HOVER)
            btn.configure(state="disabled")
            token = self._hv_token

            def job():
                pair = geo.parse_latlon(text)
                if pair:
                    try:
                        a = geo.reverse_geocode(*pair)
                    except geo.LocationError:
                        a = {"display": "", "city": ""}
                    return {"lat": pair[0], "lon": pair[1], "display": text if not a["display"] else a["display"],
                            "city": a["city"]}
                return geo.geocode_address(text)

            def done(res, err):
                try:
                    if not msg.winfo_exists():
                        return
                except tk.TclError:
                    return
                btn.configure(state="normal")
                if err is not None:
                    msg.configure(text=str(err) if isinstance(err, geo.LocationError)
                                  else "Could not look up that address. Please check it and try again.",
                                  text_color=DANGER)
                    return
                typed = text if not geo.parse_latlon(text) else ""
                self._hv_resolve(res["lat"], res["lon"], "manual", typed or res["display"], res["city"], False)

            # not using _hv_bg here: the token changes when the result card replaces this form
            run_in_background(self.hv_step_frame, job, lambda r, e: (token == self._hv_token) and done(r, e))

    def _hv_resolve(self, lat, lon, source, address, city, approximate):
        """coordinates known -> compare with the ADMIN-configured branches -> nearest eligible one"""
        branches = self.app.db.get_branches_full(include_inactive=False)
        best, ranked = geo.rank_branches(lat, lon, branches)
        self.hv_state.update(lat=lat, lon=lon, source=source, address=address or "", city=city or "",
                             approximate=approximate, branch=best, ranked=ranked)
        self._hv_show_result()

    def _hv_show_result(self):
        s = self.hv_state
        self._hv_box_clear()
        c = card(self.hv_box, border_color=SUCCESS if s["branch"] else DANGER)
        c.pack(fill="x")
        place = s["city"] or f"{s['lat']:.4f}, {s['lon']:.4f}"
        ctk.CTkLabel(c, text="📍 Your Location", text_color=MUTED, font=ctk.CTkFont(size=11)
                     ).pack(anchor="w", padx=20, pady=(16, 0))
        ctk.CTkLabel(c, text=place, font=ctk.CTkFont(size=17, weight="bold")).pack(anchor="w", padx=20)
        ctk.CTkLabel(c, text=f"({s['lat']:.5f}, {s['lon']:.5f})", text_color=MUTED,
                     font=ctk.CTkFont(size=10)).pack(anchor="w", padx=20)
        if s["approximate"]:
            ctk.CTkLabel(c, text="ℹ️ This position comes from your internet connection, so it can be off by a few "
                                 "kilometres. You will type your exact home address in a later step.",
                         text_color=WARN, wraplength=700, justify="left", font=ctk.CTkFont(size=11)
                         ).pack(anchor="w", padx=20, pady=(4, 0))
        b = s["branch"]
        if b:
            self._hv_paint_stepper(1)
            ctk.CTkLabel(c, text="🏥 Automatically Selected Branch", text_color=MUTED, font=ctk.CTkFont(size=11)
                         ).pack(anchor="w", padx=20, pady=(12, 0))
            ctk.CTkLabel(c, text=b["branch_name"], font=ctk.CTkFont(size=17, weight="bold"),
                         text_color=TEAL_TXT).pack(anchor="w", padx=20)
            ctk.CTkLabel(c, text="📏 Distance from Branch", text_color=MUTED, font=ctk.CTkFont(size=11)
                         ).pack(anchor="w", padx=20, pady=(12, 0))
            ctk.CTkLabel(c, text=f"{b['distance_km']:.1f} km   (Home Visit service radius: {b['hv_radius_km']:g} km)",
                         font=ctk.CTkFont(size=15, weight="bold")).pack(anchor="w", padx=20)
            row = ctk.CTkFrame(c, fg_color="transparent")
            row.pack(anchor="w", padx=20, pady=(14, 16))
            gold_button(row, "Continue: Choose a Doctor  →", self._hv_step_doctor, width=260).pack(side="left")
            ghost_button(row, "Change location", self._hv_step_location, width=150).pack(side="left", padx=8)
        else:
            self._hv_paint_stepper(0)
            ctk.CTkLabel(c, text="⚠️ Home Visit is currently unavailable in your location.",
                         font=ctk.CTkFont(size=15, weight="bold"), text_color=WARN
                         ).pack(anchor="w", padx=20, pady=(14, 2))
            ranked = s["ranked"]
            if not ranked:
                detail = "No SRM branch has been set up for Home Visit yet. Please contact the hospital."
            else:
                n = ranked[0]
                detail = (f"The nearest SRM branch is {n['branch_name']}, {n['distance_km']:.1f} km away. ")
                detail += (f"Its Home Visit service radius is {n['hv_radius_km']:g} km." if n["hv_enabled"]
                           else "Home Visit is not offered at that branch.")
            ctk.CTkLabel(c, text=detail, text_color=SOFT, wraplength=700, justify="left"
                         ).pack(anchor="w", padx=20)
            row = ctk.CTkFrame(c, fg_color="transparent")
            row.pack(anchor="w", padx=20, pady=(12, 16))
            gold_button(row, "✏️  Try Another Address", self._hv_show_manual_form, width=200).pack(side="left")
            ghost_button(row, "↻ Detect Again", self._hv_use_current_location, width=130).pack(side="left", padx=8)

    # ---------------- step 2: doctors of the selected branch ----------------
    def _hv_step_doctor(self):
        s = self.hv_state
        b = s.get("branch")
        if not b:
            self._hv_step_location()
            return
        self._hv_clear()
        f = self.hv_step_frame
        self._hv_stepper(2)
        ctk.CTkLabel(f, text=f"🏥 {b['branch_name']}   ·   📏 {b['distance_km']:.1f} km from you",
                     text_color=MUTED).pack(anchor="w", padx=20, pady=(16, 0))
        ctk.CTkLabel(f, text="👨‍⚕️ Available Home Visit Doctors", font=ctk.CTkFont(size=20, weight="bold"),
                     text_color=TEAL_TXT).pack(anchor="w", padx=20, pady=(2, 10))

        # re-check the branch on the database side too (admin may have just changed it)
        fresh = self.app.db.get_branch(b["branch_id"])
        doctors = []
        if fresh and fresh["is_active"] and fresh["hv_enabled"]:
            doctors = self.app.db.get_bookable_hv_doctors(b["branch_id"])
        if not doctors:
            c = card(f)
            c.pack(fill="x", padx=20, pady=10)
            ctk.CTkLabel(c, text="😔  No Home Visit doctors are available at this branch right now.\n"
                                 "They may be on leave or fully booked. Please try again later.",
                         text_color=SOFT, justify="left", font=ctk.CTkFont(size=13)).pack(padx=20, pady=20)
            ghost_button(f, "← Back", self._hv_step_location).pack(anchor="w", padx=20, pady=6)
            return

        for d in doctors:
            c = card(f)
            c.pack(fill="x", padx=20, pady=6)
            inner = ctk.CTkFrame(c, fg_color="transparent")
            inner.pack(fill="x", padx=14, pady=12)
            badge = ctk.CTkFrame(inner, fg_color=TILE_TEAL, corner_radius=14, width=52, height=52)
            badge.pack(side="left")
            badge.pack_propagate(False)
            ctk.CTkLabel(badge, text="👨‍⚕️", font=ctk.CTkFont(size=22)).pack(expand=True)
            info = ctk.CTkFrame(inner, fg_color="transparent")
            info.pack(side="left", padx=14, fill="x", expand=True)
            ctk.CTkLabel(info, text=f"Dr. {d['name']}", font=ctk.CTkFont(size=16, weight="bold")
                         ).pack(anchor="w")
            area = f"   ·   Service area: {d['service_area']}" if d["service_area"] else ""
            ctk.CTkLabel(info, text=f"{d['specialization']}{area}", text_color=SOFT).pack(anchor="w")
            total = d["consultation_fee"] + d["visit_fee"]
            ctk.CTkLabel(info, text=f"Consultation {money(d['consultation_fee'])}  +  Home Visit "
                                    f"{money(d['visit_fee'])}  =  {money(total)}",
                         text_color=GOLD_HOVER, font=ctk.CTkFont(size=12, weight="bold")).pack(anchor="w")
            nxt = fmt_date(d["dates"][0][0])
            ctk.CTkLabel(info, text=f"🟢 Available   ·   next free day: {nxt}", text_color=SUCCESS,
                         font=ctk.CTkFont(size=11)).pack(anchor="w")
            if d["note"]:
                ctk.CTkLabel(info, text="🔴 " + d["note"], text_color=WARN, font=ctk.CTkFont(size=11)
                             ).pack(anchor="w")
            gold_button(inner, "Select  →", lambda doc=d: self._hv_step_details(doc), width=110
                        ).pack(side="right")
            hover_border(c)
        ghost_button(f, "← Back", self._hv_step_location).pack(anchor="w", padx=20, pady=10)

    # ---------------- step 3: date, time, details, fee ----------------
    def _hv_step_details(self, doc):
        s = self.hv_state
        # always read fresh dates/slots - someone else may have booked meanwhile
        dates = self.app.db.get_bookable_dates(doc["hv_doctor_id"])
        if not dates:
            messagebox.showinfo("Doctor unavailable", "Sorry, this doctor has no free slots any more. "
                                                      "Please choose another doctor.")
            self._hv_step_doctor()
            return
        self._hv_clear()
        f = self.hv_step_frame
        self._hv_stepper(3)
        ctk.CTkLabel(f, text=f"Dr. {doc['name']}  ·  {doc['specialization']}  ·  {s['branch']['branch_name']}",
                     text_color=MUTED).pack(anchor="w", padx=20, pady=(16, 0))
        ctk.CTkLabel(f, text="📅 Date, Time & Visit Details", font=ctk.CTkFont(size=20, weight="bold"),
                     text_color=TEAL_TXT).pack(anchor="w", padx=20, pady=(2, 10))

        cols = ctk.CTkFrame(f, fg_color="transparent")
        cols.pack(fill="x", padx=20)
        left = ctk.CTkFrame(cols, fg_color="transparent")
        left.pack(side="left", fill="both", expand=True)
        right = card(cols, width=290)
        right.pack(side="left", fill="y", padx=(16, 0))
        right.pack_propagate(False)

        slot_map = {d: sl for d, sl in dates}
        label_to_date = {fmt_date(d, True): d for d, _ in dates}

        ctk.CTkLabel(left, text="📅 Date").pack(anchor="w")
        self.hv_date_menu = ctk.CTkOptionMenu(left, values=list(label_to_date), width=320, height=36,
                                               fg_color=NAVY, button_color=NAVY_DARK)
        self.hv_date_menu.pack(anchor="w", pady=(2, 8))
        ctk.CTkLabel(left, text="🕐 Time").pack(anchor="w")
        self.hv_time_menu = ctk.CTkOptionMenu(left, values=slot_map[dates[0][0]], width=320, height=36,
                                               fg_color=NAVY, button_color=NAVY_DARK)
        self.hv_time_menu.pack(anchor="w", pady=(2, 8))

        def on_date(label):
            slots = slot_map[label_to_date[label]]
            self.hv_time_menu.configure(values=slots)
            self.hv_time_menu.set(slots[0])
        self.hv_date_menu.configure(command=on_date)
        self.hv_date_menu.set(list(label_to_date)[0])

        ctk.CTkLabel(left, text="📞 Contact number").pack(anchor="w")
        self.hv_phone = ctk.CTkEntry(left, width=320, height=36)
        self.hv_phone.pack(anchor="w", pady=(2, 8))
        self.hv_phone.insert(0, self.app.db.get_patient_contact(self.app.current_patient.patient_id))

        ctk.CTkLabel(left, text="🏠 Full home address (the doctor will come here)").pack(anchor="w")
        self.hv_addr = ctk.CTkTextbox(left, width=420, height=70)
        self.hv_addr.pack(anchor="w", pady=(2, 8))
        self.hv_addr.insert("1.0", s.get("address", ""))

        ctk.CTkLabel(left, text="📝 Problem / reason for the visit").pack(anchor="w")
        self.hv_reason = ctk.CTkTextbox(left, width=420, height=70)
        self.hv_reason.pack(anchor="w", pady=(2, 8))

        # fee summary
        total = doc["consultation_fee"] + doc["visit_fee"]
        ctk.CTkLabel(right, text="💳 Fee Summary", font=ctk.CTkFont(size=15, weight="bold"),
                     text_color=TEAL_TXT).pack(anchor="w", padx=18, pady=(16, 8))
        for label, val in (("Consultation fee", doc["consultation_fee"]), ("Home Visit fee", doc["visit_fee"])):
            r = ctk.CTkFrame(right, fg_color="transparent")
            r.pack(fill="x", padx=18, pady=2)
            ctk.CTkLabel(r, text=label, text_color=SOFT).pack(side="left")
            ctk.CTkLabel(r, text=money(val), font=ctk.CTkFont(weight="bold")).pack(side="right")
        ctk.CTkFrame(right, fg_color=BORDER, height=1).pack(fill="x", padx=18, pady=8)
        ctk.CTkLabel(right, text="Total to pay", text_color=MUTED, font=ctk.CTkFont(size=11)
                     ).pack(anchor="w", padx=18)
        ctk.CTkLabel(right, text=money(total), text_color=GOLD, font=ctk.CTkFont(size=30, weight="bold")
                     ).pack(anchor="w", padx=18, pady=(0, 6))
        ctk.CTkLabel(right, text="Pay online with a UPI QR in the next step, or pay the doctor in cash at the "
                                 "visit.", text_color=MUTED, wraplength=240, justify="left",
                     font=ctk.CTkFont(size=11)).pack(anchor="w", padx=18, pady=(0, 14))

        row = ctk.CTkFrame(f, fg_color="transparent")
        row.pack(anchor="w", padx=20, pady=14)
        ghost_button(row, "← Back", self._hv_step_doctor, width=100).pack(side="left", padx=(0, 8))
        gold_button(row, "💳  Proceed to Payment", lambda: self._hv_proceed(doc, label_to_date),
                    width=240).pack(side="left")

    def _hv_proceed(self, doc, label_to_date):
        s = self.hv_state
        phone_digits = "".join(ch for ch in self.hv_phone.get() if ch.isdigit())
        address = self.hv_addr.get("1.0", "end").strip()
        reason = self.hv_reason.get("1.0", "end").strip()
        if len(phone_digits) < 10:
            messagebox.showerror("Input Error", "Please enter a valid 10-digit contact number.")
            return
        if len(address) < 10:
            messagebox.showerror("Input Error", "Please type your full home address so the doctor can find you.")
            return
        if len(reason) < 3:
            messagebox.showerror("Input Error", "Please describe the problem / reason for the visit.")
            return
        date_str = label_to_date.get(self.hv_date_menu.get())
        time_str = self.hv_time_menu.get()
        if not date_str or time_str not in self.app.db.get_available_slots(doc["hv_doctor_id"], date_str):
            messagebox.showwarning("Slot unavailable", "That slot is no longer free. Please pick another time.")
            self._hv_step_details(doc)
            return

        total = doc["consultation_fee"] + doc["visit_fee"]
        details = dict(date=date_str, time=time_str, contact=phone_digits[-10:], address=address, reason=reason)

        def finalize(method, ref):
            booking_method = {"UPI": "UPI", "Counter": "Visit"}.get(method, "None")
            try:
                ok, res = self.app.db.create_hv_booking(
                    patient_id=self.app.current_patient.patient_id, hv_doctor_id=doc["hv_doctor_id"],
                    branch_id=s["branch"]["branch_id"], appointment_date=details["date"],
                    appointment_time=details["time"], contact=details["contact"], reason=details["reason"],
                    address=details["address"], city=s.get("city", ""), latitude=s["lat"], longitude=s["lon"],
                    location_source=s["source"], distance_km=round(s["branch"]["distance_km"], 2),
                    payment_method=booking_method, payment_ref=ref)
            except Exception as e:  # never crash after the patient has paid
                ok, res = False, f"Unexpected error: {e}"
            if not ok:
                extra = (f"\n\nYou already paid online. Please keep your UPI reference {ref} and show it to the "
                         f"hospital desk - it was NOT used for any booking.") if method == "UPI" else ""
                messagebox.showerror("Home Visit Booking Failed", str(res) + extra)
                self._hv_step_details(doc)
                return
            a = self.app.db.get_hv_appointment(res["hv_appointment_id"])
            HomeVisitConfirmDialog(self.app, dict(
                id=res["hv_appointment_id"], doctor_name=doc["name"], specialization=doc["specialization"],
                branch_name=s["branch"]["branch_name"], date=details["date"], time=details["time"],
                address=details["address"], payment_text=hv_payment_text(a) if a else ""))
            notify.send_async(
                self.app.db, details["contact"],
                notify.home_visit_message(self.app.current_patient.name, f"Dr. {doc['name']}",
                                          doc["specialization"], fmt_date(details["date"]), details["time"],
                                          hv_payment_text(a) if a else ""))
            self._hv_step_location()
            self._hv_refresh_my(force=True)
            self.tabs.set(HV_MY_TAB)

        if total > 0:
            PaymentDialog(self.app, amount=total, doctor_label=f"Dr. {doc['name']}",
                          department=f"Home Visit - {doc['specialization']}", on_done=finalize,
                          allow_counter=True, counter_text="Pay cash to the doctor at the visit",
                          note="Home visit",
                          fallback_msg="Online payment is not set up yet. You can still book and pay the doctor "
                                       "in cash at the visit.")
        else:
            finalize("None", "")

    # ---------------------------------------------------------------- tab 2: my home visits
    def _build_myhv_tab(self, tab):
        self._hv_my_sig = None
        top = ctk.CTkFrame(tab, fg_color="transparent")
        top.pack(fill="x", padx=15, pady=(12, 0))
        ctk.CTkLabel(top, text="🚑 My Home Visits", font=ctk.CTkFont(size=18, weight="bold"),
                     text_color=TEAL_TXT).pack(side="left")
        ghost_button(top, "⟳ Refresh", lambda: self._hv_refresh_my(force=True), width=100).pack(side="right")
        ctk.CTkLabel(top, text="updates automatically", text_color=MUTED, font=ctk.CTkFont(size=11)
                     ).pack(side="right", padx=10)
        self.hv_my_list = ctk.CTkScrollableFrame(tab, fg_color="transparent")
        self.hv_my_list.pack(fill="both", expand=True, padx=15, pady=10)
        self._hv_refresh_my(force=True)

    def _hv_refresh_my(self, force=False):
        try:
            if not self.hv_my_list.winfo_exists():
                return
        except (tk.TclError, AttributeError):
            return
        db = self.app.db
        db.expire_stale_hv_requests()
        rows = db.get_hv_appointments_for_patient(self.app.current_patient.patient_id)
        sig = tuple((r["hv_appointment_id"], r["status"], r["payment_status"]) for r in rows)
        if not force and sig == self._hv_my_sig:
            return                                   # nothing changed - don't flicker
        self._hv_my_sig = sig
        for w in self.hv_my_list.winfo_children():
            w.destroy()
        if not rows:
            ctk.CTkLabel(self.hv_my_list, text="No Home Visits yet. Open the '🏠 Home Visit' tab to book one.",
                         text_color=MUTED).pack(pady=24)
            return
        for a in rows:
            self._hv_patient_card(a)

    def _hv_patient_card(self, a):
        c = card(self.hv_my_list)
        c.pack(fill="x", pady=6)
        top = ctk.CTkFrame(c, fg_color="transparent")
        top.pack(fill="x", padx=16, pady=(14, 2))
        ctk.CTkLabel(top, text=f"HV-{a['hv_appointment_id']:04d}   ·   Dr. {a['doctor_name']}  "
                               f"({a['specialization']})", font=ctk.CTkFont(size=15, weight="bold")
                     ).pack(side="left")
        status_pill(top, a["status"], status_color(a["status"])).pack(side="right")
        ctk.CTkLabel(c, text=f"📅 {fmt_date(a['appointment_date'], True)}   🕐 {a['appointment_time']}   "
                             f"🏥 {a['branch_name']}", text_color=SOFT).pack(anchor="w", padx=16)
        ctk.CTkLabel(c, text=f"📍 {a['address'] or '-'}", text_color=MUTED, wraplength=820, justify="left"
                     ).pack(anchor="w", padx=16)
        ctk.CTkLabel(c, text=f"💳 {hv_payment_text(a)}", text_color=GOLD_HOVER, font=ctk.CTkFont(size=12)
                     ).pack(anchor="w", padx=16, pady=(2, 6))
        progress_chips(c, a).pack(anchor="w", padx=14, pady=(0, 8))

        if a["status"] in (ST_ACCEPTED, ST_ON_WAY, ST_ARRIVED, ST_DONE):
            live = {ST_ACCEPTED: "Dr. {n} has accepted - please be ready at the given address.",
                    ST_ON_WAY: "🚗 Dr. {n} is on the way to your home.",
                    ST_ARRIVED: "🏠 Dr. {n} has arrived at your address.",
                    ST_DONE: "Visit completed. Get well soon!"}[a["status"]].format(n=a["doctor_name"])
            box = ctk.CTkFrame(c, fg_color="#0f2f26", corner_radius=10, border_width=1, border_color=SUCCESS)
            box.pack(fill="x", padx=16, pady=(0, 10))
            ctk.CTkLabel(box, text=accepted_message(a), justify="left", text_color=TEXT, anchor="w"
                         ).pack(anchor="w", padx=14, pady=(10, 2))
            ctk.CTkLabel(box, text=live, text_color=SUCCESS, font=ctk.CTkFont(size=12, weight="bold")
                         ).pack(anchor="w", padx=14, pady=(0, 10))
        elif a["status"] == ST_DECLINED:
            box = ctk.CTkFrame(c, fg_color="#33140f", corner_radius=10, border_width=1, border_color=DANGER)
            box.pack(fill="x", padx=16, pady=(0, 10))
            ctk.CTkLabel(box, text=declined_message(a), justify="left", text_color=TEXT, wraplength=800
                         ).pack(anchor="w", padx=14, pady=10)
        elif a["status"] == ST_CANCELLED:
            ctk.CTkLabel(c, text="This request was cancelled / expired."
                                 + ("  Your online payment will be refunded." if a["payment_status"] in
                                    ("Refund Due", "Refunded") else ""),
                         text_color=MUTED).pack(anchor="w", padx=16, pady=(0, 10))
        if a["status"] == ST_WAITING:
            ctk.CTkButton(c, text="Cancel Request", width=130, fg_color="transparent", text_color=DANGER,
                          border_width=1, border_color=DANGER, hover_color="#2a1512",
                          command=lambda i=a["hv_appointment_id"]: self._hv_cancel(i)
                          ).pack(anchor="w", padx=16, pady=(0, 14))
        else:
            ctk.CTkFrame(c, fg_color="transparent", height=4).pack()
        hover_border(c)

    def _hv_cancel(self, appt_id):
        if not messagebox.askyesno("Cancel Home Visit", "Cancel this Home Visit request?\n"
                                                         "(Online payments are refunded by the hospital.)"):
            return
        ok, msg = self.app.db.hv_cancel_by_patient(appt_id, self.app.current_patient.patient_id)
        if ok:
            self.app.db.mark_hv_notified(appt_id, ST_CANCELLED)
            self._hv_refresh_my(force=True)
        else:
            messagebox.showerror("Could not cancel", msg)
            self._hv_refresh_my(force=True)

    # ---------------------------------------------------------------- notifications + polling
    def _hv_check_notifications(self):
        db = self.app.db
        try:
            updates = db.get_unnotified_hv_updates(self.app.current_patient.patient_id)
        except Exception:
            return
        for a in updates:
            db.mark_hv_notified(a["hv_appointment_id"], a["status"])   # mark first -> never shown twice
            st = a["status"]
            if st == ST_ACCEPTED:
                messagebox.showinfo("Home Visit Accepted", accepted_message(a))
            elif st == ST_DECLINED:
                messagebox.showwarning("Home Visit Declined", declined_message(a))
            elif st == ST_ON_WAY:
                messagebox.showinfo("Doctor On The Way", f"🚗 Dr. {a['doctor_name']} is on the way to your home.")
            elif st == ST_ARRIVED:
                messagebox.showinfo("Doctor Arrived", f"🏠 Dr. {a['doctor_name']} has arrived at your address.")
            elif st == ST_DONE:
                messagebox.showinfo("Visit Completed", "✅ Your Home Visit is complete. Get well soon!")
            elif st == ST_CANCELLED:
                messagebox.showinfo("Home Visit Closed", "Your Home Visit request expired because the doctor "
                                                          "did not respond in time. Any online payment will be "
                                                          "refunded.")

    def _hv_start_polling(self):
        state = {"job": None}

        def stop(event=None):
            if state["job"] is not None:
                try:
                    self.after_cancel(state["job"])
                except Exception:
                    pass
                state["job"] = None

        def tick():
            state["job"] = None
            try:
                if not self.winfo_exists():
                    return
                self._hv_refresh_my()
                self._hv_check_notifications()
                state["job"] = self.after(8000, tick)
            except tk.TclError:
                return
        try:
            self.bind("<Destroy>", stop, add="+")
            state["job"] = self.after(900, tick)
        except tk.TclError:
            pass


# ==========================================================
# ADMIN SIDE  (Branch Management, Home Visit Doctors, Monitoring)
# ==========================================================
class HomeVisitAdminMixin:
    """Mixed into AdminPortalFrame (see app.py)."""

    def _build_homevisit_admin_tab(self, tab):
        self.hv_admin_tabs = ctk.CTkTabview(tab, fg_color=CARD_LIGHT, segmented_button_selected_color=NAVY,
                                            segmented_button_selected_hover_color=NAVY_DARK)
        self.hv_admin_tabs.pack(fill="both", expand=True, padx=6, pady=6)
        for name in ("📍 Branch Management", "🩺 Home Visit Doctors", "🚑 Monitoring"):
            self.hv_admin_tabs.add(name)
        self._build_hvb_tab(self.hv_admin_tabs.tab("📍 Branch Management"))
        self._build_hvd_tab(self.hv_admin_tabs.tab("🩺 Home Visit Doctors"))
        self._build_hvm_tab(self.hv_admin_tabs.tab("🚑 Monitoring"))
        self.hv_admin_tabs.set("📍 Branch Management")

    def _hv_branches_changed(self):
        # keep every branch drop-down / list in the Admin Portal in sync
        for fn in ("_refresh_branches_list", "_refresh_doctor_branch_menu", "_refresh_staff_branch_menu",
                   "_hvb_refresh_list", "_hvd_refresh_branch_menu", "_hvd_refresh_list"):
            try:
                getattr(self, fn)()
            except Exception:
                pass

    # ---------------------------------------------------------------- Branch Management
    def _build_hvb_tab(self, tab):
        self._hvb_editing = None
        form = card(tab)
        form.pack(fill="x", padx=10, pady=(10, 6))
        self.hvb_title = ctk.CTkLabel(form, text="Add / Edit SRM Branch", font=ctk.CTkFont(weight="bold"),
                                      text_color=TEAL_TXT)
        self.hvb_title.pack(anchor="w", padx=14, pady=(10, 4))
        r1 = ctk.CTkFrame(form, fg_color="transparent")
        r1.pack(fill="x", padx=14)
        self.hvb_name = ctk.CTkEntry(r1, placeholder_text="Branch name (e.g. SRM Hospital - Madurai)", width=300,
                                     height=34)
        self.hvb_name.pack(side="left", padx=(0, 6))
        self.hvb_lat = ctk.CTkEntry(r1, placeholder_text="Latitude", width=110, height=34)
        self.hvb_lat.pack(side="left", padx=3)
        self.hvb_lon = ctk.CTkEntry(r1, placeholder_text="Longitude", width=110, height=34)
        self.hvb_lon.pack(side="left", padx=3)
        self.hvb_radius = ctk.CTkEntry(r1, placeholder_text="Radius km", width=90, height=34)
        self.hvb_radius.pack(side="left", padx=3)
        self.hvb_radius.insert(0, "15")
        self.hvb_switch = ctk.CTkSwitch(r1, text="Home Visit enabled")
        self.hvb_switch.pack(side="left", padx=12)
        r2 = ctk.CTkFrame(form, fg_color="transparent")
        r2.pack(fill="x", padx=14, pady=(8, 0))
        self.hvb_addr = ctk.CTkEntry(r2, placeholder_text="Branch street address (optional - used to look up "
                                                          "coordinates)", width=420, height=34)
        self.hvb_addr.pack(side="left", padx=(0, 6))
        ghost_button(r2, "🔎 Find coordinates", self._hvb_lookup, width=140).pack(side="left", padx=3)
        ghost_button(r2, "📍 Use my location", self._hvb_detect, width=140).pack(side="left", padx=3)
        r3 = ctk.CTkFrame(form, fg_color="transparent")
        r3.pack(fill="x", padx=14, pady=(8, 4))
        gold_button(r3, "💾 Save Branch", self._hvb_save, width=150, height=34).pack(side="left")
        ghost_button(r3, "Clear / New", self._hvb_reset, width=110).pack(side="left", padx=8)
        self.hvb_msg = ctk.CTkLabel(form, text="Tip: the patient's location is compared with these coordinates "
                                               "using the Haversine formula.", text_color=MUTED,
                                    font=ctk.CTkFont(size=11), wraplength=900, justify="left")
        self.hvb_msg.pack(anchor="w", padx=14, pady=(0, 10))
        ctk.CTkLabel(tab, text="SRM Branches", font=ctk.CTkFont(weight="bold"), text_color=TEAL_TXT
                     ).pack(anchor="w", padx=14)
        self.hvb_list = ctk.CTkScrollableFrame(tab, fg_color="transparent")
        self.hvb_list.pack(fill="both", expand=True, padx=10, pady=(4, 10))
        self._hvb_refresh_list()

    def _hvb_say(self, text, color=None):
        color = color or MUTED
        self.hvb_msg.configure(text=text, text_color=color)

    def _hvb_reset(self):
        self._hvb_editing = None
        self.hvb_title.configure(text="Add / Edit SRM Branch")
        for e in (self.hvb_name, self.hvb_lat, self.hvb_lon, self.hvb_addr):
            e.delete(0, "end")
        self.hvb_radius.delete(0, "end")
        self.hvb_radius.insert(0, "15")
        self.hvb_switch.deselect()

    def _hvb_load(self, b):
        self._hvb_reset()
        self._hvb_editing = b["branch_id"]
        self.hvb_title.configure(text=f"Editing: {b['branch_name']}")
        self.hvb_name.insert(0, b["branch_name"])
        if b["latitude"] is not None:
            self.hvb_lat.insert(0, f"{b['latitude']:.6f}")
            self.hvb_lon.insert(0, f"{b['longitude']:.6f}")
        self.hvb_radius.delete(0, "end")
        self.hvb_radius.insert(0, f"{b['hv_radius_km']:g}")
        (self.hvb_switch.select if b["hv_enabled"] else self.hvb_switch.deselect)()

    def _hvb_save(self):
        ok, msg = self.app.db.save_branch(self._hvb_editing, self.hvb_name.get(), self.hvb_lat.get().strip(),
                                          self.hvb_lon.get().strip(), self.hvb_radius.get().strip(),
                                          bool(self.hvb_switch.get()))
        if ok:
            self._hvb_say(msg, SUCCESS)
            self._hvb_reset()
            self._hv_branches_changed()
        else:
            self._hvb_say(msg, DANGER)

    def _hvb_lookup(self):
        text = self.hvb_addr.get().strip() or self.hvb_name.get().strip()
        self._hvb_say("⏳ Looking up coordinates...", GOLD_HOVER)

        def done(res, err):
            if err is not None:
                self._hvb_say(str(err) if isinstance(err, geo.LocationError) else "Lookup failed.", DANGER)
                return
            self.hvb_lat.delete(0, "end")
            self.hvb_lon.delete(0, "end")
            self.hvb_lat.insert(0, f"{res['lat']:.6f}")
            self.hvb_lon.insert(0, f"{res['lon']:.6f}")
            self._hvb_say(f"Found: {res['display']}  - please check the pin is correct.", SUCCESS)
        run_in_background(self, lambda: geo.geocode_address(text), done)

    def _hvb_detect(self):
        self._hvb_say("⏳ Detecting this computer's location...", GOLD_HOVER)

        def done(res, err):
            if err is not None:
                self._hvb_say(str(err) if isinstance(err, geo.LocationError) else "Detection failed.", DANGER)
                return
            self.hvb_lat.delete(0, "end")
            self.hvb_lon.delete(0, "end")
            self.hvb_lat.insert(0, f"{res['lat']:.6f}")
            self.hvb_lon.insert(0, f"{res['lon']:.6f}")
            self._hvb_say("Filled from this computer's position" +
                          (" (approximate - use 'Find coordinates' with the street address for accuracy)."
                           if res["approximate"] else "."), SUCCESS if not res["approximate"] else WARN)
        run_in_background(self, geo.detect_current_location, done)

    def _hvb_refresh_list(self):
        for w in self.hvb_list.winfo_children():
            w.destroy()
        branches = self.app.db.get_branches_full(include_inactive=True)
        if not branches:
            ctk.CTkLabel(self.hvb_list, text="No branches yet.", text_color=MUTED).pack(pady=10)
        for b in branches:
            row = card(self.hvb_list)
            row.pack(fill="x", pady=4)
            info = ctk.CTkFrame(row, fg_color="transparent")
            info.pack(side="left", padx=14, pady=8, fill="x", expand=True)
            ctk.CTkLabel(info, text=f"🏢  {b['branch_name']}" + ("" if b["is_active"] else "   (deactivated)"),
                         font=ctk.CTkFont(weight="bold"),
                         text_color=TEXT if b["is_active"] else MUTED).pack(anchor="w")
            if b["latitude"] is None:
                coords = "⚠ coordinates not set - Home Visit cannot use this branch"
            else:
                coords = (f"📍 {b['latitude']:.5f}, {b['longitude']:.5f}   ·   radius {b['hv_radius_km']:g} km")
            ctk.CTkLabel(info, text=coords, text_color=SOFT if b["latitude"] is not None else WARN,
                         font=ctk.CTkFont(size=11)).pack(anchor="w")
            status_pill(row, "Home Visit ON" if b["hv_enabled"] else "Home Visit OFF",
                        SUCCESS if b["hv_enabled"] else MUTED).pack(side="left", padx=8)
            ctk.CTkButton(row, text="Deactivate" if b["is_active"] else "Activate", width=100,
                          fg_color="transparent", text_color=DANGER if b["is_active"] else SUCCESS,
                          border_width=1, border_color=DANGER if b["is_active"] else SUCCESS,
                          hover_color="#1c2a22",
                          command=lambda x=b: self._hvb_toggle_active(x)).pack(side="right", padx=(4, 12))
            ghost_button(row, "✏️ Edit", lambda x=b: self._hvb_load(x), width=80).pack(side="right", padx=4)

    def _hvb_toggle_active(self, b):
        if b["is_active"] and not messagebox.askyesno(
                "Deactivate branch", f"Deactivate '{b['branch_name']}'?\nPatients will no longer see it for "
                                     "booking. Existing appointments are kept."):
            return
        ok, msg = self.app.db.set_branch_active(b["branch_id"], not b["is_active"])
        (self._hvb_say(msg, SUCCESS) if ok else self._hvb_say(msg, DANGER))
        self._hv_branches_changed()

    # ---------------------------------------------------------------- Home Visit Doctors
    def _build_hvd_tab(self, tab):
        self._hvd_editing = None
        self._hvd_branch_map = {}
        scroll = ctk.CTkScrollableFrame(tab, fg_color="transparent")
        scroll.pack(fill="both", expand=True)
        form = card(scroll)
        form.pack(fill="x", padx=10, pady=(10, 6))
        self.hvd_title = ctk.CTkLabel(form, text="Add Home Visit Doctor", font=ctk.CTkFont(weight="bold"),
                                      text_color=TEAL_TXT)
        self.hvd_title.pack(anchor="w", padx=14, pady=(10, 4))

        def entry(parent, ph, w, show=None):
            e = ctk.CTkEntry(parent, placeholder_text=ph, width=w, height=34, show=show)
            e.pack(side="left", padx=3)
            return e
        r1 = ctk.CTkFrame(form, fg_color="transparent")
        r1.pack(fill="x", padx=11)
        self.hvd_code = entry(r1, "Doctor ID (login)", 130)
        self.hvd_name = entry(r1, "Doctor name", 200)
        self.hvd_spec = entry(r1, "Specialization", 170)
        self.hvd_phone = entry(r1, "Phone / contact", 150)
        self.hvd_pass = entry(r1, "Password", 130, show="*")
        r2 = ctk.CTkFrame(form, fg_color="transparent")
        r2.pack(fill="x", padx=11, pady=(6, 0))
        self.hvd_branch = ctk.CTkOptionMenu(r2, values=["(no branches)"], width=250, height=34, fg_color=NAVY,
                                            button_color=NAVY_DARK)
        self.hvd_branch.pack(side="left", padx=3)
        self.hvd_area = entry(r2, "Home Visit service area (e.g. Madurai city)", 270)
        self.hvd_cfee = entry(r2, "Consult fee ₹", 110)
        self.hvd_vfee = entry(r2, "Home Visit fee ₹", 120)
        r3 = ctk.CTkFrame(form, fg_color="transparent")
        r3.pack(fill="x", padx=14, pady=(8, 0))
        ctk.CTkLabel(r3, text="Working days:", text_color=SOFT).pack(side="left", padx=(0, 6))
        self.hvd_days = []
        for i, nm in enumerate(WEEKDAY_NAMES):
            var = tk.IntVar(value=1 if i < 6 else 0)
            ctk.CTkCheckBox(r3, text=nm, variable=var, width=58, checkbox_width=18, checkbox_height=18
                            ).pack(side="left", padx=2)
            self.hvd_days.append(var)
        ctk.CTkLabel(r3, text="  Hours:", text_color=SOFT).pack(side="left", padx=(10, 4))
        self.hvd_start = ctk.CTkOptionMenu(r3, values=HV_TIME_SLOTS, width=105, height=30, fg_color=NAVY,
                                           button_color=NAVY_DARK)
        self.hvd_start.pack(side="left")
        ctk.CTkLabel(r3, text=" to ").pack(side="left")
        self.hvd_end = ctk.CTkOptionMenu(r3, values=HV_TIME_SLOTS, width=105, height=30, fg_color=NAVY,
                                         button_color=NAVY_DARK)
        self.hvd_end.pack(side="left")
        self.hvd_end.set(HV_TIME_SLOTS[-1])
        self.hvd_avail = ctk.CTkSwitch(r3, text="Available")
        self.hvd_avail.pack(side="left", padx=14)
        self.hvd_avail.select()
        r4 = ctk.CTkFrame(form, fg_color="transparent")
        r4.pack(fill="x", padx=14, pady=(8, 4))
        gold_button(r4, "💾 Save Doctor", self._hvd_save, width=150, height=34).pack(side="left")
        ghost_button(r4, "Clear / New", self._hvd_reset, width=110).pack(side="left", padx=8)
        self.hvd_msg = ctk.CTkLabel(form, text="When editing, leave Password blank to keep the current one.",
                                    text_color=MUTED, font=ctk.CTkFont(size=11), wraplength=900, justify="left")
        self.hvd_msg.pack(anchor="w", padx=14, pady=(0, 10))
        ctk.CTkLabel(scroll, text="Home Visit Doctors (separate from hospital doctors)",
                     font=ctk.CTkFont(weight="bold"), text_color=TEAL_TXT).pack(anchor="w", padx=14)
        self.hvd_list = ctk.CTkFrame(scroll, fg_color="transparent")
        self.hvd_list.pack(fill="x", padx=10, pady=(4, 10))
        self._hvd_refresh_branch_menu()
        self._hvd_refresh_list()

    def _hvd_say(self, text, color=None):
        color = color or MUTED
        self.hvd_msg.configure(text=text, text_color=color)

    def _hvd_refresh_branch_menu(self):
        branches = self.app.db.get_branches_full(include_inactive=False)
        self._hvd_branch_map = {b["branch_name"]: b["branch_id"] for b in branches}
        names = list(self._hvd_branch_map) or ["(no branches)"]
        cur = self.hvd_branch.get()
        self.hvd_branch.configure(values=names)
        self.hvd_branch.set(cur if cur in names else names[0])

    def _hvd_reset(self):
        self._hvd_editing = None
        self.hvd_title.configure(text="Add Home Visit Doctor")
        for e in (self.hvd_code, self.hvd_name, self.hvd_spec, self.hvd_phone, self.hvd_pass, self.hvd_area,
                  self.hvd_cfee, self.hvd_vfee):
            e.delete(0, "end")
        for i, v in enumerate(self.hvd_days):
            v.set(1 if i < 6 else 0)
        self.hvd_start.set(HV_TIME_SLOTS[0])
        self.hvd_end.set(HV_TIME_SLOTS[-1])
        self.hvd_avail.select()

    def _hvd_load(self, d):
        self._hvd_reset()
        self._hvd_editing = d["hv_doctor_id"]
        self.hvd_title.configure(text=f"Editing: Dr. {d['name']}")
        for e, v in ((self.hvd_code, d["doctor_code"]), (self.hvd_name, d["name"]), (self.hvd_spec, d["specialization"]),
                     (self.hvd_phone, d["phone"]), (self.hvd_area, d["service_area"]),
                     (self.hvd_cfee, f"{d['consultation_fee']:g}"), (self.hvd_vfee, f"{d['visit_fee']:g}")):
            e.insert(0, v)
        for name, bid in self._hvd_branch_map.items():
            if bid == d["branch_id"]:
                self.hvd_branch.set(name)
        sched = self.app.db.get_hv_schedule(d["hv_doctor_id"])
        for i, v in enumerate(self.hvd_days):
            v.set(1 if i in sched else 0)
        if sched:
            first = next(iter(sched.values()))
            self.hvd_start.set(first[0])
            self.hvd_end.set(first[1])
        (self.hvd_avail.select if d["is_available"] else self.hvd_avail.deselect)()

    def _hvd_save(self):
        try:
            cfee = float(self.hvd_cfee.get().strip() or 0)
            vfee = float(self.hvd_vfee.get().strip() or 0)
        except ValueError:
            self._hvd_say("Fees must be numbers.", DANGER)
            return
        branch_id = self._hvd_branch_map.get(self.hvd_branch.get())
        days = [i for i, v in enumerate(self.hvd_days) if v.get()]
        args = (self.hvd_code.get().strip(), self.hvd_name.get(), self.hvd_spec.get(), self.hvd_phone.get(),
                branch_id, self.hvd_area.get(), cfee, vfee)
        kw = dict(weekdays=days, start=self.hvd_start.get(), end=self.hvd_end.get(),
                  is_available=bool(self.hvd_avail.get()))
        db = self.app.db
        if self._hvd_editing is None:
            ok, msg = db.add_hv_doctor(*args, self.hvd_pass.get(), **kw)
        else:
            ok, msg = db.update_hv_doctor(self._hvd_editing, *args, self.hvd_pass.get() or None, **kw)
        if ok:
            self._hvd_say(msg, SUCCESS)
            self._hvd_reset()
            self._hvd_refresh_list()
        else:
            self._hvd_say(msg, DANGER)

    def _hvd_refresh_list(self):
        for w in self.hvd_list.winfo_children():
            w.destroy()
        docs = self.app.db.get_hv_doctors()
        if not docs:
            ctk.CTkLabel(self.hvd_list, text="No Home Visit doctors added yet.", text_color=MUTED).pack(pady=10)
        for d in docs:
            state, label = self.app.db.hv_doctor_state(d)
            col = {"available": SUCCESS, "leave": DANGER, "unavailable": WARN, "disabled": MUTED}[state]
            row = card(self.hvd_list)
            row.pack(fill="x", pady=4)
            info = ctk.CTkFrame(row, fg_color="transparent")
            info.pack(side="left", padx=14, pady=8, fill="x", expand=True)
            ctk.CTkLabel(info, text=f"👨‍⚕️  Dr. {d['name']}   ({d['doctor_code']})",
                         font=ctk.CTkFont(weight="bold")).pack(anchor="w")
            ctk.CTkLabel(info, text=f"{d['specialization']}  ·  {d['branch_name']}  ·  area: "
                                    f"{d['service_area'] or '-'}  ·  📞 {d['phone']}", text_color=SOFT,
                         font=ctk.CTkFont(size=11)).pack(anchor="w")
            ctk.CTkLabel(info, text=f"Consult {money(d['consultation_fee'])}  +  Home Visit "
                                    f"{money(d['visit_fee'])}", text_color=GOLD_HOVER,
                         font=ctk.CTkFont(size=11)).pack(anchor="w")
            status_pill(row, label, col).pack(side="left", padx=8)
            ctk.CTkButton(row, text="Delete", width=70, fg_color="transparent", text_color=DANGER,
                          border_width=1, border_color=DANGER, hover_color="#2a1512",
                          command=lambda x=d: self._hvd_delete(x)).pack(side="right", padx=(4, 12))
            ghost_button(row, "✏️ Edit", lambda x=d: self._hvd_load(x), width=80).pack(side="right", padx=4)
            ghost_button(row, "Set Unavailable" if d["is_available"] else "Set Available",
                         lambda x=d: self._hvd_toggle(x), width=120).pack(side="right", padx=4)

    def _hvd_toggle(self, d):
        ok, msg = self.app.db.set_hv_doctor_availability(d["hv_doctor_id"], not d["is_available"])
        self._hvd_say(msg, SUCCESS if ok else DANGER)
        self._hvd_refresh_list()

    def _hvd_delete(self, d):
        if not messagebox.askyesno("Delete doctor", f"Remove Dr. {d['name']} from Home Visit doctors?"):
            return
        ok, msg = self.app.db.delete_hv_doctor(d["hv_doctor_id"])
        self._hvd_say(msg, SUCCESS if ok else DANGER)
        self._hvd_refresh_list()

    # ---------------------------------------------------------------- Monitoring
    def _build_hvm_tab(self, tab):
        self.hvm_stats = ctk.CTkFrame(tab, fg_color="transparent")
        self.hvm_stats.pack(fill="x", padx=10, pady=(10, 4))
        top = ctk.CTkFrame(tab, fg_color="transparent")
        top.pack(fill="x", padx=14)
        ctk.CTkLabel(top, text="All Home Visit appointments (newest first)", font=ctk.CTkFont(weight="bold"),
                     text_color=TEAL_TXT).pack(side="left")
        ghost_button(top, "⟳ Refresh", self._hvm_refresh, width=100).pack(side="right")
        self.hvm_list = ctk.CTkScrollableFrame(tab, fg_color="transparent")
        self.hvm_list.pack(fill="both", expand=True, padx=10, pady=(4, 10))
        self._hvm_refresh()

    def _hvm_refresh(self):
        db = self.app.db
        db.expire_stale_hv_requests()
        for w in self.hvm_stats.winfo_children():
            w.destroy()
        st = db.get_hv_stats()
        for i in range(4):
            self.hvm_stats.grid_columnconfigure(i, weight=1)
        for i, (icon, key, label, col) in enumerate((("🏠", "total", "Total Requests", TILE_BLUE),
                                                     ("⏳", "waiting", "Awaiting Doctor", TILE_ORANGE),
                                                     ("🚑", "in_progress", "In Progress", TILE_PURPLE),
                                                     ("✅", "completed", "Completed", TILE_GREEN))):
            stat_tile(self.hvm_stats, icon=icon, value=st[key], label=label, color=col
                      ).grid(row=0, column=i, sticky="ew", padx=5)
        for w in self.hvm_list.winfo_children():
            w.destroy()
        rows = db.get_all_hv_appointments(limit=100)
        if not rows:
            ctk.CTkLabel(self.hvm_list, text="No Home Visit bookings yet.", text_color=MUTED).pack(pady=14)
        for a in rows:
            c = card(self.hvm_list)
            c.pack(fill="x", pady=4)
            info = ctk.CTkFrame(c, fg_color="transparent")
            info.pack(side="left", padx=14, pady=8, fill="x", expand=True)
            ctk.CTkLabel(info, text=f"HV-{a['hv_appointment_id']:04d}   {a['patient_name']}  →  "
                                    f"Dr. {a['doctor_name']}", font=ctk.CTkFont(weight="bold")).pack(anchor="w")
            ctk.CTkLabel(info, text=f"{a['branch_name']}  ·  {fmt_date(a['appointment_date'])} "
                                    f"{a['appointment_time']}  ·  📍 {a['city'] or (a['address'] or '')[:40]}"
                                    + (f"  ·  {a['distance_km']:.1f} km" if a["distance_km"] is not None else ""),
                         text_color=SOFT, font=ctk.CTkFont(size=11)).pack(anchor="w")
            ctk.CTkLabel(info, text="💳 " + hv_payment_text(a), text_color=GOLD_HOVER,
                         font=ctk.CTkFont(size=11)).pack(anchor="w")
            status_pill(c, a["status"], status_color(a["status"])).pack(side="left", padx=8)
            if a["payment_status"] == "Paid - Unverified":
                gold_button(c, "Verify Payment", lambda i=a["hv_appointment_id"]: self._hvm_act(
                    self.app.db.verify_hv_payment, i), width=120, height=30).pack(side="right", padx=10)
            elif a["payment_status"] == "Refund Due":
                gold_button(c, "Mark Refunded", lambda i=a["hv_appointment_id"]: self._hvm_act(
                    self.app.db.mark_hv_refunded, i), width=120, height=30).pack(side="right", padx=10)

    def _hvm_act(self, fn, appt_id):
        ok, msg = fn(appt_id)
        if not ok:
            messagebox.showerror("Error", msg)
        self._hvm_refresh()


# ==========================================================
# HOME VISIT DOCTOR - login + dashboard
# ==========================================================
class HomeVisitDoctorLoginFrame(ctk.CTkFrame):
    def __init__(self, parent, app):
        super().__init__(parent, fg_color=BG_LIGHT)
        self.app = app
        self.pack(fill="both", expand=True)
        AmbientBackground(self)
        form = card(self, width=360, border_color=HV_ACCENT)
        form.place(relx=0.5, rely=0.5, anchor="center")
        ctk.CTkLabel(form, text="🏠", font=ctk.CTkFont(size=40)).pack(pady=(26, 0))
        ctk.CTkLabel(form, text="Home Visit Doctor Login", font=ctk.CTkFont(size=22, weight="bold"),
                     text_color=HV_ACCENT).pack(pady=(4, 4), padx=40)
        ctk.CTkLabel(form, text="Sign in with the Doctor ID given by the hospital", font=ctk.CTkFont(size=12),
                     text_color=MUTED).pack(pady=(0, 16))
        self.code = ctk.CTkEntry(form, placeholder_text="Doctor ID", width=280, height=38)
        self.code.pack(pady=8, padx=40)
        self.pw = ctk.CTkEntry(form, placeholder_text="Password", show="*", width=280, height=38)
        self.pw.pack(pady=8, padx=40)
        self.pw.bind("<Return>", lambda e: self.handle_login())
        ctk.CTkButton(form, text="Login", width=280, height=40, fg_color=HV_ACCENT, hover_color=HV_ACCENT_HOVER,
                      text_color=ON_GOLD, font=ctk.CTkFont(weight="bold"), command=self.handle_login
                      ).pack(pady=(18, 8), padx=40)
        ctk.CTkButton(form, text="← Back to Patient Login", width=280, fg_color="transparent",
                      text_color=TEAL_TXT, border_width=1, border_color=TEAL_BORDER,
                      command=self.app.show_login_frame).pack(pady=(4, 28), padx=40)
        self.code.focus_set()

    def handle_login(self):
        code, pw = self.code.get().strip(), self.pw.get()
        if not code or not pw:
            messagebox.showerror("Input Error", "Please enter your Doctor ID and password.")
            return
        try:
            doc = self.app.db.authenticate_hv_doctor(code, pw)
        except Exception as e:
            messagebox.showerror("Error", f"Something went wrong: {e}")
            return
        if not doc:
            messagebox.showerror("Login Failed", "Invalid Doctor ID or password (or the account is disabled).")
            return
        self.app.current_hv_doctor = doc
        self.app.welcome_then(f"WELCOME, DR. {doc['name'].upper()}", "Home Visit Doctor",
                              self.app.show_hv_doctor_dashboard_frame)


class DeclineDialog(ctk.CTkToplevel):
    REASONS = ("Not available", "Too far", "Schedule conflict", "Other")

    def __init__(self, app, patient_name, on_submit):
        super().__init__(app)
        self.on_submit = on_submit
        self.title("Decline Home Visit")
        self.geometry("400x400")
        self.resizable(False, False)
        self.configure(fg_color=BG_LIGHT)
        try:
            self.transient(app)
            self.after(150, lambda: self.winfo_exists() and self.grab_set())
        except tk.TclError:
            pass
        ctk.CTkLabel(self, text="❌ Decline this request?", font=ctk.CTkFont(size=18, weight="bold"),
                     text_color=DANGER).pack(pady=(20, 2))
        ctk.CTkLabel(self, text=f"Patient: {patient_name}", text_color=MUTED).pack()
        ctk.CTkLabel(self, text="Select a reason:", text_color=SOFT).pack(anchor="w", padx=30, pady=(14, 4))
        self.var = tk.StringVar(value=self.REASONS[0])
        for r in self.REASONS:
            ctk.CTkRadioButton(self, text=r, variable=self.var, value=r, command=self._toggle,
                               fg_color=DANGER, hover_color=DANGER).pack(anchor="w", padx=34, pady=3)
        self.other = ctk.CTkEntry(self, placeholder_text="Type your reason", width=320, height=34)
        self.msg = ctk.CTkLabel(self, text="", text_color=DANGER, font=ctk.CTkFont(size=11))
        self.msg.pack(pady=(6, 0))
        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(side="bottom", pady=18)
        ctk.CTkButton(row, text="Decline Request", width=150, fg_color=DANGER, hover_color="#a03328",
                      font=ctk.CTkFont(weight="bold"), command=self._submit).pack(side="left", padx=6)
        ghost_button(row, "Keep Request", self.destroy, width=120).pack(side="left", padx=6)

    def _toggle(self):
        if self.var.get() == "Other":
            self.other.pack(before=self.msg, pady=(6, 0))
            self.other.focus_set()
        else:
            self.other.pack_forget()

    def _submit(self):
        reason = self.var.get()
        if reason == "Other":
            reason = self.other.get().strip()
            if len(reason) < 3:
                self.msg.configure(text="Please type your reason.")
                return
        cb, self.on_submit = self.on_submit, None
        self.destroy()
        if cb:
            cb(reason)


class LeaveDialog(ctk.CTkToplevel):
    """Mark as On Leave: Today / Tomorrow / Specific date / Date range"""

    def __init__(self, app, on_submit):
        super().__init__(app)
        self.on_submit = on_submit
        self.title("Mark as On Leave")
        self.geometry("420x460")
        self.resizable(False, False)
        self.configure(fg_color=BG_LIGHT)
        try:
            self.transient(app)
            self.after(150, lambda: self.winfo_exists() and self.grab_set())
        except tk.TclError:
            pass
        ctk.CTkLabel(self, text="🔴 Mark as On Leave", font=ctk.CTkFont(size=18, weight="bold"),
                     text_color=DANGER).pack(pady=(20, 8))
        self.var = tk.StringVar(value="today")
        for text, val in (("Today", "today"), ("Tomorrow", "tomorrow"), ("Specific date", "date"),
                          ("Date range", "range")):
            ctk.CTkRadioButton(self, text=text, variable=self.var, value=val, command=self._toggle,
                               fg_color=HV_ACCENT, hover_color=HV_ACCENT_HOVER).pack(anchor="w", padx=40, pady=4)
        self.fields = ctk.CTkFrame(self, fg_color="transparent")
        self.fields.pack(fill="x", padx=40, pady=(8, 0))
        self.from_lbl = ctk.CTkLabel(self.fields, text="Leave From (DD/MM/YYYY)", text_color=SOFT)
        self.from_e = ctk.CTkEntry(self.fields, placeholder_text="e.g. 12/10/2026", width=220, height=34)
        self.to_lbl = ctk.CTkLabel(self.fields, text="Leave To (DD/MM/YYYY)", text_color=SOFT)
        self.to_e = ctk.CTkEntry(self.fields, placeholder_text="e.g. 15/10/2026", width=220, height=34)
        self.msg = ctk.CTkLabel(self, text="", text_color=DANGER, wraplength=340, font=ctk.CTkFont(size=11))
        self.msg.pack(pady=(8, 0))
        ctk.CTkLabel(self, text="While on leave you will not receive new Home Visit bookings. Existing visits "
                                "stay visible. You become Available again automatically after the last day.",
                     text_color=MUTED, wraplength=340, justify="left", font=ctk.CTkFont(size=11)
                     ).pack(padx=40, pady=(6, 0))
        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(side="bottom", pady=16)
        ctk.CTkButton(row, text="Confirm Leave", width=140, fg_color=DANGER, hover_color="#a03328",
                      font=ctk.CTkFont(weight="bold"), command=self._submit).pack(side="left", padx=6)
        ghost_button(row, "Cancel", self.destroy, width=100).pack(side="left", padx=6)

    def _toggle(self):
        for w in (self.from_lbl, self.from_e, self.to_lbl, self.to_e):
            w.pack_forget()
        mode = self.var.get()
        if mode in ("date", "range"):
            self.from_lbl.configure(text="Leave From (DD/MM/YYYY)" if mode == "range" else "Date (DD/MM/YYYY)")
            self.from_lbl.pack(anchor="w")
            self.from_e.pack(anchor="w", pady=(0, 6))
        if mode == "range":
            self.to_lbl.pack(anchor="w")
            self.to_e.pack(anchor="w")

    def _submit(self):
        today = datetime.now().date()
        mode = self.var.get()
        try:
            if mode == "today":
                a = b = today
            elif mode == "tomorrow":
                a = b = today + timedelta(days=1)
            elif mode == "date":
                a = b = _DateField.parse(self.from_e.get())
            else:
                a, b = _DateField.parse(self.from_e.get()), _DateField.parse(self.to_e.get())
        except ValueError:
            self.msg.configure(text="Please enter dates as DD/MM/YYYY, e.g. 12/10/2026.")
            return
        if a < today:
            self.msg.configure(text="The leave start date cannot be in the past.")
            return
        if b < a:
            self.msg.configure(text="'Leave To' cannot be before 'Leave From'.")
            return
        cb, self.on_submit = self.on_submit, None
        self.destroy()
        if cb:
            cb(a.strftime("%Y-%m-%d"), b.strftime("%Y-%m-%d"))


class HomeVisitDoctorDashboard(ctk.CTkFrame):
    """Separate dashboard: amber accent + left sidebar, so it never looks like the patient screen."""

    NAV = (("requests", "📋  Today's Requests"), ("schedule", "🗓  My Schedule"),
           ("leave", "🟢  Availability & Leave"), ("history", "🗂  History"))

    def __init__(self, parent, app):
        super().__init__(parent, fg_color=BG_LIGHT)
        self.app = app
        self.doc_id = app.current_hv_doctor["hv_doctor_id"]
        self.pack(fill="both", expand=True)
        self.db = app.db
        self.db.expire_stale_hv_requests()
        self.doc = self.db.get_hv_doctor(self.doc_id) or app.current_hv_doctor

        # ---- header
        header = ctk.CTkFrame(self, fg_color=HV_HEADER, corner_radius=0, height=72)
        header.pack(fill="x")
        header.pack_propagate(False)
        ctk.CTkFrame(self, fg_color=HV_ACCENT, height=2, corner_radius=0).pack(fill="x")
        ctk.CTkLabel(header, text="🏠", font=ctk.CTkFont(size=30)).pack(side="left", padx=(22, 8))
        left = ctk.CTkFrame(header, fg_color="transparent")
        left.pack(side="left")
        ctk.CTkLabel(left, text="HOME VISIT DOCTOR DASHBOARD", font=ctk.CTkFont(size=18, weight="bold"),
                     text_color=HV_ACCENT).pack(anchor="w", pady=(12, 0))
        self.sub_lbl = ctk.CTkLabel(left, text="", text_color=SOFT, font=ctk.CTkFont(size=12))
        self.sub_lbl.pack(anchor="w")
        right = ctk.CTkFrame(header, fg_color="transparent")
        right.pack(side="right", padx=22)
        ctk.CTkButton(right, text="Logout", width=100, fg_color=HV_ACCENT, hover_color=HV_ACCENT_HOVER,
                      text_color=ON_GOLD, command=self.app.hv_doctor_logout).pack(side="right", pady=18)
        self.state_pill = ctk.CTkLabel(right, text="", corner_radius=12, text_color="white",
                                       font=ctk.CTkFont(size=12, weight="bold"))
        self.state_pill.pack(side="right", padx=14, pady=20)

        # ---- sidebar + panel area
        body = ctk.CTkFrame(self, fg_color=BG_LIGHT)
        body.pack(fill="both", expand=True)
        side = ctk.CTkFrame(body, fg_color=HV_SIDEBAR, corner_radius=0, width=230)
        side.pack(side="left", fill="y")
        side.pack_propagate(False)
        ctk.CTkLabel(side, text="MENU", text_color=MUTED, font=ctk.CTkFont(size=10, weight="bold")
                     ).pack(anchor="w", padx=20, pady=(20, 6))
        self.nav_buttons = {}
        for key, label in self.NAV:
            b = ctk.CTkButton(side, text=label, anchor="w", height=42, corner_radius=10, fg_color="transparent",
                              hover_color="#2a1c0e", text_color=TEXT, font=ctk.CTkFont(size=13),
                              command=lambda k=key: self.show_panel(k))
            b.pack(fill="x", padx=12, pady=3)
            self.nav_buttons[key] = b
        self.side_note = ctk.CTkLabel(side, text="", text_color=MUTED, font=ctk.CTkFont(size=11), wraplength=190,
                                      justify="left")
        self.side_note.pack(side="bottom", anchor="w", padx=20, pady=20)
        self.area = ctk.CTkFrame(body, fg_color=BG_LIGHT)
        self.area.pack(side="left", fill="both", expand=True, padx=18, pady=14)

        self._panel = None
        self._sig = None
        self._refresh_header()
        self.show_panel("requests")
        self._start_polling()

    # ---------------------------------------------------------------- shell helpers
    def _refresh_header(self):
        self.doc = self.db.get_hv_doctor(self.doc_id) or self.doc
        d = self.doc
        self.sub_lbl.configure(text=f"Dr. {d['name']}   ·   {d['specialization']}   ·   {d['branch_name']}   "
                                    f"·   ID {d['doctor_code']}")
        state, label = self.db.hv_doctor_state(d)
        color = {"available": SUCCESS, "leave": DANGER, "unavailable": WARN, "disabled": MUTED}[state]
        icon = "🟢" if state == "available" else "🔴"
        self.state_pill.configure(text=f"  {icon} {label.upper() if state != 'available' else 'AVAILABLE'}  ",
                                  fg_color=color)
        self.side_note.configure(text="You are visible to patients." if state == "available" else
                                 "You are NOT shown to patients for new bookings.")

    def show_panel(self, key):
        self._panel = key
        for k, b in self.nav_buttons.items():
            b.configure(fg_color=HV_ACCENT if k == key else "transparent",
                        text_color=ON_GOLD if k == key else TEXT)
        for w in self.area.winfo_children():
            w.destroy()
        self._sig = self._signature()
        {"requests": self._panel_requests, "schedule": self._panel_schedule,
         "leave": self._panel_leave, "history": self._panel_history}[key]()

    def _signature(self):
        rows = self.db.get_hv_requests_for_doctor(self.doc_id, "today") + \
            self.db.get_hv_requests_for_doctor(self.doc_id, "upcoming")
        return tuple((r["hv_appointment_id"], r["status"], r["payment_status"]) for r in rows)

    def _start_polling(self):
        state = {"job": None}

        def stop(event=None):
            if state["job"] is not None:
                try:
                    self.after_cancel(state["job"])
                except Exception:
                    pass
                state["job"] = None

        def tick():
            state["job"] = None
            try:
                if not self.winfo_exists():
                    return
                self.db.expire_stale_hv_requests()
                self._refresh_header()                  # also flips back to Available when leave ends
                sig = self._signature()
                if sig != self._sig and self._panel in ("requests", "schedule"):
                    self.show_panel(self._panel)       # new request arrived / status changed
                state["job"] = self.after(10000, tick)
            except tk.TclError:
                return
        try:
            self.bind("<Destroy>", stop, add="+")
            state["job"] = self.after(10000, tick)
        except tk.TclError:
            pass

    def _title(self, text, sub=None):
        ctk.CTkLabel(self.area, text=text, font=ctk.CTkFont(size=22, weight="bold"), text_color=HV_ACCENT
                     ).pack(anchor="w")
        if sub:
            ctk.CTkLabel(self.area, text=sub, text_color=MUTED).pack(anchor="w", pady=(0, 8))

    # ---------------------------------------------------------------- panel: requests
    def _panel_requests(self):
        today = self.db.get_hv_requests_for_doctor(self.doc_id, "today")
        upcoming = self.db.get_hv_requests_for_doctor(self.doc_id, "upcoming")
        self._title("📋 Today's Home Visit Requests", datetime.now().strftime("%A, %d %B %Y"))
        state, label = self.db.hv_doctor_state(self.doc)
        if state != "available":
            b = ctk.CTkFrame(self.area, fg_color="#33140f", corner_radius=10, border_width=1, border_color=DANGER)
            b.pack(fill="x", pady=(0, 8))
            ctk.CTkLabel(b, text=f"🔴 {label}. New Home Visit requests are not being assigned to you. "
                                 "Your existing visits below stay visible.", text_color=TEXT, wraplength=800,
                         justify="left").pack(anchor="w", padx=14, pady=10)
        stats = ctk.CTkFrame(self.area, fg_color="transparent")
        stats.pack(fill="x", pady=(0, 8))
        for i in range(4):
            stats.grid_columnconfigure(i, weight=1)
        n_wait = len([r for r in today + upcoming if r["status"] == ST_WAITING])
        n_prog = len([r for r in today if r["status"] in (ST_ACCEPTED, ST_ON_WAY, ST_ARRIVED)])
        n_done = len([r for r in today if r["status"] == ST_DONE])
        for i, (icon, val, lab, col) in enumerate((("📋", len(today), "Today's Visits", TILE_BLUE),
                                                   ("⏳", n_wait, "Awaiting Your Reply", TILE_ORANGE),
                                                   ("🚗", n_prog, "In Progress", TILE_PURPLE),
                                                   ("✅", n_done, "Completed Today", TILE_GREEN))):
            stat_tile(stats, icon=icon, value=val, label=lab, color=col).grid(row=0, column=i, sticky="ew", padx=5)

        scroll = ctk.CTkScrollableFrame(self.area, fg_color="transparent")
        scroll.pack(fill="both", expand=True)
        ctk.CTkLabel(scroll, text="TODAY", text_color=MUTED, font=ctk.CTkFont(size=11, weight="bold")
                     ).pack(anchor="w", padx=4, pady=(4, 2))
        if not today:
            ctk.CTkLabel(scroll, text="No Home Visit requests for today.", text_color=MUTED).pack(pady=10)
        for a in today:
            self._request_card(scroll, a)
        ctk.CTkLabel(scroll, text="UPCOMING REQUESTS", text_color=MUTED, font=ctk.CTkFont(size=11, weight="bold")
                     ).pack(anchor="w", padx=4, pady=(14, 2))
        if not upcoming:
            ctk.CTkLabel(scroll, text="No upcoming requests.", text_color=MUTED).pack(pady=10)
        for a in upcoming:
            self._request_card(scroll, a)

    def _request_card(self, parent, a):
        c = card(parent, border_color=BORDER)
        c.pack(fill="x", pady=6, padx=2)
        top = ctk.CTkFrame(c, fg_color="transparent")
        top.pack(fill="x", padx=16, pady=(14, 4))
        ctk.CTkLabel(top, text=f"HV-{a['hv_appointment_id']:04d}   👤 {a['patient_name']}  (Age {a['patient_age']})",
                     font=ctk.CTkFont(size=16, weight="bold")).pack(side="left")
        status_pill(top, a["status"], status_color(a["status"])).pack(side="right")

        grid = ctk.CTkFrame(c, fg_color="transparent")
        grid.pack(fill="x", padx=16)

        def line(icon_label, value, color=TEXT):
            r = ctk.CTkFrame(grid, fg_color="transparent")
            r.pack(fill="x", pady=1)
            ctk.CTkLabel(r, text=icon_label, text_color=MUTED, width=150, anchor="w",
                         font=ctk.CTkFont(size=12)).pack(side="left")
            ctk.CTkLabel(r, text=value, text_color=color, anchor="w", justify="left", wraplength=620,
                         font=ctk.CTkFont(size=12)).pack(side="left", fill="x", expand=True)
        line("📞 Patient contact", a["contact"] or "-")
        line("🏠 Home address", a["address"] or "-")
        if a["latitude"] is not None:
            r = ctk.CTkFrame(grid, fg_color="transparent")
            r.pack(fill="x", pady=1)
            ctk.CTkLabel(r, text="📍 Patient location", text_color=MUTED, width=150, anchor="w",
                         font=ctk.CTkFont(size=12)).pack(side="left")
            where = f"{a['latitude']:.5f}, {a['longitude']:.5f}"
            if a["distance_km"] is not None:
                where += f"   ({a['distance_km']:.1f} km from branch)"
            ctk.CTkLabel(r, text=where, font=ctk.CTkFont(size=12)).pack(side="left")
            ctk.CTkButton(r, text="🗺 Open Map", width=96, height=24, fg_color="transparent", text_color=TEAL_TXT,
                          border_width=1, border_color=TEAL_BORDER, hover_color="#0f2a31",
                          command=lambda x=a: webbrowser.open(
                              f"https://www.google.com/maps?q={x['latitude']},{x['longitude']}")
                          ).pack(side="left", padx=10)
        line("🏥 Assigned branch", a["branch_name"])
        line("📅 Requested date", fmt_date(a["appointment_date"], True))
        line("🕐 Requested time", a["appointment_time"])
        line("📝 Problem / reason", a["reason"] or "-", GOLD_HOVER)
        line("💰 Fees", f"Consultation {money(a['consultation_fee'])} + Home Visit {money(a['visit_fee'])} = "
                        f"{money(a['total_fee'])}")
        line("💳 Payment status", hv_payment_text(a), SUCCESS if a["payment_status"] == "Verified" else TEXT)

        btns = ctk.CTkFrame(c, fg_color="transparent")
        btns.pack(fill="x", padx=16, pady=(10, 14))
        st = a["status"]
        i = a["hv_appointment_id"]
        if st == ST_WAITING:
            ctk.CTkButton(btns, text="✅  ACCEPT", width=160, height=40, fg_color=SUCCESS, hover_color="#26b574",
                          font=ctk.CTkFont(weight="bold"), command=lambda: self._accept(i)).pack(side="left")
            ctk.CTkButton(btns, text="❌  DECLINE", width=160, height=40, fg_color=DANGER, hover_color="#e0564a",
                          font=ctk.CTkFont(weight="bold"),
                          command=lambda x=a: self._decline(x)).pack(side="left", padx=10)
        else:
            nxt = {ST_ACCEPTED: "🚗  Start Home Visit / On The Way", ST_ON_WAY: "🏠  Arrived",
                   ST_ARRIVED: "✅  Complete Visit"}.get(st)
            if nxt:
                gold_button(btns, nxt, lambda: self._advance(i, st), width=280, height=40).pack(side="left")
            elif st == ST_DONE:
                ctk.CTkLabel(btns, text="✔ Visit completed", text_color=SUCCESS,
                             font=ctk.CTkFont(weight="bold")).pack(side="left")
        hover_border(c, HV_ACCENT)

    def _accept(self, appt_id):
        ok, msg = self.db.hv_accept(appt_id, self.doc_id)
        if not ok:
            messagebox.showerror("Could not accept", msg)
        self.show_panel(self._panel)

    def _decline(self, a):
        def submit(reason):
            ok, msg = self.db.hv_decline(a["hv_appointment_id"], self.doc_id, reason)
            if not ok:
                messagebox.showerror("Could not decline", msg)
            self.show_panel(self._panel)
        DeclineDialog(self.app, a["patient_name"], submit)

    def _advance(self, appt_id, status):
        if status == ST_ARRIVED and not messagebox.askyesno(
                "Complete visit", "Mark this Home Visit as completed?\n(Cash visits are recorded as collected.)"):
            return
        ok, msg = self.db.hv_advance(appt_id, self.doc_id)
        if not ok:
            messagebox.showerror("Could not update", msg)
        self.show_panel(self._panel)

    # ---------------------------------------------------------------- panel: schedule
    def _panel_schedule(self):
        self._title("🗓 My Schedule", "Your working hours and confirmed visits")
        sched = self.db.get_hv_schedule(self.doc_id)
        c = card(self.area)
        c.pack(fill="x", pady=(0, 10))
        ctk.CTkLabel(c, text="Weekly working hours (set by the Admin)", font=ctk.CTkFont(weight="bold"),
                     text_color=TEAL_TXT).pack(anchor="w", padx=16, pady=(12, 6))
        row = ctk.CTkFrame(c, fg_color="transparent")
        row.pack(fill="x", padx=12, pady=(0, 12))
        for i, nm in enumerate(WEEKDAY_NAMES):
            cell = ctk.CTkFrame(row, fg_color=BG_LIGHT, corner_radius=10)
            cell.pack(side="left", padx=4, fill="x", expand=True)
            ctk.CTkLabel(cell, text=nm, font=ctk.CTkFont(weight="bold"),
                         text_color=HV_ACCENT if i in sched else MUTED).pack(pady=(8, 0))
            ctk.CTkLabel(cell, text=f"{sched[i][0]}\n{sched[i][1]}" if i in sched else "Off\n",
                         text_color=SOFT if i in sched else MUTED, font=ctk.CTkFont(size=10)).pack(pady=(0, 8))
        ctk.CTkLabel(self.area, text="Confirmed & upcoming visits", font=ctk.CTkFont(weight="bold"),
                     text_color=TEAL_TXT).pack(anchor="w")
        scroll = ctk.CTkScrollableFrame(self.area, fg_color="transparent")
        scroll.pack(fill="both", expand=True)
        today = datetime.now().strftime("%Y-%m-%d")
        rows = [r for r in self.db.get_hv_requests_for_doctor(self.doc_id, "today") +
                self.db.get_hv_requests_for_doctor(self.doc_id, "upcoming")
                if r["status"] in (ST_ACCEPTED, ST_ON_WAY, ST_ARRIVED)]
        if not rows:
            ctk.CTkLabel(scroll, text="No confirmed visits yet.", text_color=MUTED).pack(pady=14)
        last = None
        for r in rows:
            if r["appointment_date"] != last:
                last = r["appointment_date"]
                ctk.CTkLabel(scroll, text=("TODAY - " if last == today else "") + fmt_date(last, True).upper(),
                             text_color=MUTED, font=ctk.CTkFont(size=11, weight="bold")
                             ).pack(anchor="w", padx=4, pady=(10, 2))
            rc = card(scroll)
            rc.pack(fill="x", pady=3)
            ctk.CTkLabel(rc, text=f"🕐 {r['appointment_time']}   👤 {r['patient_name']}   ·   📍 "
                                  f"{(r['city'] or r['address'])[:60]}", anchor="w").pack(side="left", padx=14, pady=10)
            status_pill(rc, r["status"], status_color(r["status"])).pack(side="right", padx=12)

    # ---------------------------------------------------------------- panel: availability & leave
    def _panel_leave(self):
        self._title("🟢 Availability & Leave", "Control whether patients can book you for Home Visits")
        d = self.doc
        state, label = self.db.hv_doctor_state(d)
        leave = self.db.hv_leave_on(self.doc_id)
        c = card(self.area, border_color=SUCCESS if state == "available" else DANGER)
        c.pack(fill="x", pady=(0, 10))
        if state == "available":
            ctk.CTkLabel(c, text="🟢  AVAILABLE", font=ctk.CTkFont(size=26, weight="bold"), text_color=SUCCESS
                         ).pack(anchor="w", padx=20, pady=(16, 0))
            ctk.CTkLabel(c, text="Patients can book Home Visits with you.", text_color=SOFT
                         ).pack(anchor="w", padx=20, pady=(0, 14))
        elif state == "leave":
            until = datetime.strptime(leave["end"], "%Y-%m-%d").strftime("%d-%b-%Y")
            ctk.CTkLabel(c, text="🔴  ON LEAVE", font=ctk.CTkFont(size=26, weight="bold"), text_color=DANGER
                         ).pack(anchor="w", padx=20, pady=(16, 0))
            ctk.CTkLabel(c, text=f"Until {until}.  You become 🟢 Available automatically afterwards. New requests "
                                 "are not assigned to you; existing visits stay visible.", text_color=SOFT,
                         wraplength=760, justify="left").pack(anchor="w", padx=20, pady=(0, 14))
        else:
            ctk.CTkLabel(c, text=f"🔴  {label.upper()}", font=ctk.CTkFont(size=22, weight="bold"), text_color=WARN
                         ).pack(anchor="w", padx=20, pady=(16, 0))
            ctk.CTkLabel(c, text="The hospital admin has set you as unavailable - please contact the admin.",
                         text_color=SOFT).pack(anchor="w", padx=20, pady=(0, 14))
        row = ctk.CTkFrame(self.area, fg_color="transparent")
        row.pack(anchor="w", pady=(0, 10))
        ctk.CTkButton(row, text="🟢  Available", width=200, height=44, font=ctk.CTkFont(weight="bold"),
                      fg_color=SUCCESS if state == "available" else "transparent", hover_color="#26b574",
                      text_color="white" if state == "available" else SUCCESS, border_width=1, border_color=SUCCESS,
                      command=self._mark_available).pack(side="left", padx=(0, 10))
        ctk.CTkButton(row, text="🔴  Mark as On Leave", width=220, height=44, font=ctk.CTkFont(weight="bold"),
                      fg_color=DANGER if state == "leave" else "transparent", hover_color="#e0564a",
                      text_color="white" if state == "leave" else DANGER, border_width=1, border_color=DANGER,
                      command=self._mark_leave).pack(side="left")

        ctk.CTkLabel(self.area, text="Current & upcoming leave", font=ctk.CTkFont(weight="bold"),
                     text_color=TEAL_TXT).pack(anchor="w", pady=(10, 4))
        leaves = self.db.get_hv_leaves(self.doc_id)
        if not leaves:
            ctk.CTkLabel(self.area, text="No leave planned.", text_color=MUTED).pack(anchor="w")
        for l in leaves:
            lc = card(self.area)
            lc.pack(fill="x", pady=3)
            a, b = fmt_date(l["start_date"]), fmt_date(l["end_date"])
            ctk.CTkLabel(lc, text=f"🔴  {a}" + (f"   →   {b}" if a != b else ""), anchor="w"
                         ).pack(side="left", padx=14, pady=10)
            ctk.CTkButton(lc, text="Cancel leave", width=110, height=28, fg_color="transparent", text_color=DANGER,
                          border_width=1, border_color=DANGER, hover_color="#2a1512",
                          command=lambda x=l: self._cancel_leave(x)).pack(side="right", padx=12)

    def _mark_available(self):
        if not self.db.hv_leave_on(self.doc_id):
            if not self.doc.get("is_available", 1):
                messagebox.showinfo("Set by admin", "The admin has set your account to unavailable. "
                                                    "Please contact the admin to change this.")
            else:
                messagebox.showinfo("Already available", "You are already available for Home Visits.")
            return
        if messagebox.askyesno("End leave", "End your current leave and become Available now?"):
            ok, msg = self.db.end_hv_leave_now(self.doc_id)
            if not ok:
                messagebox.showerror("Error", msg)
            self._refresh_header()
            self.show_panel("leave")

    def _mark_leave(self):
        def submit(start, end):
            ok, msg, n = self.db.add_hv_leave(self.doc_id, start, end)
            if not ok:
                messagebox.showerror("Could not save leave", msg)
            elif n:
                messagebox.showwarning("Leave saved", f"Leave saved. You still have {n} existing Home Visit "
                                                      "request(s) in this period - they remain visible so you can "
                                                      "handle them (accept/decline or complete).")
            self._refresh_header()
            self.show_panel("leave")
        LeaveDialog(self.app, submit)

    def _cancel_leave(self, l):
        if messagebox.askyesno("Cancel leave", "Remove this leave period?"):
            self.db.cancel_hv_leave(l["leave_id"], self.doc_id)
            self._refresh_header()
            self.show_panel("leave")

    # ---------------------------------------------------------------- panel: history
    def _panel_history(self):
        self._title("🗂 History", "Completed, declined and cancelled Home Visits")
        scroll = ctk.CTkScrollableFrame(self.area, fg_color="transparent")
        scroll.pack(fill="both", expand=True)
        rows = self.db.get_hv_requests_for_doctor(self.doc_id, "history")
        if not rows:
            ctk.CTkLabel(scroll, text="Nothing here yet.", text_color=MUTED).pack(pady=14)
        for r in rows:
            c = card(scroll)
            c.pack(fill="x", pady=4)
            info = ctk.CTkFrame(c, fg_color="transparent")
            info.pack(side="left", padx=14, pady=8, fill="x", expand=True)
            ctk.CTkLabel(info, text=f"HV-{r['hv_appointment_id']:04d}   {r['patient_name']}   ·   "
                                    f"{fmt_date(r['appointment_date'])} {r['appointment_time']}",
                         font=ctk.CTkFont(weight="bold")).pack(anchor="w")
            extra = f"Reason declined: {r['decline_reason']}" if r["status"] == ST_DECLINED and \
                r["decline_reason"] else (r["reason"] or "")
            ctk.CTkLabel(info, text=f"{extra[:90]}   ·   {money(r['total_fee'])}", text_color=SOFT,
                         font=ctk.CTkFont(size=11)).pack(anchor="w")
            status_pill(c, r["status"], status_color(r["status"])).pack(side="right", padx=12)
