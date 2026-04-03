from datetime import date, datetime
from typing import Optional

from sqlalchemy import Index, UniqueConstraint
from sqlmodel import Field, SQLModel


class FIRDataSource(SQLModel, table=True):
    __tablename__ = "firdatasource"

    year: int = Field(primary_key=True)
    last_updated: Optional[date] = Field(default=None)
    date_posted: Optional[date] = Field(default=None)
    file_url: Optional[str] = Field(default=None)
    loaded_into_db: bool = Field(default=False)
    loaded_at: Optional[datetime] = Field(default=None)


class Municipality(SQLModel, table=True):
    __tablename__ = "municipality"

    munid: str = Field(primary_key=True, max_length=10)
    assessment_code: Optional[str] = Field(default=None)
    municipality_desc: Optional[str] = Field(default=None)
    mso_number: Optional[str] = Field(default=None, max_length=5)
    sgc_code: Optional[str] = Field(default=None, max_length=10)
    ut_number: Optional[str] = Field(default=None, max_length=10)
    mtype_code: Optional[int] = Field(default=None)  # 0=UT, 1=City, 3=Sep.Town, 4=Town, 5=Village, 6=Township
    tier_code: Optional[str] = Field(default=None, max_length=5)  # LT / ST / UT


class FIRRecord(SQLModel, table=True):
    __tablename__ = "firrecord"

    id: Optional[int] = Field(default=None, primary_key=True)
    munid: str = Field(foreign_key="municipality.munid", index=True)
    marsyear: int = Field(index=True)
    schedule_desc: Optional[str] = Field(default=None)
    sub_schedule_desc: Optional[str] = Field(default=None)
    schedule_line_desc: Optional[str] = Field(default=None)
    schedule_column_desc: Optional[str] = Field(default=None)
    slc: Optional[str] = Field(default=None, max_length=30)
    datatype_desc: Optional[str] = Field(default=None, max_length=30)
    amount: Optional[float] = Field(default=None)
    value_text: Optional[str] = Field(default=None)
    last_update_date: Optional[str] = Field(default=None)


class FIRScheduleMeta(SQLModel, table=True):
    """One row per (schedule, version). Describes a FIR schedule as a whole."""

    __tablename__ = "fir_schedule_meta"
    __table_args__ = (
        UniqueConstraint("schedule", "valid_from_year", "valid_to_year"),
        Index("ix_fir_schedule_meta_schedule", "schedule"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    schedule: str = Field()  # natural key, e.g. "10", "51A", "74E"
    schedule_name: str = Field()
    category: str = Field()
    description: str = Field()
    valid_from_year: Optional[int] = Field(default=None)  # NULL = before earliest PDF
    valid_to_year: Optional[int] = Field(default=None)  # NULL = still current
    change_notes: Optional[str] = Field(default=None)


class FIRLineMeta(SQLModel, table=True):
    """One row per (schedule, line, version). Covers Functional Classifications content and schedule-specific reporting rules."""

    __tablename__ = "fir_line_meta"
    __table_args__ = (
        UniqueConstraint("schedule", "line_id", "valid_from_year", "valid_to_year"),
        Index("ix_fir_line_meta_schedule", "schedule"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    schedule_id: Optional[int] = Field(default=None, foreign_key="fir_schedule_meta.id")
    schedule: str = Field()  # denormalized from fir_schedule_meta.schedule
    line_id: str = Field(max_length=4)  # 4-digit string, e.g. "0410"
    line_name: str = Field()
    section: Optional[str] = Field(default=None)  # section heading within the schedule
    description: Optional[str] = Field(default=None)
    includes: Optional[str] = Field(default=None)
    excludes: Optional[str] = Field(default=None)
    is_subtotal: bool = Field(default=False)
    is_auto_calculated: bool = Field(default=False)
    carry_forward_from: Optional[str] = Field(default=None)  # SLC ref if auto-populated
    applicability: Optional[str] = Field(default=None)
    valid_from_year: Optional[int] = Field(default=None)
    valid_to_year: Optional[int] = Field(default=None)
    change_notes: Optional[str] = Field(default=None)


class FIRColumnMeta(SQLModel, table=True):
    """One row per (schedule, column, version)."""

    __tablename__ = "fir_column_meta"
    __table_args__ = (
        UniqueConstraint("schedule", "column_id", "valid_from_year", "valid_to_year"),
        Index("ix_fir_column_meta_schedule", "schedule"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    schedule_id: Optional[int] = Field(default=None, foreign_key="fir_schedule_meta.id")
    schedule: str = Field()  # denormalized from fir_schedule_meta.schedule
    column_id: str = Field(max_length=2)  # 2-digit string, e.g. "01"
    column_name: str = Field()
    description: Optional[str] = Field(default=None)
    valid_from_year: Optional[int] = Field(default=None)
    valid_to_year: Optional[int] = Field(default=None)
    change_notes: Optional[str] = Field(default=None)


class FIRInstructionChangelog(SQLModel, table=True):
    """One row per documented or inferred change event.

    Source of truth for valid_from_year/valid_to_year on the metadata tables.
    Note: slc_pattern is nullable. PostgreSQL treats NULLs as distinct in unique
    constraints, so duplicate schedule-level entries (slc_pattern=NULL) must be
    deduplicated at the application level during insertion.
    """

    __tablename__ = "fir_instruction_changelog"
    __table_args__ = (
        UniqueConstraint("year", "schedule", "slc_pattern", "change_type", "source"),
        Index("ix_fir_instruction_changelog_year", "year"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    year: int = Field()  # FIR year in which the change took effect
    schedule: str = Field()
    slc_pattern: Optional[str] = Field(default=None)  # may contain wildcards, e.g. "40 xxxx 05"
    line_id: Optional[str] = Field(default=None)
    column_id: Optional[str] = Field(default=None)
    heading: Optional[str] = Field(default=None)
    change_type: str = Field()  # e.g. new_schedule, deleted_line, updated_column, inferred_new
    severity: Optional[str] = Field(default=None)  # "major" or "minor"; NULL for inferred
    description: Optional[str] = Field(default=None)
    source: str = Field()  # "pdf_changelog" or "data_inferred"
