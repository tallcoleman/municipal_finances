"""Unit tests for src/municipal_finances/api/auth.py."""

import pytest
from fastapi import HTTPException

import municipal_finances.api.auth as auth_module
from municipal_finances.api.auth import get_roles, introspect_token, require_administrator, require_editor, require_viewer

_ACTIVE_CLAIMS = {
    "active": True,
    "sub": "user-123",
    "realm_access": {"roles": ["viewer"]},
}


def _mock_introspection(mocker, claims):
    """Patch httpx.post to return a successful introspection response."""
    mock_response = mocker.MagicMock()
    mock_response.json.return_value = claims
    mock_response.raise_for_status.return_value = None
    mocker.patch("httpx.post", return_value=mock_response)
    return mock_response


# ---------------------------------------------------------------------------
# introspect_token
# ---------------------------------------------------------------------------


def test_introspect_token_active(mocker):
    _mock_introspection(mocker, _ACTIVE_CLAIMS)
    claims = introspect_token("any-token")
    assert claims["sub"] == "user-123"
    assert claims["realm_access"]["roles"] == ["viewer"]


def test_introspect_token_inactive_raises_401(mocker):
    _mock_introspection(mocker, {"active": False})
    with pytest.raises(HTTPException) as exc_info:
        introspect_token("any-token")
    assert exc_info.value.status_code == 401


def test_introspect_token_missing_active_field_raises_401(mocker):
    _mock_introspection(mocker, {"sub": "user-123"})
    with pytest.raises(HTTPException) as exc_info:
        introspect_token("any-token")
    assert exc_info.value.status_code == 401


def test_introspect_token_http_error_raises_401(mocker):
    import httpx

    mocker.patch("httpx.post", side_effect=httpx.ConnectError("connection refused"))
    with pytest.raises(HTTPException) as exc_info:
        introspect_token("any-token")
    assert exc_info.value.status_code == 401


def test_introspect_token_keycloak_5xx_raises_401(mocker):
    import httpx

    mock_response = mocker.MagicMock()
    mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "500", request=mocker.MagicMock(), response=mocker.MagicMock()
    )
    mocker.patch("httpx.post", return_value=mock_response)
    with pytest.raises(HTTPException) as exc_info:
        introspect_token("any-token")
    assert exc_info.value.status_code == 401


def test_introspect_token_sends_client_credentials(mocker):
    """Verify client_id and client_secret are included in the POST body."""
    mock_post = mocker.patch("httpx.post")
    mock_post.return_value.json.return_value = _ACTIVE_CLAIMS
    mock_post.return_value.raise_for_status.return_value = None

    introspect_token("my-token")

    _, kwargs = mock_post.call_args
    assert kwargs["data"]["token"] == "my-token"
    assert kwargs["data"]["client_id"] == auth_module.KEYCLOAK_CLIENT_ID
    assert "client_secret" in kwargs["data"]


# ---------------------------------------------------------------------------
# get_roles
# ---------------------------------------------------------------------------


def test_get_roles_extracts_roles():
    claims = {"realm_access": {"roles": ["viewer", "offline_access"]}}
    assert get_roles(claims) == ["viewer", "offline_access"]


def test_get_roles_missing_realm_access():
    assert get_roles({}) == []


def test_get_roles_empty_roles():
    assert get_roles({"realm_access": {"roles": []}}) == []


# ---------------------------------------------------------------------------
# require_viewer
# ---------------------------------------------------------------------------


def test_require_viewer_passes_for_viewer(mocker):
    _mock_introspection(mocker, {**_ACTIVE_CLAIMS, "realm_access": {"roles": ["viewer"]}})
    claims = require_viewer(token="any-token")
    assert claims["sub"] == "user-123"


def test_require_viewer_passes_for_editor(mocker):
    _mock_introspection(mocker, {**_ACTIVE_CLAIMS, "realm_access": {"roles": ["editor"]}})
    claims = require_viewer(token="any-token")
    assert claims["sub"] == "user-123"


def test_require_viewer_passes_for_administrator(mocker):
    _mock_introspection(mocker, {**_ACTIVE_CLAIMS, "realm_access": {"roles": ["administrator"]}})
    claims = require_viewer(token="any-token")
    assert claims["sub"] == "user-123"


def test_require_viewer_raises_403_for_no_role(mocker):
    _mock_introspection(mocker, {**_ACTIVE_CLAIMS, "realm_access": {"roles": []}})
    with pytest.raises(HTTPException) as exc_info:
        require_viewer(token="any-token")
    assert exc_info.value.status_code == 403


def test_require_viewer_raises_403_for_unknown_role(mocker):
    _mock_introspection(mocker, {**_ACTIVE_CLAIMS, "realm_access": {"roles": ["some_other_role"]}})
    with pytest.raises(HTTPException) as exc_info:
        require_viewer(token="any-token")
    assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# require_editor
# ---------------------------------------------------------------------------


def test_require_editor_passes_for_editor(mocker):
    _mock_introspection(mocker, {**_ACTIVE_CLAIMS, "realm_access": {"roles": ["editor"]}})
    claims = require_editor(token="any-token")
    assert claims["sub"] == "user-123"


def test_require_editor_passes_for_administrator(mocker):
    _mock_introspection(mocker, {**_ACTIVE_CLAIMS, "realm_access": {"roles": ["administrator"]}})
    claims = require_editor(token="any-token")
    assert claims["sub"] == "user-123"


def test_require_editor_raises_403_for_viewer(mocker):
    _mock_introspection(mocker, {**_ACTIVE_CLAIMS, "realm_access": {"roles": ["viewer"]}})
    with pytest.raises(HTTPException) as exc_info:
        require_editor(token="any-token")
    assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# require_administrator
# ---------------------------------------------------------------------------


def test_require_administrator_passes_for_administrator(mocker):
    _mock_introspection(mocker, {**_ACTIVE_CLAIMS, "realm_access": {"roles": ["administrator"]}})
    claims = require_administrator(token="any-token")
    assert claims["sub"] == "user-123"


def test_require_administrator_raises_403_for_editor(mocker):
    _mock_introspection(mocker, {**_ACTIVE_CLAIMS, "realm_access": {"roles": ["editor"]}})
    with pytest.raises(HTTPException) as exc_info:
        require_administrator(token="any-token")
    assert exc_info.value.status_code == 403


def test_require_administrator_raises_403_for_viewer(mocker):
    _mock_introspection(mocker, {**_ACTIVE_CLAIMS, "realm_access": {"roles": ["viewer"]}})
    with pytest.raises(HTTPException) as exc_info:
        require_administrator(token="any-token")
    assert exc_info.value.status_code == 403
