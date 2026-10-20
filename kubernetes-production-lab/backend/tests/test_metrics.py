from contextlib import asynccontextmanager

import main
import pytest
from fastapi.testclient import TestClient


class FakeConnection:
    async def execute(self, *args, **kwargs):
        return "SELECT 1"


class FakePool:
    def __init__(self, healthy: bool):
        self.healthy = healthy

    @asynccontextmanager
    async def _acquire(self):
        if not self.healthy:
            raise OSError("connection refused")
        yield FakeConnection()

    def acquire(self, timeout=None):
        return self._acquire()


@pytest.fixture
def client(monkeypatch):
    # No `with` block: the lifespan (real asyncpg pool) is not started.
    monkeypatch.setattr(main, "db_pool", FakePool(healthy=True))
    return TestClient(main.app)


def sample(client, name, labels=None):
    text = client.get("/metrics").text
    value = None
    for line in text.splitlines():
        if line.startswith("#"):
            continue
        metric, _, raw = line.rpartition(" ")
        if metric.split("{")[0] != name:
            continue
        if labels and not all(f'{k}="{v}"' in metric for k, v in labels.items()):
            continue
        value = float(raw)
    return value


def test_metrics_endpoint_exposes_prometheus_text(client):
    client.get("/api/health/live")
    response = client.get("/metrics")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert "http_requests_total" in response.text
    assert "http_request_duration_seconds_bucket" in response.text


def test_request_count_and_latency_use_route_template(client):
    labels = {"method": "GET", "route": "/api/health/live", "status": "200"}
    before = sample(client, "http_requests_total", labels) or 0
    for _ in range(3):
        assert client.get("/api/health/live").status_code == 200
    assert sample(client, "http_requests_total", labels) == before + 3
    assert sample(
        client,
        "http_request_duration_seconds_count",
        {"method": "GET", "route": "/api/health/live"},
    ) >= 3


def test_unknown_paths_share_one_label(client):
    client.get("/does-not-exist/123")
    client.get("/another/random/path")
    text = client.get("/metrics").text
    assert 'route="unmatched"' in text
    assert "/does-not-exist/123" not in text


def test_database_up_gauge_tracks_pool_health(client, monkeypatch):
    assert sample(client, "database_up") == 1.0
    monkeypatch.setattr(main, "db_pool", FakePool(healthy=False))
    assert sample(client, "database_up") == 0.0
    assert client.get("/api/health/ready").status_code == 503
    monkeypatch.setattr(main, "db_pool", None)
    assert sample(client, "database_up") == 0.0
