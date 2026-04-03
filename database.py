"""
Database models and setup for CHW Patient Tracking System.
"""
import json
from datetime import datetime
from sqlalchemy import (
    create_engine, Column, Integer, String, Float,
    DateTime, Boolean, Text, ForeignKey
)
from sqlalchemy.orm import declarative_base, sessionmaker, relationship

import os
_DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./chw_patients.db")
# Railway gives postgres:// but SQLAlchemy needs postgresql://
if _DATABASE_URL.startswith("postgres://"):
    _DATABASE_URL = _DATABASE_URL.replace("postgres://", "postgresql://", 1)

DATABASE_URL = _DATABASE_URL
_kwargs = {} if DATABASE_URL.startswith("postgresql") else {"check_same_thread": False}
engine = create_engine(DATABASE_URL, connect_args=_kwargs)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class HealthWorker(Base):
    __tablename__ = "health_workers"

    id = Column(Integer, primary_key=True, index=True)
    phone = Column(String, unique=True, index=True, nullable=False)
    name = Column(String, nullable=False)
    village = Column(String, nullable=True)
    district = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    patients = relationship("Patient", back_populates="chw")
    sessions = relationship("ConversationSession", back_populates="chw")


class Patient(Base):
    __tablename__ = "patients"

    id = Column(Integer, primary_key=True, index=True)
    chw_id = Column(Integer, ForeignKey("health_workers.id"), nullable=False)
    name = Column(String, nullable=False)
    patient_type = Column(String, nullable=False)   # "pregnant" or "cu2"
    created_at = Column(DateTime, default=datetime.utcnow)

    chw = relationship("HealthWorker", back_populates="patients")
    pregnant_screenings = relationship("PregnantScreening", back_populates="patient")
    child_screenings = relationship("ChildScreening", back_populates="patient")


class PregnantScreening(Base):
    __tablename__ = "pregnant_screenings"

    id = Column(Integer, primary_key=True, index=True)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False)
    mother_age = Column(Integer, nullable=True)
    weeks_pregnant = Column(Integer, nullable=True)
    muac_cm = Column(Float, nullable=True)
    hb_gdl = Column(Float, nullable=True)
    anemia_symptoms = Column(Boolean, nullable=True)
    systolic_bp = Column(Integer, nullable=True)
    diastolic_bp = Column(Integer, nullable=True)

    # Screening results
    muac_status = Column(String, nullable=True)     # normal / kek / kek_berat
    anemia_status = Column(String, nullable=True)   # normal / moderate / severe
    bp_status = Column(String, nullable=True)       # normal / hypertension / skipped
    overall_status = Column(String, nullable=True)  # normal / at_risk / referred
    needs_referral = Column(Boolean, default=False)

    education_message = Column(Text, nullable=True)
    referral_message = Column(Text, nullable=True)

    screened_at = Column(DateTime, default=datetime.utcnow)

    patient = relationship("Patient", back_populates="pregnant_screenings")


class ChildScreening(Base):
    __tablename__ = "child_screenings"

    id = Column(Integer, primary_key=True, index=True)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False)
    age_months = Column(Integer, nullable=True)
    sex = Column(String, nullable=True)        # "M" or "F"
    weight_kg = Column(Float, nullable=True)
    height_cm = Column(Float, nullable=True)

    # Z-scores
    waz = Column(Float, nullable=True)         # Weight-for-Age Z-score
    haz = Column(Float, nullable=True)         # Height-for-Age Z-score

    # Screening results
    weight_status = Column(String, nullable=True)   # normal / underweight / severely_underweight
    height_status = Column(String, nullable=True)   # normal / stunted / severely_stunted
    overall_status = Column(String, nullable=True)  # normal / at_risk / referred
    needs_referral = Column(Boolean, default=False)

    education_message = Column(Text, nullable=True)
    referral_message = Column(Text, nullable=True)

    screened_at = Column(DateTime, default=datetime.utcnow)

    patient = relationship("Patient", back_populates="child_screenings")


class ConversationSession(Base):
    __tablename__ = "conversation_sessions"

    id = Column(Integer, primary_key=True, index=True)
    phone = Column(String, unique=True, index=True, nullable=False)
    chw_db_id = Column(Integer, ForeignKey("health_workers.id"), nullable=True)
    state = Column(String, default="new_user")
    temp_data_json = Column(Text, default="{}")
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    chw = relationship("HealthWorker", back_populates="sessions")

    @property
    def temp_data(self):
        return json.loads(self.temp_data_json or "{}")

    @temp_data.setter
    def temp_data(self, value):
        self.temp_data_json = json.dumps(value)


def init_db():
    from sqlalchemy import text
    Base.metadata.create_all(bind=engine)
    # Add new columns to existing tables — each in its own transaction.
    # No IF NOT EXISTS: SQLite doesn't support it. The except silently skips
    # columns that already exist on both SQLite and PostgreSQL.
    migrations = [
        "ALTER TABLE health_workers ADD COLUMN district VARCHAR",
        "ALTER TABLE pregnant_screenings ADD COLUMN systolic_bp INTEGER",
        "ALTER TABLE pregnant_screenings ADD COLUMN diastolic_bp INTEGER",
        "ALTER TABLE pregnant_screenings ADD COLUMN bp_status VARCHAR",
    ]
    for sql in migrations:
        try:
            with engine.connect() as conn:
                conn.execute(text(sql))
                conn.commit()
        except Exception:
            pass
