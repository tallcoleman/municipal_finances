from datetime import date, datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class FIRDataSource(SQLModel, table=True):
    __tablename__ = "firdatasource"

    year: int = Field(primary_key=True)
    last_updated: date
    date_posted: date
    file_url: str
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
