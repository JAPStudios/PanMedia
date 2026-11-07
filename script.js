(() => {
  "use strict";
  const $ = (selector, root = document) => root.querySelector(selector);
  const state = { agents: [] };
  const api = async (path, method = "GET", body = undefined) => {
    const options = { method, headers: { Accept: "application/json" } };
    if (body !== undefined) {
      options.headers["Content-Type"] = "application/json";
      options.body = JSON.stringify(body);
    }
    const response = await fetch(path, options);
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.error || "Request failed (" + response.status + ")");
    return payload;
  };
  const node = (tag, className, text) => {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (text !== undefined) element.textContent = text;
    return element;
  };
  const setStatus = (element, message, kind = "") => {
    element.textContent = message;
    element.className = ("status " + kind).trim();
  };
  const globalStatus = message => { $("#global-status").textContent = message; };
  const selectOptions = () => {
    for (const id of ["#goal-owner", "#approval-agent", "#budget-agent"]) {
      const select = $(id);
      const current = select.value;
      select.replaceChildren(new Option("Organization-wide", ""));
      for (const agent of state.agents) select.add(new Option(agent.name, agent.id));
      select.value = current;
    }
  };
  const renderAgents = () => {
    const container = $("#agents");
    container.replaceChildren();
    if (!state.agents.length) {
      container.append(node("p", "muted", "No agents are registered."));
      selectOptions();
      return;
    }
    for (const agent of state.agents) {
      const card = node("article", "agent-card");
      card.append(node("h3", "", agent.name));
      card.append(node("div", "agent-meta",
        [agent.role, agent.adapter, agent.model || "default model", agent.state,
         agent.heartbeat_seconds ? String(agent.heartbeat_seconds) + "s heartbeat" : "manual heartbeat"]
          .filter(Boolean).join(" · ")));
      if (agent.last_heartbeat) card.append(node("p", "status", "Last heartbeat: " + new Date(agent.last_heartbeat * 1000).toLocaleString()));
      const actions = node("div", "agent-actions");
      const toggle = node("button", "secondary", agent.state === "active" ? "Pause" : "Activate");
      toggle.type = "button";
      toggle.addEventListener("click", async () => {
        toggle.disabled = true;
        try {
          await api("/api/agents/" + encodeURIComponent(agent.id), "PATCH",
            { state: agent.state === "active" ? "paused" : "active" });
          await loadAgents();
          globalStatus("Updated " + agent.name + ".");
        } catch (error) { globalStatus(error.message); }
        finally { toggle.disabled = false; }
      });
      actions.append(toggle);
      const heartbeat = node("button", "secondary", "Heartbeat");
      heartbeat.type = "button";
      heartbeat.disabled = agent.state !== "active";
      heartbeat.addEventListener("click", async () => {
        try {
          await api("/api/agents/" + encodeURIComponent(agent.id) + "/heartbeat", "POST", {});
          await loadAgents();
          globalStatus("Heartbeat recorded for " + agent.name + ".");
        } catch (error) { globalStatus(error.message); }
      });
      actions.append(heartbeat);
      card.append(actions);
      const execute = node("form", "execute-box");
      const prompt = node("input");
      prompt.name = "prompt";
      prompt.placeholder = "Task for this agent";
      prompt.required = true;
      prompt.maxLength = 10000;
      const run = node("button", "", "Execute");
      run.type = "submit";
      run.disabled = agent.state !== "active";
      execute.append(prompt, run);
      const result = node("p", "status", "");
      execute.addEventListener("submit", async event => {
        event.preventDefault();
        run.disabled = true;
        setStatus(result, "Running…");
        try {
          const payload = await api("/api/agents/" + encodeURIComponent(agent.id) + "/execute", "POST", { prompt: prompt.value });
          setStatus(result, String(payload.output || "Execution complete") + " · Run " + payload.run_id, "success");
          prompt.value = "";
        } catch (error) { setStatus(result, error.message, "error"); }
        finally { run.disabled = agent.state !== "active"; }
      });
      card.append(execute, result);
      container.append(card);
    }
    selectOptions();
  };
  async function loadAgents() {
    const payload = await api("/api/agents");
    state.agents = Array.isArray(payload.agents) ? payload.agents : [];
    renderAgents();
  }
  async function loadGoals() {
    const payload = await api("/api/goals");
    const container = $("#goals");
    container.replaceChildren();
    for (const goal of payload.goals || []) {
      const card = node("article", "compact-card");
      const detail = node("div");
      detail.append(node("h3", "", goal.title), node("p", "", goal.description || goal.status));
      card.append(detail);
      container.append(card);
    }
    if (!container.childNodes.length) container.append(node("p", "muted", "No goals yet."));
  }
  async function loadApprovals() {
    const payload = await api("/api/approvals?status=pending");
    const container = $("#approvals");
    container.replaceChildren();
    for (const approval of payload.approvals || []) {
      const card = node("article", "compact-card");
      const detail = node("div");
      detail.append(node("h3", "", approval.action), node("p", "", JSON.stringify(approval.details)));
      const actions = node("div", "actions");
      for (const decision of ["approved", "rejected"]) {
        const button = node("button", decision === "rejected" ? "danger" : "secondary", decision);
        button.type = "button";
        button.addEventListener("click", async () => {
          button.disabled = true;
          try {
            await api("/api/approvals/" + encodeURIComponent(approval.id) + "/decision", "POST",
              { decision: decision, decided_by: "PanMedia operator" });
            await loadApprovals();
          } catch (error) { globalStatus(error.message); }
          finally { button.disabled = false; }
        });
        actions.append(button);
      }
      card.append(detail, actions);
      container.append(card);
    }
    if (!container.childNodes.length) container.append(node("p", "muted", "No pending approvals."));
  }
  async function loadBudgets() {
    const payload = await api("/api/budgets");
    const container = $("#budgets");
    container.replaceChildren();
    for (const budget of payload.budgets || []) {
      const label = budget.agent_id
        ? (state.agents.find(agent => agent.id === budget.agent_id)?.name || budget.agent_id)
        : "Organization-wide";
      const card = node("article", "compact-card");
      card.append(node("div", "", label + " · " + budget.period),
        node("p", "", budget.spent_amount + " / " + budget.limit_amount + " " + budget.currency));
      container.append(card);
    }
    if (!container.childNodes.length) container.append(node("p", "muted", "No budgets configured."));
  }
  async function refreshAll() {
    globalStatus("Refreshing control-plane data…");
    try {
      await loadAgents();
      await Promise.all([loadGoals(), loadApprovals(), loadBudgets()]);
      globalStatus("Control plane is current.");
    } catch (error) {
      globalStatus(error.message);
    }
  }
  $("#agent-form").addEventListener("submit", async event => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const allowedTools = String(form.get("allowed_tools") || "").split(/\r?\n/).map(value => value.trim()).filter(Boolean);
    const config = {};
    if (allowedTools.length) config.allowed_tools = allowedTools;
    const systemPrompt = String(form.get("system_prompt") || "").trim();
    if (systemPrompt) config.system_prompt = systemPrompt;
    config.max_tool_rounds = 4;
    const payload = {
      name: String(form.get("name")).trim(),
      adapter: String(form.get("adapter")),
      role: String(form.get("role") || "agent").trim() || "agent",
      model: String(form.get("model") || "").trim() || null,
      heartbeat_seconds: Number(form.get("heartbeat_seconds") || 0),
      config: config
    };
    const status = $("#agent-form-status");
    try {
      await api("/api/agents", "POST", payload);
      event.currentTarget.reset();
      event.currentTarget.elements.role.value = "agent";
      event.currentTarget.elements.heartbeat_seconds.value = "0";
      setStatus(status, "Agent registered.", "success");
      await loadAgents();
    } catch (error) { setStatus(status, error.message, "error"); }
  });
  $("#goal-form").addEventListener("submit", async event => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    try {
      await api("/api/goals", "POST", {
        title: String(form.get("title")).trim(),
        description: String(form.get("description") || "").trim(),
        owner_agent_id: String(form.get("owner_agent_id") || "") || null
      });
      event.currentTarget.reset();
      await loadGoals();
      globalStatus("Goal created.");
    } catch (error) { globalStatus(error.message); }
  });
  $("#approval-form").addEventListener("submit", async event => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    let details;
    try { details = JSON.parse(String(form.get("details"))); }
    catch { globalStatus("Approval details must be valid JSON."); return; }
    if (!details || Array.isArray(details) || typeof details !== "object") {
      globalStatus("Approval details must be a JSON object.");
      return;
    }
    try {
      await api("/api/approvals", "POST", {
        action: String(form.get("action")).trim(),
        details: details,
        agent_id: String(form.get("agent_id") || "") || null
      });
      await loadApprovals();
      globalStatus("Approval requested.");
    } catch (error) { globalStatus(error.message); }
  });
  $("#budget-form").addEventListener("submit", async event => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const status = $("#budget-form-status");
    try {
      await api("/api/budgets", "POST", {
        limit_amount: Number(form.get("limit_amount")),
        period: String(form.get("period")).trim(),
        currency: String(form.get("currency") || "USD").trim().toUpperCase(),
        agent_id: String(form.get("agent_id") || "") || null
      });
      setStatus(status, "Budget saved.", "success");
      await loadBudgets();
    } catch (error) { setStatus(status, error.message, "error"); }
  });
  $("#refresh-agents").addEventListener("click", () => loadAgents().catch(error => globalStatus(error.message)));
  $("#refresh-goals").addEventListener("click", () => loadGoals().catch(error => globalStatus(error.message)));
  $("#refresh-approvals").addEventListener("click", () => loadApprovals().catch(error => globalStatus(error.message)));
  $("#refresh-budgets").addEventListener("click", () => loadBudgets().catch(error => globalStatus(error.message)));
  api("/healthz").then(payload => {
    const badge = $("#connection");
    badge.textContent = payload.configured ? "Connected to Astrologically Intelligent" : "Server configuration required";
    badge.className = "connection " + (payload.configured ? "ok" : "bad");
    return refreshAll();
  }).catch(error => {
    $("#connection").textContent = "PanMedia server unavailable";
    $("#connection").className = "connection bad";
    globalStatus(error.message);
  });
})();
