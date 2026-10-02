const state = { summary: null, activities: [], events: [], view: "overview", ai: null, processing: false };
const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const safe = (value) => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c]));
const displayDate = value => {
  if (!value) return "Date not specified";
  const parsed = new Date(String(value).slice(0, 10) + "T12:00:00");
  return Number.isNaN(parsed.getTime()) ? safe(value) : new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", year: "numeric" }).format(parsed);
};
const labels = { overview: "Overview", capture: "Capture report", review: "Review queue", schedule: "Schedule activities", analytics: "Schedule insights", history: "Progress history", exports: "Approved exports" };
const offline = window.CarrickOffline;
const checkIcon = '<svg viewBox="0 0 20 20" aria-hidden="true"><path d="m4 10 4 4 8-8"/></svg>';
const reportIcon = '<svg viewBox="0 0 20 20" aria-hidden="true"><path d="M4 2h8l4 4v12H4zM12 2v5h4M7 10h6M7 13h4"/></svg>';
const mobileNavigation = window.matchMedia("(max-width: 760px)");

function setNavigation(open) {
  const expanded = open && mobileNavigation.matches;
  document.body.classList.toggle("nav-open", expanded);
  $("#nav-backdrop").hidden = !expanded;
  $("#mobile-nav-toggle").setAttribute("aria-expanded", String(expanded));
  $("#mobile-nav-toggle").setAttribute("aria-label", expanded ? "Close workspace navigation" : "Open workspace navigation");
  $("#app-sidebar").inert = mobileNavigation.matches && !expanded;
}

