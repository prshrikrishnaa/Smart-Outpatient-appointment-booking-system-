
"""
Home Visit database layer for Smart OPD.

This module deliberately contains only the Home Visit extension.  The existing
Database class inherits HomeVisitDBMixin, so patients/doctors/appointments
already present in the original OPD database remain the source of truth.
"""
import hashlib
import sqlite3
from datetime import datetime, timedelta, date

HV_FLOW = (
    "Payment Completed",
    "Waiting for Doctor Response",
    "Doctor Accepted",
    "Doctor On The Way",
    "Doctor Arrived",
    "Visit Completed",
)
ST_WAITING = "Waiting for Doctor Response"
ST_ACCEPTED = "Doctor Accepted"
ST_ON_WAY = "Doctor On The Way"
ST_ARRIVED = "Doctor Arrived"
ST_DONE = "Visit Completed"
ST_DECLINED = "Declined"
ST_CANCELLED = "Cancelled"

WEEKDAY_NAMES = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
HV_TIME_SLOTS = (
    "09:00 AM", "10:00 AM", "11:00 AM", "12:00 PM",
    "01:00 PM", "02:00 PM", "03:00 PM", "04:00 PM", "05:00 PM",
)

def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def _today():
    return date.today().isoformat()

def _hash(password):
    return hashlib.sha256((password or "").encode("utf-8")).hexdigest()


