"""create_initial_schema

Revision ID: 7a3f8b2e1d9c
Revises:
Create Date: 2026-05-31 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = '7a3f8b2e1d9c'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create all tables in their original pre-migration state."""
    op.create_table(
        'firdatasource',
        sa.Column('year', sa.Integer(), nullable=False),
        sa.Column('last_updated', sa.Date(), nullable=False),
        sa.Column('date_posted', sa.Date(), nullable=False),
        sa.Column('file_url', sa.VARCHAR(), nullable=False),
        sa.Column('loaded_into_db', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('loaded_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('year'),
    )
    op.create_table(
        'municipality',
        sa.Column('munid', sa.VARCHAR(length=10), nullable=False),
        sa.Column('assessment_code', sa.VARCHAR(), nullable=True),
        sa.Column('municipality_desc', sa.VARCHAR(), nullable=True),
        sa.Column('mso_number', sa.VARCHAR(length=5), nullable=True),
        sa.Column('sgc_code', sa.VARCHAR(length=10), nullable=True),
        sa.Column('ut_number', sa.VARCHAR(length=10), nullable=True),
        sa.Column('mtype_code', sa.Integer(), nullable=True),
        sa.Column('tier_code', sa.VARCHAR(length=5), nullable=True),
        sa.PrimaryKeyConstraint('munid'),
    )
    op.create_table(
        'firrecord',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('munid', sa.VARCHAR(), nullable=False),
        sa.Column('marsyear', sa.Integer(), nullable=False),
        sa.Column('schedule_desc', sa.VARCHAR(), nullable=True),
        sa.Column('sub_schedule_desc', sa.VARCHAR(), nullable=True),
        sa.Column('schedule_line_desc', sa.VARCHAR(), nullable=True),
        sa.Column('schedule_column_desc', sa.VARCHAR(), nullable=True),
        sa.Column('slc', sa.VARCHAR(length=30), nullable=True),
        sa.Column('datatype_desc', sa.VARCHAR(length=30), nullable=True),
        sa.Column('amount', sa.Float(), nullable=True),
        sa.Column('value_text', sa.VARCHAR(), nullable=True),
        sa.Column('last_update_date', sa.VARCHAR(), nullable=True),
        sa.ForeignKeyConstraint(['munid'], ['municipality.munid']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_firrecord_munid', 'firrecord', ['munid'], unique=False)
    op.create_index('ix_firrecord_marsyear', 'firrecord', ['marsyear'], unique=False)
    op.create_table(
        'fir_schedule_meta',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('schedule', sa.VARCHAR(), nullable=False),
        sa.Column('schedule_name', sa.VARCHAR(), nullable=False),
        sa.Column('category', sa.VARCHAR(), nullable=False),
        sa.Column('description', sa.VARCHAR(), nullable=False),
        sa.Column('valid_from_year', sa.Integer(), nullable=True),
        sa.Column('valid_to_year', sa.Integer(), nullable=True),
        sa.Column('change_notes', sa.VARCHAR(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('schedule', 'valid_from_year', 'valid_to_year'),
    )
    op.create_index('ix_fir_schedule_meta_schedule', 'fir_schedule_meta', ['schedule'], unique=False)
    op.create_table(
        'fir_line_meta',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('schedule_id', sa.Integer(), nullable=True),
        sa.Column('schedule', sa.VARCHAR(), nullable=False),
        sa.Column('line_id', sa.VARCHAR(length=4), nullable=False),
        sa.Column('line_name', sa.VARCHAR(), nullable=False),
        sa.Column('section', sa.VARCHAR(), nullable=True),
        sa.Column('description', sa.VARCHAR(), nullable=True),
        sa.Column('is_subtotal', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('is_auto_calculated', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('carry_forward_from', sa.VARCHAR(), nullable=True),
        sa.Column('applicability', sa.VARCHAR(), nullable=True),
        sa.Column('valid_from_year', sa.Integer(), nullable=True),
        sa.Column('valid_to_year', sa.Integer(), nullable=True),
        sa.Column('change_notes', sa.VARCHAR(), nullable=True),
        sa.ForeignKeyConstraint(['schedule_id'], ['fir_schedule_meta.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('schedule', 'line_id', 'valid_from_year', 'valid_to_year'),
    )
    op.create_index('ix_fir_line_meta_schedule', 'fir_line_meta', ['schedule'], unique=False)
    op.create_table(
        'fir_column_meta',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('schedule_id', sa.Integer(), nullable=True),
        sa.Column('schedule', sa.VARCHAR(), nullable=False),
        sa.Column('column_id', sa.VARCHAR(length=2), nullable=False),
        sa.Column('column_name', sa.VARCHAR(), nullable=False),
        sa.Column('description', sa.VARCHAR(), nullable=True),
        sa.Column('valid_from_year', sa.Integer(), nullable=True),
        sa.Column('valid_to_year', sa.Integer(), nullable=True),
        sa.Column('change_notes', sa.VARCHAR(), nullable=True),
        sa.ForeignKeyConstraint(['schedule_id'], ['fir_schedule_meta.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('schedule', 'column_id', 'valid_from_year', 'valid_to_year'),
    )
    op.create_index('ix_fir_column_meta_schedule', 'fir_column_meta', ['schedule'], unique=False)
    op.create_table(
        'fir_instruction_changelog',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('year', sa.Integer(), nullable=False),
        sa.Column('schedule', sa.VARCHAR(), nullable=False),
        sa.Column('slc_pattern', sa.VARCHAR(), nullable=True),
        sa.Column('line_id', sa.VARCHAR(), nullable=True),
        sa.Column('column_id', sa.VARCHAR(), nullable=True),
        sa.Column('heading', sa.VARCHAR(), nullable=True),
        sa.Column('change_type', sa.VARCHAR(), nullable=False),
        sa.Column('severity', sa.VARCHAR(), nullable=True),
        sa.Column('description', sa.VARCHAR(), nullable=True),
        sa.Column('source', sa.VARCHAR(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('year', 'schedule', 'slc_pattern', 'change_type', 'source'),
    )
    op.create_index('ix_fir_instruction_changelog_year', 'fir_instruction_changelog', ['year'], unique=False)


def downgrade() -> None:
    """Drop all tables."""
    op.drop_index('ix_fir_instruction_changelog_year', table_name='fir_instruction_changelog')
    op.drop_table('fir_instruction_changelog')
    op.drop_index('ix_fir_column_meta_schedule', table_name='fir_column_meta')
    op.drop_table('fir_column_meta')
    op.drop_index('ix_fir_line_meta_schedule', table_name='fir_line_meta')
    op.drop_table('fir_line_meta')
    op.drop_index('ix_fir_schedule_meta_schedule', table_name='fir_schedule_meta')
    op.drop_table('fir_schedule_meta')
    op.drop_index('ix_firrecord_marsyear', table_name='firrecord')
    op.drop_index('ix_firrecord_munid', table_name='firrecord')
    op.drop_table('firrecord')
    op.drop_table('municipality')
    op.drop_table('firdatasource')
