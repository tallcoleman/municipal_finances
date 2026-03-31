from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session, select

from municipal_finances.database import get_session
from municipal_finances.models import FIRRecord

router = APIRouter()

SessionDep = Annotated[Session, Depends(get_session)]


@router.get("/", response_model=list[FIRRecord])
def list_fir_records(
    session: SessionDep,
    munid: Optional[str] = None,
    marsyear: Optional[int] = None,
    schedule_desc: Optional[str] = None,
    slc: Optional[str] = None,
    offset: int = 0,
    limit: int = Query(default=100, le=1000),
):
    query = select(FIRRecord)
    if munid is not None:
        query = query.where(FIRRecord.munid == munid)
    if marsyear is not None:
        query = query.where(FIRRecord.marsyear == marsyear)
    if schedule_desc is not None:
        query = query.where(FIRRecord.schedule_desc == schedule_desc)
    if slc is not None:
        query = query.where(FIRRecord.slc == slc)
    query = query.offset(offset).limit(limit)
    return session.exec(query).all()
