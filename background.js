// Single writer for session state and event storage, so tabs and the popup never race each other.
importScripts('common.js');

const store = chrome.storage.local;
let queue = Promise.resolve();

chrome.runtime.onInstalled.addListener(async () => {
  const s = await store.get(['labels', 'sites']);
  await store.set({ labels: s.labels ?? KS.DEFAULT_LABELS, sites: { ...KS.DEFAULT_SITES, ...s.sites } });
});

chrome.runtime.onMessage.addListener((msg, _sender, reply) => {
  const job = {
    rows: () => saveRows(msg.uid, msg.rows),
    start: () => start(msg),
    stop: () => stop(),
    delete: () => remove(msg.uid),
  }[msg.type];
  if (!job) return;
  queue = queue.then(job).then(
    res => reply({ ok: true, res }),
    err => { console.error(err); reply({ ok: false, error: String(err) }); },
  );
  return true;
});

async function start({ participant_id, label, alertness }) {
  const { active, sessions = {}, counters = {} } = await store.get(['active', 'sessions', 'counters']);
  if (active) return active;
  const n = (counters[participant_id] ?? 0) + 1;
  const now = Date.now();
  const s = {
    uid: `${participant_id}_${now}`,
    participant_id,
    session_id: `S${n}`,
    state_label: label,
    alertness,
    language: 'en',
    start: new Date(now).toISOString(),
    start_epoch: now,
    end: null,
    duration_s: null,
    keystrokes: 0,
  };
  sessions[s.uid] = s;
  const act = { uid: s.uid, participant_id, session_id: s.session_id, start_epoch: now };
  await store.set({ sessions, active: act, counters: { ...counters, [participant_id]: n } });
  return act;
}

async function stop() {
  const { active, sessions = {} } = await store.get(['active', 'sessions']);
  if (!active) return;
  const s = sessions[active.uid];
  if (s) {
    const now = Date.now();
    s.end = new Date(now).toISOString();
    s.duration_s = Math.round((now - s.start_epoch) / 1000);
  }
  await store.set({ active: null, sessions });
}

async function saveRows(uid, rows) {
  const { sessions = {} } = await store.get('sessions');
  const s = sessions[uid];
  if (!s || !rows?.length) return; // session deleted
  s.keystrokes += rows.filter(r => r.event === 'down').length;
  for (const r of rows) { r.participant_id = s.participant_id; r.session_id = s.session_id; }
  const key = `ev_${uid}_${String(Date.now()).padStart(15, '0')}_${Math.random().toString(36).slice(2, 6)}`;
  await store.set({ [key]: rows, sessions });
}

async function remove(uid) {
  const { active, sessions = {} } = await store.get(['active', 'sessions']);
  if (active?.uid === uid) await stop();
  const keys = Object.keys(await store.get(null)).filter(k => k.startsWith(`ev_${uid}_`));
  await store.remove(keys);
  delete sessions[uid];
  await store.set({ sessions });
}
