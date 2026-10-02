const $ = selector => document.querySelector(selector);
const safe = value => String(value ?? '').replace(/[&<>"']/g, character => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[character]));
const formatDate = value => {
  if (!value) return 'Date not specified';
  const parsed = new Date(value.slice(0, 10) + 'T12:00:00');
  return Number.isNaN(parsed.getTime()) ? value : new Intl.DateTimeFormat('en-GB', {day:'numeric',month:'short',year:'numeric'}).format(parsed);
};
const today = new Intl.DateTimeFormat('sv-SE', {timeZone:'Asia/Kolkata',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());
const tomorrow = new Date(today + 'T12:00:00');
tomorrow.setDate(tomorrow.getDate() + 1);
const tomorrowISO = new Intl.DateTimeFormat('sv-SE', {year:'numeric',month:'2-digit',day:'2-digit'}).format(tomorrow);
$('#preview-date').value = today;
$('#copyright-year').textContent = new Date().getFullYear();

const samples = [
  {title:'North pipeline welding', text:'North pipeline welding started today.', kind:'actual_start', event_date:today,
    discipline:'Piping', location:'North pipeline', warnings:[],
    candidates:[{activity_id:'PI-301',name:'Weld North Pipeline',wbs:'Piping Works',evidence:['north','pipe','weld']},
      {activity_id:'PI-302',name:'Weld South Pipeline',wbs:'Piping Works',evidence:['pipe','weld']}]},
  {title:'Main foundation concrete', text:'Finished pouring the main foundation today.', kind:'actual_finish', event_date:today,
    discipline:'Civil', location:'Main foundation', warnings:[],
    candidates:[{activity_id:'CV-102',name:'Main Foundation Concrete Pour',wbs:'Civil Works',evidence:['main','foundation','pour']},
      {activity_id:'CV-103',name:'Cure Main Foundation',wbs:'Civil Works',evidence:['main','foundation']}]},
  {title:'Pump A installation', text:'Pump A will finish tomorrow.', kind:'forecast_finish', event_date:tomorrowISO,
    discipline:'Mechanical', location:'Pump A', warnings:['This is a forecast, so it does not set an actual finish date.'],
    candidates:[{activity_id:'ME-201',name:'Install Pump A',wbs:'Mechanical Works',evidence:['pump']},
      {activity_id:'ME-202',name:'Install Pump B',wbs:'Mechanical Works',evidence:['pump']}]}
];
let current = {...samples[0]};
let stage = 'review';
let confirmed = false;
let processing = false;
let requestNumber = 0;
let controller;
const stages = {
  capture:{breadcrumb:'Capture report', label:'Field reporting', caption:'Start with the words your site team already uses. Add a report date for context.'},
  match:{breadcrumb:'Activity matching',label:'Schedule context',caption:'Compare suggested activities from the imported schedule before choosing the right one.'},
  review:{breadcrumb:'Planner review',label:'Report review',caption:'Review the report alongside the proposed activity and actual date.'}
};
const tabs = [...document.querySelectorAll('[data-stage]')];
const kindLabels = {actual_start:'Proposed actual start',actual_finish:'Proposed actual finish',forecast_start:'Forecast start',forecast_finish:'Forecast finish',in_progress:'Progress reported',not_started:'Not started',partial_progress:'Partial progress',blocked:'Blocker reported',unknown:'Date from report'};
const check = '<svg viewBox="0 0 20 20" aria-hidden="true"><path d="m4 10 4 4 8-8"/></svg>';
const arrow = '<svg viewBox="0 0 20 20" aria-hidden="true"><path d="M4 10h12m-5-5 5 5-5 5"/></svg>';

function renderTour() {
  const actual = current.kind === 'actual_start' || current.kind === 'actual_finish';
  const ambiguous = current.warnings?.includes('Several activities are plausible');
  $('#tour-panel').dataset.stage = stage;
  $('#tour-panel').setAttribute('aria-labelledby', 'tour-tab-' + stage);
  $('#demo-breadcrumb').textContent = stages[stage].breadcrumb;
  $('#demo-stage-label').textContent = stages[stage].label;
  $('#tour-caption').textContent = stages[stage].caption;
  tabs.forEach(tab => {
    const active = tab.dataset.stage === stage;
    tab.setAttribute('aria-selected', String(active));
    tab.tabIndex = active ? 0 : -1;
  });
  $('#demo-title').textContent = current.title;
  $('#demo-quote').textContent = current.text;
  $('#demo-quote').hidden = stage === 'capture';
  $('#demo-editor').hidden = stage !== 'capture';
  $('#source-details').hidden = stage === 'capture';
  $('#demo-discipline').textContent = current.discipline || 'Not specified';
  $('#demo-location').textContent = current.location || 'Not specified';
  $('#demo-date').textContent = formatDate($('#preview-date').value);
  $('#demo-event-label').textContent = kindLabels[current.kind] || 'Reported date';
  $('#demo-proposed-date').textContent = formatDate(current.event_date);
  const status = $('#demo-status');
  status.className = 'pill ' + (confirmed ? 'approved' : actual ? 'pending' : 'forecast');
  status.innerHTML = '<span></span>' + (confirmed ? actual ? 'Confirmed in tour' : 'Forecast recorded' : actual ? 'Awaiting review' : 'Forecast only');
  const candidates = current.candidates || [];
  $('#demo-candidates').innerHTML = candidates.length ? candidates.slice(0, stage === 'match' || ambiguous ? 2 : 1).map((candidate, index) =>
    '<div class="activity-suggestion' + (index ? ' alternative' : '') + '"><div><span class="task-id">' + safe(candidate.activity_id) + '</span><span class="pill neutral">' + (index ? 'Alternative' : 'Suggested') + '</span></div><h3>' + safe(candidate.name) + '</h3><p>' + safe(candidate.wbs || 'Imported schedule activity') + '</p>' + (!index ? '<div class="matching-context">' + check + '<span>' + (candidate.evidence?.length ? 'Report terms: ' + safe(candidate.evidence.join(', ')) : 'Check activity and location before approval') + '</span></div>' : '') + '</div>'
  ).join('') : '<div class="activity-suggestion"><h3>No activity suggestion</h3><p>Add an activity name or location to your note.</p></div>';
  const warnings = (current.warnings || []).filter(warning => warning !== 'Event does not set an actual date');
  if (!actual && !warnings.length) warnings.push('This report does not establish an actual start or finish.');
  $('#demo-warning').hidden = !warnings.length;
  $('#demo-warning').textContent = warnings.join(' ');
  $('#demo-decision').hidden = stage !== 'review' || !candidates.length;
  const approve = $('#demo-approve');
  approve.disabled = confirmed || (actual && (!current.event_date || ambiguous));
  approve.innerHTML = check + (confirmed ? ' Confirmed' : actual ? ' Confirm in tour' : ' Keep forecast in tour');
  $('#demo-feedback').hidden = !confirmed;
  $('#demo-feedback').textContent = actual ? 'Sample decision complete. No report is saved and no schedule is changed.' : 'Forecast kept as a note. It does not enter an actual-date export.';
  $('#demo-final-step').innerHTML = confirmed ? check + ' Review complete' : '<span class="progress-ring"></span> Planner review';
  $('#demo-final-step').classList.toggle('completed', confirmed);
}

function showStage(value, focus = false) {
  if (!stages[value]) return;
  stage = value;
  renderTour();
  if (focus) $('#tour-tab-' + value).focus();
}
tabs.forEach((tab, index) => {
  tab.addEventListener('click', () => showStage(tab.dataset.stage));
  tab.addEventListener('keydown', event => {
    let next;
    if (event.key === 'ArrowRight' || event.key === 'ArrowDown') next = (index + 1) % tabs.length;
    if (event.key === 'ArrowLeft' || event.key === 'ArrowUp') next = (index - 1 + tabs.length) % tabs.length;
    if (event.key === 'Home') next = 0;
    if (event.key === 'End') next = tabs.length - 1;
    if (next !== undefined) { event.preventDefault(); showStage(tabs[next].dataset.stage, true); }
  });
});

function resetPreviewButton() {
  processing = false;
  $('#preview-button').disabled = false;
  $('#preview-button').innerHTML = 'Find activity ' + arrow;
}
document.querySelectorAll('[data-sample]').forEach(button => button.addEventListener('click', () => {
  controller?.abort();
  requestNumber++;
  resetPreviewButton();
  current = {...samples[Number(button.dataset.sample)]};
  confirmed = false;
  $('#preview-note').value = current.text;
  $('#preview-date').value = today;
  document.querySelectorAll('[data-sample]').forEach(item => {
    const selected = item === button;
    item.classList.toggle('active', selected);
    item.setAttribute('aria-pressed', String(selected));
  });
  renderTour();
}));
$('#demo-approve').addEventListener('click', () => { confirmed = true; renderTour(); });
$('#try-custom-note').addEventListener('click', () => {
  showStage('capture');
  $('#preview-note').focus({preventScroll:true});
  $('#product').scrollIntoView({behavior:window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth'});
});
document.querySelectorAll('[data-tour-stage]').forEach(link => link.addEventListener('click', () => showStage(link.dataset.tourStage)));

async function runPreview() {
  if (processing) return;
  const text = $('#preview-note').value.trim();
  if (!text) { $('#preview-note').focus(); $('#demo-warning').hidden = false; $('#demo-warning').textContent = 'Enter a field update to find a schedule activity.'; return; }
  const thisRequest = ++requestNumber;
  controller = new AbortController();
  processing = true;
  $('#preview-button').disabled = true;
  $('#preview-button').textContent = 'Finding activity…';
  $('#demo-warning').hidden = true;
  try {
    const response = await fetch('/api/preview', {method:'POST',headers:{'Content-Type':'application/json'},signal:controller.signal,
      body:JSON.stringify({content:text,event_date:$('#preview-date').value})});
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'The preview could not be completed. Try again.');
    if (thisRequest !== requestNumber) return;
    if (!data.events?.length) throw new Error('No progress claim was found. Add the work that started, finished, or changed.');
    const event = data.events[0];
    current = {...event,title:event.candidates?.[0]?.name || 'Field update',discipline:event.discipline,location:event.location};
    confirmed = false;
    document.querySelectorAll('[data-sample]').forEach(button => { button.classList.remove('active'); button.setAttribute('aria-pressed','false'); });
    showStage('match');
  } catch (error) {
    if (error.name !== 'AbortError' && thisRequest === requestNumber) {
      $('#demo-warning').hidden = false;
      $('#demo-warning').textContent = error.message;
    }
  } finally { if (thisRequest === requestNumber) resetPreviewButton(); }
}
$('#preview-button').addEventListener('click', runPreview);
$('#preview-note').addEventListener('keydown', event => {
  if ((event.metaKey || event.ctrlKey) && event.key === 'Enter') { event.preventDefault(); runPreview(); }
});
const menuButton = $('.menu-toggle');
const mobileMenu = $('#mobile-menu');
function closeMenu() {
  mobileMenu.hidden = true;
  menuButton.setAttribute('aria-expanded','false');
  menuButton.setAttribute('aria-label','Open navigation');
}
menuButton.addEventListener('click', () => {
  const open = menuButton.getAttribute('aria-expanded') !== 'true';
  mobileMenu.hidden = !open;
  menuButton.setAttribute('aria-expanded',String(open));
  menuButton.setAttribute('aria-label',open ? 'Close navigation' : 'Open navigation');
});
mobileMenu.querySelectorAll('a').forEach(link => link.addEventListener('click',closeMenu));
document.addEventListener('keydown', event => { if (event.key === 'Escape') closeMenu(); });
renderTour();
