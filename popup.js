const store = chrome.storage.local;
const $ = id => document.getElementById(id);
let state = {};
let tick = null;

function fill(select, options, value) {
  select.replaceChildren(...options.map(([v, text]) => new Option(text, v)));
  if (value != null) select.value = value;
}

function renderForm() {
  const { participant = '', labels = KS.DEFAULT_LABELS, lastLabel, sites = KS.DEFAULT_SITES } = state;
  fill($('participant'), [['', 'Choose…'], ...KS.PARTICIPANTS.map(([id, name]) => [id, `${name} (${id})`])], participant);
  fill($('label'), labels.map(l => [l, l]), labels.includes(lastLabel) ? lastLabel : labels[0]);
  $('sites').replaceChildren(...Object.entries(sites).map(([domain, on]) => {
    const l = document.createElement('label');
    const cb = Object.assign(document.createElement('input'), { type: 'checkbox', checked: on });
    cb.onchange = () => store.set({ sites: { ...state.sites, [domain]: cb.checked } });
    l.append(cb, domain);
    return l;
  }));
}

function renderStatus() {
  const { active, sessions = {}, testPassed = {}, participant } = state;
  $('form').disabled = !!active;

  const passed = testPassed[participant];
  $('test').innerHTML = !participant
    ? '<span class="muted">Choose a participant first.</span>'
    : passed
      ? `<span class="ok">✓ Collector test passed ${new Date(passed).toLocaleDateString()}</span><br><span class="muted">Optional now. Re-run it if you change keyboard or machine.</span>`
      : '<span class="warn">Collector test not done yet</span><br><span class="muted">Recommended once before your first session (takes ~1 min).</span>';
  if (participant) {
    const b = Object.assign(document.createElement('button'), { textContent: passed ? 'Run again' : 'Run test' });
    b.style.marginTop = '8px';
    b.disabled = !!active;
    b.onclick = () => chrome.tabs.create({ url: 'test.html' });
    $('test').append(document.createElement('br'), b);
  }

  clearInterval(tick);
  const t = $('toggle');
  if (active) {
    t.textContent = 'Stop recording';
    t.className = 'stop';
    const s = sessions[active.uid];
    const show = () => {
      const sec = Math.floor((Date.now() - active.start_epoch) / 1000);
      const mm = String(Math.floor(sec / 60)).padStart(2, '0'), ss = String(sec % 60).padStart(2, '0');
      $('status').innerHTML = `<span class="rec">● Recording ${active.participant_id} ${active.session_id}</span> · `
        + `${s?.keystrokes ?? 0} keystrokes · ${mm}:${ss}<br>Target: at least 2,000 keystrokes (~15 min).`;
    };
    show();
    tick = setInterval(show, 1000);
  } else {
    t.textContent = 'Start recording';
    t.className = 'primary';
    $('status').textContent = '';
  }
}

async function load() {
  state = await store.get(['participant', 'labels', 'lastLabel', 'sites', 'active', 'sessions', 'testPassed']);
  renderForm();
  renderStatus();
}

chrome.storage.onChanged.addListener(async (c, area) => {
  if (area !== 'local') return;
  for (const [k, v] of Object.entries(c)) state[k] = v.newValue;
  if (c.labels || c.sites) renderForm();
  renderStatus();
});

$('participant').onchange = e => store.set({ participant: e.target.value });
$('label').onchange = e => store.set({ lastLabel: e.target.value });

$('addLabel').onclick = async () => {
  const l = $('newLabel').value.trim().toLowerCase();
  if (!l) return;
  const labels = state.labels ?? KS.DEFAULT_LABELS;
  $('newLabel').value = '';
  await store.set({ labels: labels.includes(l) ? labels : [...labels, l], lastLabel: l });
};

$('toggle').onclick = async () => {
  if (state.active) {
    await chrome.runtime.sendMessage({ type: 'stop' });
    return;
  }
  const participant_id = $('participant').value, alertness = $('alertness').value;
  if (!participant_id || !alertness) {
    $('status').innerHTML = '<span class="warn">Choose a participant and an alertness rating first.</span>';
    return;
  }
  const res = await chrome.runtime.sendMessage({ type: 'start', participant_id, label: $('label').value, alertness: +alertness });
  if (!res?.ok) $('status').textContent = `Could not start: ${res?.error}`;
};

$('data').onclick = () => chrome.tabs.create({ url: 'data.html' });

load();
