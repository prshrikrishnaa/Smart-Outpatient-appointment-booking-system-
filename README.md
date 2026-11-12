# Smart OPD Appointment Booking System

> **Predict. Organize. Care.**

A desktop hospital outpatient (OPD) appointment system built with **Python, CustomTkinter and SQLite**. Patients book doctors across hospital branches and get a live queue position with a predicted waiting time. Staff and admins manage queues, payments and doctors. A **Home Visit** module lets patients request a doctor at their location, matched to the nearest eligible branch.

## Features

| Module | What it does | File |
|---|---|---|
| Cinematic intro | Animated movie-style opening and 3D-globe splash (click/key to skip) | `intro.py`, `opening_intro.py` |
| Patient portal | Register/login, book by branch → department → doctor → date/slot, track queue, cancel, download PDF slip | `app.py` |
| Queue management | Priority queue (Emergency → Senior Citizen → Normal), token numbers per doctor/day | `database.py` |
| Waiting-time prediction | `(patients ahead × doctor avg. consultation time) + live doctor delay` | `database.py` |
| Staff portal (RBAC) | Receptionist accounts scoped to one branch; call next patient, mark status, set doctor delay | `app.py` |
| Admin portal | Branches, doctors, staff, fees, payments verification, Home Visit settings (login `admin` / `0000`) | `app.py` |
| UPI QR payments | UPI deep-link QR, UTR reference entry, duplicate-reference blocking, manual Verify step | `payment.py` |
| PDF appointment slip | A5 slip with QR code, Unicode font support | `pdf_slip.py` |
| Booking notifications | WhatsApp Web (own number) or Twilio SMS/WhatsApp | `notify.py` |
| Home Visit (patient) | "Use current location" / typed address / coordinates → nearest eligible branch → doctor → slot → payment | `homevisit_ui.py`, `geo.py` |
| Home Visit (doctor) | Separate login; accept/decline, On the way → Arrived → Completed, schedule, leave | `homevisit_ui.py`, `homevisit_db.py` |
| OOP models | `Patient`, `Doctor`, `Appointment` (classes, constructors, encapsulation) | `models.py` |
| Security | SHA-256 hashed passwords, parameterised SQL queries | `database.py` |

## Project structure

```
smart-opd/
├── src/                    # all Python source code
│   ├── app.py              # entry point + main GUI
│   ├── database.py         # SQLite layer (OPD)
│   ├── homevisit_db.py     # SQLite layer (Home Visit)
│   ├── homevisit_ui.py     # Home Visit screens
│   ├── geo.py              # distance, location detection, geocoding
│   ├── models.py  payment.py  notify.py  pdf_slip.py
│   └── intro.py  opening_intro.py
├── database/
│   ├── schema.sql          # all tables and indexes
│   ├── seed.sql            # demo data (no real patient data)
│   └── load_sql.py         # builds the .db from the two scripts
├── screenshots/            # project output screenshots
├── requirements.txt
└── README.md
```

## Requirements

* Python 3.9 or newer (with `tkinter`; it is included in the standard Windows/macOS installers)
* Libraries in `requirements.txt`: `customtkinter`, `Pillow`, `numpy`, `qrcode[pil]`, `fpdf2`, and optionally `pyautogui`
* Internet is needed only for Home Visit location lookup, notifications and the optional `pyautogui` auto-install

## How to run

```bash
# 1. clone
git clone <your-repo-url>
cd smart-opd

# 2. (optional) virtual environment
python -m venv .venv
.venv\Scripts\activate          # Windows
source .venv/bin/activate       # macOS / Linux

# 3. install dependencies
pip install -r requirements.txt

# 4. create the database with demo data (optional - app.py also creates empty tables itself)
python database/load_sql.py

# 5. start the app (run from src/ so opd_system.db is found)
cd src
python app.py
```

Using the SQLite command line instead of step 4:

```bash
sqlite3 src/opd_system.db < database/schema.sql
sqlite3 src/opd_system.db < database/seed.sql
```

### Demo logins (from `seed.sql`)

| Role | Username | Password |
|---|---|---|
| Admin | `admin` | `0000` |
| Patient | `demo` | `demo123` |
| Receptionist (Trichy) | `reception` | `staff123` |
| Home Visit doctor | `HV001` | `doctor123` |

## Database

SQLite file `opd_system.db`. Tables: `patients`, `branches`, `doctors`, `staff`, `appointments`, `settings`, `hv_doctors`, `hv_schedule`, `hv_leave`, `hv_appointments`, `hv_status_history`. See `database/schema.sql`. A UPI reference number can be used only once across OPD and Home Visit bookings.

## Notes

* **Payments:** a plain UPI QR cannot confirm that money arrived, so bookings are saved as *Paid – Unverified* and staff press **Verify** after checking the bank/GPay history. Automatic confirmation needs a payment gateway.
* **Messages:** configure the provider in Admin Portal → Payments → *Booking confirmation messages*. A failed message never blocks a booking.
* **Home Visit setup:** an admin must set each branch's latitude/longitude, service radius and enable Home Visit before patients can use it.
* **Opening intro fonts:** drop an optional font at `assets/fonts/subtitle.ttf`; otherwise system fonts are used.

## Screenshots

See [`screenshots/`](screenshots/).

## Team

Shafir Ahamed J · Shri Krishnaa PR · Kailash R · Yogesh VS
