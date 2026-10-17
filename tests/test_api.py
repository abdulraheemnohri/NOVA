from fastapi.testclient import TestClient
from nova.main import app

def test_health_is_litert_only():
    with TestClient(app) as client: data=client.get("/api/health").json()
    assert data["offline_mode"] is True and data["llm_runtime"]=="LiteRT-LM only"
def test_unknown_approval_is_denied():
    with TestClient(app) as client:
        response=client.post("/api/approvals",json={"action":"arbitrary_shell","payload":{},"reason":"test"})
    assert response.status_code==403
