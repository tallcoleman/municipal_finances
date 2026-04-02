from municipal_finances.models import FIRDataSource, FIRRecord, Municipality

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

MUNI = Municipality(
    munid="TST001", municipality_desc="Test City", tier_code="LT", mtype_code=1
)
MUNI2 = Municipality(
    munid="TST002", municipality_desc="Test Town", tier_code="ST", mtype_code=4
)


def seed_municipality(session, **kwargs):
    """Insert a Municipality row with sensible defaults, overridable via kwargs."""
    defaults = dict(
        munid="TST001", municipality_desc="Test City", tier_code="LT", mtype_code=1
    )
    defaults.update(kwargs)
    muni = Municipality(**defaults)
    session.add(muni)
    session.commit()
    session.refresh(muni)
    return muni


def seed_fir_record(session, munid="TST001", **kwargs):
    """Insert a FIRRecord row with sensible defaults, overridable via kwargs."""
    defaults = dict(munid=munid, marsyear=2023, schedule_desc="Schedule A", slc="1000")
    defaults.update(kwargs)
    record = FIRRecord(**defaults)
    session.add(record)
    session.commit()
    session.refresh(record)
    return record


def seed_fir_source(session, year=2023, **kwargs):
    """Insert a FIRDataSource row with sensible defaults, overridable via kwargs."""
    source = FIRDataSource(year=year, **kwargs)
    session.add(source)
    session.commit()
    session.refresh(source)
    return source


# ---------------------------------------------------------------------------
# main.py — root redirect
# ---------------------------------------------------------------------------


def test_root_redirects_to_docs(client):
    """GET / returns a 307 redirect pointing to /docs."""
    response = client.get("/")
    assert response.status_code == 307
    assert response.headers["location"] == "/docs"


# ---------------------------------------------------------------------------
# municipalities.py
# ---------------------------------------------------------------------------


def test_list_municipalities_empty(client):
    """GET /municipalities/ returns an empty list when no municipalities exist."""
    response = client.get("/municipalities/")
    assert response.status_code == 200
    assert response.json() == []


def test_list_municipalities_returns_data(client, session):
    """GET /municipalities/ returns seeded municipalities."""
    seed_municipality(session)
    response = client.get("/municipalities/")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["munid"] == "TST001"


def test_list_municipalities_filter_tier_code(client, session):
    """GET /municipalities/?tier_code= returns only municipalities matching that tier."""
    seed_municipality(session, munid="TST001", tier_code="LT")
    seed_municipality(session, munid="TST002", tier_code="ST")
    response = client.get("/municipalities/?tier_code=LT")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["tier_code"] == "LT"


def test_list_municipalities_filter_mtype_code(client, session):
    """GET /municipalities/?mtype_code= returns only municipalities matching that type."""
    seed_municipality(session, munid="TST001", mtype_code=1)
    seed_municipality(session, munid="TST002", mtype_code=4)
    response = client.get("/municipalities/?mtype_code=4")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["mtype_code"] == 4


def test_list_municipalities_offset_limit(client, session):
    """GET /municipalities/?offset=&limit= returns the correct page of results."""
    seed_municipality(session, munid="TST001")
    seed_municipality(session, munid="TST002")
    response = client.get("/municipalities/?offset=1&limit=1")
    assert response.status_code == 200
    assert len(response.json()) == 1


def test_get_municipality_found(client, session):
    """GET /municipalities/{munid} returns the municipality when it exists."""
    seed_municipality(session, munid="TST001", municipality_desc="Test City")
    response = client.get("/municipalities/TST001")
    assert response.status_code == 200
    assert response.json()["munid"] == "TST001"
    assert response.json()["municipality_desc"] == "Test City"


def test_get_municipality_not_found(client):
    """GET /municipalities/{munid} returns 404 when the munid does not exist."""
    response = client.get("/municipalities/MISSING")
    assert response.status_code == 404
    assert response.json()["detail"] == "Municipality not found"


# ---------------------------------------------------------------------------
# fir_records.py
# ---------------------------------------------------------------------------


def test_list_fir_records_empty(client):
    """GET /records/ returns an empty list when no records exist."""
    response = client.get("/records/")
    assert response.status_code == 200
    assert response.json() == []


def test_list_fir_records_returns_data(client, session):
    """GET /records/ returns seeded FIR records."""
    seed_municipality(session)
    seed_fir_record(session)
    response = client.get("/records/")
    assert response.status_code == 200
    assert len(response.json()) == 1


def test_list_fir_records_filter_munid(client, session):
    """GET /records/?munid= returns only records for the specified municipality."""
    seed_municipality(session, munid="TST001")
    seed_municipality(session, munid="TST002")
    seed_fir_record(session, munid="TST001")
    seed_fir_record(session, munid="TST002")
    response = client.get("/records/?munid=TST001")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["munid"] == "TST001"


def test_list_fir_records_filter_marsyear(client, session):
    """GET /records/?marsyear= returns only records for the specified reporting year."""
    seed_municipality(session)
    seed_fir_record(session, marsyear=2022)
    seed_fir_record(session, marsyear=2023)
    response = client.get("/records/?marsyear=2022")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["marsyear"] == 2022


def test_list_fir_records_filter_schedule_desc(client, session):
    """GET /records/?schedule_desc= returns only records matching that schedule."""
    seed_municipality(session)
    seed_fir_record(session, schedule_desc="Schedule A")
    seed_fir_record(session, schedule_desc="Schedule B")
    response = client.get("/records/?schedule_desc=Schedule+A")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["schedule_desc"] == "Schedule A"


def test_list_fir_records_filter_slc(client, session):
    """GET /records/?slc= returns only records matching that SLC code."""
    seed_municipality(session)
    seed_fir_record(session, slc="1000")
    seed_fir_record(session, slc="2000")
    response = client.get("/records/?slc=1000")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["slc"] == "1000"


def test_list_fir_records_limit_capped(client):
    """GET /records/?limit= returns 422 when limit exceeds the maximum of 1000."""
    response = client.get("/records/?limit=1001")
    assert response.status_code == 422


def test_list_fir_records_offset_limit(client, session):
    """GET /records/?offset=&limit= returns the correct page of results."""
    seed_municipality(session)
    seed_fir_record(session, slc="1000")
    seed_fir_record(session, slc="2000")
    response = client.get("/records/?offset=1&limit=1")
    assert response.status_code == 200
    assert len(response.json()) == 1


# ---------------------------------------------------------------------------
# fir_sources.py
# ---------------------------------------------------------------------------


def test_list_fir_sources_empty(client):
    """GET /sources/ returns an empty list when no sources exist."""
    response = client.get("/sources/")
    assert response.status_code == 200
    assert response.json() == []


def test_list_fir_sources_returns_data_ordered_by_year(client, session):
    """GET /sources/ returns all sources sorted ascending by year."""
    seed_fir_source(session, year=2022)
    seed_fir_source(session, year=2020)
    seed_fir_source(session, year=2021)
    response = client.get("/sources/")
    assert response.status_code == 200
    years = [s["year"] for s in response.json()]
    assert years == [2020, 2021, 2022]


def test_get_fir_source_found(client, session):
    """GET /sources/{year} returns the source when the year exists."""
    seed_fir_source(session, year=2023)
    response = client.get("/sources/2023")
    assert response.status_code == 200
    assert response.json()["year"] == 2023


def test_get_fir_source_not_found(client):
    """GET /sources/{year} returns 404 when the year does not exist."""
    response = client.get("/sources/1999")
    assert response.status_code == 404
    assert response.json()["detail"] == "Year not found"
