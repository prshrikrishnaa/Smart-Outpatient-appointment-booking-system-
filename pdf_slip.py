"""
pdf_slip.py
Generates a one-page printable appointment slip (PDF) with a QR code
encoding the token/doctor/date, so a patient can scan it at the counter
instead of reading the token number aloud.

Requires:  pip install fpdf2 qrcode[pil]
If either library is missing, generate_slip() raises ImportError with a
clear message — app.py catches this and tells the user what to install,
instead of crashing.

UNICODE FONT SUPPORT
---------------------
fpdf2's built-in fonts (Helvetica, Times, Courier) only cover the
Latin-1 character set. A patient name typed in Tamil/Hindi script, an
accented name (e.g. "Priyā", "Müller"), or a currency symbol like ₹
would either raise an encoding error or silently print as "?" boxes.

_find_unicode_font() looks for a Unicode TrueType font already present
on the machine (DejaVu Sans on Linux, Arial/Segoe UI on Windows, Arial
on macOS) and registers it with fpdf2 so the slip renders correctly no
matter what script the name is in. If no such font can be found, we
fall back to core Helvetica and sanitize the text instead of crashing,
so the slip still generates either way.
"""

import os
import platform
import tempfile


def _find_unicode_font(pdf):
    """
    Registers a Unicode TTF font (regular + bold + italic where available)
    under the family name "Body" and returns "Body". Returns None if no
    suitable font file could be found on this machine, meaning the caller
    should fall back to core Helvetica.
    """
    system = platform.system()

    # (regular, bold, italic) candidate paths per platform — first match wins.
    if system == "Windows":
        windir = os.environ.get("WINDIR", r"C:\Windows")
        fonts_dir = os.path.join(windir, "Fonts")
        font_sets = [
            ("arial.ttf", "arialbd.ttf", "ariali.ttf"),
            ("segoeui.ttf", "segoeuib.ttf", "segoeuii.ttf"),
            ("calibri.ttf", "calibrib.ttf", "calibrii.ttf"),
            ("tahoma.ttf", "tahomabd.ttf", "tahoma.ttf"),
        ]
        candidates = [tuple(os.path.join(fonts_dir, f) for f in trio) for trio in font_sets]
    elif system == "Darwin":
        candidates = [
            ("/System/Library/Fonts/Supplemental/Arial.ttf",
             "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
             "/System/Library/Fonts/Supplemental/Arial Italic.ttf"),
            ("/Library/Fonts/Arial Unicode.ttf",
             "/Library/Fonts/Arial Unicode.ttf",
             "/Library/Fonts/Arial Unicode.ttf"),
        ]
    else:  # Linux and everything else
        candidates = [
            ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
             "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
             "/usr/share/fonts/truetype/dejavu/DejaVuSans-Oblique.ttf"),
            ("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
             "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
             "/usr/share/fonts/truetype/liberation/LiberationSans-Italic.ttf"),
            ("/usr/share/fonts/noto/NotoSans-Regular.ttf",
             "/usr/share/fonts/noto/NotoSans-Bold.ttf",
             "/usr/share/fonts/noto/NotoSans-Italic.ttf"),
        ]

    for regular, bold, italic in candidates:
        if not os.path.exists(regular):
            continue
        try:
            pdf.add_font("Body", "", regular)
            pdf.add_font("Body", "B", bold if os.path.exists(bold) else regular)
            pdf.add_font("Body", "I", italic if os.path.exists(italic) else regular)
            return "Body"
        except Exception:
            continue  # this font file was unusable — try the next candidate

    return None  # nothing found — caller falls back to Helvetica


