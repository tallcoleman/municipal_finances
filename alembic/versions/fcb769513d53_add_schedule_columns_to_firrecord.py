"""add schedule columns to firrecord

Revision ID: fcb769513d53
Revises: cbb231d92caa
Create Date: 2026-04-30 07:40:40.295501

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'fcb769513d53'
down_revision: Union[str, Sequence[str], None] = 'cbb231d92caa'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('firrecord', sa.Column('schedule_code', sa.VARCHAR(length=3), nullable=True))
    op.add_column('firrecord', sa.Column('base_schedule_code', sa.VARCHAR(length=2), nullable=True))
    op.add_column('firrecord', sa.Column('sub_schedule_code', sa.VARCHAR(length=1), nullable=True))
    op.add_column('firrecord', sa.Column('line_id', sa.VARCHAR(length=4), nullable=True))
    op.add_column('firrecord', sa.Column('column_section', sa.VARCHAR(length=2), nullable=True))
    op.add_column('firrecord', sa.Column('column_id', sa.VARCHAR(length=2), nullable=True))

    conn = op.get_context().connection

    row = conn.execute(sa.text(
        "SELECT MIN(id), MAX(id) FROM firrecord WHERE slc IS NOT NULL"
    )).fetchone()
    min_id, max_id = row

    if min_id is not None:
        chunk_size = 500_000
        total_ids = max_id - min_id + 1
        num_chunks = -(-total_ids // chunk_size)  # ceiling division
        total_updated = 0

        for i, start in enumerate(range(min_id, max_id + 1, chunk_size), 1):
            end = start + chunk_size - 1
            result = conn.execute(sa.text("""
                UPDATE firrecord
                SET
                    schedule_code      = CASE WHEN RIGHT(split_part(slc, '.', 2), 1) = 'X'
                                              THEN LEFT(split_part(slc, '.', 2), 2)
                                              ELSE split_part(slc, '.', 2) END,
                    base_schedule_code = LEFT(split_part(slc, '.', 2), 2),
                    sub_schedule_code  = CASE WHEN RIGHT(split_part(slc, '.', 2), 1) = 'X'
                                              THEN NULL
                                              ELSE RIGHT(split_part(slc, '.', 2), 1) END,
                    line_id            = SUBSTRING(split_part(slc, '.', 3), 2),
                    column_section     = SUBSTRING(split_part(slc, '.', 4), 2),
                    column_id          = split_part(slc, '.', 5)
                WHERE id BETWEEN :start AND :end
                  AND slc IS NOT NULL
            """), {"start": start, "end": end})
            total_updated += result.rowcount
            print(
                f"  Backfilling firrecord: chunk {i}/{num_chunks}"
                f" ({total_updated:,} rows updated so far)",
                flush=True,
            )

        print(f"  Backfill complete: {total_updated:,} rows updated.", flush=True)

    op.create_index('ix_firrecord_schedule_code', 'firrecord', ['schedule_code'], unique=False)
    op.create_index('ix_firrecord_base_schedule_code', 'firrecord', ['base_schedule_code'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_firrecord_schedule_code', table_name='firrecord')
    op.drop_index('ix_firrecord_base_schedule_code', table_name='firrecord')
    op.drop_column('firrecord', 'column_id')
    op.drop_column('firrecord', 'column_section')
    op.drop_column('firrecord', 'line_id')
    op.drop_column('firrecord', 'sub_schedule_code')
    op.drop_column('firrecord', 'base_schedule_code')
    op.drop_column('firrecord', 'schedule_code')
