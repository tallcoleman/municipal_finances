from fastapi import FastAPI
from fastapi.responses import RedirectResponse

from municipal_finances.api.routes import fir_records, fir_sources, municipalities

app = FastAPI(title="Municipal Finances API")


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse(url="/docs")

app.include_router(municipalities.router, prefix="/municipalities", tags=["municipalities"])
app.include_router(fir_records.router, prefix="/records", tags=["records"])
app.include_router(fir_sources.router, prefix="/sources", tags=["sources"])
