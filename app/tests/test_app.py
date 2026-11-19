import os
import sys
from unittest.mock import MagicMock

import pytest
import requests

os.environ["SKIP_APP_INIT"] = "1"
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import create_app
from nbp_client import NBPClient, NBPError

PAYLOAD = {
    "table": "A",
    "currency": "dolar amerykański",
    "code": "USD",
    "rates": [{"no": "223/A/NBP/2025", "effectiveDate": "2025-11-18", "mid": 3.6543}],
}


def make_session(payload=PAYLOAD, exc=None):
    session = MagicMock()
    if exc:
        session.get.side_effect = exc
    else:
        resp = MagicMock()
        resp.json.return_value = payload
        resp.raise_for_status.return_value = None
        session.get.return_value = resp
    return session


def test_client_parses_and_caches():
    session = make_session()
    client = NBPClient(session=session, cache_ttl=60)
    first = client.get_rate()
    second = client.get_rate()
    assert first.rate.code == "USD"
    assert first.rate.mid == pytest.approx(3.6543)
    assert not first.stale
    assert session.get.call_count == 1  # drugi odczyt z cache'u
    assert second is first


def test_client_returns_stale_on_failure():
    session = make_session()
    client = NBPClient(session=session, cache_ttl=0)
    client.get_rate()
    session.get.side_effect = requests.ConnectionError("boom")
    result = client.get_rate()
    assert result.stale
    assert result.rate.mid == pytest.approx(3.6543)


def test_client_raises_without_cache():
    client = NBPClient(session=make_session(exc=requests.Timeout("t")))
    with pytest.raises(NBPError):
        client.get_rate()


def test_client_raises_on_malformed_payload():
    client = NBPClient(session=make_session(payload={"rates": []}))
    with pytest.raises(NBPError):
        client.get_rate()


def test_index_renders_table():
    app = create_app(NBPClient(session=make_session()))
    resp = app.test_client().get("/")
    body = resp.get_data(as_text=True)
    assert resp.status_code == 200
    assert "<table>" in body and "USD" in body and "3.6543" in body and "2025-11-18" in body


def test_index_503_when_nbp_down():
    app = create_app(NBPClient(session=make_session(exc=requests.Timeout("t"))))
    resp = app.test_client().get("/")
    assert resp.status_code == 503


def test_healthz_independent_of_nbp():
    app = create_app(NBPClient(session=make_session(exc=requests.Timeout("t"))))
    assert app.test_client().get("/healthz").status_code == 200


def test_api_rate_json():
    app = create_app(NBPClient(session=make_session()))
    data = app.test_client().get("/api/rate").get_json()
    assert data["code"] == "USD" and data["effectiveDate"] == "2025-11-18"
