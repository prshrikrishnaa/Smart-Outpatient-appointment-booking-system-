"""
notify.py
Booking-confirmation messages (SMS / WhatsApp) sent to the patient's phone.

Uses only the Python standard library (urllib) - no extra pip packages.

How it works
------------
Option A - "WhatsApp (my number)"  (free, no account, no API key)
    Opens WhatsApp Web in the default browser with the patient's number and the
    message already filled in, waits for it to load, and presses Enter to send.
    Needs: WhatsApp Web already logged in (scan the QR once with the hospital
    phone) and, for the automatic Enter key,   pip install pyautogui
    Without pyautogui the chat still opens pre-filled and staff just press Send.
    The message is sent from the phone you linked to WhatsApp Web.

Option B - Twilio
Messages go out through Twilio (https://www.twilio.com), which can send both
SMS and WhatsApp. The Admin enters the Twilio credentials once in
Admin Portal > Payments > "Booking confirmation messages", then every new
booking sends a message to the patient's registered mobile number.

 - WhatsApp (Twilio): for testing use the Twilio WhatsApp *Sandbox*
   (From = +14155238886). Each phone must first send the sandbox "join <word>"
   message to that number. For real patients you need an approved WhatsApp
   Business sender + message template (Twilio / Meta rules).
 - SMS (Twilio): needs a Twilio phone number. Sending SMS to Indian numbers
   requires DLT registration (TRAI rule) - see Twilio's India SMS guidelines.

If sending fails (no internet, wrong credentials, ...) the booking is NOT
affected - the problem is only printed to the console.
"""

import base64
import json
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser

WEB_PROVIDER = "WhatsApp (my number)"
PROVIDERS = ["Off", WEB_PROVIDER, "WhatsApp (Twilio)", "SMS (Twilio)"]
_web_lock = threading.Lock()         # one WhatsApp Web message at a time
DEFAULT_COUNTRY_CODE = "91"          # India


def normalize_phone(raw, default_cc=DEFAULT_COUNTRY_CODE):
    """'93459 79867' / '09345979867' / '+919345979867' -> '+919345979867' (None if unusable)."""
    s = (raw or "").strip()
    digits = re.sub(r"\D", "", s)
    if not digits:
        return None
    if s.startswith("+"):
        return "+" + digits if 8 <= len(digits) <= 15 else None
    if len(digits) == 10:
        return "+" + default_cc + digits
    if len(digits) == 11 and digits.startswith("0"):
        return "+" + default_cc + digits[1:]
    if len(digits) == 12 and digits.startswith(default_cc):
        return "+" + digits
    return None


def opd_message(patient_name, doctor_label, department, branch_name, date_label,
                time_label, token_number, wait_minutes=None, payment_text=""):
    lines = [f"Smart OPD - appointment confirmed for {patient_name}.",
             f"{doctor_label} ({department}), {branch_name}",
             f"Date: {date_label}  Time: {time_label}",
             f"Token: {int(token_number):03d}"]
    if wait_minutes is not None:
        lines.append(f"Estimated wait: about {wait_minutes} min")
    if payment_text:
        lines.append(f"Payment: {payment_text}")
    lines.append("Please arrive a few minutes early.")
    return "\n".join(lines)


def home_visit_message(patient_name, doctor_label, specialization, date_label, time_label,
                       payment_text=""):
    lines = [f"Smart OPD - Home Visit request received for {patient_name}.",
             f"{doctor_label} ({specialization})",
             f"Date: {date_label}  Time: {time_label}",
             "The doctor will accept or decline - you will see the update in the app."]
    if payment_text:
        lines.append(f"Payment: {payment_text}")
    return "\n".join(lines)


