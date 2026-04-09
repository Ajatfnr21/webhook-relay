import pytest
from fastapi.testclient import TestClient
from httpx import AsyncClient
import json

from app.main import app, redis_client

client = TestClient(app)

@pytest.fixture
def sample_webhook_payload():
    return {
        "repository": {
            "name": "test-repo",
            "full_name": "user/test-repo"
        },
        "pusher": {
            "name": "testuser",
            "email": "test@example.com"
        },
        "head_commit": {
            "message": "Test commit",
            "url": "https://github.com/user/test-repo/commit/abc123"
        },
        "ref": "refs/heads/main"
    }

@pytest.fixture
def mock_slack_destination(monkeypatch):
    import httpx
    
    async def mock_post(*args, **kwargs):
        class MockResponse:
            status_code = 200
            text = "ok"
            def json(self):
                return {"ok": True}
        return MockResponse()
    
    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)

class TestWebhookRelay:
    def test_health_check(self):
        """Test health check endpoint"""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "version" in data
    
    def test_metrics_endpoint(self):
        """Test Prometheus metrics endpoint"""
        response = client.get("/metrics")
        assert response.status_code == 200
        assert "webhooks_received_total" in response.text
    
    def test_list_routes(self):
        """Test routes listing"""
        response = client.get("/api/v1/routes")
        assert response.status_code == 200
        data = response.json()
        assert "routes" in data
        assert "count" in data
    
    def test_receive_webhook_no_route(self):
        """Test webhook reception with no matching route"""
        response = client.post("/unknown", json={"test": "data"})
        assert response.status_code == 404
        assert "No route configured" in response.json()["detail"]
    
    def test_receive_webhook_success(self, sample_webhook_payload, mock_slack_destination):
        """Test successful webhook reception and routing"""
        response = client.post("/forward", json=sample_webhook_payload)
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "accepted"
        assert "routed_to" in data
        assert "latency_ms" in data
    
    def test_dlq_endpoint(self):
        """Test dead letter queue endpoint"""
        response = client.get("/api/v1/dlq")
        assert response.status_code == 200
        data = response.json()
        assert "dlq_size" in data
        assert "items" in data
    
    def test_metrics_summary(self):
        """Test metrics summary endpoint"""
        response = client.get("/api/v1/metrics/summary")
        assert response.status_code == 200
        data = response.json()
        assert "total_received" in data
        assert "total_forwarded" in data
        assert "dlq_size" in data
        assert "routes_active" in data

class TestFilters:
    def test_apply_filter_valid(self):
        """Test filter application"""
        from app.main import apply_filter
        
        payload = {"repository": {"name": "test-repo"}}
        result = apply_filter(payload, "$.repository.name")
        assert result is True
    
    def test_apply_filter_invalid(self):
        """Test filter with non-matching path"""
        from app.main import apply_filter
        
        payload = {"repository": {"name": "test-repo"}}
        result = apply_filter(payload, "$.nonexistent.path")
        assert result is False

class TestTransforms:
    def test_transform_payload(self):
        """Test payload transformation"""
        from app.main import transform_payload
        
        payload = {"name": "test", "value": 123}
        template = '{"processed_name": "{{ name }}", "processed_value": {{ value }}}'
        
        result = transform_payload(payload, template)
        assert result["processed_name"] == "test"
        assert result["processed_value"] == 123
