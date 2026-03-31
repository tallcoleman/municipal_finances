from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from municipal_finances.database import get_session
from municipal_finances.models import FIRDataSource

router = APIRouter()

SessionDep = Annotated[Session, Depends(get_session)]


@router.get("/", response_model=list[FIRDataSource])
def list_fir_sources(session: SessionDep):
    return session.exec(select(FIRDataSource).order_by(FIRDataSource.year)).all()


@router.get("/{year}", response_model=FIRDataSource)
def get_fir_source(year: int, session: SessionDep):
    source = session.get(FIRDataSource, year)
    if not source:
        raise HTTPException(status_code=404, detail="Year not found")
    return source
