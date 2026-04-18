"""add_section_name_to_fir_column_meta

Revision ID: cbb231d92caa
Revises: 0e3aaec3cbcb
Create Date: 2026-04-18 04:48:52.347939

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'cbb231d92caa'
down_revision: Union[str, Sequence[str], None] = '0e3aaec3cbcb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('fir_column_meta', sa.Column('section_name', sa.VARCHAR(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('fir_column_meta', 'section_name')