async function request(path, options = {}) {
  let response;
  try { response = await fetch(path, { headers: { "Content-Type": "application/json" }, ...options }); }
  catch (_) {
    offline.setReachable(false);
    const error = new Error("The local server is unavailable. Your saved workspace can still be used offline.");
    error.transport = true;
    throw error;
  }
  offline.setReachable(true);
  const contentType = response.headers.get("content-type") || "";
  const data = contentType.includes("json") ? await response.json() : await response.text();
  if (!response.ok) { const error = new Error(data.error || `Request failed (${response.status})`); error.status = response.status; error.code = data.code; throw error; }
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

function go(view, updateHistory = true) {
  if (!labels[view]) return;
  state.view = view;
  $$(".nav-item").forEach(el => {
    const active = el.dataset.view === view;
    el.classList.toggle("active", active);
    if (active) el.setAttribute("aria-current", "page"); else el.removeAttribute("aria-current");
  });
  $$(".view").forEach(el => el.classList.toggle("active", el.id === `view-${view}`));
  $("#breadcrumb").textContent = labels[view];
  document.title = `Carrick · ${labels[view]}`;
  if (updateHistory && location.hash !== `#${view}`) history.pushState(null, "", `#${view}`);
  setNavigation(false);
  if (view === "review") renderReview();
  if (view === "schedule") renderSchedule();
  if (view === "history") renderHistory();
  if (view === "exports") renderExports();
  if (view === "analytics") window.CarrickAnalytics.load();
  window.scrollTo({ top: 0, behavior: "instant" });
}

async function refresh() {
  try {
    const [summary, activities, events] = await Promise.all([
      request("/api/summary"), request("/api/activities"), request("/api/events")
    ]);
    state.summary = summary; state.activities = activities; state.events = events;
    await offline.snapshot({ summary, activities, events }).catch(error => toast(error.message, true));
  } catch (error) {
    if (!error.transport) throw error;
    offline.setReachable(false);
    const stored = await offline.get("snapshots", "workspace");
    if (stored) Object.assign(state, stored.value);
    else toast("No saved workspace yet. Connect to the server once to enable offline capture.");
  }
  renderOverview(); renderReview(); renderSchedule(); renderHistory(); renderExports();
  renderDeviceReports();
}

async function refreshAiStatus() {
  const status = await request("/api/ai/status");
  state.ai = status;
  $("#ai-mode").disabled = !status.available;
  $("#ai-mode").checked = status.available;
  $("#ai-status").textContent = status.available
    ? (status.mode === "ollama" ? "Local AI uses schedule context. No cloud connection is needed." : "Schedule context helps interpret field language.")
    : "AI is unavailable. Standard matching is ready to use.";
  $("#ai-data-note").textContent = status.mode === "ollama"
    ? "AI analysis runs on this computer. Every proposed actual requires planner approval."
    : "When AI is enabled, the report and relevant schedule entries are sent to OpenAI for analysis. Every proposed actual requires planner approval.";
}

async function refreshCaptureStatus() {
  const status = await request("/api/capture/status");
  $("#capture-engine-status").textContent = status.ocr.available
    ? "Printed scan OCR is configured on the local server."
    : "Printed scans need the optional local OCR engine. Text files and emails are ready to use.";
  if (!status.voice.available) $("#voice-status").textContent = "Recording is available. Provision a local speech model to enable transcription.";
}

function statusTag(status) {
  const text = { needs_review: "Awaiting review", staged: "Ready for review", approved: "Approved", rejected: "Rejected", recorded: "Recorded", exported: "Exported" }[status] || "Unclassified";
  return `<span class="tag ${safe(status)}">${safe(text)}</span>`;
}

function renderOverview() {
  const schedule = state.summary?.schedule;
  $("#welcome").hidden = Boolean(schedule);
  $("#schedule-chip").textContent = schedule ? `${schedule.filename} · ${schedule.activity_count} activities` : "No schedule loaded";
  $("#schedule-chip").title = $("#schedule-chip").textContent;
  $("#sidebar-project").textContent = schedule ? schedule.filename.replace(/\.(xer|csv)$/i, "").replaceAll("-", " ").replaceAll("_", " ") : "Project workspace";
  const counts = state.summary?.counts || {};
  const pending = (counts.needs_review || 0) + (counts.staged || 0);
  $("#review-badge").hidden = !pending;
  $("#review-badge").textContent = pending;
  const metrics = [
    ["Schedule activities", schedule?.activity_count || 0, "In imported schedule"],
    ["Field events", state.events.length, "Captured from reports"],
    ["Awaiting review", pending, "Pending planner decision"],
    ["Approved actuals", (counts.approved || 0) + (counts.exported || 0), "Approved or exported"]
  ];
  $("#metrics").innerHTML = metrics.map(([label, value, sub]) => `<div class="metric"><div class="label">${label}</div><div class="value">${value}</div><div class="sub">${sub}</div></div>`).join("");
  $("#recent-events").innerHTML = state.events.length ? state.events.slice(0, 5).map(eventRow).join("") : empty("No field events yet", "Capture a report to see its extracted events here.");
  const action = $("#work-queue-action");
  if (!schedule) {
    $("#work-queue-title").textContent = "Import your schedule";
    $("#work-queue-copy").textContent = "Connect a schedule to start linking field reports to its activities.";
    action.dataset.goto = "schedule";
    action.textContent = "Open schedule →";
  } else if (pending) {
    $("#work-queue-title").textContent = `${pending} ${pending === 1 ? "event needs" : "events need"} a decision`;
    $("#work-queue-copy").textContent = "Check the source report, activity, and actual date before approval.";
    action.dataset.goto = "review";
    action.textContent = "Open review queue →";
  } else {
    $("#work-queue-title").textContent = "You’re up to date";
    $("#work-queue-copy").textContent = "Capture the next report to keep your project progress moving.";
    action.dataset.goto = "capture";
    action.textContent = "Write a field report →";
  }
}

function empty(title, message) {
  return `<div class="empty">${reportIcon}<strong>${safe(title)}</strong><span>${safe(message)}</span></div>`;
}

function eventRow(event) {
  const candidate = event.selected_activity || event.candidates?.[0]?.activity_id || "Unmatched";
  return `<div class="event-row"><div class="event-glyph">${reportIcon}</div><div class="event-body"><strong>${safe(event.text)}</strong><div class="event-meta"><small>${safe(candidate)} · ${displayDate(event.event_date)} · ${safe(event.kind.replaceAll("_", " "))}</small>${statusTag(event.status)}</div></div></div>`;
}

function renderReview() {
  const pending = state.events.filter(e => ["needs_review", "staged"].includes(e.status));
  $("#review-count").textContent = pending.length;
  $("#review-list").innerHTML = pending.length ? pending.map(reviewCard).join("") : `<div class="panel">${empty("No decisions waiting", "New or uncertain field events will appear here.")}</div>`;
  $$(".approve-button").forEach(button => button.addEventListener("click", () => decide(button.dataset.id, button.dataset.action)));
  $$(".reject-button").forEach(button => button.addEventListener("click", () => decide(button.dataset.id, "reject")));
  $$(".clarify-button").forEach(button => button.addEventListener("click", () => clarify(button.dataset.id)));
  $$(".candidate-choice").forEach(input => input.addEventListener("change", () => {
    $(".candidate-select", input.closest(".review-card")).value = input.value;
  }));
  $$(".candidate-select").forEach(select => select.addEventListener("change", () => {
    $$(".candidate-choice", select.closest(".review-card")).forEach(input => input.checked = input.value === select.value);
  }));
  if (!offline.reachable) $$(".approve-button, .reject-button, .clarify-button").forEach(button => button.disabled = true);
}

function reviewCard(event) {
  const isActual = ["actual_start", "actual_finish"].includes(event.kind);
  const suggested = new Set((event.candidates || []).map(c => c.activity_id));
  const options = (event.candidates || []).map(c => `<option value="${safe(c.activity_id)}">${safe(c.activity_id)} · ${safe(c.name)}</option>`).join("");
  const other = state.activities.filter(a => !suggested.has(a.external_id)).map(a => `<option value="${safe(a.external_id)}">${safe(a.external_id)} · ${safe(a.name)}</option>`).join("");
  const select = `<select class="candidate-select"><option value="">Choose activity</option>${options}${other}</select>`;
  const warningList = (event.warnings || []).filter(w => w !== "AI suggestion requires planner confirmation" &&
    !(w === "No reliable activity match" && event.warnings.includes("Several activities are plausible")));
  const warnings = warningList.length ? `<div class="warning"><ul>${warningList.map(w => `<li>${safe(w === "Event does not set an actual date" ? "Keep this event as a progress note; it does not establish an actual date." : w)}</li>`).join("")}</ul></div>` : "";
  const top = event.candidates?.[0];
  const evidence = top?.match_reason && top.match_reason !== "Ranked by local cross-encoder"
    ? `<p class="match-evidence">Matching context: ${safe(top.match_reason)}</p>`
    : top?.evidence?.length ? `<p class="match-evidence">Related report terms: ${safe(top.evidence.join(", "))}</p>` : "";
  const sourceDetails = event.capture_asset_id ? `<p class="capture-source-note">${event.source_row ? `Page ${safe(event.source_row)} · ` : ""}<a class="text-button" href="/api/captures/${safe(event.capture_asset_id)}/original" target="_blank" rel="noopener">Download original source →</a></p>` : "";
  const analysisDetails = sourceDetails + (event.analysis_mode === "ai" ? `<details class="analysis-details"><summary>Analysis details</summary><p>AI matching · ${safe(event.model_name || "model")} · Proposed values require planner confirmation.</p></details>` : "");
  const question = event.clarification_question ? `<div class="warning">${safe(event.clarification_question)}</div>` : "";
  const clarification = event.analysis_mode === "ai" ? `<div class="clarification"><label>${event.clarification_answer ? "Update field context" : "Add field context"}<input class="clarification-answer" maxlength="400" placeholder="e.g. North pipeline near Pump A" value="${safe(event.clarification_answer || "")}"></label><button class="button secondary clarify-button" data-id="${safe(event.id)}">Refine suggestions</button></div>` : "";
  const shortlist = (event.candidates || []).slice(0, 3).map((candidate, index) => `<label class="candidate-option"><input type="radio" class="candidate-choice" name="activity-${safe(event.id)}" value="${safe(candidate.activity_id)}"><span><strong><span class="candidate-id">${safe(candidate.activity_id)}</span><span class="candidate-name">${safe(candidate.name)}</span></strong><small>${safe(candidate.wbs || "Imported schedule activity")}${index === 0 ? " · First suggestion" : ""}</small></span></label>`).join("");
  const kind = event.kind.replaceAll("_", " ");
  return `<article class="panel review-card" data-event-id="${safe(event.id)}"><div class="review-head"><h2>${safe(kind.charAt(0).toUpperCase() + kind.slice(1))}</h2>${statusTag(event.status)}</div><div class="review-layout"><div class="review-source"><span class="review-label">Source report</span><blockquote>${safe(event.text)}</blockquote><div class="review-details"><div class="detail"><small>Reported date</small><strong>${displayDate(event.event_date)}</strong></div><div class="detail"><small>Discipline</small><strong>${safe(event.discipline || "Not specified")}</strong></div><div class="detail"><small>Work area</small><strong>${safe(event.location || "Not specified")}</strong></div></div>${analysisDetails}${warnings}${question}${clarification}</div><div class="review-proposal"><span class="review-label">Suggested activities · Select one to confirm</span><div class="candidate-shortlist">${shortlist || '<p class="muted">Choose an activity from the imported schedule.</p>'}</div>${evidence}<div class="review-fields"><label>${isActual ? "Schedule activity" : "Related activity (optional)"}${select}</label><label>${isActual ? "Actual date" : "Reference date"}<input class="decision-date" type="date" value="${safe(event.event_date || "")}"></label></div><label class="decision-note">Decision note <span class="optional">Optional</span><input class="decision-reason" placeholder="Add context for the planning team" aria-label="Decision note"></label></div></div><div class="review-actions"><span class="decision-help">Confirm the activity and date before approving.</span><button class="button secondary reject-button" data-id="${safe(event.id)}">Reject event</button><button class="button primary approve-button" data-action="${isActual ? "approve" : "record"}" data-id="${safe(event.id)}">${isActual ? "Approve actual" : "Record note"}</button></div></article>`;
}

async function clarify(id) {
  const card = $(`.review-card[data-event-id="${id}"]`);
  const button = $(".clarify-button", card);
  if (button.disabled) return;
  const answer = $(".clarification-answer", card).value.trim();
  if (!answer) return toast("Add context from the field first.", true);
  button.disabled = true;
  button.textContent = "Refining…";
  try {
    await post(`/api/events/${id}/clarify`, { answer });
    toast("Suggestion refined. Check the activity and date before deciding.");
    await refresh();
  } catch (error) { toast(error.message, true); }
  finally { button.disabled = false; button.textContent = "Refine suggestions"; }
}

async function decide(id, action) {
  const card = $(`.review-card[data-event-id="${id}"]`);
  const buttons = $$(".approve-button, .reject-button", card);
  if (buttons.some(button => button.disabled)) return;
  buttons.forEach(button => button.disabled = true);
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
  finally { buttons.forEach(button => button.disabled = false); }
}

function renderSchedule() {
  const schedule = state.summary?.schedule;
  $("#schedule-title").textContent = schedule?.filename || "No schedule loaded";
  $("#schedule-meta").textContent = schedule ? `${schedule.format.toUpperCase()} · ${schedule.activity_count} activities · imported ${displayDate(schedule.created_at)}` : "Import an XER or CSV schedule to begin.";
  const query = $("#schedule-search").value.toLowerCase().trim();
  const rows = state.activities.filter(a => !query || `${a.external_id} ${a.name} ${a.wbs}`.toLowerCase().includes(query));
  $("#schedule-result-count").textContent = `${rows.length} ${rows.length === 1 ? "activity" : "activities"}`;
  const status = value => ({ TK_Active: "In progress", TK_NotStart: "Not started", TK_Complete: "Complete" }[value] || value || "—");
  $("#schedule-rows").innerHTML = rows.length ? rows.map(a => `<tr><td><strong>${safe(a.external_id)}</strong>${safe(a.name)}</td><td>${safe(a.wbs || "—")}</td><td>${displayDate(a.planned_start)}</td><td>${displayDate(a.planned_finish)}</td><td>${safe(status(a.status))}</td></tr>`).join("") : `<tr><td colspan="5">${state.activities.length ? "No matching activities." : "No schedule activities yet."}</td></tr>`;
}

function renderHistory() {
  const query = $("#history-search").value.trim().toLowerCase();
  const filter = $("#history-filter").value;
  const events = state.events.filter(event => {
    const statusMatches = filter === "all" || (filter === "pending" ? ["needs_review", "staged"].includes(event.status) : event.status === filter);
    const searchText = [event.text, event.selected_activity, ...(event.candidates || []).map(candidate => candidate.activity_id)].join(" ").toLowerCase();
    return statusMatches && (!query || searchText.includes(query));
  });
  $("#history-list").innerHTML = events.length ? events.map(eventRow).join("") : empty(state.events.length ? "No matching progress records" : "No progress records yet", state.events.length ? "Try another search or review status." : "Capture a field report to start your project history.");
}

function renderExports() {
  const approved = state.events.filter(e => e.status === "approved").length;
  $("#export-count").textContent = `${approved} approved event${approved === 1 ? "" : "s"} ready`;
  $("#create-export").disabled = approved === 0 || !offline.reachable;
}

async function importFile(file) {
  if (!file) return;
  const button = $("#import-schedule");
  if (button.disabled) return;
  const label = button.innerHTML;
  button.disabled = true;
  button.textContent = "Importing schedule…";
  try {
    const result = await post("/api/schedules/import", { filename: file.name, content: await file.text() });
    toast(`Imported ${result.activity_count} activities.`);
    await refresh();
    go("schedule");
  } catch (error) { toast(error.message, true); }
  finally { button.disabled = false; button.innerHTML = label; $("#schedule-file").value = ""; }
}

async function uploadSpreadsheet(file) {
  if (!file) return;
  if (state.processing) return;
  state.processing = true;
  const button = $("#upload-spreadsheet");
  button.disabled = true;
  const label = button.innerHTML;
  button.textContent = "Analyzing file…";
  try {
    if (file.size > 10000000) throw new Error("Choose a CSV file of 10 MB or less.");
    const payload = { source_kind: "spreadsheet", filename: file.name, content: await file.text(),
      analysis_mode: $("#ai-mode").checked ? "ai" : "rules", schedule_version: state.summary?.schedule?.id,
      client_request_id: offline.id(), event_date: $("#report-date").value,
      discipline: $("#report-discipline").value, location: $("#report-location").value };
    let result, conflict = false;
    if (offline.reachable) {
      try { result = await post("/api/reports", payload); }
      catch (error) {
        if (error.status === 409) { conflict = true; await offline.enqueue(payload, { status: "conflict", error: error.message }); await refresh(); }
        else if (!error.transport) throw error;
      }
    }
    if (!result) { if (!conflict) await offline.enqueue(payload); toast(conflict ? "CSV saved. Review it against the current schedule in Saved on this device." : "CSV report saved for submission when connected."); await renderDeviceReports(); return; }
    toast(`Processed ${result.events.length} field events.`);
    await refresh();
    go("review");
  } catch (error) { toast(error.message, true); }
  finally { state.processing = false; button.disabled = false; button.innerHTML = label; $("#spreadsheet-file").value = ""; }
}

async function uploadDocument(file) {
  return window.CarrickCapture.uploadDocument(file);
}

async function submitReport(event) {
  event.preventDefault();
  if (state.processing) return;
  const content = $("#report-text").value.trim();
  if (!content) return toast("Write a field update first.", true);
  state.processing = true;
  const button = $("#report-form button[type=submit]");
  button.disabled = true;
  const label = button.innerHTML;
  button.textContent = "Analyzing report…";
  try {
    const voice = window.CarrickCapture.voiceSource;
    const payload = {
      source_kind: voice ? "voice" : "text", content,
      ...(voice ? { capture_asset_id: voice.assetId, filename: voice.filename } : {}),
      analysis_mode: $("#ai-mode").checked ? "ai" : "rules",
      event_date: $("#report-date").value,
      discipline: $("#report-discipline").value,
      location: $("#report-location").value,
      schedule_version: voice?.scheduleVersion || state.summary?.schedule?.id,
      client_request_id: offline.id()
    };
    let result, conflict = false;
    if (offline.reachable) {
      try { result = await post("/api/reports", payload); }
      catch (error) {
        if (error.status === 409) { conflict = true; await offline.enqueue(payload, { status: "conflict", error: error.message }); await refresh(); }
        else if (!error.transport) throw error;
      }
    }
    if (!result) {
      if (!conflict) await offline.enqueue(payload);
      $("#report-text").value = "";
      await window.CarrickCapture.completeVoice();
      await clearTypedDraft();
      $("#capture-result").innerHTML = `<div class="panel"><h2>Report saved on this device</h2><p>${conflict ? "The schedule changed. Review this saved report against the current import before submission." : "It will be submitted when the local server is available. Planner review happens after analysis."}</p></div>`;
      toast(conflict ? "Report saved. Review its schedule connection before submission." : "Report saved offline.");
      await renderDeviceReports();
      return;
    }
    $("#capture-result").innerHTML = `<div class="panel"><p class="eyebrow">Report analyzed</p><h2>${result.events.length} progress event${result.events.length === 1 ? "" : "s"} ready for review</h2>${result.events.map(e => `<div class="event-row"><div class="event-glyph">${reportIcon}</div><div class="event-body"><strong>${safe(e.text)}</strong><div class="event-meta"><small>${safe(e.candidates[0]?.activity_id || "Unmatched")} · ${displayDate(e.event_date)}</small>${statusTag(e.status)}</div></div></div>`).join("")}<div class="divider"></div><button class="button primary" id="result-review">Review suggestions →</button></div>`;
    $("#result-review").addEventListener("click", () => go("review"));
    $("#report-text").value = "";
    await window.CarrickCapture.completeVoice();
    await clearTypedDraft();
    toast(`Processed ${result.events.length} event${result.events.length === 1 ? "" : "s"}.`);
    await refresh();
  } catch (error) { toast(error.message, true); }
  finally { state.processing = false; button.disabled = false; button.innerHTML = label; renderDeviceReports(); }
}

async function loadDemo() {
  const button = $("#load-demo");
  if (button.disabled) return;
  button.disabled = true;
  try {
    const result = await post("/api/demo/load");
    toast(`Sample project loaded: ${result.activity_count} activities.`);
    await refresh();
  } catch (error) { toast(error.message, true); }
  finally { button.disabled = false; }
}

async function createExport() {
  const button = $("#create-export");
  if (button.disabled) return;
  const label = button.innerHTML;
  button.disabled = true;
  button.textContent = "Preparing export…";
  try {
    const result = await post("/api/exports");
    $("#export-result").innerHTML = `<div class="result-card"><strong>Your export is ready</strong><p>${result.manifest.row_count} approved ${result.manifest.row_count === 1 ? "event" : "events"}, with source and approval references.</p><a href="${safe(result.download)}">Download progress CSV →</a></div>`;
    toast("Export created.");
    await refresh();
  } catch (error) { toast(error.message, true); }
  finally { button.innerHTML = label; renderExports(); }
}

let draftTimer;
async function persistTypedDraft() {
  try {
    await offline.put("snapshots", { id: "typed-report", text: $("#report-text").value,
      event_date: $("#report-date").value, discipline: $("#report-discipline").value,
      location: $("#report-location").value, voiceSource: window.CarrickCapture.voiceSource,
      savedAt: new Date().toISOString() });
  } catch (error) { toast(error.message, true); }
}
async function clearTypedDraft() { clearTimeout(draftTimer); await offline.remove("snapshots", "typed-report"); }
async function restoreTypedDraft() {
  const draft = await offline.get("snapshots", "typed-report");
  if (!draft || $("#report-text").value) return;
  $("#report-text").value = draft.text || "";
  $("#report-date").value = draft.event_date || "";
  $("#report-discipline").value = draft.discipline || "";
  $("#report-location").value = draft.location || "";
  if (draft.voiceSource) window.CarrickCapture.restoreVoiceSource(draft.voiceSource);
}

async function renderDeviceReports() {
  try {
    const [outbox, drafts] = await Promise.all([offline.list("outbox"), offline.list("drafts")]);
    const banner = $("#connection-banner");
    banner.hidden = offline.reachable && outbox.length === 0;
    $("#connection-copy").textContent = !offline.reachable
      ? `Working offline. Showing your last saved workspace. ${outbox.length} report${outbox.length === 1 ? "" : "s"} waiting to sync.`
      : `${outbox.length} saved report${outbox.length === 1 ? "" : "s"} waiting for submission${offline.syncing ? " · Syncing…" : ""}.`;
    $("#sync-now").textContent = offline.reachable ? "Sync now" : "Reconnect";
    $("#retry-outbox").disabled = !offline.reachable || offline.syncing;
    if (!state.processing) $("#report-form button[type=submit]").textContent = offline.reachable ? "Analyze report →" : "Save report offline";
    $("#device-reports-list").innerHTML = outbox.length || drafts.length
      ? outbox.map(item => `<div class="device-report"><div><strong>${safe(item.payload.filename || item.payload.content?.slice(0, 90) || "Field report")}</strong><small>${safe({ pending: "Submitted offline · Waiting to sync", failed: "Submission needs attention", conflict: "Schedule changed · Review required" }[item.status])}</small>${item.error ? `<p class="capture-warning">${safe(item.error)}</p>` : ""}${item.payload.reviewed_pages ? `<details><summary>Reviewed document text</summary><p>${safe(item.payload.reviewed_pages.map(page => page.text).join("\n\n"))}</p></details>` : ""}</div><div class="device-report-actions">${item.status === "conflict" ? `<button class="text-button" data-rebind-report="${safe(item.id)}" ${!offline.reachable ? "disabled" : ""}>Review with current schedule</button>` : ""}<button class="text-button" data-download-report="${safe(item.id)}">Download copy</button><button class="text-button" data-remove-report="${safe(item.id)}">Discard</button></div></div>`).join("")
        + drafts.map(draft => `<div class="device-report"><div><strong>${safe(draft.filename)}</strong><small>${draft.kind === "voice" ? "Voice recording" : "Document"} · ${draft.receipt ? "Ready for your review" : "Saved for local extraction"}</small></div><div class="device-report-actions"><button class="text-button" data-open-draft="${safe(draft.id)}">${draft.receipt ? "Review" : draft.kind === "voice" ? "Open recording" : "Extract text"}</button><button class="text-button" data-download-draft="${safe(draft.id)}">Download copy</button><button class="text-button" data-remove-draft="${safe(draft.id)}">Discard</button></div></div>`).join("")
      : '<p class="muted">No reports or attachments waiting on this device.</p>';
    const download = (blob, filename) => {
      const url = URL.createObjectURL(blob), link = document.createElement("a");
      link.href = url; link.download = filename; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
    };
    $$("[data-open-draft]").forEach(button => button.addEventListener("click", () => window.CarrickCapture.openDraft(drafts.find(draft => draft.id === button.dataset.openDraft))));
    $$("[data-download-draft]").forEach(button => button.addEventListener("click", () => { const draft = drafts.find(item => item.id === button.dataset.downloadDraft); download(draft.blob, draft.filename); }));
    $$("[data-download-report]").forEach(button => button.addEventListener("click", () => { const item = outbox.find(row => row.id === button.dataset.downloadReport); download(new Blob([JSON.stringify(item.payload, null, 2)], { type: "application/json" }), "carrick-saved-report.json"); }));
    $$("[data-rebind-report]").forEach(button => button.addEventListener("click", async () => {
      if (!window.confirm("Submit this saved report for matching against the currently imported schedule? Planner review will still be required.")) return;
      button.disabled = true;
      try { await offline.rebind(button.dataset.rebindReport, state.summary?.schedule?.id); }
      catch (error) { toast(error.message, true); }
      finally { await renderDeviceReports(); }
    }));
    $$("[data-remove-report], [data-remove-draft]").forEach(button => button.addEventListener("click", async () => {
      if (!window.confirm("Discard this device-local report or attachment? Download a copy first if you need it.")) return;
      try { await offline.remove(button.dataset.removeReport ? "outbox" : "drafts", button.dataset.removeReport || button.dataset.removeDraft); await renderDeviceReports(); }
      catch (error) { toast(error.message, true); }
    }));
  } catch (error) { toast(error.message, true); }
}

function bind() {
  $$(".nav-item").forEach(el => el.addEventListener("click", () => go(el.dataset.view)));
  $$("[data-goto]").forEach(el => el.addEventListener("click", () => go(el.dataset.goto)));
  $$(".example").forEach(el => el.addEventListener("click", () => {
    window.CarrickCapture.clearVoiceSource();
    $("#report-text").value = el.dataset.example;
    $("#report-location").value = el.dataset.location;
    $("#report-date").value = new Intl.DateTimeFormat("sv-SE", { timeZone: "Asia/Kolkata", year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date());
    $("#report-text").focus();
    persistTypedDraft();
  }));
  $("#report-form").addEventListener("submit", submitReport);
  $("#load-demo").addEventListener("click", loadDemo);
  $("#import-schedule").addEventListener("click", () => $("#schedule-file").click());
  $("#schedule-file").addEventListener("change", e => importFile(e.target.files[0]));
  $("#upload-spreadsheet").addEventListener("click", () => $("#spreadsheet-file").click());
  $("#spreadsheet-file").addEventListener("change", e => uploadSpreadsheet(e.target.files[0]));
  $("#upload-document").addEventListener("click", () => $("#document-file").click());
  $("#document-file").addEventListener("change", e => uploadDocument(e.target.files[0]));
  $("#schedule-search").addEventListener("input", renderSchedule);
  $("#history-search").addEventListener("input", renderHistory);
  $("#history-filter").addEventListener("change", renderHistory);
  $("#create-export").addEventListener("click", createExport);
  $("#sync-now").addEventListener("click", async () => { await offline.health(); await offline.sync(true); });
  $("#retry-outbox").addEventListener("click", () => offline.sync(true).catch(error => toast(error.message, true)));
  $$("#report-text, #report-date, #report-discipline, #report-location").forEach(input => input.addEventListener("input", () => { clearTimeout(draftTimer); draftTimer = setTimeout(persistTypedDraft, 400); }));
  let lastReachable = offline.reachable;
  offline.subscribe(() => {
    renderDeviceReports();
    if (offline.reachable !== lastReachable) {
      lastReachable = offline.reachable;
      $$(".approve-button, .reject-button, .clarify-button").forEach(button => button.disabled = !offline.reachable);
      renderExports();
    }
  });
  window.addEventListener("carrick-drafts-changed", renderDeviceReports);
  window.addEventListener("carrick-schedule-conflict", () => refresh().catch(error => toast(error.message, true)));
  window.addEventListener("carrick-report-synced", () => { refresh().catch(error => toast(error.message, true)); toast("Saved report synced. Its events are ready for planner review."); });
  window.addEventListener("carrick-reconnected", () => { refresh().catch(error => toast(error.message, true)); refreshAiStatus().catch(() => {}); refreshCaptureStatus().catch(() => {}); });
  window.addEventListener("carrick-cache-unavailable", () => toast("Offline page caching is unavailable. Device drafts can still be saved, but keep the page open.", true));
  $("#mobile-nav-toggle").addEventListener("click", () => setNavigation(!document.body.classList.contains("nav-open")));
  $("#nav-backdrop").addEventListener("click", () => setNavigation(false));
  mobileNavigation.addEventListener("change", () => setNavigation(false));
  window.addEventListener("popstate", () => go(location.hash.slice(1) || "overview", false));
  window.addEventListener("hashchange", () => go(location.hash.slice(1) || "overview", false));
  document.addEventListener("keydown", event => {
    if (event.key === "Escape" && document.body.classList.contains("nav-open")) {
      setNavigation(false); $("#mobile-nav-toggle").focus();
    }
  });
}

window.CarrickCapture.init({ post, toast, refresh, go, offline, getSchedule: () => state.summary?.schedule?.id, isAi: () => $("#ai-mode").checked });
window.CarrickAnalytics.init({ post, request, toast, offline, date: displayDate });
bind();
setNavigation(false);
go(labels[location.hash.slice(1)] ? location.hash.slice(1) : "overview", false);
refreshAiStatus().catch(() => $("#ai-status").textContent = "AI availability could not be checked. Standard matching is available.");
refreshCaptureStatus().catch(() => $("#capture-engine-status").textContent = "Connect to the local server to check scan extraction availability.");
refresh().catch(error => toast(error.message, true));
restoreTypedDraft().catch(error => toast(error.message, true));
