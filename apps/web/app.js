const state = { summary: null, activities: [], events: [], view: "overview" };
const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const safe = (value) => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c]));
const displayDate = (value) => value ? safe(String(value).slice(0, 10)) : "Date unknown";
const labels = { overview: "Progress desk", capture: "New report", review: "Review queue", schedule: "Schedule", history: "Event log", exports: "Exports" };

async function request(path, options = {}) {
  const response = await fetch(path, { headers: { "Content-Type": "application/json" }, ...options });
  const contentType = response.headers.get("content-type") || "";
  const data = contentType.includes("json") ? await response.json() : await response.text();
  if (!response.ok) throw new Error(data.error || `Request failed (${response.status})`);
  return data;
}
const post = (path, body = {}) => request(path, { method: "POST", body: JSON.stringify(body) });

let toastTimer;
function toast(message, error = false) {
  const el = $("#toast");
  el.textContent = message;
  el.className = error ? "show error" : "show";
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.className = "", 4000);
}

function go(view) {
  state.view = view;
  $$(".nav-item").forEach(el => el.classList.toggle("active", el.dataset.view === view));
  $$(".view").forEach(el => el.classList.toggle("active", el.id === `view-${view}`));
  $("#breadcrumb").textContent = labels[view];
  if (view === "review") renderReview();
  if (view === "schedule") renderSchedule();
  if (view === "history") renderHistory();
  if (view === "exports") renderExports();
  window.scrollTo({ top: 0, behavior: "smooth" });
}

async function refresh() {
  const [summary, activities, events] = await Promise.all([
    request("/api/summary"), request("/api/activities"), request("/api/events")
  ]);
  state.summary = summary;
  state.activities = activities;
  state.events = events;
  renderOverview(); renderReview(); renderSchedule(); renderHistory(); renderExports();
}

function statusTag(status) {
  const text = (status || "unknown").replaceAll("_", " ");
  return `<span class="tag ${safe(status)}">${safe(text)}</span>`;
}

function renderOverview() {
  const schedule = state.summary?.schedule;
  $("#welcome").hidden = Boolean(schedule);
  $("#schedule-chip").textContent = schedule ? `${schedule.filename} · ${schedule.activity_count} activities` : "No schedule loaded";
  const counts = state.summary?.counts || {};
  const pending = (counts.needs_review || 0) + (counts.staged || 0);
  $("#review-badge").hidden = !pending;
  $("#review-badge").textContent = pending;
  const metrics = [
    ["ACTIVITIES", schedule?.activity_count || 0, "In working schedule"],
    ["FIELD EVENTS", state.events.length, "Recorded from reports"],
    ["TO REVIEW", pending, "Awaiting decision"],
    ["APPROVED", (counts.approved || 0) + (counts.exported || 0), "Ready or exported"]
  ];
  $("#metrics").innerHTML = metrics.map(([label, value, sub]) => `<div class="metric"><div class="label">${label}</div><div class="value">${value}</div><div class="sub">${sub}</div></div>`).join("");
  $("#recent-events").innerHTML = state.events.length ? state.events.slice(0, 5).map(eventRow).join("") : empty("No field events yet", "Capture a report to see its extracted events here.");
  const action = $("#work-queue-action");
  if (!schedule) {
    $("#work-queue-title").textContent = "Load a schedule";
    $("#work-queue-copy").textContent = "The activity list gives field reports a plan to link to.";
    action.dataset.goto = "schedule";
    action.textContent = "Open schedule →";
  } else if (pending) {
    $("#work-queue-title").textContent = `${pending} ${pending === 1 ? "event needs" : "events need"} a decision`;
    $("#work-queue-copy").textContent = "Verify each schedule link and date, then approve an actual or keep a note.";
    action.dataset.goto = "review";
    action.textContent = "Open review queue →";
  } else {
    $("#work-queue-title").textContent = "Queue is clear";
    $("#work-queue-copy").textContent = "New field notes will appear here when they need review.";
    action.dataset.goto = "capture";
    action.textContent = "Write a field report →";
  }
}

function empty(title, message) {
  return `<div class="empty"><strong>${safe(title)}</strong>${safe(message)}</div>`;
}

function eventRow(event) {
  const candidate = event.selected_activity || event.candidates?.[0]?.activity_id || "Unmatched";
  return `<div class="event-row"><div class="event-body"><strong>${safe(event.text)}</strong><div class="event-meta"><small>${safe(candidate)} · ${displayDate(event.event_date)} · ${safe(event.kind.replaceAll("_", " "))}</small>${statusTag(event.status)}</div></div></div>`;
}

