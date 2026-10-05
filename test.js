const PHRASE = '.tie5Roanl', REPS = 10;
const $ = id => document.getElementById(id);
const box = $('box');
const t0 = Date.now();
const rows = [];
const goodSamples = [];
let participant = null;

const rec = KS.createRecorder({
  findTarget: t => (t === box ? box : null),
  origin: () => t0,
  onRows: r => rows.push(...r),
});

chrome.storage.local.get('participant').then(s => {
  participant = s.participant;
  if (!participant) {
    box.disabled = true;
    $('progress').innerHTML = '<span class="warn">Choose a participant in the extension popup first, then reload this page.</span>';
    return;
  }
  rec.start();
  box.focus();
});

box.addEventListener('keydown', e => {
  if (e.key !== 'Enter') return;
  e.preventDefault();
  if (e.repeat) return;
  const ok = box.value === PHRASE;
  if (ok) goodSamples.push(rec.lastDown().sample_id);
  box.value = '';
  $('progress').innerHTML = `${goodSamples.length} / ${REPS}`
    + (ok ? '' : ' <span class="warn">That one didn\'t match, so type it again.</span>');
  if (goodSamples.length === REPS) {
    box.disabled = true;
    setTimeout(finish, 400); // let the last Enter release arrive
  }
});

function finish() {
  rec.stop();
  const keys = rows.filter(r => r.event !== 'marker');
  const downs = keys.filter(r => r.event === 'down');
  const ups = new Map();
  for (const u of keys.filter(r => r.event === 'up')) ups.set(u.press_id, [...(ups.get(u.press_id) ?? []), u]);
  const upOf = d => ups.get(d.press_id)?.[0];

  // 1. Every press has exactly one normal release.
  const unpaired = downs.filter(d => ups.get(d.press_id)?.length !== 1 || upOf(d).detail);
  // 2. Each clean rep (no Backspace) has exactly the expected keys, in order.
  const expected = [...PHRASE, 'Enter'].join(' ');
  const clean = goodSamples.map(s => downs.filter(d => d.sample_id === s && !KS.MODIFIERS.has(d.key)).map(d => d.key))
    .filter(seq => !seq.includes('Backspace') && !seq.includes('Delete'));
  const wrongSeq = clean.filter(seq => seq.join(' ') !== expected);
  // 3. Timestamps never go backwards.
  const backwards = rows.filter((r, i) => i && r.timestamp_ms < rows[i - 1].timestamp_ms).length;
  // 4. Hold times look human.
  const holds = downs.filter(d => !KS.MODIFIERS.has(d.key) && upOf(d)).map(d => upOf(d).timestamp_ms - d.timestamp_ms);
  const sorted = [...holds].sort((a, b) => a - b);
  const median = sorted[Math.floor(sorted.length / 2)] ?? NaN;
  const badHolds = holds.filter(h => h <= 0 || h > 1500).length;
  // 5. Overlapping keys are captured (e.g. Shift still down when R is pressed).
  let overlaps = 0;
  for (let i = 0; i + 1 < downs.length; i++) {
    const u = upOf(downs[i]);
    if (u && downs[i + 1].sample_id === downs[i].sample_id && downs[i + 1].timestamp_ms < u.timestamp_ms) overlaps++;
  }

  const checks = [
    ['Every press has exactly one release (linked by press_id)', unpaired.length === 0, `${downs.length} presses, ${unpaired.length} unpaired`],
    ['No keys missing or counted twice', clean.length > 0 && wrongSeq.length === 0,
      `${clean.length - wrongSeq.length} / ${clean.length} correction-free reps match exactly`],
    ['Timestamps always increase', backwards === 0, `${backwards} out of order`],
    ['Hold times are plausible (median 30–300 ms, none ≤ 0 or > 1.5 s)', median >= 30 && median <= 300 && badHolds === 0,
      `median ${median.toFixed(1)} ms, ${badHolds} suspicious`],
    ['Overlapping keys recorded (negative release→press latency)', null, `${overlaps} overlaps (info only)`],
  ];
  const passed = checks.every(([, ok]) => ok !== false);

  $('results').innerHTML = `<div class="card"><table>
    ${checks.map(([name, ok, detail]) => `<tr><td>${name}</td>
      <td class="${ok === false ? 'warn' : 'ok'}">${ok === null ? 'ℹ' : ok ? '✓' : '✗'}</td><td class="muted">${detail}</td></tr>`).join('')}
    </table>
    <p class="${passed ? 'ok' : 'warn'}"><b>${passed ? 'Collector works. You can start recording.' : 'Something looks wrong. Send the test CSV to the group before recording.'}</b></p>
    <div class="row"><button id="csv">Download test CSV</button><button id="again">Run again</button></div></div>`;

  $('csv').onclick = () => {
    const out = KS.normalise(rows).map(r => ({ ...r, participant_id: participant, session_id: 'TEST' }));
    KS.download(`${participant}_TEST.csv`, KS.toCSV(out));
  };
  $('again').onclick = () => location.reload();

  if (passed) {
    chrome.storage.local.get('testPassed').then(({ testPassed = {} }) =>
      chrome.storage.local.set({ testPassed: { ...testPassed, [participant]: new Date().toISOString() } }));
  }
}
