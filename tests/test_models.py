"""Tests for the FIR instruction metadata models.

Unit tests verify model instantiation and defaults without a database.
Integration tests (using the `session` fixture) verify unique constraints
and nullable field behaviour against a real PostgreSQL instance.
"""

import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import SQLModel

from municipal_finances.models import (
    FIRColumnMeta,
    FIRInstructionChangelog,
    FIRLineMeta,
    FIRScheduleMeta,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TABLE_NAMES = {t.name for t in SQLModel.metadata.sorted_tables}

EXPECTED_NEW_TABLES = {
    "fir_schedule_meta",
    "fir_line_meta",
    "fir_column_meta",
    "fir_instruction_changelog",
}


def seed_schedule_meta(session, **kwargs):
    """Insert a FIRScheduleMeta row with sensible defaults, overridable via kwargs."""
    defaults = dict(
        schedule="10",
        schedule_name="Revenue",
        category="Revenue",
        description="Consolidated Statement of Operations: Revenue",
    )
    defaults.update(kwargs)
    row = FIRScheduleMeta(**defaults)
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def seed_line_meta(session, **kwargs):
    """Insert a FIRLineMeta row with sensible defaults, overridable via kwargs."""
    defaults = dict(schedule="10", line_id="0010", line_name="Taxation")
    defaults.update(kwargs)
    row = FIRLineMeta(**defaults)
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def seed_column_meta(session, **kwargs):
    """Insert a FIRColumnMeta row with sensible defaults, overridable via kwargs."""
    defaults = dict(schedule="10", column_id="01", column_name="Total")
    defaults.update(kwargs)
    row = FIRColumnMeta(**defaults)
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def seed_changelog(session, **kwargs):
    """Insert a FIRInstructionChangelog row with sensible defaults, overridable via kwargs."""
    defaults = dict(
        year=2023,
        schedule="71",
        change_type="new_schedule",
        source="pdf_changelog",
    )
    defaults.update(kwargs)
    row = FIRInstructionChangelog(**defaults)
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


# ---------------------------------------------------------------------------
# Unit tests — model instantiation (no DB)
# ---------------------------------------------------------------------------


def test_fir_schedule_meta_instantiation():
    """FIRScheduleMeta can be created with required fields."""
    row = FIRScheduleMeta(
        schedule="10",
        schedule_name="Revenue",
        category="Revenue",
        description="General revenue schedule",
    )
    assert row.schedule == "10"
    assert row.schedule_name == "Revenue"
    assert row.category == "Revenue"
    assert row.description == "General revenue schedule"
    assert row.valid_from_year is None
    assert row.valid_to_year is None
    assert row.change_notes is None
    assert row.id is None


def test_fir_line_meta_instantiation():
    """FIRLineMeta can be created with required fields and correct defaults."""
    row = FIRLineMeta(schedule="10", line_id="0010", line_name="Taxation")
    assert row.schedule == "10"
    assert row.line_id == "0010"
    assert row.line_name == "Taxation"
    assert row.is_subtotal is False
    assert row.is_auto_calculated is False
    assert row.schedule_id is None
    assert row.section is None
    assert row.description is None
    assert row.includes is None
    assert row.excludes is None
    assert row.carry_forward_from is None
    assert row.applicability is None
    assert row.valid_from_year is None
    assert row.valid_to_year is None
    assert row.change_notes is None


def test_fir_column_meta_instantiation():
    """FIRColumnMeta can be created with required fields."""
    row = FIRColumnMeta(schedule="10", column_id="01", column_name="Total")
    assert row.schedule == "10"
    assert row.column_id == "01"
    assert row.column_name == "Total"
    assert row.schedule_id is None
    assert row.description is None
    assert row.valid_from_year is None
    assert row.valid_to_year is None
    assert row.change_notes is None


def test_fir_instruction_changelog_instantiation():
    """FIRInstructionChangelog can be created with required fields."""
    row = FIRInstructionChangelog(
        year=2023,
        schedule="71",
        change_type="new_schedule",
        source="pdf_changelog",
    )
    assert row.year == 2023
    assert row.schedule == "71"
    assert row.change_type == "new_schedule"
    assert row.source == "pdf_changelog"
    assert row.slc_pattern is None
    assert row.line_id is None
    assert row.column_id is None
    assert row.heading is None
    assert row.severity is None
    assert row.description is None


def test_fir_line_meta_boolean_defaults():
    """is_subtotal and is_auto_calculated default to False."""
    row = FIRLineMeta(schedule="40", line_id="0100", line_name="General Government")
    assert row.is_subtotal is False
    assert row.is_auto_calculated is False


def test_fir_line_meta_boolean_fields_can_be_set():
    """is_subtotal and is_auto_calculated can be set to True."""
    row = FIRLineMeta(
        schedule="40",
        line_id="9910",
        line_name="Total",
        is_subtotal=True,
        is_auto_calculated=True,
    )
    assert row.is_subtotal is True
    assert row.is_auto_calculated is True


# ---------------------------------------------------------------------------
# Integration tests — require real database (session fixture from conftest.py)
# ---------------------------------------------------------------------------


def test_all_new_tables_registered_in_metadata():
    """All four new tables are registered in SQLModel metadata."""
    assert EXPECTED_NEW_TABLES.issubset(TABLE_NAMES)


def test_fir_schedule_meta_unique_constraint(session):
    """Inserting a duplicate (schedule, valid_from_year, valid_to_year) raises IntegrityError.

    Uses non-NULL year values because PostgreSQL treats NULL as distinct in unique constraints
    (NULL != NULL), so two rows with all-NULL years would not trigger the constraint.
    """
    seed_schedule_meta(session, schedule="10", valid_from_year=2023, valid_to_year=2025)
    with pytest.raises(IntegrityError):
        seed_schedule_meta(session, schedule="10", valid_from_year=2023, valid_to_year=2025)


def test_fir_schedule_meta_different_versions_allowed(session):
    """Two rows with the same schedule but different year ranges are both allowed."""
    seed_schedule_meta(session, schedule="10", valid_from_year=None, valid_to_year=2022)
    seed_schedule_meta(session, schedule="10", valid_from_year=2023, valid_to_year=None)
    # Both inserts succeed — no assertion beyond not raising


def test_fir_line_meta_unique_constraint(session):
    """Inserting a duplicate (schedule, line_id, valid_from_year, valid_to_year) raises IntegrityError.

    Uses non-NULL year values because PostgreSQL treats NULL as distinct in unique constraints.
    """
    seed_line_meta(session, schedule="10", line_id="0010", valid_from_year=2023, valid_to_year=2025)
    with pytest.raises(IntegrityError):
        seed_line_meta(session, schedule="10", line_id="0010", valid_from_year=2023, valid_to_year=2025)


def test_fir_column_meta_unique_constraint(session):
    """Inserting a duplicate (schedule, column_id, valid_from_year, valid_to_year) raises IntegrityError.

    Uses non-NULL year values because PostgreSQL treats NULL as distinct in unique constraints.
    """
    seed_column_meta(session, schedule="10", column_id="01", valid_from_year=2023, valid_to_year=2025)
    with pytest.raises(IntegrityError):
        seed_column_meta(session, schedule="10", column_id="01", valid_from_year=2023, valid_to_year=2025)


def test_fir_instruction_changelog_unique_constraint(session):
    """Inserting a duplicate (year, schedule, slc_pattern, change_type, source) raises IntegrityError."""
    seed_changelog(
        session,
        year=2023,
        schedule="71",
        slc_pattern="71 0010 01",
        change_type="new_line",
        source="pdf_changelog",
    )
    session.rollback()

    with pytest.raises(IntegrityError):
        seed_changelog(
            session,
            year=2023,
            schedule="71",
            slc_pattern="71 0010 01",
            change_type="new_line",
            source="pdf_changelog",
        )


def test_fir_schedule_meta_nullable_fields_accept_none(session):
    """valid_from_year, valid_to_year, and change_notes accept NULL values."""
    row = seed_schedule_meta(
        session,
        valid_from_year=None,
        valid_to_year=None,
        change_notes=None,
    )
    assert row.valid_from_year is None
    assert row.valid_to_year is None
    assert row.change_notes is None


def test_fir_line_meta_nullable_fields_accept_none(session):
    """All optional fields on FIRLineMeta accept NULL values."""
    row = seed_line_meta(
        session,
        schedule_id=None,
        section=None,
        description=None,
        includes=None,
        excludes=None,
        carry_forward_from=None,
        applicability=None,
        valid_from_year=None,
        valid_to_year=None,
        change_notes=None,
    )
    assert row.schedule_id is None
    assert row.section is None
    assert row.description is None
    assert row.includes is None
    assert row.excludes is None
    assert row.carry_forward_from is None
    assert row.applicability is None
    assert row.valid_from_year is None
    assert row.valid_to_year is None
    assert row.change_notes is None


def test_fir_column_meta_nullable_fields_accept_none(session):
    """All optional fields on FIRColumnMeta accept NULL values."""
    row = seed_column_meta(
        session,
        schedule_id=None,
        description=None,
        valid_from_year=None,
        valid_to_year=None,
        change_notes=None,
    )
    assert row.schedule_id is None
    assert row.description is None
    assert row.valid_from_year is None
    assert row.valid_to_year is None
    assert row.change_notes is None


def test_fir_instruction_changelog_nullable_fields_accept_none(session):
    """All optional fields on FIRInstructionChangelog accept NULL values."""
    row = seed_changelog(
        session,
        slc_pattern=None,
        line_id=None,
        column_id=None,
        heading=None,
        severity=None,
        description=None,
    )
    assert row.slc_pattern is None
    assert row.line_id is None
    assert row.column_id is None
    assert row.heading is None
    assert row.severity is None
    assert row.description is None


def test_clear_db_includes_new_tables(mocker):
    """clear-db deletes from all four new metadata tables."""
    from typer.testing import CliRunner

    from municipal_finances.app import app

    mocker.patch("municipal_finances.db_management.get_engine")
    mock_session = mocker.MagicMock()
    mock_session.__enter__ = mocker.MagicMock(return_value=mock_session)
    mock_session.__exit__ = mocker.MagicMock(return_value=False)
    mocker.patch("municipal_finances.db_management.Session", return_value=mock_session)

    runner = CliRunner()
    result = runner.invoke(app, ["clear-db", "--yes"])

    assert result.exit_code == 0
    deleted_tables = {
        call.args[0].table.name for call in mock_session.execute.call_args_list
    }
    assert EXPECTED_NEW_TABLES.issubset(deleted_tables)