def _twilio_post(sid, token, data):
    url = f"https://api.twilio.com/2010-04-01/Accounts/{urllib.parse.quote(sid)}/Messages.json"
    req = urllib.request.Request(url, data=urllib.parse.urlencode(data).encode("utf-8"), method="POST")
    auth = base64.b64encode(f"{sid}:{token}".encode("utf-8")).decode("ascii")
    req.add_header("Authorization", "Basic " + auth)
    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            body = json.loads(resp.read().decode("utf-8", "replace"))
            return True, body.get("status", "queued")
    except urllib.error.HTTPError as e:
        try:
            detail = json.loads(e.read().decode("utf-8", "replace")).get("message", "")
        except Exception:
            detail = ""
        return False, f"Twilio error {e.code}: {detail or e.reason}"
    except (urllib.error.URLError, OSError) as e:
        return False, f"Could not reach the message service ({e})."


def _get_pyautogui():
    """Imports pyautogui; if it is missing, installs it once automatically (needs internet)."""
    try:
        import pyautogui
        return pyautogui
    except ImportError:
        pass
    try:
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        subprocess.run([sys.executable, "-m", "pip", "install", "pyautogui"],
                       capture_output=True, timeout=240, creationflags=flags)
        import importlib
        importlib.invalidate_caches()
        import pyautogui
        return pyautogui
    except Exception as e:
        print("[notify] could not install pyautogui automatically:", e)
        return None


def _whatsapp_web(contact, text, wait_seconds):
    """Send through WhatsApp Web in the default browser (your own WhatsApp number)."""
    to = normalize_phone(contact)
    if not to:
        return False, f"'{contact}' is not a valid mobile number."
    url = ("https://web.whatsapp.com/send?phone=" + to.lstrip("+") +
           "&text=" + urllib.parse.quote(text) + "&app_absent=0")
    pyautogui = _get_pyautogui()
    with _web_lock:                        # two bookings at once must not fight over the browser
        try:
            webbrowser.open(url, new=2)
        except Exception as e:
            return False, f"Could not open the browser ({e})."
        if pyautogui is None:
            return False, ("Automatic sending needs the pyautogui library and it could not be installed. "
                           "Run in a terminal:  pip install pyautogui   (the chat was opened with the "
                           "message ready - press Send this time)")
        time.sleep(max(8, wait_seconds))   # let WhatsApp Web load the chat
        try:
            pyautogui.press("enter")       # sends the pre-filled message
            time.sleep(2)
            pyautogui.press("enter")       # safety: harmless if the first Enter already sent it
            time.sleep(3)
            pyautogui.hotkey("ctrl", "w")  # close the WhatsApp tab again
        except Exception as e:
            return False, f"Could not press Send automatically ({e})."
    return True, "sent via WhatsApp Web"


def send_message(db, contact, text):
    """Sends `text` to `contact` using the provider saved by the Admin. Returns (ok, info)."""
    provider = db.get_setting("notify_provider", "Off")
    if provider == "Off" or provider not in PROVIDERS:
        return False, "Messages are switched off."
    if provider == WEB_PROVIDER:
        try:
            wait = int(float(db.get_setting("notify_wait", "18")))
        except ValueError:
            wait = 18
        return _whatsapp_web(contact, text, wait)
    sid = db.get_setting("notify_sid", "").strip()
    token = db.get_setting("notify_token", "").strip()
    sender = db.get_setting("notify_from", "").strip()
    if not (sid and token and sender):
        return False, "Message settings are incomplete (Account SID, Auth Token and From number)."
    to = normalize_phone(contact)
    frm = normalize_phone(sender, default_cc="")
    if not to:
        return False, f"'{contact}' is not a valid mobile number."
    if not frm:
        return False, "The 'From' number must look like +14155238886."
    if provider.startswith("WhatsApp"):
        to, frm = "whatsapp:" + to, "whatsapp:" + frm
    return _twilio_post(sid, token, {"To": to, "From": frm, "Body": text})


def send_async(db, contact, text):
    """Fire-and-forget (own thread, so the window never freezes). Never raises."""
    def work():
        try:
            ok, info = send_message(db, contact, text)
            print("[notify]", "OK:" if ok else "NOT SENT:", info)
        except Exception as e:  # a notification problem must never break a booking
            print("[notify] unexpected error:", e)
    threading.Thread(target=work, daemon=True).start()
