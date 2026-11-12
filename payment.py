"""
payment.py
UPI / GPay QR payment helpers for the booking flow.

How it works
------------
1. The patient picks a doctor/slot and presses "Confirm Booking".
2. app.py shows a payment window with a QR code built from a standard UPI
   deep link:  upi://pay?pa=<UPI ID>&pn=<name>&am=<amount>&cu=INR&tn=<note>
   Scanning it with GPay / PhonePe / Paytm / any UPI app opens the pay screen
   with the hospital's UPI ID and the amount already filled in.
3. The patient pays in their own app, then types the 12-digit UPI reference
   (UTR / "UPI transaction ID") shown on the success screen of their app.
4. The appointment is booked with the status "Paid - Unverified". Staff / admin
   open the Payments tab, compare the reference with the GPay history on the
   hospital phone, and press Verify.

IMPORTANT: a plain QR code cannot tell this app that money has arrived (there is
no callback). Automatic confirmation needs a payment gateway account
(Razorpay / Cashfree / PhonePe PG ...). The Verify step above is the safe
manual alternative.

Requires:  pip install "qrcode[pil]"
"""

import re
from urllib.parse import quote

DEFAULT_PAYEE = "Smart OPD Hospital"
DEFAULT_FEE = 200            # rupees - admin can change it in the Payments tab
# GPay number given for the hospital. A UPI ID is "number@bankhandle"; the handle
# (e.g. okaxis / oksbi / okhdfcbank / okicici / ybl) depends on the bank linked to
# GPay, so the admin completes it once in Admin Portal > Payments.
DEFAULT_UPI_ID = "9345979867@"

# Bank handles patients/admin can pick from to complete the UPI ID
COMMON_HANDLES = ["@okaxis", "@oksbi", "@okhdfcbank", "@okicici", "@ybl", "@ibl", "@paytm", "@axl"]

_UPI_RE = re.compile(r"[A-Za-z0-9._\-]{2,256}@[A-Za-z][A-Za-z0-9.\-]{1,64}")
_UTR_RE = re.compile(r"\d{12}")


def is_valid_upi_id(upi_id):
    return bool(_UPI_RE.fullmatch((upi_id or "").strip()))


def is_valid_utr(ref):
    return bool(_UTR_RE.fullmatch((ref or "").strip()))


def build_upi_uri(upi_id, payee, amount, note="OPD consultation"):
    note = re.sub(r"[^A-Za-z0-9 ._\-]", "", note)[:40] or "OPD"
    return "upi://pay?pa=%s&pn=%s&am=%.2f&cu=INR&tn=%s" % (
        quote(upi_id.strip(), safe="@._-"), quote(payee or DEFAULT_PAYEE), float(amount), quote(note))


def make_qr_image(data, px=240):
    """Returns a black-on-white PIL image (scanners need high contrast, so it is
    deliberately NOT themed). Raises ImportError with install instructions."""
    try:
        import qrcode
        from PIL import Image
    except ImportError as e:
        raise ImportError('QR payments need an extra library. Install it with:\n'
                          '    pip install "qrcode[pil]"') from e
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=10, border=3)
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
    return img.resize((px, px), Image.NEAREST)