function renderReview() {
  const pending = state.events.filter(e => ["needs_review", "staged"].includes(e.status));
  $("#review-list").innerHTML = pending.length ? pending.map(reviewCard).join("") : `<div class="panel">${empty("No decisions waiting", "New or uncertain field events will appear here.")}</div>`;
  $$(".approve-button").forEach(button => button.addEventListener("click", () => decide(button.dataset.id, button.dataset.action)));
  $$(".reject-button").forEach(button => button.addEventListener("click", () => decide(button.dataset.id, "reject")));
}

function reviewCard(event) {
  const isActual = ["actual_start", "actual_finish"].includes(event.kind);
  const suggested = new Set((event.candidates || []).map(c => c.activity_id));
  const options = (event.candidates || []).map(c => `<option value="${safe(c.activity_id)}">${safe(c.activity_id)} · ${safe(c.name)}</option>`).join("");
  const other = state.activities.filter(a => !suggested.has(a.external_id)).map(a => `<option value="${safe(a.external_id)}">${safe(a.external_id)} · ${safe(a.name)}</option>`).join("");
  const select = `<select class="candidate-select"><option value="">Choose activity</option>${options}${other}</select>`;
  const warningList = (event.warnings || []).includes("Several activities are plausible")
    ? event.warnings.filter(w => w !== "No reliable activity match") : (event.warnings || []);
  const warnings = warningList.length ? `<div class="warning">${warningList.map(w => safe(w === "Event does not set an actual date" ? "This note will not update actual dates" : w)).join(" · ")}</div>` : "";
  const evidence = event.candidates?.[0]?.evidence?.length ? `<p class="match-evidence">Matched words: ${safe(event.candidates[0].evidence.join(", "))}</p>` : "";
  return `<article class="panel review-card" data-event-id="${safe(event.id)}"><div class="review-head"><div><p class="eyebrow">${safe(event.kind.replaceAll("_", " ").toUpperCase())}</p><h2>Field statement</h2></div>${statusTag(event.status)}</div><blockquote>${safe(event.text)}</blockquote>${evidence}${warnings}<div class="review-details"><div class="detail"><small>Event date</small><strong>${displayDate(event.event_date)}</strong></div><div class="detail"><small>Discipline</small><strong>${safe(event.discipline || "Unspecified")}</strong></div><div class="detail"><small>Location</small><strong>${safe(event.location || "Unspecified")}</strong></div></div><div class="review-actions"><label>${isActual ? "Schedule activity" : "Related activity (optional)"}${select}</label><label>${isActual ? "Actual date" : "Reference date"}<input class="decision-date" type="date" value="${safe(event.event_date || "")}"></label><button class="button secondary reject-button" data-id="${safe(event.id)}">Reject</button><button class="button primary approve-button" data-action="${isActual ? "approve" : "record"}" data-id="${safe(event.id)}">${isActual ? "Approve" : "Save note"}</button></div><input class="decision-reason" placeholder="Add a decision note (optional)" aria-label="Decision note"></article>`;
}

async function decide(id, action) {
  const card = $(`.review-card[data-event-id="${id}"]`);
  try {
    const result = await post(`/api/events/${id}/decision`, {
      action,
      activity_id: $(".candidate-select", card).value,
      event_date: $(".decision-date", card).value,
      reason: $(".decision-reason", card).value,
      actor: "Planner"
    });
    toast(`Event ${result.status}.`);
    await refresh();
  } catch (error) { toast(error.message, true); }
}

function renderSchedule() {
  const schedule = state.summary?.schedule;
  $("#schedule-title").textContent = schedule?.filename || "No schedule loaded";
  $("#schedule-meta").textContent = schedule ? `${schedule.format.toUpperCase()} · ${schedule.activity_count} activities · imported ${displayDate(schedule.created_at)}` : "Import an XER or CSV schedule to begin.";
  const query = $("#schedule-search").value.toLowerCase().trim();
  const rows = state.activities.filter(a => !query || `${a.external_id} ${a.name} ${a.wbs}`.toLowerCase().includes(query));
  const status = value => ({ TK_Active: "In progress", TK_NotStart: "Not started", TK_Complete: "Complete" }[value] || value || "—");
  $("#schedule-rows").innerHTML = rows.length ? rows.map(a => `<tr><td><strong>${safe(a.external_id)}</strong>${safe(a.name)}</td><td>${safe(a.wbs || "—")}</td><td>${displayDate(a.planned_start)}</td><td>${displayDate(a.planned_finish)}</td><td>${safe(status(a.status))}</td></tr>`).join("") : `<tr><td colspan="5">${state.activities.length ? "No matching activities." : "No schedule activities yet."}</td></tr>`;
}

