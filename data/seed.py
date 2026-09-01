"""
Dev seed script — inserts fake data for local development/testing.

NOT for production use. Run manually, once your migrations are applied:

    python -m data.seed

Safe to re-run: it checks for existing seed data by a marker username
and skips re-inserting if it's already there, rather than duplicating rows
on every run.
"""

from decimal import Decimal

from argon2 import PasswordHasher

from data.database import SessionLocal
from data.models.doctor import Doctor
from data.models.patient import Patient
from data.models.transaction import Transaction
from data.models.user import ROLE_RECEPTIONIST, User

ph = PasswordHasher()

SEED_RECEPTIONIST_USERNAME = "seed_receptionist"


def seed() -> None:
    session = SessionLocal()
    try:
        already_seeded = (
            session.query(User)
            .filter(User.username == SEED_RECEPTIONIST_USERNAME)
            .first()
        )
        if already_seeded:
            print("Seed data already present — skipping. Delete the rows manually to re-seed.")
            return

        # --- Users ---
        receptionist = User(
            username=SEED_RECEPTIONIST_USERNAME,
            password_hash=ph.hash("devpassword123"),
            role=ROLE_RECEPTIONIST,
            active=True,
        )
        session.add(receptionist)

        # --- Doctors ---
        dr_smith = Doctor(name="Dr. Ahmed Smith", standard_percentage=Decimal("60.00"), active=True)
        dr_lee = Doctor(name="Dr. Sara Lee", standard_percentage=Decimal("50.00"), active=True)
        session.add_all([dr_smith, dr_lee])

        # --- Patients ---
        patient_one = Patient(full_name="Mona Youssef", phone="01000000001", email="mona@example.com")
        patient_two = Patient(full_name="Karim Adel", phone="01000000002", email=None)
        session.add_all([patient_one, patient_two])

        # Flush so the above rows get real IDs we can reference below,
        # without committing yet (keeps the whole seed atomic).
        session.flush()

        # --- Transactions ---
        # Mirrors what logic/transactions.py will eventually do automatically:
        # snapshot the doctor's current percentage and compute the split.
        def make_transaction(patient, doctor, total_amount: Decimal) -> Transaction:
            doctor_pct = doctor.standard_percentage
            center_pct = Decimal("100.00") - doctor_pct
            doctor_amount = (total_amount * doctor_pct / Decimal("100")).quantize(Decimal("0.01"))
            center_amount = total_amount - doctor_amount
            return Transaction(
                patient_id=patient.id,
                doctor_id=doctor.id,
                recorded_by=receptionist.id,
                total_amount=total_amount,
                doctor_percentage=doctor_pct,
                center_percentage=center_pct,
                doctor_amount=doctor_amount,
                center_amount=center_amount,
                description="Seed data — routine consultation",
            )

        session.add_all([
            make_transaction(patient_one, dr_smith, Decimal("500.00")),
            make_transaction(patient_two, dr_lee, Decimal("750.00")),
        ])

        session.commit()
        print("Seed data inserted: 1 receptionist, 2 doctors, 2 patients, 2 transactions.")

    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


if __name__ == "__main__":
    seed()