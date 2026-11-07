"""End-to-end PanMedia proxy tests against the real Astrologically Intelligent API."""
from __future__ import annotations

import json
import os
import sys
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

AI_ROOT = Path(os.getenv("ASTRO_AI_REPO_PATH", "")).expanduser()
if str(AI_ROOT) not in sys.path and AI_ROOT.is_dir():
    sys.path.insert(0, str(AI_ROOT))

try:
    from astrologically_intelligent.runtime import AgentRuntime
    from astrologically_intelligent.storage import Store
    from astrologically_intelligent.server import make_handler as make_ai_handler
except ImportError:
    AgentRuntime = Store = make_ai_handler = None

from panmedia_server import make_handler as make_panmedia_handler

TOKEN = "panmedia-integration-token-2026-secure"


class DeterministicProvider:
    def chat(self, messages, tools):
        return {"role": "assistant", "content": "PanMedia integration execution completed.", "tool_calls": []}


class PanMediaBackendIntegrationTests(unittest.TestCase):
    def setUp(self):
        if not AI_ROOT.is_dir():
            self.skipTest("ASTRO_AI_REPO_PATH is not configured; live backend integration runs in CI.")
        if AgentRuntime is None:
            self.fail("Astrologically Intelligent backend could not be imported from ASTRO_AI_REPO_PATH.")

        self.runtime = AgentRuntime(provider=DeterministicProvider(), store=Store(":memory:"))
        self.backend = ThreadingHTTPServer(("127.0.0.1", 0), make_ai_handler(self.runtime, TOKEN))
        self.backend_thread = threading.Thread(target=self.backend.serve_forever, daemon=True)
        self.backend_thread.start()
        backend_url = f"http://127.0.0.1:{self.backend.server_port}"
        self.proxy = ThreadingHTTPServer(("127.0.0.1", 0), make_panmedia_handler(backend_url, TOKEN))
        self.proxy_thread = threading.Thread(target=self.proxy.serve_forever, daemon=True)
        self.proxy_thread.start()
        self.base = f"http://127.0.0.1:{self.proxy.server_port}"

    def tearDown(self):
        if getattr(self, "proxy", None):
            self.proxy.shutdown()
            self.proxy.server_close()
            self.proxy_thread.join(timeout=2)
        if getattr(self, "backend", None):
            self.backend.shutdown()
            self.backend.server_close()
            self.backend_thread.join(timeout=2)
        if getattr(self, "runtime", None):
            self.runtime.close()

    def request(self, path, method="GET", payload=None):
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json"} if body is not None else {}
        request = urllib.request.Request(self.base + path, data=body, headers=headers, method=method)
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read())

    def test_console_proxy_manages_real_agent_runtime(self):
        status, health = self.request("/healthz")
        self.assertEqual(status, 200)
        self.assertTrue(health["configured"])

        status, created = self.request("/api/agents", "POST", {
            "name": "PanMedia integration agent",
            "adapter": "llm",
            "role": "integration-test",
            "config": {"allowed_tools": [], "max_tool_rounds": 1},
        })
        self.assertEqual(status, 201)
        agent = created["agent"]
        agent_id = agent["id"]

        status, listing = self.request("/api/agents")
        self.assertEqual(status, 200)
        self.assertIn(agent_id, [item["id"] for item in listing["agents"]])

        status, detail = self.request(f"/api/agents/{agent_id}")
        self.assertEqual(status, 200)
        self.assertEqual(detail["agent"]["name"], "PanMedia integration agent")

        status, paused = self.request(f"/api/agents/{agent_id}", "PATCH", {"state": "paused"})
        self.assertEqual(status, 200)
        self.assertEqual(paused["agent"]["state"], "paused")
        self.request(f"/api/agents/{agent_id}", "PATCH", {"state": "active"})
        self.request(f"/api/agents/{agent_id}/heartbeat", "POST", {})

        status, execution = self.request(
            f"/api/agents/{agent_id}/execute", "POST", {"prompt": "Run the integration check."}
        )
        self.assertEqual(status, 200)
        self.assertEqual(execution["status"], "succeeded")
        self.assertEqual(execution["output"], "PanMedia integration execution completed.")

        status, run = self.request(f"/api/runs/{execution['run_id']}")
        self.assertEqual(status, 200)
        self.assertEqual(run["run"]["status"], "succeeded")

        status, goal = self.request("/api/goals", "POST", {
            "title": "Verify PanMedia integration",
            "description": "Exercise the real backend through the PanMedia proxy.",
            "owner_agent_id": agent_id,
        })
        self.assertEqual(status, 201)
        self.assertEqual(goal["goal"]["owner_agent_id"], agent_id)

        status, approval = self.request("/api/approvals", "POST", {
            "action": "approve integration report",
            "details": {"goal_id": goal["goal"]["id"]},
            "agent_id": agent_id,
        })
        self.assertEqual(status, 201)
        approval_id = approval["approval"]["id"]
        status, pending = self.request("/api/approvals?status=pending")
        self.assertIn(approval_id, [item["id"] for item in pending["approvals"]])
        status, decided = self.request(f"/api/approvals/{approval_id}/decision", "POST", {
            "decision": "approved",
            "decided_by": "integration-test",
        })
        self.assertEqual(decided["approval"]["status"], "approved")

        status, budget = self.request("/api/budgets", "POST", {
            "limit_amount": 10,
            "period": "integration-test",
            "agent_id": agent_id,
        })
        self.assertEqual(status, 200)
        self.request("/api/budgets/costs", "POST", {
            "amount": 2,
            "period": "integration-test",
            "agent_id": agent_id,
        })
        status, budgets = self.request("/api/budgets")
        self.assertIn(agent_id, [item["agent_id"] for item in budgets["budgets"]])

    def test_backend_control_plane_rejects_requests_without_server_token(self):
        url = f"http://127.0.0.1:{self.backend.server_port}/v1/agents"
        request = urllib.request.Request(url, method="GET")
        with self.assertRaises(urllib.error.HTTPError) as raised:
            urllib.request.urlopen(request, timeout=3)
        self.assertEqual(raised.exception.code, 401)


if __name__ == "__main__":
    unittest.main()