def generate_slip(output_path, *, patient_name, patient_age, token_number,
                   doctor_name, department, branch_name, appointment_date,
                   appointment_time, priority, wait_minutes=None, payment_text=None):
    try:
        from fpdf import FPDF
        import qrcode
    except ImportError as e:
        raise ImportError(
            "PDF slip needs two extra libraries. Install them with:\n"
            "    pip install fpdf2 qrcode[pil]"
        ) from e

    token_display = f"{token_number:03d}"

    # ---- 1. build the QR code as a temporary PNG ----
    qr_data = (f"OPD|Token:{token_display}|Doctor:{doctor_name}|"
               f"Date:{appointment_date}|Time:{appointment_time}")
    qr_img = qrcode.make(qr_data)
    qr_tmp_path = os.path.join(tempfile.gettempdir(), f"opd_qr_{token_display}.png")
    qr_img.save(qr_tmp_path)

    # ---- 2. lay out the PDF ----
    pdf = FPDF(format="A5")  # A5 — a real appointment slip, not a full A4 sheet
    pdf.add_page()
    pdf.set_auto_page_break(auto=False)

    # Pick a Unicode font if one is available on this machine; otherwise
    # fall back to core Helvetica and sanitize any text we set on it so
    # a non-Latin name can't crash the PDF generation.
    font = _find_unicode_font(pdf) or "Helvetica"
    using_fallback = (font == "Helvetica")

    def txt(value):
        # only needed for the Helvetica fallback, which is Latin-1 only —
        # replaces anything it can't render instead of raising/crashing
        s = str(value)
        if using_fallback:
            s = s.encode("latin-1", "replace").decode("latin-1")
        return s

    navy = (7, 38, 44)        # deep teal-black - matches the app theme
    gold = (216, 180, 98)
    gray = (91, 100, 114)

    # header band
    pdf.set_fill_color(*navy)
    pdf.rect(0, 0, 148, 24, style="F")
    pdf.set_text_color(255, 255, 255)
    pdf.set_font(font, "B", 15)
    pdf.set_xy(8, 6)
    pdf.cell(0, 8, txt("Smart OPD Appointment Booking System"), ln=1)
    pdf.set_font(font, "", 10)
    pdf.set_x(8)
    pdf.cell(0, 6, txt("Appointment Slip   |   Predict. Organize. Care."), ln=1)
    pdf.set_fill_color(*gold)
    pdf.rect(0, 24, 148, 1.2, style="F")   # gold hairline under the header band

    pdf.set_text_color(20, 20, 20)
    pdf.set_xy(8, 32)

    def field(label, value, size=12):
        pdf.set_font(font, "", 10)
        pdf.set_text_color(*gray)
        pdf.cell(0, 5, txt(label), ln=1)
        pdf.set_font(font, "B", size)
        pdf.set_text_color(20, 20, 20)
        pdf.cell(0, 7, txt(value), ln=1)
        pdf.ln(2)

    pdf.set_x(8)
    field("PATIENT", f"{patient_name}  (Age {patient_age})")
    pdf.set_x(8)
    field("DOCTOR", f"Dr. {doctor_name}  —  {department}")
    pdf.set_x(8)
    field("BRANCH", branch_name)
    pdf.set_x(8)
    field("DATE & TIME", f"{appointment_date}   {appointment_time}")
    pdf.set_x(8)
    field("PRIORITY", priority)

    if wait_minutes is not None:
        pdf.set_x(8)
        field("ESTIMATED WAIT (at booking time)", f"{wait_minutes} minutes")
    if payment_text:
        pdf.set_x(8)
        field("PAYMENT", payment_text)

    # token — the big, unmissable number
    pdf.set_xy(8, pdf.get_y() + 2)
    pdf.set_fill_color(*gold)
    pdf.rect(8, pdf.get_y(), 60, 20, style="F")
    pdf.set_xy(8, pdf.get_y() + 4)
    pdf.set_text_color(7, 38, 44)
    pdf.set_font(font, "B", 9)
    pdf.cell(60, 5, txt("TOKEN NUMBER"), align="C", ln=1)
    pdf.set_x(8)
    pdf.set_font(font, "B", 22)
    pdf.cell(60, 10, txt(token_display), align="C", ln=1)

    # QR code, top-right of the slip
    pdf.image(qr_tmp_path, x=105, y=90, w=35, h=35)
    pdf.set_xy(100, 126)
    pdf.set_text_color(*gray)
    pdf.set_font(font, "", 8)
    pdf.cell(45, 4, txt("Scan at the counter"), align="C")

    pdf.set_xy(8, 140)
    pdf.set_font(font, "I", 8)
    pdf.set_text_color(*gray)
    pdf.cell(0, 5, txt("Please arrive at the branch a few minutes before your estimated wait time."))

    pdf.output(output_path)

    try:
        os.remove(qr_tmp_path)
    except OSError:
        pass

    return output_path
