import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from lmm.nexus.api import NexusAPIError, NexusClient, NexusRateLimitError


class _Handler(BaseHTTPRequestHandler):
    # Overridden per test via class attributes set on a fresh subclass.
    status = 200
    body = b"{}"
    headers_sent = None

    def do_POST(self):  # noqa: N802 - stdlib API name
        self.last_headers = dict(self.headers)
        self.send_response(self.status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(self.body)

    do_GET = do_POST

    def log_message(self, *args):
        pass


def _make_server(status: int, body: dict):
    handler_cls = type("Handler", (_Handler,), {"status": status, "body": json.dumps(body).encode()})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler_cls)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


@pytest.fixture
def server_factory():
    servers = []

    def make(status=200, body=None):
        server, thread = _make_server(status, body if body is not None else {})
        servers.append((server, thread))
        return server

    yield make

    for server, thread in servers:
        server.shutdown()
        thread.join()


def test_graphql_returns_data_on_success(server_factory, monkeypatch):
    server = server_factory(200, {"data": {"hello": "world"}})
    import lmm.nexus.api as api_module

    monkeypatch.setattr(api_module, "GRAPHQL_URL", f"http://127.0.0.1:{server.server_address[1]}")

    client = NexusClient("test-key")
    result = client.graphql("query { hello }")
    assert result == {"hello": "world"}


def test_graphql_raises_on_error_field(server_factory, monkeypatch):
    server = server_factory(200, {"errors": [{"message": "bad query"}]})
    import lmm.nexus.api as api_module

    monkeypatch.setattr(api_module, "GRAPHQL_URL", f"http://127.0.0.1:{server.server_address[1]}")

    client = NexusClient("test-key")
    with pytest.raises(NexusAPIError, match="bad query"):
        client.graphql("query { hello }")


def test_graphql_raises_rate_limit_error(server_factory, monkeypatch):
    server = server_factory(429, {})
    import lmm.nexus.api as api_module

    monkeypatch.setattr(api_module, "GRAPHQL_URL", f"http://127.0.0.1:{server.server_address[1]}")

    client = NexusClient("test-key")
    with pytest.raises(NexusRateLimitError):
        client.graphql("query { hello }")


def test_graphql_requires_api_key():
    client = NexusClient("")
    with pytest.raises(NexusAPIError, match="No Nexus Mods API key"):
        client.graphql("query { hello }")


def test_is_premium_true(monkeypatch):
    client = NexusClient("test-key")
    monkeypatch.setattr(client, "validate_user", lambda: {"is_premium": True, "name": "someone"})
    assert client.is_premium() is True


def test_is_premium_false(monkeypatch):
    client = NexusClient("test-key")
    monkeypatch.setattr(client, "validate_user", lambda: {"is_premium": False, "name": "someone"})
    assert client.is_premium() is False
