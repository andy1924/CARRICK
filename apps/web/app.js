const state = { summary: null, activities: [], events: [], view: "overview", ai: null, processing: false, ready: false, refreshing: false, stale: false, exporting: false };
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
  const timeout = AbortSignal.timeout(options.method === "POST" ? 90000 : 15000);
  const signal = options.signal ? AbortSignal.any([options.signal, timeout]) : timeout;
  try { response = await fetch(path, { ...options, signal, headers: { "Content-Type": "application/json", ...window.CarrickAuth.headers(), ...options.headers } }); }
  catch (failure) {
    if (options.signal?.aborted) throw failure;
    if (timeout.aborted) throw new Error("The server is taking longer than expected. Retry when it responds. Saved reports are retained.");
    offline.setReachable(false);
    const error = new Error("The local server is unavailable. Your saved workspace can still be used offline.");
    error.transport = true;
    throw error;
  }
  offline.setReachable(true);
  const contentType = response.headers.get("content-type") || "";
  let data;
  try { data = contentType.includes("json") ? await response.json() : await response.text(); }
  catch (_) { throw new Error("The server returned an incomplete response. Retry loading; your saved work is retained."); }
  if (!response.ok) { const error = new Error(data.error || `Request failed (${response.status})`); error.status = response.status; error.code = data.code; error.data = data; if(response.status===401) window.CarrickAuth.showLogin("Your session expired. Sign in to retry saved reports."); throw error; }
  return data;
}
const post = (path, body = {}) => request(path, { method: "POST", body: JSON.stringify(body) });

let toastTimer;
function toast(message, error = false) {
  const el = $("#toast");
  $("#toast-message").textContent = message;
  el.className = error ? "show error" : "show";
  clearTimeout(toastTimer);
  if (!error) toastTimer = setTimeout(() => el.className = "", 5000);
}

function workspaceStatus(kind, title, copy) {
  const panel = $("#workspace-status");
  panel.hidden = !kind;
  panel.dataset.state = kind || "";
  $("#workspace-status-title").textContent = title || "";
  $("#workspace-status-copy").textContent = copy || "";
  $("#workspace-retry").hidden = !["error", "offline"].includes(kind);
}

