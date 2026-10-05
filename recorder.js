// Keystroke recorder shared by the content script and the test page.
// It emits raw rows only; all features are computed offline.
(() => {
  KS.createRecorder = ({ findTarget, onRows, origin }) => {
    const tag = Math.random().toString(36).slice(2, 8); // keeps ids unique across tabs / page reloads
    const open = new Map(); // e.code -> press currently held down
    let buffer = [];
    let pressSeq = 0, sampleSeq = 0;
    let curSample = null;
    let lastDown = null;
    let lastTextLen = 0, lastWasDelete = false;
    let running = false, timer = null;

    // High-resolution wall clock (sub-ms, comparable across tabs).
    const clock = () => performance.timeOrigin + performance.now();

    const row = (event, t, fields) => ({
      sample_id: '', event, key_code: '', timestamp_ms: +(t - origin()).toFixed(3), press_id: '', key: '',
      t_epoch_ms: Math.round(t), shift: '', ctrl: '', alt: '', meta: '', capslock: '', location: '',
      repeat_count: '', input_type: '', text_len: '', caret_pos: '', detail: '',
      ...fields,
    });

    const mods = e => ({
      shift: +e.shiftKey, ctrl: +e.ctrlKey, alt: +e.altKey, meta: +e.metaKey,
      capslock: +!!(e.getModifierState && e.getModifierState('CapsLock')),
    });

    function measure(el) {
      if (!el) return { text_len: '', caret_pos: '' };
      if (typeof el.value === 'string') return { text_len: el.value.length, caret_pos: el.selectionStart ?? '' };
      let caret_pos = '';
      const sel = getSelection();
      if (sel && sel.rangeCount && el.contains(sel.anchorNode)) {
        const r = document.createRange();
        r.selectNodeContents(el);
        r.setEnd(sel.anchorNode, sel.anchorOffset);
        caret_pos = r.toString().length;
      }
      return { text_len: el.textContent.length, caret_pos };
    }

    const marker = (name, t = clock(), extra = {}) =>
      buffer.push(row('marker', t, { sample_id: curSample ?? '', detail: name, ...extra }));

    function startSample(t) {
      if (curSample) return;
      curSample = `${tag}:${++sampleSeq}`;
      marker('sample_start', t);
    }

    function endSample(reason, len, t) {
      if (!curSample) return;
      marker(`sample_end:${reason}`, t, { text_len: len });
      curSample = null;
    }

    const release = (p, t, fields) => buffer.push(row('up', t, {
      sample_id: p.sample, key_code: p.code, press_id: p.id, key: p.key, repeat_count: p.repeat, ...fields,
    }));

    // Close presses whose release we will never see (window lost focus, recording stopped...).
    function releaseAll(t = clock()) {
      for (const p of open.values()) release(p, t, { location: p.location, detail: 'forced_release' });
      open.clear();
    }

    function onKeyDown(e) {
      if (!running) return;
      const el = findTarget(e.target);
      if (!el) return;
      const t = clock();
      const held = open.get(e.code);
      if (e.repeat) { // auto-repeat: counted on the release row, never as a new press
        if (held) held.repeat++;
        return;
      }
      if (held) { open.delete(e.code); release(held, t, { location: held.location, detail: 'forced_release' }); }

      const m = measure(el);
      // Box emptied without a delete key: the message was sent with the send button.
      if (curSample && m.text_len === 0 && lastTextLen > 0 && !lastWasDelete) endSample('cleared', lastTextLen, t);
      startSample(t);

      const press = { id: `${tag}:${++pressSeq}`, code: e.code, key: e.key, sample: curSample, repeat: 0, location: e.location };
      open.set(e.code, press);
      lastDown = row('down', t, {
        sample_id: curSample, key_code: e.code, press_id: press.id, key: e.key,
        ...mods(e), location: e.location, repeat_count: 0, ...m,
      });
      buffer.push(lastDown);
      lastWasDelete = e.key === 'Backspace' || e.key === 'Delete';
      lastTextLen = m.text_len;
      if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) endSample('enter', m.text_len, t);
    }

    function onKeyUp(e) {
      if (!running) return;
      const p = open.get(e.code);
      if (!p) return;
      const t = clock();
      open.delete(e.code);
      const el = findTarget(e.target);
      const m = measure(el);
      release(p, t, { ...mods(e), location: e.location, ...m });
      if (el) lastTextLen = m.text_len;
    }

    // Attach what the keypress actually did (insertText, deleteContentBackward, insertFromPaste...).
    function onBeforeInput(e) {
      if (!running || !lastDown || lastDown.input_type || !findTarget(e.target)) return;
      if (clock() - lastDown.t_epoch_ms < 1000) lastDown.input_type = e.inputType;
    }

    const onPaste = e => { if (running && findTarget(e.target)) marker('paste'); };
    const onBlur = () => { if (running) { const t = clock(); releaseAll(t); marker('blur', t); } };
    const onFocus = () => { if (running) marker('focus'); };
    const onVisibility = () => { if (running) marker(`visibility_${document.visibilityState}`); };

    // Keep the newest rows briefly so beforeinput can still annotate them.
    function flush(all) {
      const cut = all ? Infinity : clock() - 500;
      let n = 0;
      while (n < buffer.length && buffer[n].t_epoch_ms < cut) n++;
      if (n) onRows(buffer.splice(0, n));
    }

    window.addEventListener('keydown', onKeyDown, true);
    window.addEventListener('keyup', onKeyUp, true);
    document.addEventListener('beforeinput', onBeforeInput, true);
    document.addEventListener('paste', onPaste, true);
    window.addEventListener('blur', onBlur);
    window.addEventListener('focus', onFocus);
    document.addEventListener('visibilitychange', onVisibility);
    window.addEventListener('pagehide', () => running && flush(true));

    return {
      start() {
        if (running) return;
        running = true;
        curSample = null;
        lastTextLen = 0;
        timer = setInterval(() => flush(false), 1000);
      },
      stop() {
        if (!running) return;
        const t = clock();
        releaseAll(t);
        endSample('stop', lastTextLen, t);
        flush(true);
        running = false;
        clearInterval(timer);
      },
      lastDown: () => lastDown,
    };
  };
})();
