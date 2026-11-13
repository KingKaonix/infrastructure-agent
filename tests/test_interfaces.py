from fastapi.testclient import TestClient

from infrastructure_agent.api import create_app


class EmptyDiscovery:
    def get_all_devices(self):
        return {}


def test_health_and_status_api_are_available():
    client = TestClient(create_app(discovery=EmptyDiscovery()))
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/status").json() == {"devices": [], "count": 0}