class HomeVisitDBMixin:
    """SQLite operations used by homevisit_ui.py."""

    def _create_home_visit_tables(self):
        conn = self._connect()
        try:
            cur = conn.cursor()

            # Existing branches are extended; no duplicate branch table.
            for sql in (
                "ALTER TABLE branches ADD COLUMN latitude REAL",
                "ALTER TABLE branches ADD COLUMN longitude REAL",
                "ALTER TABLE branches ADD COLUMN hv_radius_km REAL NOT NULL DEFAULT 15",
                "ALTER TABLE branches ADD COLUMN hv_enabled INTEGER NOT NULL DEFAULT 0",
                "ALTER TABLE branches ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1",
            ):
                try:
                    cur.execute(sql)
                except sqlite3.OperationalError:
                    pass

            cur.execute("""
                CREATE TABLE IF NOT EXISTS hv_doctors (
                    hv_doctor_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    doctor_code TEXT NOT NULL UNIQUE,
                    name TEXT NOT NULL,
                    specialization TEXT NOT NULL,
                    phone TEXT NOT NULL DEFAULT '',
                    branch_id INTEGER NOT NULL,
                    service_area TEXT NOT NULL DEFAULT '',
                    consultation_fee REAL NOT NULL DEFAULT 0,
                    visit_fee REAL NOT NULL DEFAULT 0,
                    password TEXT NOT NULL,
                    is_available INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(branch_id) REFERENCES branches(branch_id)
                )
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS hv_schedule (
                    schedule_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    hv_doctor_id INTEGER NOT NULL,
                    weekday INTEGER NOT NULL,
                    start_time TEXT NOT NULL,
                    end_time TEXT NOT NULL,
                    UNIQUE(hv_doctor_id, weekday),
                    FOREIGN KEY(hv_doctor_id) REFERENCES hv_doctors(hv_doctor_id) ON DELETE CASCADE
                )
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS hv_leave (
                    leave_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    hv_doctor_id INTEGER NOT NULL,
                    start_date TEXT NOT NULL,
                    end_date TEXT NOT NULL,
                    active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(hv_doctor_id) REFERENCES hv_doctors(hv_doctor_id) ON DELETE CASCADE
                )
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS hv_appointments (
                    hv_appointment_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    patient_id INTEGER NOT NULL,
                    hv_doctor_id INTEGER NOT NULL,
                    branch_id INTEGER NOT NULL,
                    appointment_date TEXT NOT NULL,
                    appointment_time TEXT NOT NULL,
                    contact TEXT NOT NULL DEFAULT '',
                    reason TEXT NOT NULL DEFAULT '',
                    address TEXT NOT NULL DEFAULT '',
                    city TEXT NOT NULL DEFAULT '',
                    latitude REAL,
                    longitude REAL,
                    location_source TEXT NOT NULL DEFAULT 'manual',
                    distance_km REAL,
                    consultation_fee REAL NOT NULL DEFAULT 0,
                    visit_fee REAL NOT NULL DEFAULT 0,
                    total_fee REAL NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'Waiting for Doctor Response',
                    decline_reason TEXT,
                    payment_status TEXT NOT NULL DEFAULT 'No Charge',
                    payment_method TEXT NOT NULL DEFAULT 'None',
                    payment_ref TEXT NOT NULL DEFAULT '',
                    patient_notified_status TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(patient_id) REFERENCES patients(patient_id),
                    FOREIGN KEY(hv_doctor_id) REFERENCES hv_doctors(hv_doctor_id),
                    FOREIGN KEY(branch_id) REFERENCES branches(branch_id)
                )
            """)

            try:
                cur.execute(
                    "CREATE UNIQUE INDEX IF NOT EXISTS idx_hv_payment_ref "
                    "ON hv_appointments(payment_ref) WHERE payment_ref <> ''"
                )
            except sqlite3.Error:
                # Existing databases containing duplicate legacy references can
                # still open; create_hv_booking performs an explicit duplicate check.
                pass

            cur.execute("""
                CREATE TABLE IF NOT EXISTS hv_status_history (
                    history_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    hv_appointment_id INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    note TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(hv_appointment_id) REFERENCES hv_appointments(hv_appointment_id) ON DELETE CASCADE
                )
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_hv_appt_patient ON hv_appointments(patient_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_hv_appt_doctor_date ON hv_appointments(hv_doctor_id, appointment_date)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_hv_leave_dates ON hv_leave(hv_doctor_id, start_date, end_date)")
            conn.commit()
        finally:
            conn.close()

    # ---------- branch helpers ----------
    def get_branches_full(self, include_inactive=False):
        conn = self._connect()
        try:
            q = """SELECT branch_id, branch_name, latitude, longitude,
                          hv_radius_km, hv_enabled, is_active
                   FROM branches"""
            if not include_inactive:
                q += " WHERE is_active = 1"
            q += " ORDER BY branch_name"
            cur = conn.execute(q)
            return [
                {"branch_id":r[0], "branch_name":r[1], "latitude":r[2], "longitude":r[3],
                 "hv_radius_km":r[4], "hv_enabled":bool(r[5]), "is_active":bool(r[6])}
                for r in cur.fetchall()
            ]
        finally:
            conn.close()

    def get_branch(self, branch_id):
        rows = [b for b in self.get_branches_full(True) if b["branch_id"] == branch_id]
        return rows[0] if rows else None

    def save_branch(self, branch_id, name, lat, lon, radius, enabled):
        name = (name or "").strip()
        if not name:
            return False, "Branch name is required."
        try:
            radius = float(radius)
            if radius <= 0 or radius > 500:
                raise ValueError
        except (TypeError, ValueError):
            return False, "Home Visit radius must be a number between 0 and 500 km."
        lat_s, lon_s = str(lat or "").strip(), str(lon or "").strip()
        latitude = longitude = None
        if lat_s or lon_s:
            try:
                latitude, longitude = float(lat_s), float(lon_s)
                if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
                    raise ValueError
            except ValueError:
                return False, "Latitude/longitude are invalid."
        conn = self._connect()
        try:
            cur = conn.cursor()
            if branch_id is None:
                cur.execute("""INSERT INTO branches
                    (branch_name, latitude, longitude, hv_radius_km, hv_enabled, is_active)
                    VALUES (?,?,?,?,?,1)""",
                    (name, latitude, longitude, radius, int(bool(enabled))))
                msg = "Branch added successfully."
            else:
                cur.execute("""UPDATE branches SET branch_name=?, latitude=?, longitude=?,
                               hv_radius_km=?, hv_enabled=? WHERE branch_id=?""",
                            (name, latitude, longitude, radius, int(bool(enabled)), branch_id))
                msg = "Branch updated successfully."
            conn.commit()
            return True, msg
        except sqlite3.IntegrityError:
            return False, "This branch name already exists."
        except sqlite3.Error as e:
            return False, f"Database error: {e}"
        finally:
            conn.close()

    def set_branch_active(self, branch_id, active):
        conn = self._connect()
        try:
            conn.execute("UPDATE branches SET is_active=? WHERE branch_id=?", (int(bool(active)), branch_id))
            conn.commit()
            return True, "Branch activated." if active else "Branch deactivated."
        except sqlite3.Error as e:
            return False, f"Database error: {e}"
        finally:
            conn.close()

    # ---------- home visit doctors ----------
    def add_hv_doctor(self, code, name, specialization, phone, branch_id, service_area,
                      consultation_fee, visit_fee, password, *, weekdays=None,
                      start="09:00 AM", end="05:00 PM", is_available=True):
        code, name, specialization = (code or "").strip(), (name or "").strip(), (specialization or "").strip()
        if not all((code, name, specialization, password or "")):
            return False, "Doctor ID, name, specialization and password are required."
        if not branch_id:
            return False, "Please select an SRM branch."
        try:
            cf, vf = float(consultation_fee), float(visit_fee)
            if cf < 0 or vf < 0:
                raise ValueError
        except (TypeError, ValueError):
            return False, "Fees must be valid non-negative numbers."
        weekdays = list(weekdays if weekdays is not None else range(6))
        conn = self._connect()
        try:
            cur = conn.cursor()
            cur.execute("""INSERT INTO hv_doctors
                (doctor_code,name,specialization,phone,branch_id,service_area,
                 consultation_fee,visit_fee,password,is_available,created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (code,name,specialization,phone or "",branch_id,service_area or "",
                 cf,vf,_hash(password),int(bool(is_available)),_now()))
            did = cur.lastrowid
            for wd in weekdays:
                cur.execute("""INSERT OR REPLACE INTO hv_schedule
                    (hv_doctor_id,weekday,start_time,end_time) VALUES (?,?,?,?)""",
                    (did,int(wd),start,end))
            conn.commit()
            return True, "Home Visit doctor added successfully."
        except sqlite3.IntegrityError:
            return False, "That Home Visit Doctor ID already exists."
        except sqlite3.Error as e:
            return False, f"Database error: {e}"
        finally:
            conn.close()

    def update_hv_doctor(self, hv_doctor_id, code, name, specialization, phone, branch_id,
                         service_area, consultation_fee, visit_fee, password=None, *,
                         weekdays=None, start="09:00 AM", end="05:00 PM", is_available=True):
        try:
            cf, vf = float(consultation_fee), float(visit_fee)
            if cf < 0 or vf < 0:
                raise ValueError
        except (TypeError, ValueError):
            return False, "Fees must be valid non-negative numbers."
        conn = self._connect()
        try:
            cur = conn.cursor()
            if password:
                cur.execute("""UPDATE hv_doctors SET doctor_code=?,name=?,specialization=?,phone=?,
                    branch_id=?,service_area=?,consultation_fee=?,visit_fee=?,password=?,is_available=?
                    WHERE hv_doctor_id=?""",
                    (code,name,specialization,phone or "",branch_id,service_area or "",cf,vf,
                     _hash(password),int(bool(is_available)),hv_doctor_id))
            else:
                cur.execute("""UPDATE hv_doctors SET doctor_code=?,name=?,specialization=?,phone=?,
                    branch_id=?,service_area=?,consultation_fee=?,visit_fee=?,is_available=?
                    WHERE hv_doctor_id=?""",
                    (code,name,specialization,phone or "",branch_id,service_area or "",cf,vf,
                     int(bool(is_available)),hv_doctor_id))
            cur.execute("DELETE FROM hv_schedule WHERE hv_doctor_id=?", (hv_doctor_id,))
            for wd in list(weekdays if weekdays is not None else range(6)):
                cur.execute("""INSERT INTO hv_schedule
                    (hv_doctor_id,weekday,start_time,end_time) VALUES (?,?,?,?)""",
                    (hv_doctor_id,int(wd),start,end))
            conn.commit()
            return True, "Home Visit doctor updated successfully."
        except sqlite3.IntegrityError:
            return False, "That Home Visit Doctor ID already exists."
        except sqlite3.Error as e:
            return False, f"Database error: {e}"
        finally:
            conn.close()

    def delete_hv_doctor(self, hv_doctor_id):
        conn = self._connect()
        try:
            cur = conn.cursor()
            cur.execute("""SELECT COUNT(*) FROM hv_appointments
                           WHERE hv_doctor_id=? AND status NOT IN (?,?)""",
                        (hv_doctor_id, ST_DONE, ST_CANCELLED))
            if cur.fetchone()[0]:
                return False, "Cannot delete a doctor with active Home Visit requests."
            cur.execute("DELETE FROM hv_doctors WHERE hv_doctor_id=?", (hv_doctor_id,))
            conn.commit()
            return True, "Home Visit doctor removed."
        except sqlite3.Error as e:
            return False, f"Database error: {e}"
        finally:
            conn.close()

    def get_hv_doctors(self):
        conn = self._connect()
        try:
            rows = conn.execute("""SELECT d.*, b.branch_name
                FROM hv_doctors d JOIN branches b ON b.branch_id=d.branch_id
                ORDER BY b.branch_name,d.name""").fetchall()
            cols = [x[0] for x in conn.execute("SELECT * FROM hv_doctors LIMIT 0").description]
            out=[]
            for r in rows:
                d=dict(zip(cols,r)); d["branch_name"]=r[-1]
                d["is_available"]=bool(d["is_available"])
                out.append(d)
            return out
        finally:
            conn.close()

    def get_hv_doctor(self, hv_doctor_id):
        docs = [d for d in self.get_hv_doctors() if d["hv_doctor_id"] == hv_doctor_id]
        return docs[0] if docs else None

    def authenticate_hv_doctor(self, code, password):
        conn=self._connect()
        try:
            row=conn.execute("""SELECT hv_doctor_id FROM hv_doctors
                                WHERE doctor_code=? AND password=?""",
                             ((code or "").strip(),_hash(password))).fetchone()
            if not row:
                return None
        finally:
            conn.close()
        return self.get_hv_doctor(row[0])

    def get_hv_schedule(self, hv_doctor_id):
        conn=self._connect()
        try:
            rows=conn.execute("""SELECT weekday,start_time,end_time FROM hv_schedule
                                 WHERE hv_doctor_id=? ORDER BY weekday""",(hv_doctor_id,)).fetchall()
            return {r[0]:(r[1],r[2]) for r in rows}
        finally:
            conn.close()

    def set_hv_doctor_availability(self, hv_doctor_id, available):
        conn=self._connect()
        try:
            conn.execute("UPDATE hv_doctors SET is_available=? WHERE hv_doctor_id=?",
                         (int(bool(available)),hv_doctor_id))
            conn.commit()
            return True, "Availability updated."
        finally:
            conn.close()

    def hv_leave_on(self, hv_doctor_id, on_date=None):
        on_date=on_date or _today()
        conn=self._connect()
        try:
            row=conn.execute("""SELECT * FROM hv_leave
                WHERE hv_doctor_id=? AND active=1 AND start_date<=? AND end_date>=?
                ORDER BY start_date LIMIT 1""",(hv_doctor_id,on_date,on_date)).fetchone()
            if not row: return None
            return {"leave_id":row[0],"hv_doctor_id":row[1],"start":row[2],"end":row[3],
                    "start_date":row[2],"end_date":row[3],"active":bool(row[4])}
        finally: conn.close()

    def hv_doctor_state(self, doctor):
        if not doctor or not doctor.get("is_available",1):
            return "disabled", "Unavailable"
        leave=self.hv_leave_on(doctor["hv_doctor_id"])
        if leave:
            return "leave", f"On leave until {leave['end_date']}"
        return "available", "Available"

    def add_hv_leave(self, hv_doctor_id, start, end):
        try:
            a=date.fromisoformat(start); b=date.fromisoformat(end)
            if b<a: raise ValueError
        except ValueError:
            return False,"Please provide a valid leave date range.",0
        conn=self._connect()
        try:
            overlap=conn.execute("""SELECT COUNT(*) FROM hv_leave
                WHERE hv_doctor_id=? AND active=1 AND NOT(end_date<? OR start_date>?)""",
                (hv_doctor_id,start,end)).fetchone()[0]
            if overlap: return False,"That leave period overlaps an existing leave.",0
            cur=conn.cursor()
            cur.execute("""INSERT INTO hv_leave(hv_doctor_id,start_date,end_date,active,created_at)
                           VALUES(?,?,?,?,?)""",(hv_doctor_id,start,end,1,_now()))
            # Count existing non-closed requests; do not delete them.
            n=cur.execute("""SELECT COUNT(*) FROM hv_appointments
                WHERE hv_doctor_id=? AND appointment_date BETWEEN ? AND ?
                AND status NOT IN (?,?)""",(hv_doctor_id,start,end,ST_DONE,ST_CANCELLED)).fetchone()[0]
            conn.commit()
            return True,"Leave saved.",n
        except sqlite3.Error as e:
            return False,f"Database error: {e}",0
        finally: conn.close()

    def get_hv_leaves(self,hv_doctor_id):
        conn=self._connect()
        try:
            rows=conn.execute("""SELECT leave_id,hv_doctor_id,start_date,end_date,active
                FROM hv_leave WHERE hv_doctor_id=? ORDER BY start_date""",(hv_doctor_id,)).fetchall()
            return [{"leave_id":r[0],"hv_doctor_id":r[1],"start_date":r[2],"end_date":r[3],"active":bool(r[4])}
                    for r in rows if r[4] and r[3] >= _today()]
        finally: conn.close()

    def cancel_hv_leave(self,leave_id,hv_doctor_id):
        conn=self._connect()
        try:
            conn.execute("UPDATE hv_leave SET active=0 WHERE leave_id=? AND hv_doctor_id=?",(leave_id,hv_doctor_id))
            conn.commit(); return True,"Leave cancelled."
        finally: conn.close()

    def end_hv_leave_now(self,hv_doctor_id):
        conn=self._connect()
        try:
            conn.execute("""UPDATE hv_leave SET end_date=?,active=0
                            WHERE hv_doctor_id=? AND active=1 AND start_date<=? AND end_date>=?""",
                         (_today(),hv_doctor_id,_today(),_today()))
            conn.commit(); return True,"Leave ended. You are available now."
        finally: conn.close()

    # ---------- booking / availability ----------
    def _date_slots(self, hv_doctor_id, appointment_date):
        d=date.fromisoformat(appointment_date)
        sched=self.get_hv_schedule(hv_doctor_id)
        if d.weekday() not in sched or self.hv_leave_on(hv_doctor_id, appointment_date):
            return []
        start,end=sched[d.weekday()]
        try:
            si=HV_TIME_SLOTS.index(start); ei=HV_TIME_SLOTS.index(end)
        except ValueError:
            si,ei=0,len(HV_TIME_SLOTS)-1
        if ei < si: return []
        slots=list(HV_TIME_SLOTS[si:ei+1])
        if appointment_date==_today():
            now=datetime.now().time()
            slots=[x for x in slots if datetime.strptime(x,"%I:%M %p").time()>now]
        conn=self._connect()
        try:
            booked={r[0] for r in conn.execute("""SELECT appointment_time FROM hv_appointments
                WHERE hv_doctor_id=? AND appointment_date=? AND status NOT IN (?,?)""",
                (hv_doctor_id,appointment_date,ST_DECLINED,ST_CANCELLED)).fetchall()}
        finally: conn.close()
        return [x for x in slots if x not in booked]

    def get_available_slots(self,hv_doctor_id,appointment_date):
        return self._date_slots(hv_doctor_id,appointment_date)

    def get_bookable_dates(self,hv_doctor_id,days=30):
        out=[]
        d=date.today()
        for n in range(days):
            ds=(d+timedelta(days=n)).isoformat()
            slots=self._date_slots(hv_doctor_id,ds)
            if slots: out.append((ds,slots))
        return out

    def get_bookable_hv_doctors(self,branch_id):
        docs=[]
        for d in self.get_hv_doctors():
            if d["branch_id"]!=branch_id: continue
            state,label=self.hv_doctor_state(d)
            dates=self.get_bookable_dates(d["hv_doctor_id"])
            if state=="available" and dates:
                d=dict(d); d["dates"]=dates; d["note"]=""
                docs.append(d)
        return docs

    def _row_dict(self, row):
        return dict(row) if isinstance(row,sqlite3.Row) else None

    def _appointment_select(self, where="", params=()):
        conn=self._connect()
        try:
            conn.row_factory=sqlite3.Row
            q="""SELECT a.*, p.name AS patient_name, p.age AS patient_age,
                         d.name AS doctor_name, d.specialization, d.phone AS doctor_phone,
                         b.branch_name
                  FROM hv_appointments a
                  JOIN patients p ON p.patient_id=a.patient_id
                  JOIN hv_doctors d ON d.hv_doctor_id=a.hv_doctor_id
                  JOIN branches b ON b.branch_id=a.branch_id """ + where
            rows=conn.execute(q,params).fetchall()
            return [dict(r) for r in rows]
        finally: conn.close()

    def create_hv_booking(self, **kwargs):
        required=("patient_id","hv_doctor_id","branch_id","appointment_date","appointment_time",
                   "contact","reason","address","city","latitude","longitude","location_source",
                   "distance_km","payment_method","payment_ref")
        if any(k not in kwargs for k in required):
            return False,"Incomplete Home Visit booking data."
        self.expire_stale_hv_requests()
        doc=self.get_hv_doctor(kwargs["hv_doctor_id"])
        branch=self.get_branch(kwargs["branch_id"])
        if not doc or not branch or not branch["is_active"] or not branch["hv_enabled"]:
            return False,"The selected branch or Home Visit doctor is no longer available."
        if doc["branch_id"]!=branch["branch_id"]:
            return False,"Doctor and branch no longer match."
        state,_=self.hv_doctor_state(doc)
        if state!="available":
            return False,"This doctor is currently unavailable or on leave."
        if kwargs["appointment_time"] not in self.get_available_slots(doc["hv_doctor_id"],kwargs["appointment_date"]):
            return False,"That date/time slot is no longer available."
        if kwargs["latitude"] is not None and kwargs["longitude"] is not None:
            from geo import haversine_km
            dist=haversine_km(float(kwargs["latitude"]),float(kwargs["longitude"]),
                              float(branch["latitude"]),float(branch["longitude"])) if branch["latitude"] is not None else None
            if dist is None or dist>float(branch["hv_radius_km"]):
                return False,"The Home Visit service area has changed. Please choose your location again."
        total=float(doc["consultation_fee"])+float(doc["visit_fee"])
        method=kwargs["payment_method"] or "None"
        if method=="UPI": pstatus="Paid - Unverified"
        elif method in ("Visit","Counter"): pstatus="Pay on Visit"
        else: pstatus="No Charge"
        conn=self._connect()
        try:
            cur=conn.cursor()
            payment_ref = (kwargs["payment_ref"] or "").strip()
            if payment_ref:
                existing = cur.execute(
                    "SELECT 1 FROM appointments WHERE payment_ref=? LIMIT 1",
                    (payment_ref,)
                ).fetchone()
                if existing:
                    return False, "This payment reference has already been used for another booking."
                existing = cur.execute(
                    "SELECT 1 FROM hv_appointments WHERE payment_ref=? LIMIT 1",
                    (payment_ref,)
                ).fetchone()
                if existing:
                    return False, "This payment reference has already been used for another booking."
            cur.execute("""INSERT INTO hv_appointments
                (patient_id,hv_doctor_id,branch_id,appointment_date,appointment_time,contact,reason,address,city,
                 latitude,longitude,location_source,distance_km,consultation_fee,visit_fee,total_fee,status,
                 payment_status,payment_method,payment_ref,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (kwargs["patient_id"],doc["hv_doctor_id"],branch["branch_id"],kwargs["appointment_date"],
                 kwargs["appointment_time"],kwargs["contact"],kwargs["reason"],kwargs["address"],kwargs["city"],
                 kwargs["latitude"],kwargs["longitude"],kwargs["location_source"],kwargs["distance_km"],
                 doc["consultation_fee"],doc["visit_fee"],total,ST_WAITING,pstatus,method,kwargs["payment_ref"] or "",
                 _now(),_now()))
            aid=cur.lastrowid
            initial="Payment Completed" if method=="UPI" else "Request Placed"
            cur.execute("INSERT INTO hv_status_history(hv_appointment_id,status,note,created_at) VALUES(?,?,?,?)",
                        (aid,initial,pstatus,_now()))
            conn.commit()
            return True,{"hv_appointment_id":aid}
        except sqlite3.Error as e:
            return False,f"Database error: {e}"
        finally: conn.close()

    def get_hv_appointment(self,appointment_id):
        rows=self._appointment_select("WHERE a.hv_appointment_id=?",(appointment_id,))
        return rows[0] if rows else None

    def get_hv_appointments_for_patient(self,patient_id):
        self.expire_stale_hv_requests()
        return self._appointment_select("WHERE a.patient_id=? ORDER BY a.appointment_date DESC,a.appointment_time DESC",
                                        (patient_id,))

    def get_hv_requests_for_doctor(self,hv_doctor_id,scope="today"):
        self.expire_stale_hv_requests()
        if scope=="history":
            where="WHERE a.hv_doctor_id=? AND a.status IN (?,?,?) ORDER BY a.appointment_date DESC,a.appointment_time DESC"
            params=(hv_doctor_id,ST_DONE,ST_DECLINED,ST_CANCELLED)
        elif scope=="upcoming":
            where="WHERE a.hv_doctor_id=? AND a.appointment_date>? AND a.status NOT IN (?,?) ORDER BY a.appointment_date,a.appointment_time"
            params=(hv_doctor_id,_today(),ST_DECLINED,ST_CANCELLED)
        else:
            where="WHERE a.hv_doctor_id=? AND a.appointment_date=? ORDER BY a.appointment_time"
            params=(hv_doctor_id,_today())
        return self._appointment_select(where,params)

    def get_all_hv_appointments(self, limit=100):
        try: limit = max(1, min(int(limit), 1000))
        except (TypeError, ValueError): limit = 100
        return self._appointment_select(f"ORDER BY a.appointment_date DESC,a.appointment_time DESC LIMIT {limit}")

    def get_hv_stats(self):
        conn=self._connect()
        try:
            today=_today()
            total=conn.execute("SELECT COUNT(*) FROM hv_appointments").fetchone()[0]
            waiting=conn.execute("SELECT COUNT(*) FROM hv_appointments WHERE status=?",(ST_WAITING,)).fetchone()[0]
            active=conn.execute("""SELECT COUNT(*) FROM hv_appointments
                                   WHERE appointment_date=? AND status NOT IN (?,?)""",
                                (today,ST_DONE,ST_CANCELLED)).fetchone()[0]
            in_progress=conn.execute("""SELECT COUNT(*) FROM hv_appointments
                                   WHERE status IN (?,?,?)""",
                                   (ST_ACCEPTED,ST_ON_WAY,ST_ARRIVED)).fetchone()[0]
            completed=conn.execute("SELECT COUNT(*) FROM hv_appointments WHERE status=?",(ST_DONE,)).fetchone()[0]
            return {"total":total,"waiting":waiting,"today_active":active,
                    "in_progress":in_progress,"completed":completed}
        finally: conn.close()

    def _set_hv_status(self,aid,new_status,actor_doctor_id=None,reason=None):
        conn=self._connect()
        try:
            conn.row_factory=sqlite3.Row
            row=conn.execute("SELECT * FROM hv_appointments WHERE hv_appointment_id=?",(aid,)).fetchone()
            if not row: return False,"Home Visit request not found."
            if actor_doctor_id is not None and row["hv_doctor_id"]!=actor_doctor_id:
                return False,"You are not assigned to this Home Visit."
            cur=conn.cursor()
            cur.execute("""UPDATE hv_appointments SET status=?,decline_reason=?,updated_at=?,
                           patient_notified_status=? WHERE hv_appointment_id=?""",
                        (new_status,reason,row and _now(),"" ,aid))
            cur.execute("INSERT INTO hv_status_history(hv_appointment_id,status,note,created_at) VALUES(?,?,?,?)",
                        (aid,new_status,reason or "",_now()))
            conn.commit()
            return True,"Status updated."
        except sqlite3.Error as e:
            return False,f"Database error: {e}"
        finally: conn.close()

    def hv_accept(self,aid,doctor_id):
        row=self.get_hv_appointment(aid)
        if not row or row["status"]!=ST_WAITING:
            return False,"This request is no longer waiting for a response."
        # Do not allow a doctor to accept after becoming unavailable.
        doc=self.get_hv_doctor(doctor_id)
        if not doc or self.hv_doctor_state(doc)[0]!="available":
            return False,"You are currently unavailable for new Home Visits."
        return self._set_hv_status(aid,ST_ACCEPTED,doctor_id)

    def hv_decline(self,aid,doctor_id,reason):
        row=self.get_hv_appointment(aid)
        if not row or row["status"]!=ST_WAITING:
            return False,"This request is no longer waiting."
        return self._set_hv_status(aid,ST_DECLINED,doctor_id,reason or "Other")

    def hv_advance(self,aid,doctor_id):
        row=self.get_hv_appointment(aid)
        if not row or row["hv_doctor_id"]!=doctor_id:
            return False,"Home Visit not found."
        nxt={ST_ACCEPTED:ST_ON_WAY,ST_ON_WAY:ST_ARRIVED,ST_ARRIVED:ST_DONE}.get(row["status"])
        if not nxt:
            return False,"This Home Visit cannot be advanced from its current status."
        return self._set_hv_status(aid,nxt,doctor_id)

    def hv_cancel_by_patient(self,aid,patient_id):
        row=self.get_hv_appointment(aid)
        if not row or row["patient_id"]!=patient_id:
            return False,"Home Visit not found."
        if row["status"]!=ST_WAITING:
            return False,"Only requests waiting for the doctor can be cancelled."
        conn=self._connect()
        try:
            conn.execute("""UPDATE hv_appointments SET status=?,payment_status=?,updated_at=?,
                            patient_notified_status=? WHERE hv_appointment_id=?""",
                         (ST_CANCELLED,"Refund Due" if row["payment_status"]=="Paid - Unverified" else row["payment_status"],
                          _now(),"",aid))
            conn.execute("INSERT INTO hv_status_history(hv_appointment_id,status,note,created_at) VALUES(?,?,?,?)",
                         (aid,ST_CANCELLED,"Cancelled by patient",_now()))
            conn.commit()
            return True,"Home Visit request cancelled."
        finally: conn.close()

    def expire_stale_hv_requests(self):
        conn=self._connect()
        try:
            # Requests older than their slot and still waiting are closed; online
            # payments become Refund Due so an admin can verify/refund them.
            cutoff=datetime.now().strftime("%Y-%m-%d %H:%M")
            rows=conn.execute("""SELECT hv_appointment_id,payment_status FROM hv_appointments
                WHERE status=? AND (appointment_date || ' ' || appointment_time) < ?""",
                (ST_WAITING,cutoff)).fetchall()
            for aid,pstatus in rows:
                conn.execute("""UPDATE hv_appointments SET status=?,payment_status=?,updated_at=?,
                                patient_notified_status=? WHERE hv_appointment_id=?""",
                             (ST_CANCELLED,"Refund Due" if pstatus=="Paid - Unverified" else pstatus,
                              _now(),"",aid))
                conn.execute("INSERT INTO hv_status_history(hv_appointment_id,status,note,created_at) VALUES(?,?,?,?)",
                             (aid,ST_CANCELLED,"Doctor did not respond before the slot.",_now()))
            conn.commit()
        finally: conn.close()

    # ---------- payment/admin ----------
    def verify_hv_payment(self,aid):
        conn=self._connect()
        try:
            row=conn.execute("SELECT payment_status FROM hv_appointments WHERE hv_appointment_id=?",(aid,)).fetchone()
            if not row: return False,"Payment record not found."
            if row[0]!="Paid - Unverified": return False,"This payment does not need verification."
            conn.execute("UPDATE hv_appointments SET payment_status='Verified',updated_at=? WHERE hv_appointment_id=?",
                         (_now(),aid)); conn.commit()
            return True,"Payment verified."
        finally: conn.close()

    def mark_hv_refunded(self,aid):
        conn=self._connect()
        try:
            conn.execute("UPDATE hv_appointments SET payment_status='Refunded',updated_at=? WHERE hv_appointment_id=?",
                         (_now(),aid)); conn.commit(); return True,"Payment marked as refunded."
        finally: conn.close()

    def get_unnotified_hv_updates(self,patient_id):
        return self._appointment_select("""WHERE a.patient_id=? AND a.status!=a.patient_notified_status
                                           AND a.status!=? ORDER BY a.updated_at""",
                                        (patient_id,ST_WAITING))

    def mark_hv_notified(self,aid,status):
        conn=self._connect()
        try:
            conn.execute("UPDATE hv_appointments SET patient_notified_status=? WHERE hv_appointment_id=?",
                         (status,aid)); conn.commit()
        finally: conn.close()

    def get_patient_contact(self,patient_id):
        conn=self._connect()
        try:
            r=conn.execute("SELECT contact FROM patients WHERE patient_id=?",(patient_id,)).fetchone()
            return r[0] if r else ""
        finally: conn.close()
