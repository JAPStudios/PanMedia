# PanMedia

PanMedia is the agent-management service for Astrologically Intelligent. It provides a same-origin management console for registered agents, goals, approvals, heartbeats, execution runs, and budgets. Agent state remains in Astrologically Intelligent's orchestration database; PanMedia does not create a second source of truth.

## Run

Python 3.10+ is sufficient. No third-party Python packages are required.

    export ASTRO_AI_BASE_URL="https://your-astrologically-intelligent-host"
    export ASTRO_AI_API_TOKEN="your-server-side-token-with-at-least-24-characters"
    python panmedia_server.py

Open http://127.0.0.1:7801/. The PanMedia server binds to loopback only. For remote access, place an HTTPS reverse proxy in front of it. Do not put ASTRO_AI_API_TOKEN in browser code, HTML, query strings, or a public repository.

The Astrologically Intelligent backend must expose the authenticated agent-management API documented in its AGENT_RUNTIME.md. Configure ASTRO_AI_BASE_URL to the backend base URL. The token is forwarded only by the PanMedia server.

Optional listener settings: PANMEDIA_HOST (loopback only) and PANMEDIA_PORT (default 7801).

## Features

- Register model-backed agents with explicit tool allowlists.
- List agents, retrieve individual agent records, pause or activate them, record heartbeats.
- Execute prompts through the existing agent runtime.
- Create goals, request human approvals, approve or reject pending actions.
- Set organization or per-agent budgets; view recorded spend.
- Retrieve execution results by run identifier.

## Security

The browser never receives the Astrologically Intelligent bearer token. PanMedia accepts only a fixed allowlist of API routes; it is not an arbitrary URL proxy. The upstream URL must be HTTPS outside loopback. Request and response bodies are size-limited. The UI uses text nodes for API-provided content.

The old prototype script contained a hard-coded API credential. That value has been removed from the current source. Revoke it with its provider; removing a value from the latest commit does not erase it from Git history.

## Tests

    python -m unittest discover -s tests -v

Tests use a local fake upstream service. They do not require a live Astrologically Intelligent instance.