function updateAvailability() {
  $("#workspace-refresh").disabled = state.refreshing;
  $("#workspace-retry").disabled = state.refreshing;
  $("#report-form button[type=submit]").disabled = state.processing || !state.ready || !state.summary?.schedule;
  $("#report-form").setAttribute("aria-busy", String(state.processing));
  $$("input,textarea,select",$("#report-form")).forEach(input=>input.disabled=state.processing || input.id === "ai-mode" && !state.ai?.available);
  $$(".example, #voice-use").forEach(button=>button.disabled=state.processing);
  $("#report-form .form-footer .field-help").textContent = state.summary?.schedule ? "Your original report is retained." : "Import a schedule before submitting. You can save a draft while you wait.";
  $$(".review-card").forEach(updateReviewAvailability);
  renderExports();
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

let refreshSequence = 0, refreshController;
async function refresh() {
  const sequence = ++refreshSequence;
  refreshController?.abort();
  refreshController = new AbortController();
  const signal = refreshController.signal;
  state.refreshing = true;
  $(".content").setAttribute("aria-busy", "true");
  workspaceStatus("loading", state.ready ? "Refreshing workspace" : "Loading workspace", state.ready ? "Your current view stays available while we check for updates." : "Getting your latest schedule and reports…");
  updateAvailability();
  try {
    const [summary, activities, events] = await Promise.all([
      request("/api/summary", {signal}), request("/api/activities", {signal}), request("/api/events", {signal})
    ]);
    if (sequence !== refreshSequence) return;
    if (!summary || typeof summary !== "object" || !Array.isArray(activities) || !Array.isArray(events)) throw new Error("Workspace data could not be read. Retry loading.");
    state.summary = summary; state.activities = activities; state.events = events; state.ready = true; state.stale = false;
    $("#workspace-updated").textContent = `Updated ${new Intl.DateTimeFormat(undefined, {hour:"2-digit", minute:"2-digit"}).format(new Date())}`;
    workspaceStatus(null);
    await offline.snapshot({ summary, activities, events }).catch(error => toast(error.message, true));
    return true;
  } catch (error) {
    if (sequence !== refreshSequence || signal.aborted) return;
    state.stale = true;
    if (!state.ready) {
      try {
        const stored = await offline.get("snapshots", "workspace");
        if (stored) { Object.assign(state, stored.value); state.ready = true; $("#workspace-updated").textContent = `Saved workspace · ${displayDate(stored.savedAt)}`; }
      } catch (storageError) { toast(storageError.message, true); }
    }
    workspaceStatus(error.transport ? "offline" : "error", state.ready ? "Showing saved workspace" : "Workspace could not load", `${error.message} ${state.ready ? "Approvals and exports will resume after a successful refresh." : "Use Retry loading to reconnect."}`);
    return false;
  } finally {
    if (sequence === refreshSequence) {
      state.refreshing = false;
      $(".content").setAttribute("aria-busy", "false");
      renderOverview(); renderReview(); renderSchedule(); renderExports();
      if (state.view === "history") renderHistory();
      renderDeviceReports(); updateAvailability();
    }
  }
}

async function refreshAiStatus() {
  const status = await request("/api/ai/status");
  state.ai = status;
  $("#ai-mode").disabled = !status.available || state.processing;
  $("#ai-mode").checked = status.available && (state.aiPreferred ?? true);
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
  if (!status.voice.available && $("#voice-preview").hidden && $("#voice-record").getAttribute("aria-pressed") !== "true") $("#voice-status").textContent = "Recording is available. Provision a local speech model to enable transcription.";
}

function statusTag(status) {
  const text = { needs_review: "Awaiting review", staged: "Ready for review", approved: "Approved", rejected: "Rejected", recorded: "Recorded", exported: "Exported", duplicate: "Repeated actual" }[status] || "Unclassified";
  return `<span class="tag ${safe(status)}">${safe(text)}</span>`;
}

function renderOverview() {
  if (!state.ready) {
    $("#welcome").hidden = true;
    $("#metrics").innerHTML = ["Schedule activities","Field events","Awaiting review","Approved actuals"].map(label=>`<div class="metric"><div class="label">${label}</div><div class="value metric-placeholder">—</div><div class="sub">Waiting for workspace data</div></div>`).join("");
    $("#recent-events").innerHTML = empty("Progress is not available yet", "Retry loading to see your project records.");
    $("#work-queue-title").textContent = "Workspace unavailable";
    $("#work-queue-copy").textContent = "Load project data before making a planning decision.";
    return;
  }
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

const reviewDrafts = new Map(), pendingDecisions = new Set();
function updateReviewAvailability(card) {
  const allowed = state.ready && !state.stale && !state.refreshing && offline.reachable && ["owner","planner"].includes(window.CarrickAuth.project?.role);
  const busy = pendingDecisions.has(card.dataset.eventId);
  const signature = `${$(".candidate-select",card).value}|${$(".decision-date",card).value}`;
  const checked = card.dataset.actual !== "true" || card.dataset.checked === signature && card.dataset.blocked === "false";
  const noteReady = !$(".decision-reason",card).required || Boolean($(".decision-reason",card).value.trim());
  $(".approve-button",card).disabled = !allowed || busy || !checked || !noteReady;
  $(".reject-button",card).disabled = !allowed || busy;
  $$("input,select,.clarify-button",card).forEach(input=>input.disabled = busy || input.classList.contains("clarify-button") && (!offline.reachable || state.stale));
  card.setAttribute("aria-busy", String(busy));
}

function renderReview() {
  $$(".review-card").forEach(card=>reviewDrafts.set(card.dataset.eventId, {
    activity:$(".candidate-select",card).value, date:$(".decision-date",card).value,
    reason:$(".decision-reason",card).value, answer:$(".clarification-answer",card)?.value,
    version:card.dataset.scheduleVersion
  }));
  if (!state.ready) {
    $("#review-list").innerHTML = `<div class="panel">${empty("Review queue is not available yet", "Load the workspace before making a decision.")}</div>`;
    return;
  }
  const pending = state.events.filter(e => ["needs_review", "staged"].includes(e.status));
  for (const id of reviewDrafts.keys()) if (!pending.some(event=>event.id===id)) reviewDrafts.delete(id);
  $("#review-count").textContent = pending.length;
  $("#review-list").innerHTML = pending.length ? pending.map(reviewCard).join("") : `<div class="panel">${empty("No decisions waiting", "New or uncertain field events will appear here.")}</div>`;
  $$(".approve-button").forEach(button => button.addEventListener("click", () => decide(button.dataset.id, button.dataset.action)));
  $$(".reject-button").forEach(button => button.addEventListener("click", () => decide(button.dataset.id, "reject")));
  $$(".clarify-button").forEach(button => button.addEventListener("click", () => clarify(button.dataset.id)));
  $$(".candidate-choice").forEach(input => input.addEventListener("change", () => {
    $(".candidate-select", input.closest(".review-card")).value = input.value;
    checkDecision(input.closest(".review-card"));
  }));
  $$(".candidate-select").forEach(select => select.addEventListener("change", () => {
    $$(".candidate-choice", select.closest(".review-card")).forEach(input => input.checked = input.value === select.value);
    checkDecision(select.closest(".review-card"));
  }));
  $$(".decision-date").forEach(input => input.addEventListener("change", () => checkDecision(input.closest(".review-card"))));
  $$(".review-card").forEach(card=>{
    card.dataset.actual = String(["actual_start","actual_finish"].includes(pending.find(event=>event.id===card.dataset.eventId).kind));
    card.dataset.scheduleVersion = state.summary?.schedule?.id || "";
    const draft = reviewDrafts.get(card.dataset.eventId);
    if (draft?.version === card.dataset.scheduleVersion) {
      $(".candidate-select",card).value = draft.activity;
      $(".decision-date",card).value = draft.date;
      $(".decision-reason",card).value = draft.reason;
      if ($(".clarification-answer",card)) $(".clarification-answer",card).value = draft.answer || "";
      $$(".candidate-choice",card).forEach(input=>input.checked=input.value===draft.activity);
    }
    $(".decision-reason",card).addEventListener("input",()=>updateReviewAvailability(card));
    updateReviewAvailability(card);
    if ($(".candidate-select",card).value && !state.stale && !pendingDecisions.has(card.dataset.eventId)) checkDecision(card);
  });
}

async function checkDecision(card) {
  const button = $(".approve-button",card);
  const panel = $(".proposal-checks",card);
  const revision = Number(card.dataset.checkRevision || 0)+1;
  card.dataset.checkRevision = revision;
  delete card.dataset.checked;
  const signature = `${$(".candidate-select",card).value}|${$(".decision-date",card).value}`;
  button.disabled = true;
  panel.textContent = "Checking the activity and date…";
  try {
    const result = await post(`/api/events/${card.dataset.eventId}/checks`, {
      activity_id: $(".candidate-select",card).value, event_date: $(".decision-date",card).value
    });
    if (!card.isConnected || Number(card.dataset.checkRevision) !== revision) return;
    panel.innerHTML = result.checks.length ? `<ul>${result.checks.map(check => `<li class="check-${safe(check.severity)}">${safe(check.message)}</li>`).join("")}</ul>` : "Activity and date pass the current checks.";
    $(".decision-note .optional",card).textContent = result.requires_reason ? "Required for these warnings" : "Optional";
    $(".decision-reason",card).required = result.requires_reason;
    card.dataset.checked = signature;
    card.dataset.blocked = String(result.blocked);
    updateReviewAvailability(card);
  } catch (error) {
    if (!card.isConnected || Number(card.dataset.checkRevision) !== revision) return;
    panel.textContent = error.message;
    const retry = document.createElement("button"); retry.type = "button"; retry.className = "text-button"; retry.textContent = "Retry checks";
    retry.addEventListener("click",()=>checkDecision(card)); panel.append(retry);
    button.disabled = true;
  }
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
  return `<article class="panel review-card" data-event-id="${safe(event.id)}"><div class="review-head"><h2>${safe(kind.charAt(0).toUpperCase() + kind.slice(1))}</h2>${statusTag(event.status)}</div><div class="review-layout"><div class="review-source"><span class="review-label">Source report</span><blockquote>${safe(event.text)}</blockquote><div class="review-details"><div class="detail"><small>Reported date</small><strong>${displayDate(event.event_date)}</strong></div><div class="detail"><small>Discipline</small><strong>${safe(event.discipline || "Not specified")}</strong></div><div class="detail"><small>Work area</small><strong>${safe(event.location || "Not specified")}</strong></div></div>${analysisDetails}<p class="capture-source-note">Source: ${safe(({confirmed_by_submitter:"Confirmed by reporter",original_text:"Original text",needs_review:"Needs review"})[event.verification?.source] || "Needs review")} · ${event.status === "approved" || event.status === "exported" ? "Planner approved" : "Proposal needs planner review"}</p>${warnings}${question}${clarification}</div><div class="review-proposal"><span class="review-label">Suggested activities · Select one to confirm</span><div class="candidate-shortlist">${shortlist || '<p class="muted">Choose an activity from the imported schedule.</p>'}</div>${evidence}<div class="review-fields"><label>${isActual ? "Schedule activity" : "Related activity (optional)"}${select}</label><label>${isActual ? "Actual date" : "Reference date"}<input class="decision-date" type="date" value="${safe(event.event_date || "")}"></label></div><div class="proposal-checks" role="status" aria-live="polite">Choose an activity to check its dates and dependencies.</div><label class="decision-note">Decision note <span class="optional">Optional</span><input class="decision-reason" placeholder="Add context for the planning team" aria-label="Decision note"></label></div></div><div class="review-actions"><span class="decision-help">Confirm the activity and date before approving.</span><button class="button secondary reject-button" data-id="${safe(event.id)}">Reject event</button><button class="button primary approve-button" data-action="${isActual ? "approve" : "record"}" data-id="${safe(event.id)}">${isActual ? "Approve actual" : "Record note"}</button></div></article>`;
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
  const clicked = action === "reject" ? $(".reject-button",card) : $(".approve-button",card);
  if (clicked.disabled || pendingDecisions.has(id)) return;
  pendingDecisions.add(id);
  $(".review-feedback",card)?.remove();
  const label = clicked.textContent;
  clicked.textContent = "Saving decision…";
  updateReviewAvailability(card);
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
    const event = state.events.find(item=>item.id===id);
    if (event) event.status = result.status;
    reviewDrafts.delete(id);
    await refresh();
  } catch (error) {
    toast(error.message, true);
    if (card.isConnected) {
      let feedback = $(".review-feedback",card);
      if (!feedback) { feedback = document.createElement("p"); feedback.className = "review-feedback"; feedback.setAttribute("role","alert"); card.append(feedback); }
      feedback.textContent = error.message;
    }
  } finally {
    pendingDecisions.delete(id);
    if (card.isConnected) { clicked.textContent = label; updateReviewAvailability(card); }
    $$(".review-card").forEach(updateReviewAvailability);
  }
}

function renderSchedule() {
  if (!state.ready) {
    $("#schedule-title").textContent = "Schedule is not available yet";
    $("#schedule-result-count").textContent = "Waiting for data";
    $("#schedule-rows").innerHTML = '<tr><td colspan="5">Retry loading to see the imported schedule.</td></tr>';
    return;
  }
  const schedule = state.summary?.schedule;
  $("#schedule-title").textContent = schedule?.filename || "No schedule loaded";
  $("#schedule-meta").textContent = schedule ? `${schedule.format.toUpperCase()} · ${schedule.activity_count} activities · imported ${displayDate(schedule.created_at)}` : "Import an XER or CSV schedule to begin.";
  const query = $("#schedule-search").value.toLowerCase().trim();
  const rows = state.activities.filter(a => !query || `${a.external_id} ${a.name} ${a.wbs}`.toLowerCase().includes(query));
  $("#schedule-result-count").textContent = `${rows.length} ${rows.length === 1 ? "activity" : "activities"}`;
  const status = value => ({ TK_Active: "In progress", TK_NotStart: "Not started", TK_Complete: "Complete" }[value] || value || "—");
  $("#schedule-rows").innerHTML = rows.length ? rows.map(a => `<tr><td><strong>${safe(a.external_id)}</strong>${safe(a.name)}</td><td>${safe(a.wbs || "—")}</td><td>${displayDate(a.planned_start)}</td><td>${displayDate(a.planned_finish)}</td><td>${safe(status(a.status))}</td></tr>`).join("") : `<tr><td colspan="5">${state.activities.length ? "No matching activities." : "No schedule activities yet."}</td></tr>`;
}

const historyFields = { q: "history-search", activity: "history-activity", discipline: "history-discipline", status: "history-filter", date_field: "history-date-field", date_from: "history-from", date_to: "history-to", source: "history-source", source_query: "history-source-query", duplicates: "history-duplicates" };
let historyOffset = 0, historySequence = 0, historyController, historyTimer, historyPageEvents = [];
function historyParams() {
  return Object.fromEntries(Object.entries(historyFields).map(([key,id]) => [key,$(`#${id}`).value.trim()]));
}
function cachedHistory(params) {
  const lower = value => String(value || "").toLowerCase();
  return state.events.filter(event => {
    const ids = [event.selected_activity, ...(event.candidates || []).map(c => c.activity_id)];
    const status = params.status === "all" || (params.status === "pending" ? ["staged","needs_review"].includes(event.status) : params.status === event.status);
    const within = value => value && (!params.date_from || value.slice(0,10) >= params.date_from) && (!params.date_to || value.slice(0,10) <= params.date_to);
    const sources = event.sources || [{ id:event.report_id, source_kind:event.source_kind, filename:event.filename, created_at:event.received_at, capture_asset_id:event.capture_asset_id }];
    const source = sources.some(s => (!params.source || s.source_kind === params.source) && (!params.source_query || lower(s.filename).includes(lower(params.source_query)) || s.id === params.source_query || s.capture_asset_id === params.source_query) && (params.date_field !== "received_at" || (!params.date_from && !params.date_to) || within(s.created_at)));
    return status && source && (!params.activity || ids.some(id => lower(id) === lower(params.activity))) && (!params.discipline || lower(event.discipline) === lower(params.discipline)) && (!params.q || lower([event.text,...ids,...(event.candidates || []).map(c=>c.name)].join(" ")).includes(lower(params.q))) && (params.duplicates !== "grouped" || sources.length > 1) && (params.date_field === "received_at" || (!params.date_from && !params.date_to) || within(event[params.date_field]));
  });
}
function sourceEvidence(event) {
  const sources = event.sources || [];
  const similar = event.similar_reports || [];
  return `<details class="history-evidence"><summary>${sources.length || 1} source submission${sources.length === 1 ? "" : "s"}${similar.length ? " · Possible repeat to compare" : ""}</summary><ul>${sources.map(source => `<li><strong>${safe(source.filename || ({text:"Written note",voice:"Voice recording",document:"Document",spreadsheet:"CSV field log"}[source.source_kind] || "Source"))}</strong><small>${safe(source.id)} · ${displayDate(source.created_at)}${source.duplicate_of ? " · Grouped repeat" : ""}</small>${source.capture_asset_id ? `<a href="/api/captures/${safe(source.capture_asset_id)}/original" target="_blank" rel="noopener">Download original</a>` : ""}</li>`).join("")}</ul>${similar.length ? `<p>Similar wording needs review; these reports remain separate.</p><ul>${similar.map(item => `<li>${safe(item.report_id === event.report_id ? item.related_id : item.report_id)} · ${safe(item.reason)}</li>`).join("")}</ul>` : ""}${event.decision_reason ? `<p>Decision note: ${safe(event.decision_reason)}</p>` : ""}${(event.decisions || []).length ? `<ul>${event.decisions.map(decision=>`<li>${safe(decision.action)} · ${safe(decision.actor)} · ${displayDate(decision.created_at)}</li>`).join("")}</ul>` : ""}${event.duplicate_of_event ? `<p>Earlier actual: ${safe(event.duplicate_of_event)}</p>` : ""}</details>`;
}
function renderHistoryPage() {
  const mode = $("#history-group").value;
  if (!historyPageEvents.length) { $("#history-list").innerHTML = empty("No matching progress records", "Adjust the filters or capture a field report."); return; }
  const item = event => `<div class="history-record">${eventRow(event)}${sourceEvidence(event)}</div>`;
  if (mode === "none") { $("#history-list").innerHTML = historyPageEvents.map(item).join(""); return; }
  const groups = new Map();
  historyPageEvents.forEach(event => {
    const key = mode === "activity" ? event.selected_activity || event.candidates?.[0]?.activity_id || "Unmatched" : event.duplicate_group_id || event.report_id;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(event);
  });
  $("#history-list").innerHTML = [...groups].map(([key, events]) => `<section class="history-group"><h2>${mode === "activity" ? "Activity " : "Report "}${safe(key)}<span>${events.length} event${events.length===1?"":"s"} on this page</span></h2>${events.map(item).join("")}</section>`).join("");
}
async function renderHistory() {
  const sequence = ++historySequence;
  if (historyController) historyController.abort();
  historyController = new AbortController();
  const params = historyParams();
  $("#history-retry").hidden = true;
  $("#history-previous").disabled = true; $("#history-next").disabled = true;
  $("#history-activities").innerHTML = state.activities.map(a => `<option value="${safe(a.external_id)}">${safe(a.name)}</option>`).join("");
  $("#history-disciplines").innerHTML = [...new Set(state.events.map(e=>e.discipline).filter(Boolean))].map(d=>`<option value="${safe(d)}">`).join("");
  if (params.date_from && params.date_to && params.date_from > params.date_to) { $("#history-result-count").textContent = "Choose an end date on or after the start date."; return; }
  $("#history-result-count").textContent = "Loading records…";
  let result, cached = false;
  try {
    if (!offline.reachable) throw Object.assign(new Error("Offline"), {transport:true});
    result = await request(`/api/history?${new URLSearchParams({...params,limit:50,offset:historyOffset})}`, {signal:historyController.signal});
  } catch (error) {
    if (sequence !== historySequence || error.name === "AbortError") return;
    if (!error.transport) { $("#history-result-count").textContent = `${error.message} Previous results are retained.`; $("#history-retry").hidden = false; return; }
    const events = cachedHistory(params); cached = true;
    result = {events:events.slice(historyOffset,historyOffset+50),total:events.length,has_more:historyOffset+50<events.length};
  }
  if (sequence !== historySequence) return;
  historyPageEvents = result.events;
  $("#history-result-count").textContent = `${result.total} matching event${result.total===1?"":"s"}${cached ? " · Saved workspace; changes since the last connection are unavailable" : ""}`;
  $("#history-page").textContent = result.total ? `${historyOffset+1}–${historyOffset+result.events.length} of ${result.total}` : "0 records";
  $("#history-previous").disabled = historyOffset === 0;
  $("#history-next").disabled = !result.has_more;
  renderHistoryPage();
}
async function loadQuality() {
  const target = $("#quality-summary");
  target.textContent = "Loading measurements…";
  try {
    const data = await request("/api/quality/status");
    const latency = data.report_latency_ms.p95;
    target.innerHTML = `<dl class="quality-values"><div><dt>Processing attempts</dt><dd>${safe(data.attempts)}</dd></div><div><dt>Failed attempts</dt><dd>${safe(data.failed_attempts)}</dd></div><div><dt>Report latency · p95</dt><dd>${latency === null ? "No measurements" : `${safe(latency)} ms`}</dd></div><div><dt>Grouped submissions</dt><dd>${safe(data.duplicate_submissions)}</dd></div></dl><p>${safe(data.scope)}</p><p>${safe(data.accuracy_note)}</p><p>${safe(data.cost_note)}</p>${data.routing_policies.map(p=>`<p>${safe(p.pipeline_id)} · ${p.calibrated ? "Validated routing policy" : "Uncalibrated baseline"}</p>`).join("")}`;
  } catch (error) { target.textContent = error.message; }
}

function renderExports() {
  const approved = state.events.filter(e => e.status === "approved").length;
  $("#export-count").textContent = `${approved} approved event${approved === 1 ? "" : "s"} ready`;
  $("#create-export").disabled = state.exporting || state.refreshing || state.stale || !state.ready || approved === 0 || !offline.reachable || !["owner","planner"].includes(window.CarrickAuth.project?.role);
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
  updateAvailability();
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
      try { result = await offline.send(payload); }
      catch (error) {
        if (error.status === 409) { conflict = true; await offline.enqueue(payload, { status: "conflict", error: error.message }); await refresh(); }
        else if (!error.transport) throw error;
      }
    }
    if (!result) { if (!conflict) await offline.enqueue(payload); toast(conflict ? "CSV saved. Review it against the current schedule in Saved on this device." : "CSV report saved for submission when connected."); await renderDeviceReports(); return; }
    toast(result.duplicate ? "Repeat report grouped with its existing source record." : `Processed ${result.events.length} field events.`);
    await refresh();
    go(result.duplicate ? "history" : "review");
  } catch (error) { toast(error.message, true); }
  finally { state.processing = false; button.disabled = false; button.innerHTML = label; $("#spreadsheet-file").value = ""; updateAvailability(); }
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
  updateAvailability();
  const button = $("#report-form button[type=submit]");
  button.disabled = true;
  const label = button.innerHTML;
  button.textContent = "Analyzing report…";
  try {
    const voice = window.CarrickCapture.voiceSource;
    const payload = {
      source_kind: voice ? "voice" : "text", content,
      ...(voice ? { capture_asset_id: voice.assetId, filename: voice.filename, source_reviewed:true } : {}),
      analysis_mode: $("#ai-mode").checked ? "ai" : "rules",
      event_date: $("#report-date").value,
      discipline: $("#report-discipline").value,
      location: $("#report-location").value,
      schedule_version: voice?.scheduleVersion || state.summary?.schedule?.id,
      client_request_id: offline.id()
    };
    let result, conflict = false;
    if (offline.reachable) {
      try { result = await offline.send(payload); }
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
    $("#capture-result").innerHTML = `<div class="panel"><p class="eyebrow">${result.duplicate ? "Repeat report grouped" : "Report analyzed"}</p><h2>${result.duplicate ? "Source added to the existing report" : `${result.events.length} progress event${result.events.length === 1 ? "" : "s"} ready for review`}</h2>${result.events.map(e => `<div class="event-row"><div class="event-glyph">${reportIcon}</div><div class="event-body"><strong>${safe(e.text)}</strong><div class="event-meta"><small>${safe(e.candidates[0]?.activity_id || "Unmatched")} · ${displayDate(e.event_date)}</small>${statusTag(e.status)}</div></div></div>`).join("")}<div class="divider"></div><button class="button primary" id="result-review">${result.duplicate ? "View source group" : "Review suggestions"} →</button></div>`;
    $("#result-review").addEventListener("click", () => go(result.duplicate ? "history" : "review"));
    $("#report-text").value = "";
    await window.CarrickCapture.completeVoice();
    await clearTypedDraft();
    toast(result.duplicate ? "Repeat source retained. Existing decisions are shown in history." : `Processed ${result.events.length} event${result.events.length === 1 ? "" : "s"}.`);
    await refresh();
  } catch (error) { toast(error.message, true); }
  finally { state.processing = false; button.innerHTML = label; updateAvailability(); renderDeviceReports(); }
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
  state.exporting = true;
  const label = button.innerHTML;
  button.disabled = true;
  button.textContent = "Preparing export…";
  try {
    const result = await post("/api/exports");
    $("#export-result").innerHTML = !result.id ? `<div class="result-card"><strong>No new actuals to export</strong><p>${safe(result.message)}</p></div>` : `<div class="result-card"><strong>Your export is ready</strong><p>${result.manifest.row_count} approved ${result.manifest.row_count === 1 ? "event" : "events"}, with source and approval references.</p><a href="${safe(result.download)}">Download progress CSV →</a>${result.xer_download ? `<p><a href="${safe(result.xer_download)}">Download updated XER →</a> · Parser round-trip passed; confirm import and recalculation in P6.</p>` : ""}<p><a href="${safe(result.changeset_download)}">Download validated change set →</a></p></div>`;
    toast(result.id ? "Export created." : "Repeated actuals grouped; no export needed.");
    await refresh();
  } catch (error) { toast(error.message, true); }
  finally { state.exporting = false; button.innerHTML = label; renderExports(); }
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

let serverRecoveryLoaded=0;
async function renderServerRecovery(outbox,drafts) {
  if(!offline.reachable || Date.now()-serverRecoveryLoaded<5000)return;
  serverRecoveryLoaded=Date.now();
  const [reports,captures]=await Promise.all([request("/api/submissions"),request("/api/captures/incomplete")]);
  const local=new Set(outbox.map(item=>item.id));const localCaptures=new Set(drafts.map(item=>item.receipt?.capture_asset_id||item.failedAssetId));
  $("#server-recovery-list").innerHTML=reports.filter(item=>!local.has(item.id)).map(item=>`<div class="device-report"><div><strong>Saved on server · ${safe(item.filename||"Field report")}</strong><small>${safe(item.id)} · Analysis needs attention</small></div><div class="device-report-actions"><button class="text-button" data-retry-server="${safe(item.id)}">Retry</button>${item.analysis_mode==="ai"?`<button class="text-button" data-standard-server="${safe(item.id)}">Use standard matching</button>`:""}<button class="text-button" data-download-server="${safe(item.id)}">Download source</button></div></div>`).join("")+captures.filter(item=>!localCaptures.has(item.capture_asset_id)).map(item=>`<div class="device-report"><div><strong>Saved original · ${safe(item.filename)}</strong><small>Capture needs retry or manual transcription</small></div><div class="device-report-actions"><a href="${safe(item.original_url)}" target="_blank" rel="noopener">Download original</a><button class="text-button" data-retry-capture="${safe(item.capture_asset_id)}">Retry capture</button><button class="text-button" data-open-source="${safe(item.capture_asset_id)}">Transcribe manually</button></div></div>`).join("");
  $$("[data-retry-server], [data-standard-server]").forEach(button=>button.addEventListener("click",async()=>{button.disabled=true;try{await post(`/api/submissions/${button.dataset.retryServer||button.dataset.standardServer}/retry`,button.dataset.standardServer?{analysis_mode:"rules"}:{});serverRecoveryLoaded=0;await refresh();toast("Saved report recovered. Planner review is required.");}catch(error){toast(error.message,true);}finally{button.disabled=false;}}));
  $$("[data-download-server]").forEach(button=>button.addEventListener("click",async()=>{try{const source=await request(`/api/submissions/${button.dataset.downloadServer}`);const url=URL.createObjectURL(new Blob([JSON.stringify(source.payload,null,2)],{type:"application/json"}));const link=document.createElement("a");link.href=url;link.download="carrick-retained-source.json";link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}catch(error){toast(error.message,true);}}));
  $$("[data-open-source]").forEach(button=>button.addEventListener("click",async()=>{button.disabled=true;try{await window.CarrickCapture.restoreServerCapture(await request(`/api/captures/${button.dataset.openSource}`));}catch(error){toast(error.message,true);}finally{button.disabled=false;}}));
  $$("[data-retry-capture]").forEach(button=>button.addEventListener("click",async()=>{button.disabled=true;try{const receipt=await post(`/api/captures/${button.dataset.retryCapture}/retry`);await window.CarrickCapture.restoreServerCapture(receipt);serverRecoveryLoaded=0;}catch(error){toast(error.message,true);}finally{button.disabled=false;}}));
}
async function renderDeviceReports() {
  try {
    const [outbox, drafts] = await Promise.all([offline.list("outbox"), offline.list("drafts")]);
    renderServerRecovery(outbox,drafts).catch(error=>{if(!error.transport)$("#server-recovery-list").textContent=error.message;});
    const banner = $("#connection-banner");
    banner.hidden = offline.reachable && outbox.length === 0;
    $("#connection-copy").textContent = !offline.reachable
      ? `Working offline. Showing your last saved workspace. ${outbox.length} report${outbox.length === 1 ? "" : "s"} waiting to sync.`
      : `${outbox.length} saved report${outbox.length === 1 ? "" : "s"} waiting for submission${offline.syncing ? " · Syncing…" : ""}.`;
    $("#sync-now").textContent = offline.reachable ? "Sync now" : "Reconnect";
    $("#retry-outbox").disabled = !offline.reachable || offline.syncing;
    if (!state.processing) $("#report-form button[type=submit]").textContent = offline.reachable ? "Analyze report →" : "Save report offline";
    $("#device-reports-list").innerHTML = outbox.length || drafts.length
      ? outbox.map(item => `<div class="device-report"><div><strong>${safe(item.payload.filename || item.payload.content?.slice(0, 90) || "Field report")}</strong><small>${safe({ pending: "Submitted offline · Waiting to sync", failed: "Submission needs attention", conflict: "Schedule changed · Review required" }[item.status])}</small>${item.error ? `<p class="capture-warning">${safe(item.error)}</p>` : ""}${item.payload.reviewed_pages ? `<details><summary>Reviewed document text</summary><p>${safe(item.payload.reviewed_pages.map(page => page.text).join("\n\n"))}</p></details>` : ""}</div><div class="device-report-actions">${item.status === "conflict" ? `<button class="text-button" data-rebind-report="${safe(item.id)}" ${!offline.reachable ? "disabled" : ""}>Review with current schedule</button>` : ""}${item.payload.analysis_mode === "ai" && item.error ? `<button class="text-button" data-fallback-report="${safe(item.id)}" ${!offline.reachable?"disabled":""}>Use standard matching</button>` : ""}<button class="text-button" data-download-report="${safe(item.id)}">Download copy</button><button class="text-button" data-remove-report="${safe(item.id)}">Discard</button></div></div>`).join("")
        + drafts.map(draft => `<div class="device-report"><div><strong>${safe(draft.filename)}</strong><small>${draft.kind === "voice" ? "Voice recording" : "Document"} · ${draft.receipt ? "Ready for your review" : "Saved for local extraction"}</small></div><div class="device-report-actions"><button class="text-button" data-open-draft="${safe(draft.id)}">${draft.receipt ? "Review" : draft.kind === "voice" ? "Open recording" : "Extract text"}</button><button class="text-button" data-download-draft="${safe(draft.id)}">Download copy</button><button class="text-button" data-remove-draft="${safe(draft.id)}">Discard</button></div></div>`).join("")
      : '<p class="muted">No reports or attachments waiting on this device.</p>';
    $$("[data-fallback-report]").forEach(button=>button.addEventListener("click",()=>offline.fallbackRules(button.dataset.fallbackReport).catch(error=>toast(error.message,true))));
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
  $("#ai-mode").addEventListener("change",()=>state.aiPreferred=$("#ai-mode").checked);
  $("#toast-close").addEventListener("click",()=>{clearTimeout(toastTimer);$("#toast").className="";});
  $("#workspace-refresh").addEventListener("click",refresh);
  $("#workspace-retry").addEventListener("click",refresh);
  $("#history-retry").addEventListener("click",renderHistory);
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
  Object.values(historyFields).forEach(id => $(`#${id}`).addEventListener(["INPUT"].includes($(`#${id}`).tagName) && !["date"].includes($(`#${id}`).type) ? "input" : "change", () => {
    historyOffset = 0; clearTimeout(historyTimer); historyTimer = setTimeout(renderHistory,200);
  }));
  $("#history-group").addEventListener("change", renderHistoryPage);
  $("#history-previous").addEventListener("click", () => { historyOffset = Math.max(0,historyOffset-50); renderHistory(); });
  $("#history-next").addEventListener("click", () => { historyOffset += 50; renderHistory(); });
  $("#history-reset").addEventListener("click", () => {
    Object.entries(historyFields).forEach(([key,id]) => $(`#${id}`).value = ({status:"all",date_field:"event_date",duplicates:"all"}[key] || ""));
    historyOffset = 0; renderHistory();
  });
  $("#quality-load").addEventListener("click", loadQuality);
  $("#create-export").addEventListener("click", createExport);
  $("#sync-now").addEventListener("click", async () => { try { await offline.health(); await offline.sync(true); } catch(error) { toast(error.message,true); } });
  $("#retry-outbox").addEventListener("click", () => offline.sync(true).catch(error => toast(error.message, true)));
  $$("#report-text, #report-date, #report-discipline, #report-location").forEach(input => input.addEventListener("input", () => { clearTimeout(draftTimer); draftTimer = setTimeout(persistTypedDraft, 400); }));
  let lastReachable = offline.reachable;
  offline.subscribe(() => {
    renderDeviceReports();
    if (offline.reachable !== lastReachable) {
      lastReachable = offline.reachable;
      updateAvailability();
    }
  });
  window.addEventListener("carrick-drafts-changed", renderDeviceReports);
  window.addEventListener("carrick-schedule-conflict", () => refresh().catch(error => toast(error.message, true)));
  window.addEventListener("carrick-report-synced", event => { refresh().catch(error => toast(error.message, true)); toast(event.detail?.duplicate ? "Saved repeat report synced into its source group." : "Saved report synced. Its events are ready for planner review."); });
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
async function startWorkspace() {
await window.CarrickAuth.start();
bind();
renderOverview(); updateAvailability();
setNavigation(false);
go(labels[location.hash.slice(1)] ? location.hash.slice(1) : "overview", false);
refreshAiStatus().catch(() => $("#ai-status").textContent = "AI availability could not be checked. Standard matching is available.");
refreshCaptureStatus().catch(() => $("#capture-engine-status").textContent = "Connect to the local server to check scan extraction availability.");
refresh().catch(error => toast(error.message, true));
restoreTypedDraft().catch(error => toast(error.message, true));

}
startWorkspace().catch(error=>toast(error.message,true));
