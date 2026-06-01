"""Route-level auth enforcement tests.

Verifies that all GET endpoints return 401 without a token, 403 with a
token that carries no recognized role, and 200 with a valid viewer token.
Uses its own test client that does NOT bypass require_viewer, so the
enforcement is exercised for real.
"""

import pytest
from starlette.testclient import TestClient

from municipal_finances.api.main import app
from municipal_finances.database import get_session

ALL_GET_ROUTES = [
    "/municipalities/",
    "/municipalities/DOESNOTEXIST",
    "/records/",
    "/sources/",
    "/sources/9999",
]


def _mock_introspection(mocker, claims):
    """Patch httpx.post to return an introspection response with the given claims."""
    mock_response = mocker.MagicMock()
    mock_response.json.return_value = claims
    mock_response.raise_for_status.return_value = None
    return mocker.patch("httpx.post", return_value=mock_response)


@pytest.fixture()
def enforcement_client(session, mocker):
    """TestClient that enforces auth (no require_viewer bypass).

    Patches httpx.post so introspection calls use controlled claims
    rather than hitting a real Keycloak instance.
    """
    def override_get_session():
        yield session

    app.dependency_overrides[get_session] = override_get_session
    # Intentionally do NOT override require_viewer — enforcement is the point.
    with TestClient(app, follow_redirects=False) as c:
        yield c
    app.dependency_overrides.pop(get_session, None)


@pytest.mark.parametrize("path", ALL_GET_ROUTES)
def test_no_token_returns_401(enforcement_client, path):
    response = enforcement_client.get(path)
    assert response.status_code == 401


@pytest.mark.parametrize("path", ALL_GET_ROUTES)
def test_no_valid_role_returns_403(enforcement_client, path, mocker):
    _mock_introspection(mocker, {"active": True, "sub": "test-user", "realm_access": {"roles": []}})
    response = enforcement_client.get(path, headers={"Authorization": "Bearer any-token"})
    assert response.status_code == 403


@pytest.mark.parametrize("path", ALL_GET_ROUTES)
def test_viewer_token_returns_200(enforcement_client, path, mocker):
    _mock_introspection(mocker, {"active": True, "sub": "test-user", "realm_access": {"roles": ["viewer"]}})
    response = enforcement_client.get(path, headers={"Authorization": "Bearer any-token"})
    # 200 or 404 (for routes that look up a specific resource that doesn't exist)
    assert response.status_code in (200, 404)
