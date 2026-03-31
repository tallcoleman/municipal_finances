from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from municipal_finances.database import get_session
from municipal_finances.models import Municipality

router = APIRouter()

SessionDep = Annotated[Session, Depends(get_session)]


@router.get("/", response_model=list[Municipality])
def list_municipalities(
    session: SessionDep,
    tier_code: Optional[str] = None,
    mtype_code: Optional[int] = None,
    offset: int = 0,
    limit: int = 100,
):
    query = select(Municipality)
    if tier_code is not None:
        query = query.where(Municipality.tier_code == tier_code)
    if mtype_code is not None:
        query = query.where(Municipality.mtype_code == mtype_code)
    query = query.offset(offset).limit(limit)
    return session.exec(query).all()


@router.get("/{munid}", response_model=Municipality)
def get_municipality(munid: str, session: SessionDep):
    municipality = session.get(Municipality, munid)
    if not municipality:
        raise HTTPException(status_code=404, detail="Municipality not found")
    return municipality