function renderHistory() {
  $("#history-list").innerHTML = state.events.length ? state.events.map(eventRow).join("") : empty("No events recorded", "Events from reports will appear here.");
}

function renderExports() {
  const approved = state.events.filter(e => e.status === "approved").length;
  $("#export-count").textContent = `${approved} approved event${approved === 1 ? "" : "s"} ready`;
  $("#create-export").disabled = approved === 0;
}

async function importFile(file) {
  if (!file) return;
  try {
    const result = await post("/api/schedules/import", { filename: file.name, content: await file.text() });
    toast(`Imported ${result.activity_count} activities.`);
    await refresh();
    go("schedule");
  } catch (error) { toast(error.message, true); }
}

async function uploadSpreadsheet(file) {
  if (!file) return;
  try {
    const result = await post("/api/reports", { source_kind: "spreadsheet", filename: file.name, content: await file.text() });
    toast(`Processed ${result.events.length} field events.`);
    await refresh();
    go("review");
  } catch (error) { toast(error.message, true); }
}

async function submitReport(event) {
  event.preventDefault();
  const content = $("#report-text").value.trim();
  if (!content) return toast("Write a field update first.", true);
  try {
    const result = await post("/api/reports", {
      source_kind: "text", content,
      event_date: $("#report-date").value,
      discipline: $("#report-discipline").value,
      location: $("#report-location").value
    });
    $("#capture-result").innerHTML = `<div class="panel"><p class="eyebrow">PROCESSING COMPLETE</p><h2>${result.events.length} event${result.events.length === 1 ? "" : "s"} extracted</h2>${result.events.map(e => `<div class="event-row"><div class="event-glyph">◇</div><div class="event-body"><strong>${safe(e.text)}</strong><div class="event-meta"><small>${safe(e.candidates[0]?.activity_id || "Unmatched")} · ${displayDate(e.event_date)}</small>${statusTag(e.status)}</div></div></div>`).join("")}<div class="divider"></div><button class="button secondary" id="result-review">Open planner review →</button></div>`;
    $("#result-review").addEventListener("click", () => go("review"));
    $("#report-text").value = "";
    toast(`Processed ${result.events.length} event${result.events.length === 1 ? "" : "s"}.`);
    await refresh();
  } catch (error) { toast(error.message, true); }
}

async function loadDemo() {
  try {
    const result = await post("/api/demo/load");
    toast(`Sample project loaded: ${result.activity_count} activities.`);
    await refresh();
  } catch (error) { toast(error.message, true); }
}

async function createExport() {
  try {
    const result = await post("/api/exports");
    $("#export-result").innerHTML = `<div class="result-card"><strong>Export ready</strong><p>${result.manifest.row_count} approved ${result.manifest.row_count === 1 ? "event" : "events"} · source checksum ${safe(result.manifest.source_checksum.slice(0, 12))}…</p><a href="${safe(result.download)}">Download progress CSV →</a></div>`;
    toast("Export created.");
    await refresh();
  } catch (error) { toast(error.message, true); }
}

function bind() {
  $$(".nav-item").forEach(el => el.addEventListener("click", () => go(el.dataset.view)));
  $$("[data-goto]").forEach(el => el.addEventListener("click", () => go(el.dataset.goto)));
  $$(".example").forEach(el => el.addEventListener("click", () => {
    $("#report-text").value = el.dataset.example;
    $("#report-location").value = el.dataset.location;
    $("#report-date").value = new Intl.DateTimeFormat("sv-SE", { timeZone: "Asia/Kolkata", year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date());
    $("#report-text").focus();
  }));
  $("#report-form").addEventListener("submit", submitReport);
  $("#load-demo").addEventListener("click", loadDemo);
  $("#import-schedule").addEventListener("click", () => $("#schedule-file").click());
  $("#schedule-file").addEventListener("change", e => importFile(e.target.files[0]));
  $("#upload-spreadsheet").addEventListener("click", () => $("#spreadsheet-file").click());
  $("#spreadsheet-file").addEventListener("change", e => uploadSpreadsheet(e.target.files[0]));
  $("#schedule-search").addEventListener("input", renderSchedule);
  $("#create-export").addEventListener("click", createExport);
}

bind();
refresh().catch(error => toast(error.message, true));
