"""
database.py
All SQLite database operations for the Smart OPD Appointment Booking System.
Second Review build — adds queue management, waiting-time prediction,
doctor deletion, priority patients, appointment cancellation and
password hashing on top of the First Review core.

Each section below is clearly commented so you can explain it during
your review (e.g. "this part handles patient login", "this part handles
appointment booking").
"""

import sqlite3
from homevisit_db import HomeVisitDBMixin
import hashlib
from datetime import datetime

# priority levels used for sorting the live queue: lower number = seen first
PRIORITY_ORDER = {"Emergency": 0, "Senior Citizen": 1, "Normal": 2}


class Database(HomeVisitDBMixin):
    def __init__(self, db_name="opd_system.db"):
        self.db_name = db_name
        self._create_tables()
        self._migrate()  # safely adds new columns if opening an older database file
        self._create_home_visit_tables()  # Home Visit extension (safe on existing databases)

    def _connect(self):
        return sqlite3.connect(self.db_name)

    # ======================================================
    # PASSWORD HASHING
    # ======================================================
    @staticmethod
    def _hash_password(password):
        # SHA-256 hash so raw passwords are never stored in the database
        return hashlib.sha256(password.encode("utf-8")).hexdigest()

    # ======================================================
    # TABLE CREATION
    # ======================================================
    def _create_tables(self):
        try:
            conn = self._connect()
            cur = conn.cursor()

            # ---- PATIENTS TABLE ----
            cur.execute("""
                CREATE TABLE IF NOT EXISTS patients (
                    patient_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    age INTEGER NOT NULL,
                    gender TEXT NOT NULL,
                    contact TEXT NOT NULL,
                    username TEXT UNIQUE NOT NULL,
                    password TEXT NOT NULL
                )
            """)

            # ---- BRANCHES TABLE (added by Admin) ----
            cur.execute("""
                CREATE TABLE IF NOT EXISTS branches (
                    branch_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    branch_name TEXT NOT NULL UNIQUE
                )
            """)

            # ---- DOCTORS TABLE (added by Admin, linked to a branch + department) ----
            # delay_minutes is set live from Queue Control when a doctor is
            # running late, and feeds directly into estimate_waiting_time()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS doctors (
                    doctor_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    department TEXT NOT NULL,
                    branch_id INTEGER NOT NULL,
                    avg_consultation_minutes INTEGER NOT NULL DEFAULT 10,
                    delay_minutes INTEGER NOT NULL DEFAULT 0,
                    FOREIGN KEY (branch_id) REFERENCES branches (branch_id)
                )
            """)

            # ---- STAFF TABLE (receptionist accounts, added by Admin) ----
            # each staff account belongs to exactly one branch, and can only
            # see/manage that branch's queue — role-based access control
            cur.execute("""
                CREATE TABLE IF NOT EXISTS staff (
                    staff_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    password TEXT NOT NULL,
                    branch_id INTEGER NOT NULL,
                    FOREIGN KEY (branch_id) REFERENCES branches (branch_id)
                )
            """)

            # ---- APPOINTMENTS TABLE (created when patient books) ----
            cur.execute("""
                CREATE TABLE IF NOT EXISTS appointments (
                    appointment_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    patient_id INTEGER NOT NULL,
                    doctor_id INTEGER NOT NULL,
                    branch_id INTEGER NOT NULL,
                    token_number INTEGER NOT NULL,
                    status TEXT NOT NULL DEFAULT 'Waiting',
                    priority TEXT NOT NULL DEFAULT 'Normal',
                    appointment_date TEXT NOT NULL,
                    appointment_time TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (patient_id) REFERENCES patients (patient_id),
                    FOREIGN KEY (doctor_id) REFERENCES doctors (doctor_id),
                    FOREIGN KEY (branch_id) REFERENCES branches (branch_id)
                )
            """)

            conn.commit()
        except sqlite3.Error as e:
            print(f"[Database Error] Table creation failed: {e}")
        finally:
            conn.close()

    def _migrate(self):
        # if an older opd_system.db file (from the First Review) is reused,
        # add the new columns instead of crashing. Each ALTER is wrapped in
        # its own try/except because SQLite has no "ADD COLUMN IF NOT EXISTS".
        migrations = [
            "ALTER TABLE doctors ADD COLUMN avg_consultation_minutes INTEGER NOT NULL DEFAULT 10",
            "ALTER TABLE appointments ADD COLUMN priority TEXT NOT NULL DEFAULT 'Normal'",
            "ALTER TABLE doctors ADD COLUMN delay_minutes INTEGER NOT NULL DEFAULT 0",
            # OPD payments / UPI QR support
            "ALTER TABLE appointments ADD COLUMN payment_status TEXT NOT NULL DEFAULT 'Unpaid'",
            "ALTER TABLE appointments ADD COLUMN payment_method TEXT NOT NULL DEFAULT ''",
            "ALTER TABLE appointments ADD COLUMN payment_ref TEXT NOT NULL DEFAULT ''",
            "ALTER TABLE appointments ADD COLUMN amount_paid REAL NOT NULL DEFAULT 0",
            "CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
            # per-doctor consultation fee (NULL = use the default fee from Admin > Payments)
            "ALTER TABLE doctors ADD COLUMN consultation_fee REAL",
            # Prevent the same non-empty UPI reference from being attached to two OPD bookings.
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_appointments_payment_ref ON appointments(payment_ref) WHERE payment_ref <> ''",
        ]
        conn = self._connect()
        cur = conn.cursor()
        for sql in migrations:
            try:
                cur.execute(sql)
                conn.commit()
            except sqlite3.Error:
                pass  # column already exists — nothing to do
        conn.close()

    # ======================================================
    # PATIENT LOGIN / REGISTRATION
    # ======================================================
    def register_patient(self, name, age, gender, contact, username, password):
        try:
            conn = self._connect()
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO patients (name, age, gender, contact, username, password) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (name, age, gender, contact, username, self._hash_password(password)),
            )
            conn.commit()
            return True, "Registration successful."
        except sqlite3.IntegrityError:
            return False, "Username already exists. Please choose another."
        except sqlite3.Error as e:
            return False, f"Database error: {e}"
        finally:
            conn.close()

    def authenticate_patient(self, username, password):
        # checks the entered username/password (hashed) against the patients table
        try:
            conn = self._connect()
            cur = conn.cursor()
            cur.execute(
                "SELECT patient_id, name, age FROM patients WHERE username = ? AND password = ?",
                (username, self._hash_password(password)),
            )
            return cur.fetchone()  # None if not found
        except sqlite3.Error as e:
            print(f"[Database Error] Authentication failed: {e}")
            return None
        finally:
            conn.close()

    # ======================================================
    # ADMIN LOGIN
    # ======================================================
    def authenticate_admin(self, username, password):
        # fixed admin credentials as requested: username "admin", password "0000"
        # (kept here, not hardcoded in the GUI, so it's easy to change later)
        return username == "admin" and password == "0000"

    # ======================================================
    # STAFF ACCOUNTS  (role-based access — one branch each, added by Admin)
    # ======================================================
    def add_staff(self, username, password, branch_id):
        try:
            conn = self._connect()
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO staff (username, password, branch_id) VALUES (?, ?, ?)",
                (username, self._hash_password(password), branch_id),
            )
            conn.commit()
            return True, "Staff account created successfully."
        except sqlite3.IntegrityError:
            return False, "That staff username already exists."
        except sqlite3.Error as e:
            return False, f"Database error: {e}"
        finally:
            conn.close()

    def authenticate_staff(self, username, password):
        # returns (staff_id, branch_id, branch_name) or None — this is how
        # we scope a staff member's whole portal to just their own branch
        try:
            conn = self._connect()
            cur = conn.cursor()
            cur.execute("""
                SELECT s.staff_id, s.branch_id, b.branch_name
                FROM staff s JOIN branches b ON s.branch_id = b.branch_id
                WHERE s.username = ? AND s.password = ?
            """, (username, self._hash_password(password)))
            return cur.fetchone()
        except sqlite3.Error as e:
            print(f"[Database Error] Staff authentication failed: {e}")
            return None
        finally:
            conn.close()

    def get_all_staff_with_branch(self):
        try:
            conn = self._connect()
            cur = conn.cursor()
            cur.execute("""
                SELECT s.staff_id, s.username, b.branch_name
                FROM staff s JOIN branches b ON s.branch_id = b.branch_id
                ORDER BY b.branch_name, s.username
            """)
            return cur.fetchall()
        except sqlite3.Error as e:
            print(f"[Database Error] Fetching staff failed: {e}")
            return []
        finally:
            conn.close()

    def delete_staff(self, staff_id):
        try:
            conn = self._connect()
            cur = conn.cursor()
            cur.execute("DELETE FROM staff WHERE staff_id = ?", (staff_id,))
            conn.commit()
            return True, "Staff account removed."
        except sqlite3.Error as e:
            return False, f"Database error: {e}"
        finally:
            conn.close()

    # ======================================================
    # ADMIN: BRANCH MANAGEMENT
    # ======================================================
    def add_branch(self, branch_name):
        try:
            conn = self._connect()
            cur = conn.cursor()
            cur.execute("INSERT INTO branches (branch_name) VALUES (?)", (branch_name,))
            conn.commit()
            return True, "Branch added successfully."
        except sqlite3.IntegrityError:
            return False, "This branch already exists."
        except sqlite3.Error as e:
            return False, f"Database error: {e}"
        finally:
            conn.close()

    def get_all_branches(self):
        try:
            conn = self._connect()
            cur = conn.cursor()
            cur.execute("SELECT branch_id, branch_name FROM branches ORDER BY branch_name")
            return cur.fetchall()
        except sqlite3.Error as e:
            print(f"[Database Error] Fetching branches failed: {e}")
            return []
        finally:
            conn.close()

    # ======================================================
    # ADMIN: DOCTOR MANAGEMENT  (add + delete — delete is new)
    # ======================================================
    def add_doctor(self, name, department, branch_id, avg_consultation_minutes=10,
                   consultation_fee=None):
        # consultation_fee=None -> this doctor uses the default fee (Admin > Payments)
        try:
            conn = self._connect()
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO doctors (name, department, branch_id, avg_consultation_minutes, "
                "consultation_fee) VALUES (?, ?, ?, ?, ?)",
                (name, department, branch_id, avg_consultation_minutes, consultation_fee),
            )
            conn.commit()
            return True, "Doctor added successfully."
        except sqlite3.Error as e:
            return False, f"Database error: {e}"
        finally:
            conn.close()

    def get_doctor_fees(self):
        """{doctor_id: fee or None} - None means 'use the default fee'."""
        try:
            conn = self._connect()
            try:
                return {r[0]: r[1] for r in conn.execute(
                    "SELECT doctor_id, consultation_fee FROM doctors").fetchall()}
            finally:
                conn.close()
        except sqlite3.Error as e:
            print(f"[Database Error] Fetching doctor fees failed: {e}")
            return {}

    def get_doctor_fee(self, doctor_id, default=0.0):
        fee = self.get_doctor_fees().get(doctor_id)
        return float(default if fee is None else fee)

    def set_doctor_fee(self, doctor_id, fee):
        """fee=None resets the doctor to the default fee."""
        try:
            conn = self._connect()
            try:
                conn.execute("UPDATE doctors SET consultation_fee = ? WHERE doctor_id = ?",
                             (fee, doctor_id))
                conn.commit()
                return True, "Consultation fee updated."
            finally:
                conn.close()
        except sqlite3.Error as e:
            return False, f"Database error: {e}"

    def get_appointment_fee(self, appointment_id, default=0.0):
        """Fee of the doctor an OPD appointment was booked with (falls back to `default`)."""
        try:
            conn = self._connect()
            try:
                row = conn.execute(
                    "SELECT d.consultation_fee FROM appointments a "
                    "JOIN doctors d ON d.doctor_id = a.doctor_id WHERE a.appointment_id = ?",
                    (appointment_id,)).fetchone()
            finally:
                conn.close()
        except sqlite3.Error:
            return float(default)
        return float(default if (not row or row[0] is None) else row[0])

    def get_patient_contact(self, patient_id):
        try:
            conn = self._connect()
            try:
                row = conn.execute("SELECT contact FROM patients WHERE patient_id = ?",
                                   (patient_id,)).fetchone()
                return row[0] if row else ""
            finally:
                conn.close()
        except sqlite3.Error:
            return ""

    def delete_doctor(self, doctor_id):
        # blocks deletion if the doctor has an active appointment, so we
        # never orphan a patient's booking — a check before the risky action
        try:
            conn = self._connect()
            cur = conn.cursor()
            cur.execute(
                "SELECT COUNT(*) FROM appointments WHERE doctor_id = ? "
                "AND status IN ('Waiting', 'In Consultation')",
                (doctor_id,),
            )
            active = cur.fetchone()[0]
            if active > 0:
                return False, (f"Cannot delete: this doctor has {active} active "
                                f"appointment(s). Complete or cancel them first.")

            cur.execute("DELETE FROM doctors WHERE doctor_id = ?", (doctor_id,))
            conn.commit()
            return True, "Doctor removed successfully."
        except sqlite3.Error as e:
            return False, f"Database error: {e}"
        finally:
            conn.close()

    def get_doctors_by_branch(self, branch_id):
        try:
            conn = self._connect()
            cur = conn.cursor()
            cur.execute(
                "SELECT doctor_id, name, department, avg_consultation_minutes, delay_minutes "
                "FROM doctors WHERE branch_id = ?",
                (branch_id,),
            )
            return cur.fetchall()
        except sqlite3.Error as e:
            print(f"[Database Error] Fetching doctors failed: {e}")
            return []
        finally:
            conn.close()

    def get_all_doctors_with_branch(self, branch_id=None):
        # used by the Admin "Manage Doctors" tab and Queue Control — includes
        # branch name so the caller can see everything without extra lookups.
        # Pass branch_id to scope this to one branch (used by the Staff Portal).
        try:
            conn = self._connect()
            cur = conn.cursor()
            query = """
                SELECT d.doctor_id, d.name, d.department, b.branch_name,
                       d.avg_consultation_minutes, d.delay_minutes, d.branch_id
                FROM doctors d
                JOIN branches b ON d.branch_id = b.branch_id
            """
            params = []
            if branch_id is not None:
                query += " WHERE d.branch_id = ?"
                params.append(branch_id)
            query += " ORDER BY b.branch_name, d.name"
            cur.execute(query, params)
            return cur.fetchall()
        except sqlite3.Error as e:
            print(f"[Database Error] Fetching doctors failed: {e}")
            return []
        finally:
            conn.close()

    def set_doctor_delay(self, doctor_id, delay_minutes):
        # admin/staff report a doctor running late — this offset is added
        # on top of the queue-position calculation for every patient waiting
        # on that doctor, so the prediction reacts to real-time conditions
        try:
            conn = self._connect()
            cur = conn.cursor()
            cur.execute(
                "UPDATE doctors SET delay_minutes = ? WHERE doctor_id = ?",
                (delay_minutes, doctor_id),
            )
            conn.commit()
            return True, "Delay updated."
        except sqlite3.Error as e:
            return False, f"Database error: {e}"
        finally:
            conn.close()

    def get_departments_by_branch(self, branch_id):
        # distinct department names available under a branch, for the
        # "select department" step of booking
        try:
            conn = self._connect()
            cur = conn.cursor()
            cur.execute(
                "SELECT DISTINCT department FROM doctors WHERE branch_id = ?",
                (branch_id,),
            )
            return [row[0] for row in cur.fetchall()]
        except sqlite3.Error as e:
            print(f"[Database Error] Fetching departments failed: {e}")
            return []
        finally:
            conn.close()

    def get_doctors_by_branch_and_department(self, branch_id, department):
        try:
            conn = self._connect()
            cur = conn.cursor()
            cur.execute(
                "SELECT doctor_id, name, avg_consultation_minutes FROM doctors "
                "WHERE branch_id = ? AND department = ?",
                (branch_id, department),
            )
            return cur.fetchall()
        except sqlite3.Error as e:
            print(f"[Database Error] Fetching doctors failed: {e}")
            return []
        finally:
            conn.close()

    # ======================================================
    # BOOK APPOINTMENT / TOKEN GENERATION  (now priority-aware)
    # ======================================================
    def book_appointment(self, patient_id, doctor_id, branch_id, appointment_date,
                         appointment_time, priority="Normal", payment_status="Unpaid",
                         payment_method="", payment_ref="", amount_paid=0.0):
        """Create an OPD appointment and persist its payment state atomically."""
        conn = None
        try:
            conn = self._connect()
            cur = conn.cursor()

            payment_ref = (payment_ref or "").strip()
            if payment_ref:
                cur.execute("SELECT 1 FROM appointments WHERE payment_ref = ?", (payment_ref,))
                if cur.fetchone():
                    return False, "This payment reference has already been used for another booking."

            cur.execute(
                "SELECT COALESCE(MAX(token_number), 0) FROM appointments "
                "WHERE doctor_id = ? AND appointment_date = ?",
                (doctor_id, appointment_date),
            )
            next_token = cur.fetchone()[0] + 1

            cur.execute(
                "INSERT INTO appointments (patient_id, doctor_id, branch_id, token_number, "
                "status, priority, appointment_date, appointment_time, created_at, "
                "payment_status, payment_method, payment_ref, amount_paid) "
                "VALUES (?, ?, ?, ?, 'Waiting', ?, ?, ?, ?, ?, ?, ?, ?)",
                (patient_id, doctor_id, branch_id, next_token, priority,
                 appointment_date, appointment_time,
                 datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                 payment_status, payment_method or "", payment_ref, float(amount_paid or 0)),
            )
            appointment_id = cur.lastrowid
            conn.commit()
            return True, {"token_number": next_token, "appointment_id": appointment_id}
        except sqlite3.IntegrityError as e:
            if conn is not None:
                conn.rollback()
            if "payment_ref" in str(e).lower():
                return False, "This payment reference has already been used for another booking."
            return False, f"Database error: {e}"
        except sqlite3.Error as e:
            if conn is not None:
                conn.rollback()
            return False, f"Database error: {e}"
        finally:
            if conn is not None:
                conn.close()

    # ======================================================
    # PAYMENTS (UPI QR) + SETTINGS
    # ======================================================
    def get_setting(self, key, default=""):
        try:
            conn = self._connect()
            try:
                row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
            finally:
                conn.close()
            return row[0] if row else default
        except sqlite3.Error:
            return default

    def set_setting(self, key, value):
        try:
            conn = self._connect()
            try:
                conn.execute(
                    "INSERT INTO settings (key, value) VALUES (?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (key, str(value)),
                )
                conn.commit()
            finally:
                conn.close()
            return True
        except sqlite3.Error as e:
            print(f"[Database Error] Saving setting failed: {e}")
            return False

    def payment_ref_exists(self, payment_ref):
        """Check UPI reference across both OPD and Home Visit bookings."""
        payment_ref = (payment_ref or "").strip()
        if not payment_ref:
            return False
        try:
            conn = self._connect()
            try:
                if conn.execute(
                    "SELECT 1 FROM appointments WHERE payment_ref = ?", (payment_ref,)
                ).fetchone():
                    return True
                # Home Visit table exists in all current databases, but keep this
                # defensive for very old databases during first-time migration.
                try:
                    return conn.execute(
                        "SELECT 1 FROM hv_appointments WHERE payment_ref = ?", (payment_ref,)
                    ).fetchone() is not None
                except sqlite3.Error:
                    return False
            finally:
                conn.close()
        except sqlite3.Error:
            return False

    def get_payments(self, branch_id=None, limit=100):
        try:
            conn = self._connect()
            try:
                sql = (
                    "SELECT a.appointment_id, p.name, d.name, a.appointment_date, "
                    "a.token_number, a.amount_paid, a.payment_method, a.payment_ref, "
                    "a.payment_status "
                    "FROM appointments a "
                    "JOIN patients p ON a.patient_id = p.patient_id "
                    "JOIN doctors d ON a.doctor_id = d.doctor_id "
                )
                params = []
                if branch_id is not None:
                    sql += "WHERE a.branch_id = ? "
                    params.append(branch_id)
                sql += "ORDER BY a.appointment_id DESC LIMIT ?"
                params.append(int(limit))
                return conn.execute(sql, params).fetchall()
            finally:
                conn.close()
        except sqlite3.Error as e:
            print(f"[Database Error] Fetching payments failed: {e}")
            return []

    def get_payment_info(self, appointment_id):
        try:
            conn = self._connect()
            try:
                row = conn.execute(
                    "SELECT payment_status, payment_method, payment_ref, amount_paid "
                    "FROM appointments WHERE appointment_id = ?",
                    (appointment_id,),
                ).fetchone()
            finally:
                conn.close()
            if not row:
                return None
            return {"status": row[0], "method": row[1], "ref": row[2], "amount": row[3]}
        except sqlite3.Error:
            return None

    def verify_payment(self, appointment_id):
        return self._set_payment(appointment_id, "Verified", only_from=("Paid - Unverified",))

    def record_counter_payment(self, appointment_id, amount):
        return self._set_payment(
            appointment_id, "Verified",
            only_from=("Pay at Counter", "Unpaid"),
            method="Counter", amount=amount,
        )

    def _set_payment(self, appointment_id, new_status, only_from, method=None, amount=None):
        try:
            conn = self._connect()
            try:
                row = conn.execute(
                    "SELECT payment_status FROM appointments WHERE appointment_id = ?",
                    (appointment_id,),
                ).fetchone()
                if not row:
                    return False, "Appointment not found."
                if row[0] not in only_from:
                    return False, f"Nothing to do - payment is already '{row[0]}'."

                sets, params = ["payment_status = ?"], [new_status]
                if method is not None:
                    sets.append("payment_method = ?")
                    params.append(method)
                if amount is not None:
                    sets.append("amount_paid = ?")
                    params.append(float(amount))

                params.append(appointment_id)
                conn.execute(
                    f"UPDATE appointments SET {', '.join(sets)} WHERE appointment_id = ?",
                    params,
                )
                conn.commit()
                return True, "Payment updated."
            finally:
                conn.close()
        except sqlite3.Error as e:
            return False, f"Database error: {e}"

    def get_appointments_for_patient(self, patient_id):
        try:
            conn = self._connect()
            cur = conn.cursor()
            cur.execute("""
                SELECT a.appointment_id, d.name, d.department, b.branch_name,
                       a.token_number, a.status, a.appointment_date, a.appointment_time,
                       a.priority, d.doctor_id
                FROM appointments a
                JOIN doctors d ON a.doctor_id = d.doctor_id
                JOIN branches b ON a.branch_id = b.branch_id
                WHERE a.patient_id = ?
                ORDER BY a.appointment_date DESC, a.appointment_time DESC
            """, (patient_id,))
            return cur.fetchall()
        except sqlite3.Error as e:
            print(f"[Database Error] Fetching patient appointments failed: {e}")
            return []
        finally:
            conn.close()

    def cancel_appointment(self, appointment_id):
        # only a Waiting appointment can be cancelled — you can't cancel
        # something already completed or already in consultation
        try:
            conn = self._connect()
            cur = conn.cursor()
            cur.execute("SELECT status FROM appointments WHERE appointment_id = ?", (appointment_id,))
            row = cur.fetchone()
            if not row:
                return False, "Appointment not found."
            if row[0] != "Waiting":
                return False, f"Cannot cancel — appointment is already '{row[0]}'."
            cur.execute(
                "UPDATE appointments SET status = 'Cancelled' WHERE appointment_id = ?",
                (appointment_id,),
            )
            conn.commit()
            return True, "Appointment cancelled."
        except sqlite3.Error as e:
            return False, f"Database error: {e}"
        finally:
            conn.close()

    # ======================================================
    # QUEUE MANAGEMENT  (new — was "in process" in the First Review)
    # ======================================================
    def get_queue_for_doctor(self, doctor_id, appointment_date=None):
        # live queue for one doctor, ordered by priority first (Emergency,
        # then Senior Citizen, then Normal) and by token number within
        # each priority group — this is what "dynamic queue management" means
        try:
            conn = self._connect()
            cur = conn.cursor()
            query = """
                SELECT a.appointment_id, a.token_number, p.name, p.age, a.status,
                       a.priority, a.appointment_date, a.appointment_time
                FROM appointments a
                JOIN patients p ON a.patient_id = p.patient_id
                WHERE a.doctor_id = ? AND a.status IN ('Waiting', 'In Consultation')
            """
            params = [doctor_id]
            if appointment_date:
                query += " AND a.appointment_date = ?"
                params.append(appointment_date)
            query += """
                ORDER BY
                    CASE a.priority
                        WHEN 'Emergency' THEN 0
                        WHEN 'Senior Citizen' THEN 1
                        ELSE 2
                    END,
                    a.appointment_date ASC, a.token_number ASC
            """
            cur.execute(query, params)
            return cur.fetchall()
        except sqlite3.Error as e:
            print(f"[Database Error] Fetching queue failed: {e}")
            return []
        finally:
            conn.close()

    def get_total_active_patients(self, branch_id=None):
        # total number of patients currently waiting or in consultation.
        # Pass branch_id to scope this to one branch (used by the Staff Portal);
        # Admin leaves it as None to see every branch.
        try:
            conn = self._connect()
            cur = conn.cursor()
            query = "SELECT COUNT(*) FROM appointments WHERE status IN ('Waiting', 'In Consultation')"
            params = []
            if branch_id is not None:
                query += " AND branch_id = ?"
                params.append(branch_id)
            cur.execute(query, params)
            return cur.fetchone()[0]
        except sqlite3.Error as e:
            print(f"[Database Error] Counting active patients failed: {e}")
            return 0
        finally:
            conn.close()

    def get_currently_consulting(self, branch_id=None):
        # list of patients whose status is 'In Consultation' right now,
        # with doctor and branch. Pass branch_id to scope this to one
        # branch (used by the Staff Portal).
        try:
            conn = self._connect()
            cur = conn.cursor()
            query = """
                SELECT p.name, p.age, d.name, b.branch_name, a.token_number
                FROM appointments a
                JOIN patients p ON a.patient_id = p.patient_id
                JOIN doctors d ON a.doctor_id = d.doctor_id
                JOIN branches b ON a.branch_id = b.branch_id
                WHERE a.status = 'In Consultation'
            """
            params = []
            if branch_id is not None:
                query += " AND a.branch_id = ?"
                params.append(branch_id)
            cur.execute(query, params)
            return cur.fetchall()
        except sqlite3.Error as e:
            print(f"[Database Error] Fetching currently consulting failed: {e}")
            return []
        finally:
            conn.close()

    def update_appointment_status(self, appointment_id, status):
        try:
            conn = self._connect()
            cur = conn.cursor()
            cur.execute(
                "UPDATE appointments SET status = ? WHERE appointment_id = ?",
                (status, appointment_id),
            )
            conn.commit()
            return True, "Status updated."
        except sqlite3.Error as e:
            return False, f"Database error: {e}"
        finally:
            conn.close()

    # ======================================================
    # WAITING-TIME PREDICTION  (new — was "in process" in the First Review)
    # ======================================================
    def estimate_waiting_time(self, doctor_id, appointment_date, token_number, priority="Normal"):
        # Prediction method:
        #   (patients ahead in the SAME priority group and earlier priority
        #    groups, still Waiting, for that doctor on that date)
        #   x
        #   (that doctor's average consultation minutes)
        #   +
        #   (that doctor's live reported delay, e.g. "running 15 min late")
        # This is intentionally simple and explainable — a strict examiner
        # can follow every step of it without needing machine learning.
        try:
            conn = self._connect()
            cur = conn.cursor()

            cur.execute(
                "SELECT avg_consultation_minutes, delay_minutes FROM doctors WHERE doctor_id = ?",
                (doctor_id,),
            )
            row = cur.fetchone()
            avg_minutes, delay_minutes = row if row else (10, 0)

            my_rank = PRIORITY_ORDER.get(priority, 2)
            cur.execute("""
                SELECT token_number, priority FROM appointments
                WHERE doctor_id = ? AND appointment_date = ? AND status = 'Waiting'
            """, (doctor_id, appointment_date))
            rows = cur.fetchall()

            ahead = 0
            for tok, pr in rows:
                other_rank = PRIORITY_ORDER.get(pr, 2)
                if other_rank < my_rank:
                    ahead += 1                      # higher priority: always ahead
                elif other_rank == my_rank and tok < token_number:
                    ahead += 1                      # same priority: earlier token is ahead

            wait_minutes = ahead * avg_minutes + delay_minutes
            return ahead, wait_minutes
        except sqlite3.Error as e:
            print(f"[Database Error] Estimate failed: {e}")
            return 0, 0
        finally:
            conn.close()

    def get_queue_position(self, appointment_id):
        # convenience wrapper used by the patient's "Track Queue" screen —
        # looks up the appointment's own doctor/date/token/priority first,
        # then reuses estimate_waiting_time()
        try:
            conn = self._connect()
            cur = conn.cursor()
            cur.execute("""
                SELECT doctor_id, appointment_date, token_number, priority, status
                FROM appointments WHERE appointment_id = ?
            """, (appointment_id,))
            row = cur.fetchone()
            if not row:
                return None
            doctor_id, appt_date, token_number, priority, status = row
            if status != "Waiting":
                return {"status": status, "ahead": 0, "wait_minutes": 0}
            ahead, wait_minutes = self.estimate_waiting_time(doctor_id, appt_date, token_number, priority)
            return {"status": status, "ahead": ahead, "wait_minutes": wait_minutes}
        except sqlite3.Error as e:
            print(f"[Database Error] Queue position failed: {e}")
            return None
        finally:
            conn.close()
