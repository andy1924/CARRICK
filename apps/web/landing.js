const steps = [
  {
    kicker: 'FROM THE FIELD', title: 'Keep the language natural.',
    copy: 'A supervisor can write a simple progress note. The original wording remains attached to the event.',
    visual: '<div class="stage-paper"><span class="micro">FIELD REPORT / 01</span><p class="quote">“North pipeline welding started today.”</p><div class="paper-rule">Received from site · Piping works</div></div>'
  },
  {
    kicker: 'SCHEDULE CONTEXT', title: 'Find the work behind the words.',
    copy: 'Carrick ranks activities from the imported schedule and shows the evidence behind each suggestion.',
    visual: '<div class="stage-card"><span class="micro">FIRST SUGGESTION</span><strong>Weld North Pipeline</strong><small>PI–301 / Piping Works</small><br><span class="tag">shared terms: north · pipe · weld</span></div><div class="stage-card"><span class="micro">ALSO CONSIDERED</span><strong>Weld South Pipeline</strong><small>PI–302 / Piping Works</small></div>'
  },
  {
    kicker: 'HUMAN DECISION', title: 'Make the call with context.',
    copy: 'A planner can confirm the activity and actual date, record a note, or reject a proposed update.',
    visual: '<div class="stage-review"><div><span>FIELD EVIDENCE</span><strong>Welding started</strong></div><div><span>PROPOSED ACTIVITY</span><strong>PI–301</strong></div><div class="approved"><span>PLANNER DECISION</span><strong>Approve / Record / Reject</strong></div></div>'
  },
  {
    kicker: 'TRACEABLE OUTPUT', title: 'Carry approved progress forward.',
    copy: 'Approved actuals become a CSV with the activity, date, source report, and approval trail. The imported schedule stays unchanged.',
    visual: '<div class="stage-export"><div><span>APPROVED PROGRESS.CSV</span><span>↗</span></div><div><span>Activity</span><b>PI–301</b></div><div><span>Event</span><b>Actual start</b></div><div><span>Source</span><b>Field report</b></div><div><span>Decision</span><b>Approved by planner</b></div></div>'
  }
];

const tabs = Array.from(document.querySelectorAll('.step'));
function showStep(index, focus = false) {
  const step = steps[index];
  if (!step) return;
  tabs.forEach((tab, i) => {
    const active = i === index;
    tab.classList.toggle('active', active);
    tab.setAttribute('aria-selected', String(active));
    tab.tabIndex = active ? 0 : -1;
  });
  const panel = document.getElementById('step-panel');
  panel.setAttribute('aria-labelledby', tabs[index].id);
  document.getElementById('stage-counter').textContent = `STAGE 0${index + 1} / 04`;
  document.getElementById('stage-kicker').textContent = step.kicker;
  document.getElementById('stage-title').textContent = step.title;
  document.getElementById('stage-copy').textContent = step.copy;
  document.getElementById('stage-visual').innerHTML = step.visual;
  if (focus) tabs[index].focus();
}
tabs.forEach((tab, index) => {
  tab.addEventListener('click', () => showStep(index));
  tab.addEventListener('keydown', event => {
    const move = event.key === 'ArrowDown' || event.key === 'ArrowRight' ? 1 :
      event.key === 'ArrowUp' || event.key === 'ArrowLeft' ? -1 : 0;
    if (move) {
      event.preventDefault();
      showStep((index + move + tabs.length) % tabs.length, true);
    }
  });
});
showStep(0);

const menuButton = document.querySelector('.menu-toggle');
const mobileMenu = document.getElementById('mobile-menu');
menuButton.addEventListener('click', () => {
  const opened = menuButton.getAttribute('aria-expanded') === 'true';
  menuButton.setAttribute('aria-expanded', String(!opened));
  menuButton.setAttribute('aria-label', opened ? 'Open menu' : 'Close menu');
  mobileMenu.hidden = opened;
});
mobileMenu.querySelectorAll('a').forEach(link => link.addEventListener('click', () => {
  mobileMenu.hidden = true;
  menuButton.setAttribute('aria-expanded', 'false');
  menuButton.setAttribute('aria-label', 'Open menu');
}));

