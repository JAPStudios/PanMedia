import json
import threading
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from panmedia_server import make_handler


class UpstreamState:
    requests = []


class FakeUpstream(BaseHTTPRequestHandler):
    def _send(self, status, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        UpstreamState.requests.append((self.command, self.path, self.headers.get("Authorization"), None))
        if self.path == "/v1/agents?state=active":
            return self._send(200, {"agents": [{"id": "agent-1", "name": "Research"}]})
        if self.path == "/v1/agents":
            return self._send(200, {"agents": []})
        return self._send(404, {"error": "not_found"})

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        UpstreamState.requests.append((self.command, self.path, self.headers.get("Authorization"), body))
        return self._send(201, {"agent": {"id": "agent-2", "name": "Writer"}})

    def do_PATCH(self):
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        UpstreamState.requests.append((self.command, self.path, self.headers.get("Authorization"), body))
        return self._send(200, {"agent": {"id": "agent-1", "state": "paused"}})

    def log_message(self, *_args):
        return


class PanMediaProxyTests(unittest.TestCase):
    def setUp(self):
        UpstreamState.requests = []
        self.upstream = ThreadingHTTPServer(("127.0.0.1", 0), FakeUpstream)
        self.upstream_thread = threading.Thread(target=self.upstream.serve_forever, daemon=True)
        self.upstream_thread.start()
        self.proxy = ThreadingHTTPServer(
            ("127.0.0.1", 0),
            make_handler("http://127.0.0.1:" + str(self.upstream.server_port), "x" * 32),
        )
        self.proxy_thread = threading.Thread(target=self.proxy.serve_forever, daemon=True)
        self.proxy_thread.start()
        self.base = "http://127.0.0.1:" + str(self.proxy.server_port)

    def tearDown(self):
        self.proxy.shutdown()
        self.proxy.server_close()
        self.proxy_thread.join(timeout=2)
        self.upstream.shutdown()
        self.upstream.server_close()
        self.upstream_thread.join(timeout=2)

    def request(self, path, method="GET", payload=None):
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json"} if body is not None else {}
        request = urllib.request.Request(self.base + path, data=body, headers=headers, method=method)
        return urllib.request.urlopen(request, timeout=3)

    def test_agent_list_query_is_forwarded_with_server_side_bearer_token(self):
        with self.request("/api/agents?state=active") as response:
            payload = json.loads(response.read())
        self.assertEqual(payload["agents"][0]["id"], "agent-1")
        self.assertEqual(
            UpstreamState.requests[-1],
            ("GET", "/v1/agents?state=active", "Bearer " + "x" * 32, None),
        )

    def test_agent_registration_forwards_json_body(self):
        body = {"name": "Writer", "adapter": "llm", "config": {"allowed_tools": []}}
        with self.request("/api/agents", "POST", body) as response:
            payload = json.loads(response.read())
            self.assertEqual(response.status, 201)
        self.assertEqual(payload["agent"]["id"], "agent-2")
        method, path, auth, sent = UpstreamState.requests[-1]
        self.assertEqual((method, path, auth), ("POST", "/v1/agents", "Bearer " + "x" * 32))
        self.assertEqual(json.loads(sent), body)

    def test_agent_state_patch_uses_fixed_upstream_route(self):
        with self.request("/api/agents/agent-1", "PATCH", {"state": "paused"}) as response:
            payload = json.loads(response.read())
        self.assertEqual(payload["agent"]["state"], "paused")
        self.assertEqual(UpstreamState.requests[-1][1], "/v1/agents/agent-1")

    def test_unknown_routes_are_not_forwarded(self):
        with self.assertRaises(urllib.error.HTTPError) as raised:
            self.request("/api/arbitrary?url=https://example.com")
        self.assertEqual(raised.exception.code, 404)
        self.assertEqual(UpstreamState.requests, [])

    def test_repeated_or_unknown_query_parameters_are_rejected(self):
        for path in ("/api/agents?state=active&state=paused", "/api/agents?url=https://example.com"):
            with self.subTest(path=path):
                with self.assertRaises(urllib.error.HTTPError) as raised:
                    self.request(path)
                self.assertEqual(raised.exception.code, 400)

    def test_health_does_not_expose_the_bearer_token(self):
        with self.request("/healthz") as response:
            payload = json.loads(response.read())
        self.assertTrue(payload["configured"])
        self.assertNotIn("token", json.dumps(payload).lower())

    def test_static_console_is_served(self):
        with self.request("/") as response:
            html = response.read().decode("utf-8")
        self.assertIn("PanMedia", html)
        self.assertIn("/script.js", html)


if __name__ == "__main__":
    unittest.main()
