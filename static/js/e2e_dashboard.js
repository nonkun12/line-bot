(function () {
  "use strict";

  const STATE_ICON = {
    ok: "🟢",
    error: "🔴",
    stop_timeout: "🔴",
    not_reached: "⚪",
    unknown: "⚪",
  };

  const STATE_TEXT = {
    ok: "OK",
    error: "ERROR",
    stop_timeout: "STOP",
    not_reached: "NOT REACHED",
    unknown: "UNKNOWN",
  };

  function fmtTime(iso) {
    if (!iso) return "-";
    try {
      const d = new Date(iso);
      return d.toLocaleString("ja-JP");
    } catch (e) {
      return iso;
    }
  }

  function renderChain(data) {
    const container = document.getElementById("e2eChain");
    const badge = document.getElementById("overallStatusBadge");

    badge.textContent = (data.overall || "unknown").toUpperCase();
    badge.className = "overall-badge overall-" + (data.overall || "unknown");

    container.innerHTML = "";
    (data.steps || []).forEach((step, idx) => {
      const row = document.createElement("div");
      row.className = "e2e-step";

      const dot = document.createElement("span");
      dot.className = "dot";
      dot.textContent = STATE_ICON[step.state] || "⚪";

      const label = document.createElement("span");
      label.className = "step-label";
      label.textContent = step.label;

      const stateTag = document.createElement("span");
      stateTag.className = "step-state state-" + step.state;
      stateTag.textContent = STATE_TEXT[step.state] || step.state;

      const meta = document.createElement("span");
      meta.className = "step-meta";
      const metaParts = [];
      if (step.last_http_status) metaParts.push("HTTP " + step.last_http_status);
      if (step.last_response_time_ms != null) metaParts.push(step.last_response_time_ms + "ms");
      if (step.state === "ok" && step.last_success_at) {
        metaParts.push("成功: " + fmtTime(step.last_success_at));
      }
      if ((step.state === "error" || step.state === "stop_timeout") && step.last_failure_at) {
        metaParts.push("失敗: " + fmtTime(step.last_failure_at));
      }
      if (step.last_error) metaParts.push(step.last_error);
      meta.textContent = metaParts.join(" / ");

      row.appendChild(dot);
      row.appendChild(label);
      row.appendChild(stateTag);
      row.appendChild(meta);
      container.appendChild(row);

      if (idx < data.steps.length - 1) {
        const arrow = document.createElement("div");
        arrow.className = "e2e-arrow";
        arrow.textContent = "↓";
        container.appendChild(arrow);
      }
    });
  }

  function renderServices(services) {
    const grid = document.getElementById("servicesGrid");
    grid.innerHTML = "";

    const NAME_MAP = {
      line_bot: "LINE Bot",
      render: "Render",
      n8n: "n8n",
      mcp: "MCP",
      database: "Database",
      ai: "AI",
    };

    Object.keys(NAME_MAP).forEach((key) => {
      const info = services[key] || { status: "unknown" };
      const tile = document.createElement("div");
      tile.className = "service-tile";

      const name = document.createElement("div");
      name.className = "service-name";
      name.textContent = NAME_MAP[key];

      const state = document.createElement("div");
      state.className = "service-state state-" + (info.status || "unknown");
      const icon = STATE_ICON[info.status] || "⚪";
      state.textContent = icon + " " + (STATE_TEXT[info.status] || (info.status || "unknown").toUpperCase());

      tile.appendChild(name);
      tile.appendChild(state);

      if (info.note) {
        const note = document.createElement("div");
        note.style.fontSize = "0.75rem";
        note.style.color = "var(--text-secondary)";
        note.textContent = info.note;
        tile.appendChild(note);
      }

      grid.appendChild(tile);
    });
  }

  function renderSummary(summary) {
    const successBox = document.getElementById("lastSuccessBox");
    const failureBox = document.getElementById("lastFailureBox");

    successBox.textContent = summary.last_success
      ? "最終成功: " + fmtTime(summary.last_success)
      : "まだ成功記録がありません";

    if (summary.last_failure) {
      const f = summary.last_failure;
      failureBox.innerHTML = "";
      const line1 = document.createElement("div");
      line1.textContent = `${f.step} で失敗 (${fmtTime(f.at)})`;
      failureBox.appendChild(line1);
      if (f.error) {
        const line2 = document.createElement("div");
        line2.textContent = f.error;
        line2.style.marginTop = "0.35rem";
        failureBox.appendChild(line2);
      }
    } else {
      failureBox.textContent = "まだ失敗記録がありません";
    }
  }

  function renderErrors(errors) {
    const container = document.getElementById("errorLogContainer");
    container.innerHTML = "";

    if (!errors || errors.length === 0) {
      const empty = document.createElement("div");
      empty.className = "empty-note";
      empty.textContent = "エラーはありません";
      container.appendChild(empty);
      return;
    }

    errors.forEach((e) => {
      const item = document.createElement("div");
      item.className = "error-log-item";

      const header = document.createElement("div");
      header.className = "error-log-header";
      header.innerHTML = `<span>${e.step}</span><span>${fmtTime(e.created_at)}</span>`;

      const msg = document.createElement("div");
      msg.className = "error-log-message";
      const parts = [];
      if (e.http_status) parts.push("HTTP " + e.http_status);
      if (e.error) parts.push(e.error);
      if (e.error_location) parts.push("(" + e.error_location + ")");
      msg.textContent = parts.join(" ");

      item.appendChild(header);
      item.appendChild(msg);
      container.appendChild(item);
    });
  }

  async function fetchJSON(url) {
    const res = await fetch(url, { credentials: "same-origin" });
    if (!res.ok) throw new Error("HTTP " + res.status);
    return res.json();
  }

  async function refreshAll() {
    try {
      const status = await fetchJSON("/api/e2e/status");
      if (status.ok) renderChain(status);
    } catch (e) {
      console.error("status fetch failed", e);
    }

    try {
      const services = await fetchJSON("/api/e2e/services");
      if (services.ok) renderServices(services.services);
    } catch (e) {
      console.error("services fetch failed", e);
    }

    try {
      const summary = await fetchJSON("/api/e2e/summary");
      if (summary.ok) renderSummary(summary);
    } catch (e) {
      console.error("summary fetch failed", e);
    }

    try {
      const errors = await fetchJSON("/api/e2e/errors");
      if (errors.ok) renderErrors(errors.errors);
    } catch (e) {
      console.error("errors fetch failed", e);
    }
  }

  document.getElementById("e2eRefreshBtn").addEventListener("click", refreshAll);
  refreshAll();
  setInterval(refreshAll, 15000);
})();
