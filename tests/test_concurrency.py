"""
Phase 6: concurrent access against real PostgreSQL ("two receptionists
editing at once"). SQLite can't test this (it ignores row locks), so these
tests are SKIPPED unless TEST_DATABASE_URL points at a throwaway database:

    createdb healthcenter_test
    set TEST_DATABASE_URL=postgresql+psycopg2://user:pass@localhost:5432/healthcenter_test
    pytest tests/test_concurrency.py -v

The database name must contain "test": the fixture DROPS ALL TABLES in it.
"""

import os
import threading
from decimal import Decimal
from types import SimpleNamespace

import pytest
from argon2 import PasswordHasher
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

TEST_DB_URL = os.getenv("TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not TEST_DB_URL, reason="set TEST_DATABASE_URL to a throwaway PostgreSQL database to run"
)

from data.database import Base  # noqa: E402
from data.models.adjustment import Adjustment  # noqa: E402
from data.models.patient import Patient  # noqa: E402
from data.models.transaction import Transaction  # noqa: E402
from data.models.user import ROLE_ADMIN, ROLE_RECEPTIONIST, User  # noqa: E402
from logic import adjustments, audit, auth, doctors, patients, transactions  # noqa: E402
from logic.errors import (  # noqa: E402
    AccountLockedError,
    AuthenticationError,
    LogicError,
    ValidationError,
)


@pytest.fixture(scope="module")
def engine():
    import data.models  # noqa: F401

    url = make_url(TEST_DB_URL)
    if "test" not in (url.database or "").lower():
        pytest.fail(f"Refusing to run: database name {url.database!r} must contain 'test'.")
    eng = create_engine(TEST_DB_URL, future=True)
    yield eng
    Base.metadata.drop_all(eng)
    eng.dispose()


@pytest.fixture()
def Session(engine):
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, future=True)


def _seed(Session):
    with Session() as s:
        admin1 = User(username="admin1", password_hash="x", role=ROLE_ADMIN, active=True)
        admin2 = User(username="admin2", password_hash="x", role=ROLE_ADMIN, active=True)
        rec = User(username="rec1", password_hash="x", role=ROLE_RECEPTIONIST, active=True)
        s.add_all([admin1, admin2, rec])
        s.flush()
        doctor = doctors.create_doctor(
            s, name="Dr. Ahmed Smith", standard_percentage=Decimal("60.00"), acting_user=admin1
        )
        patient = patients.create_patient(
            s, full_name="Mona Youssef", phone="0100000001", acting_user=rec
        )
        return SimpleNamespace(
            admin1=admin1.id, admin2=admin2.id, rec=rec.id, doctor=doctor.id, patient=patient.id
        )


def run_parallel(Session, worker, count):
    """Run worker(session, index) in `count` threads released together. -> [("ok"|"err", value)]"""
    barrier = threading.Barrier(count)
    results = [None] * count

    def target(i):
        session = Session()
        try:
            barrier.wait(timeout=15)
            results[i] = ("ok", worker(session, i))
        except Exception as exc:  # noqa: BLE001 - we report every outcome
            session.rollback()
            results[i] = ("err", exc)
        finally:
            session.close()

    threads = [threading.Thread(target=target, args=(i,)) for i in range(count)]
    for th in threads:
        th.start()
    for th in threads:
        th.join(timeout=60)
    assert all(r is not None for r in results), "a worker thread hung (possible deadlock)"
    return results


def test_concurrent_patient_edits_keep_a_consistent_audit_chain(Session):
    ids = _seed(Session)

    def worker(session, i):
        user = session.get(User, ids.rec)
        patients.edit_patient(
            session, patient_id=ids.patient, acting_user=user, address=f"Address {i}"
        )

    results = run_parallel(Session, worker, 6)
    assert [r[0] for r in results] == ["ok"] * 6, results

    with Session() as s:
        history = audit.get_history(s, table_name="patients", record_id=ids.patient)
        assert len(history) == 1 + 6  # creation + six edits

        # Each edit's "old" value must equal the previous entry's "new" value.
        current = history[0].new_values["address"]
        for entry in history[1:]:
            assert entry.old_values["address"] == current
            current = entry.new_values["address"]
        assert s.get(Patient, ids.patient).address == current


def test_two_admins_cannot_both_over_adjust_the_same_transaction(Session):
    ids = _seed(Session)
    with Session() as s:
        txn = transactions.record_transaction(
            s,
            patient_id=ids.patient,
            doctor_id=ids.doctor,
            total_amount=Decimal("500.00"),
            acting_user=s.get(User, ids.rec),
        )
        txn_id = txn.id

    def worker(session, i):
        user = session.get(User, (ids.admin1, ids.admin2)[i])
        adjustments.record_adjustment(
            session,
            transaction_id=txn_id,
            amount_change=Decimal("-400"),  # either alone is fine; both would go negative
            reason="concurrent",
            acting_user=user,
        )

    results = run_parallel(Session, worker, 2)

    assert sorted(r[0] for r in results) == ["err", "ok"], results
    failure = next(r[1] for r in results if r[0] == "err")
    assert isinstance(failure, ValidationError)
    with Session() as s:
        total = sum(a.total_amount for a in s.query(Adjustment).all())
        assert total == Decimal("-400.00")


def test_simultaneous_failed_logins_are_all_counted(Session, monkeypatch):
    fast = PasswordHasher(time_cost=1, memory_cost=8, parallelism=1)
    monkeypatch.setattr(auth, "_hasher", fast)
    with Session() as s:
        s.add(
            User(
                username="sara",
                password_hash=fast.hash("right-password-1"),
                role=ROLE_RECEPTIONIST,
                active=True,
            )
        )
        s.commit()

    def worker(session, i):
        auth.authenticate(session, username="sara", password="wrong-password")

    results = run_parallel(Session, worker, 4)  # 4 < MAX_FAILED_ATTEMPTS, so no lockout yet

    for kind, value in results:
        assert kind == "err"
        assert isinstance(value, AuthenticationError)
        assert not isinstance(value, AccountLockedError)
    with Session() as s:
        assert s.query(User).filter(User.username == "sara").one().failed_login_attempts == 4


def test_delete_patient_racing_a_new_transaction_never_loses_either_side(Session):
    for _ in range(5):
        ids = _seed(Session)

        def worker(session, i):
            if i == 0:
                patients.delete_patient(
                    session, patient_id=ids.patient, acting_user=session.get(User, ids.rec)
                )
            else:
                transactions.record_transaction(
                    session,
                    patient_id=ids.patient,
                    doctor_id=ids.doctor,
                    total_amount=Decimal("100.00"),
                    acting_user=session.get(User, ids.rec),
                )

        results = run_parallel(Session, worker, 2)

        # Exactly one side wins, and the loser gets a clean LogicError (never a raw DB error).
        assert sorted(r[0] for r in results) == ["err", "ok"], results
        loser = next(r[1] for r in results if r[0] == "err")
        assert isinstance(loser, LogicError), repr(loser)

        with Session() as s:
            patient_exists = s.get(Patient, ids.patient) is not None
            txn_count = s.query(Transaction).count()
            assert patient_exists or txn_count == 0  # never a transaction without a patient
            assert results[0][0] == ("ok" if not patient_exists else "err")

        Base.metadata.drop_all(Session.kw["bind"])
        Base.metadata.create_all(Session.kw["bind"])