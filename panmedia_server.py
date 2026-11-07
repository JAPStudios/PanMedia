"""Loopback PanMedia console with a server-side Astrologically Intelligent API proxy."""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
STATIC = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/script.js": ("script.js", "application/javascript; charset=utf-8"),
    "/styles.css": ("styles.css", "text/css; charset=utf-8"),
}
RESOURCE = r"[A-Za-z0-9_-]{1,128}"
ROUTES = (
    ("GET", re.compile(r"/api/agents"), "/v1/agents"),
    ("GET", re.compile(r"/api/agents/due"), "/v1/agents/due"),
    ("GET", re.compile(rf"/api/agents/({RESOURCE})"), None),
    ("POST", re.compile(r"/api/agents"), "/v1/agents"),
    ("PATCH", re.compile(rf"/api/agents/({RESOURCE})"), None),
    ("POST", re.compile(rf"/api/agents/({RESOURCE})/execute"), None),
    ("POST", re.compile(rf"/api/agents/({RESOURCE})/heartbeat"), None),
    ("GET", re.compile(r"/api/goals"), "/v1/goals"),
    ("POST", re.compile(r"/api/goals"), "/v1/goals"),
    ("GET", re.compile(r"/api/approvals"), "/v1/approvals"),
    ("POST", re.compile(r"/api/approvals"), "/v1/approvals"),
    ("POST", re.compile(rf"/api/approvals/({RESOURCE})/decision"), None),
    ("GET", re.compile(r"/api/budgets"), "/v1/budgets"),
    ("POST", re.compile(r"/api/budgets"), "/v1/budgets"),
    ("POST", re.compile(r"/api/budgets/costs"), "/v1/budgets/costs"),
    ("GET", re.compile(rf"/api/runs/({RESOURCE})"), None),
)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def validate_upstream(base_url: str, token: str) -> tuple[str, str]:
    if not isinstance(base_url, str) or not isinstance(token, str):
        raise ValueError("Astrologically Intelligent URL and API token must be strings.")
    base_url = base_url.strip().rstrip("/")
    token = token.strip()
    parsed = urllib.parse.urlsplit(base_url)
    if (
        not base_url
        or parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("ASTRO_AI_BASE_URL must be an HTTP(S) base URL without credentials, query or fragment.")
    if parsed.scheme != "https" and parsed.hostname.lower() not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("ASTRO_AI_BASE_URL must use HTTPS outside loopback development.")
    if len(token) < 24:
        raise ValueError("ASTRO_AI_API_TOKEN must contain at least 24 characters.")
    return base_url, token


def _query_string(path: str, query: dict[str, list[str]]) -> str:
    allowed = {
        "/api/agents": {"state"},
        "/api/goals": {"status"},
        "/api/approvals": {"status"},
    }.get(path, set())
    values = []
    for key, items in query.items():
        if key not in allowed or len(items) != 1 or len(items[0]) > 80:
            raise ValueError("Unsupported or repeated query parameter.")
        values.append((key, items[0]))
    return urllib.parse.urlencode(values)


def make_handler(upstream_base_url: str, api_token: str):
    try:
        upstream_base_url, api_token = validate_upstream(upstream_base_url, api_token)
    except ValueError:
        upstream_base_url, api_token = "", ""

    class Handler(BaseHTTPRequestHandler):
        server_version = "PanMedia/1.0"

        def _send(self, status: int, body: bytes, content_type: str):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; script-src 'self'; style-src 'self'; "
                "connect-src 'self'; img-src 'self' data:; object-src 'none'; "
                "base-uri 'self'; frame-ancestors 'none'",
            )
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status: int, payload: dict):
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self._send(status, body, "application/json; charset=utf-8")

        def _body(self):
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except (TypeError, ValueError):
                self._json(400, {"error": "invalid_content_length"})
                return None
            if length < 1 or length > 1_000_000:
                self._json(413, {"error": "invalid_body_size"})
                return None
            try:
                payload = json.loads(self.rfile.read(length))
            except (UnicodeDecodeError, json.JSONDecodeError):
                self._json(400, {"error": "invalid_json"})
                return None
            if not isinstance(payload, dict):
                self._json(400, {"error": "body_must_be_object"})
                return None
            return json.dumps(payload, ensure_ascii=False).encode("utf-8")

        def _proxy(self, method: str):
            if not upstream_base_url or not api_token:
                return self._json(503, {"error": "Astrologically Intelligent API is not configured on the PanMedia server."})
            parsed = urllib.parse.urlsplit(self.path)
            path = parsed.path
            upstream_path = None
            for allowed_method, pattern, fixed_path in ROUTES:
                if pattern.fullmatch(path) and allowed_method == method:
                    upstream_path = fixed_path or path.replace("/api/", "/v1/", 1)
                    break
            if upstream_path is None:
                return self._json(404, {"error": "not_found"})
            try:
                query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
                query_string = _query_string(path, query)
            except ValueError as exc:
                return self._json(400, {"error": str(exc)})
            if query_string:
                upstream_path += "?" + query_string
            body = None
            if method in {"POST", "PATCH"}:
                body = self._body()
                if body is None:
                    return
            request = urllib.request.Request(
                upstream_base_url + upstream_path,
                data=body,
                method=method,
                headers={
                    "Authorization": "Bearer " + api_token,
                    "Accept": "application/json",
                    **({"Content-Type": "application/json"} if body is not None else {}),
                },
            )
            opener = urllib.request.build_opener(NoRedirect())
            try:
                with opener.open(request, timeout=120) as response:
                    data = response.read(1_000_001)
                    if len(data) > 1_000_000:
                        return self._json(502, {"error": "upstream_response_too_large"})
                    content_type = response.headers.get("Content-Type", "application/json")
                    if "json" not in content_type.lower():
                        return self._json(502, {"error": "upstream_returned_non_json"})
                    self._send(response.status, data, "application/json; charset=utf-8")
            except urllib.error.HTTPError as exc:
                data = exc.read(1_000_001)
                if len(data) > 1_000_000:
                    return self._json(502, {"error": "upstream_error_response_too_large"})
                try:
                    payload = json.loads(data) if data else {"error": "upstream_error"}
                except (UnicodeDecodeError, json.JSONDecodeError):
                    payload = {"error": "upstream_request_failed"}
                if not isinstance(payload, dict):
                    payload = {"error": "upstream_request_failed"}
                self._json(exc.code, payload)
            except (urllib.error.URLError, TimeoutError, OSError):
                self._json(502, {"error": "astrologically_intelligent_unavailable"})

        def do_GET(self):
            parsed = urllib.parse.urlsplit(self.path)
            if parsed.path == "/healthz":
                return self._json(200, {
                    "status": "ok",
                    "service": "panmedia",
                    "configured": bool(upstream_base_url and api_token),
                })
            if parsed.path.startswith("/api/"):
                return self._proxy("GET")
            static = STATIC.get(parsed.path)
            if static is None:
                return self._json(404, {"error": "not_found"})
            filename, content_type = static
            try:
                body = (ROOT / filename).read_bytes()
            except OSError:
                return self._json(404, {"error": "asset_not_found"})
            return self._send(200, body, content_type)

        def do_POST(self):
            if not urllib.parse.urlsplit(self.path).path.startswith("/api/"):
                return self._json(404, {"error": "not_found"})
            return self._proxy("POST")

        def do_PATCH(self):
            if not urllib.parse.urlsplit(self.path).path.startswith("/api/"):
                return self._json(404, {"error": "not_found"})
            return self._proxy("PATCH")

        def log_message(self, fmt, *args):
            return

    return Handler


def serve():
    host = os.getenv("PANMEDIA_HOST", "127.0.0.1")
    port = int(os.getenv("PANMEDIA_PORT", "7801"))
    if host.lower() not in {"127.0.0.1", "localhost", "::1"}:
        raise RuntimeError("PanMedia binds to loopback only; place an HTTPS reverse proxy in front for remote access.")
    server = ThreadingHTTPServer(
        (host, port),
        make_handler(os.getenv("ASTRO_AI_BASE_URL", ""), os.getenv("ASTRO_AI_API_TOKEN", "")),
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    serve()
