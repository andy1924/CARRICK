window.CarrickAnalytics = (() => {
  let app;
  const $ = selector => document.querySelector(selector);
  const safe = value => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  function render(data) {
    if (!data?.available) {
      $("#analytics-result").innerHTML = `<div class="panel"><h2>Scenario unavailable</h2><p>${safe(data?.reason || "Connect to the server to calculate a forecast.")}</p>${(data?.warnings || []).map(warning => `<p class="capture-warning">${safe(warning)}</p>`).join("")}</div>`;
      return;
    }
    const metrics = [["Projected finish", app.date(data.projected_finish), `${data.project_slip_days} days beyond plan`], ["Critical activities", data.counts.critical, "Zero float in this scenario"], ["Overdue activities", data.counts.overdue, "Unfinished at the data date"], ["Risk envelope P80", app.date(data.risk.p80_finish), "Illustrative duration assumptions"]];
    $("#analytics-result").innerHTML = `<div class="metric-grid">${metrics.map(([label, value, detail]) => `<div class="metric"><div class="label">${safe(label)}</div><div class="value forecast-value">${safe(value)}</div><div class="sub">${safe(detail)}</div></div>`).join("")}</div>
      <div class="panel"><div class="panel-heading"><div><h2>Activities driving the forecast</h2><p class="muted">Existing activity IDs, reviewed actuals, recorded forecasts, and imported dependencies.</p></div><button id="download-scenario" class="text-button" type="button">Download scenario CSV</button></div><div class="table-scroll"><table><thead><tr><th>Activity</th><th>Planned finish</th><th>Projected finish</th><th>Slip</th><th>Float</th><th>Scenario status</th></tr></thead><tbody>${data.activities.map(activity => `<tr><td><strong>${safe(activity.activity_id)}</strong>${safe(activity.name)}</td><td>${app.date(activity.planned_finish)}</td><td>${app.date(activity.forecast_finish)}</td><td>${activity.slip_days}d</td><td>${activity.float_days}d</td><td><span class="tag ${activity.complete ? "approved" : activity.critical ? "needs_review" : "recorded"}">${activity.complete ? "Complete" : activity.critical ? "Critical" : "Has float"}</span>${activity.blocked ? '<small class="capture-warning">Recorded blocker</small>' : ""}</td></tr>`).join("")}</tbody></table></div></div>
      <div class="panel analytics-wbs"><h2>Work breakdown summary</h2><div class="table-scroll"><table><thead><tr><th>Work breakdown</th><th>Activities</th><th>Complete</th><th>Overdue</th><th>Critical</th></tr></thead><tbody>${data.wbs.map(group => `<tr><td>${safe(group.wbs)}</td><td>${group.total}</td><td>${group.complete}</td><td>${group.overdue}</td><td>${group.critical}</td></tr>`).join("")}</tbody></table></div></div>
      <details class="panel analytics-assumptions" open><summary>Scenario assumptions and limitations</summary><p>P50 finish: ${app.date(data.risk.p50_finish)} · P80 finish: ${app.date(data.risk.p80_finish)} · ${data.risk.samples} simulated duration scenarios. These percentiles describe an illustrative model, not a validated likelihood.</p><ul>${data.assumptions.map(item => `<li>${safe(item)}</li>`).join("")}</ul>${data.warnings.map(item => `<p class="capture-warning">${safe(item)}</p>`).join("")}${data.sequence_conflicts.length ? `<h3>Actual dates conflict with dependency logic</h3><ul>${data.sequence_conflicts.map(edge => `<li>${safe(edge.predecessor)} → ${safe(edge.successor)} (${safe(edge.kind)})</li>`).join("")}</ul>` : ""}</details>`;
    $("#download-scenario").addEventListener("click", () => {
      // Neutralize formula-looking values in spreadsheet exports.
      const cell = value => '"' + String(value ?? "").replace(/^[=+@-]/, match => "'" + match).replaceAll('"', '""') + '"';
      const fields = ["activity_id", "name", "wbs", "planned_finish", "forecast_start", "forecast_finish", "slip_days", "float_days", "critical", "criticality_percent"];
      const text = [fields.map(cell).join(","), ...data.activities.map(row => fields.map(field => cell(row[field])).join(","))].join("\r\n");
      const url = URL.createObjectURL(new Blob([text], { type: "text/csv;charset=utf-8" }));
      const link = document.createElement("a"); link.href = url; link.download = "carrick-planning-scenario.csv"; link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    });
  }
  async function load(payload) {
    try {
      if (!app.offline.reachable) {
        const stored = await app.offline.get("snapshots", "analytics");
        render(stored?.value);
        app.toast(stored ? "Showing the last saved scenario. Reconnect to recalculate." : "Reconnect to calculate a scenario.");
        return;
      }
      const result = payload ? await app.post("/api/analytics/scenario", payload) : await app.request("/api/analytics");
      await app.offline.put("snapshots", { id: "analytics", value: result, savedAt: new Date().toISOString() });
      render(result);
    } catch (error) { app.toast(error.message, true); }
  }
  return { load, init(callbacks) {
    app = callbacks;
    $("#scenario-date").value = new Intl.DateTimeFormat("sv-SE", { timeZone: "Asia/Kolkata", year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date());
    $("#scenario-form").addEventListener("submit", async event => {
      event.preventDefault();
      const button = $("#scenario-form button"); button.disabled = true;
      try { await load({ as_of: $("#scenario-date").value, duration_factor: Number($("#scenario-factor").value) }); }
      finally { button.disabled = false; }
    });
  } };
})();