const note = document.getElementById('preview-note');
const dateInput = document.getElementById('preview-date');
const previewButton = document.getElementById('preview-button');
const result = document.getElementById('preview-result');
const outputState = document.getElementById('output-state');
const today = new Date();
dateInput.value = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}-${String(today.getDate()).padStart(2, '0')}`;

document.querySelectorAll('[data-note]').forEach(button => button.addEventListener('click', () => {
  note.value = button.dataset.note;
  note.focus();
  runPreview();
}));

function element(tag, className, value) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (value !== undefined) node.textContent = value;
  return node;
}

const kindLabels = {
  actual_start: 'ACTUAL START', actual_finish: 'ACTUAL FINISH',
  forecast_start: 'FORECAST START', forecast_finish: 'FORECAST FINISH',
  in_progress: 'IN PROGRESS', not_started: 'NOT STARTED',
  partial_progress: 'PARTIAL PROGRESS', blocked: 'BLOCKED', unknown: 'UNCLASSIFIED'
};

function renderPreview(data) {
  result.replaceChildren();
  const event = data.events[0];
  if (!event) {
    result.append(element('p', 'result-error', 'No progress event found in that note.'));
    outputState.textContent = 'REVIEW NEEDED';
    return;
  }
  const wrap = element('div', 'result-content');
  wrap.append(element('span', 'result-kind', kindLabels[event.kind] || 'FIELD EVENT'));
  wrap.append(element('p', 'result-event', `“${event.text}”`));
  const candidates = event.candidates || [];
  candidates.slice(0, event.warnings.includes('Several activities are plausible') ? 2 : 1).forEach((candidate, index) => {
    const card = element('div', `result-candidate${index ? ' secondary' : ''}`);
    const top = element('div', 'candidate-top');
    top.append(element('span', '', index ? 'ALSO POSSIBLE' : 'SUGGESTED ACTIVITY'));
    top.append(element('span', '', candidate.activity_id));
    card.append(top, element('h3', '', candidate.name));
    const details = candidate.evidence?.length ? `Shared words: ${candidate.evidence.join(', ')}` : 'Review the activity context';
    card.append(element('p', '', details));
    wrap.append(card);
  });
  const flags = element('div', 'result-warnings');
  if (event.warnings.length) {
    event.warnings.forEach(warning => flags.append(element('span', '', warning)));
  } else {
    flags.append(element('span', 'clear', 'Ready for planner review'));
  }
  wrap.append(flags);
  wrap.append(element('p', 'result-note', event.event_date ? `Interpreted date: ${event.event_date}. Preview only; no schedule is changed.` : 'No actual date was established. Preview only; no schedule is changed.'));
  if (data.events.length > 1) wrap.append(element('p', 'result-note', `${data.events.length - 1} more event${data.events.length > 2 ? 's' : ''} found. Open the workspace to review a full report.`));
  result.append(wrap);
  outputState.textContent = event.warnings.length ? 'REVIEW FLAGGED' : 'LINK PROPOSED';
}

async function runPreview() {
  if (!note.value.trim()) {
    result.replaceChildren(element('p', 'result-error', 'Write a note to see a schedule suggestion.'));
    outputState.textContent = 'NOTE NEEDED';
    note.focus();
    return;
  }
  previewButton.disabled = true;
  previewButton.firstChild.textContent = 'Finding the link ';
  outputState.textContent = 'READING NOTE';
  try {
    const response = await fetch('/api/preview', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({content: note.value, event_date: dateInput.value})
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'The preview could not be completed.');
    renderPreview(data);
  } catch (error) {
    result.replaceChildren(element('p', 'result-error', error.message));
    outputState.textContent = 'TRY AGAIN';
  } finally {
    previewButton.disabled = false;
    previewButton.firstChild.textContent = 'Find the schedule link ';
  }
}
previewButton.addEventListener('click', runPreview);
note.addEventListener('keydown', event => {
  if ((event.metaKey || event.ctrlKey) && event.key === 'Enter') runPreview();
});
