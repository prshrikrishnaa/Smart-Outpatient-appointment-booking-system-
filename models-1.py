"""
models.py
Data-holding classes for the OPD system. These are used by app.py to wrap
raw database rows into objects, demonstrating Classes, Objects,
Constructors and Encapsulation, as claimed in the project's
'Programming Concepts Implemented' slide.
"""


class Patient:
    def __init__(self, patient_id, name, age, gender="", contact=""):
        self._patient_id = patient_id   # leading underscore -> encapsulation
        self._name = name
        self._age = age
        self._gender = gender
        self._contact = contact

    @classmethod
    def from_row(cls, row):
        # row = (patient_id, name, age) as returned by authenticate_patient()
        return cls(row[0], row[1], row[2])

    @property
    def patient_id(self):
        return self._patient_id

    @property
    def name(self):
        return self._name

    @property
    def age(self):
        return self._age

    def is_senior_citizen(self):
        # senior citizens are auto-flagged for priority queueing
        return self._age >= 60

    def __str__(self):
        return f"Patient({self._name}, Age: {self._age}, Gender: {self._gender})"


class Doctor:
    def __init__(self, doctor_id, name, department, avg_consultation_minutes=10):
        self._doctor_id = doctor_id
        self._name = name
        self._department = department
        self._avg_consultation_minutes = avg_consultation_minutes

    @property
    def doctor_id(self):
        return self._doctor_id

    @property
    def name(self):
        return self._name

    @property
    def department(self):
        return self._department

    @property
    def avg_consultation_minutes(self):
        return self._avg_consultation_minutes

    def __str__(self):
        return f"Dr. {self._name} ({self._department})"


class Appointment:
    def __init__(self, appointment_id, patient_id, doctor_id, token_number,
                 status="Waiting", priority="Normal"):
        self._appointment_id = appointment_id
        self._patient_id = patient_id
        self._doctor_id = doctor_id
        self._token_number = token_number
        self._status = status
        self._priority = priority

    @property
    def appointment_id(self):
        return self._appointment_id

    @property
    def token_number(self):
        return self._token_number

    @property
    def status(self):
        return self._status

    @status.setter
    def status(self, new_status):
        valid_statuses = {"Waiting", "In Consultation", "Completed", "No-Show", "Cancelled"}
        if new_status not in valid_statuses:
            raise ValueError(f"Invalid status: {new_status}")
        self._status = new_status

    @property
    def priority(self):
        return self._priority

    def __str__(self):
        return f"Token {self._token_number} - {self._status} ({self._priority})"
