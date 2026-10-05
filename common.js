// Shared constants and helpers. Loaded by the background worker, the content script and the extension pages.
self.KS = self.KS || {};

// Names are only shown in the popup; every file uses the pseudonym.
KS.PARTICIPANTS = [
  ['P01', 'Oisín'],
  ['P02', 'Elias'],
  ['P03', 'Xia'],
  ['P04', 'Blaise'],
];

KS.DEFAULT_LABELS = ['normal', 'tired', 'impaired'];

KS.DEFAULT_SITES = {
  'chatgpt.com': true,
  'chat.openai.com': true,
  'claude.ai': true,
  'gemini.google.com': true,
  'chat.mistral.ai': true,
};

// First 8 columns are the class's common format; the rest are our extras.
KS.COLUMNS = [
  'participant_id', 'session_id', 'sample_id', 'event', 'key_code', 'timestamp_ms', 'press_id', 'key',
  't_epoch_ms', 'shift', 'ctrl', 'alt', 'meta', 'capslock', 'location', 'repeat_count',
  'input_type', 'text_len', 'caret_pos', 'detail',
];

KS.MODIFIERS = new Set(['Shift', 'Control', 'Alt', 'AltGraph', 'Meta', 'CapsLock']);

// Sort rows by time and replace the recorder's internal ids ("tag:n") with 1, 2, 3...
KS.normalise = rows => {
  const sorted = [...rows].sort((a, b) => a.timestamp_ms - b.timestamp_ms);
  const ids = { press_id: new Map(), sample_id: new Map() };
  return sorted.map(r => {
    const out = { ...r };
    for (const f of ['press_id', 'sample_id']) {
      if (r[f] === '' || r[f] == null) continue;
      const m = ids[f];
      if (!m.has(r[f])) m.set(r[f], m.size + 1);
      out[f] = m.get(r[f]);
    }
    return out;
  });
};

KS.toCSV = rows => {
  const esc = v => {
    const s = v == null ? '' : String(v);
    return /[",\n\r]/.test(s) || s.trim() !== s ? `"${s.replace(/"/g, '""')}"` : s;
  };
  return [KS.COLUMNS.join(','), ...rows.map(r => KS.COLUMNS.map(c => esc(r[c])).join(','))].join('\n') + '\n';
};

KS.download = (name, text, type = 'text/csv') => {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const a = Object.assign(document.createElement('a'), { href: url, download: name });
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 5000);
};
