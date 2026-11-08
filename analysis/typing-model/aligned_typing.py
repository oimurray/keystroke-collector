"""Conservative append/backspace replay and alignment to a known fixed passage.

Raw events are never modified. Complex editing is rejected, not guessed.
"""
from collections import Counter, defaultdict

from keystroke_model import BREAKS, MODIFIERS, features


def align_text(typed, reference):
    """Minimum-edit semiglobal alignment; reference prefix/suffix may be absent."""
    n = len(reference)
    previous = [0] * (n + 1)
    trace = [bytearray(n + 1)]
    for i, char in enumerate(typed, 1):
        current = [i] + [0] * n
        directions = bytearray(n + 1)
        directions[0] = 2
        for j, expected in enumerate(reference, 1):
            diagonal = previous[j - 1] + (char != expected)
            insertion, deletion = previous[j] + 1, current[j - 1] + 1
            best = min(diagonal, insertion, deletion)
            current[j] = best
            directions[j] = 1 if best == diagonal else 2 if best == insertion else 3
        trace.append(directions)
        previous = current
    end = min(range(n + 1), key=previous.__getitem__)
    distance = previous[end]
    mapping, matches, insertions, omitted = [None] * len(typed), [False] * len(typed), set(), []
    i, j = len(typed), end
    while i:
        direction = trace[i][j]
        if direction == 1:
            mapping[i - 1] = j - 1
            matches[i - 1] = typed[i - 1] == reference[j - 1]
            i, j = i - 1, j - 1
        elif direction == 2:
            mapping[i - 1] = min(max(j - 1, 0), n - 1)
            insertions.add(i - 1)
            i -= 1
        else:
            omitted.append(j - 1)
            j -= 1
    return {"mapping": mapping, "matches": matches, "insertions": insertions, "omitted": omitted,
            "start": j, "end": end, "error_rate": distance / max(len(typed), end - j, 1)}


def replay(rows):
    """Replay simple end-of-buffer edits; require reliable press pairing and caret."""
    releases = defaultdict(list)
    counts = Counter(r["press_id"] for r in rows if r["event"] == "down")
    for r in rows:
        if r["event"] == "up":
            releases[r["press_id"]].append(r)
    buffer, presses, repairs = [], [], []
    segment = 0
    unverified_caret = 0
    for r in rows:
        if r.get("detail") == "paste" or r.get("input_type") == "insertFromPaste":
            raise ValueError("paste")
        if r.get("detail") in BREAKS:
            segment += 1
        if r["event"] != "down" or r["key"] in MODIFIERS:
            continue
        key = r["key"]
        if key == "Enter":
            segment += 1
            continue
        if key != "Backspace" and len(key) != 1:
            raise ValueError("complex_edit_or_composition")
        if any(r.get(mod) == "1" for mod in ("ctrl", "alt", "meta")):
            raise ValueError("modified_shortcut")
        input_type = r.get("input_type", "")
        if input_type not in ("", "insertText", "deleteContentBackward") or (key == "Backspace" and input_type == "insertText"):
            raise ValueError("unsupported_input_edit")
        caret = r.get("caret_pos")
        if caret not in (None, ""):
            if int(caret) != len(buffer):
                raise ValueError("caret_mismatch")
        else:
            unverified_caret += 1
        ups = releases[r["press_id"]]
        if counts[r["press_id"]] != 1 or len(ups) != 1:
            raise ValueError("invalid_press_pair")
        up = ups[0]
        hold = up["timestamp_ms"] - r["timestamp_ms"]
        if (up["key"] != key or up["sample_id"] != r["sample_id"] or up["text_type"] != r["text_type"]
                or not 0 < hold <= 5000 or up.get("detail") == "forced_release"
                or int(up.get("repeat_count") or 0) or int(r.get("repeat_count") or 0)):
            raise ValueError("invalid_or_repeated_press")
        index = len(presses)
        presses.append({"key": key, "t": r["timestamp_ms"], "up": up["timestamp_ms"],
                        "hold": hold, "segment": segment, "sequence": index})
        if key == "Backspace":
            deleted = buffer.pop()[1] if buffer else None
            repairs.append((deleted, index, len(buffer)))
        else:
            buffer.append((key, index))
    return buffer, presses, repairs, unverified_caret


def extract_aligned(rows, reference, size=200, minimum_match=.90):
    samples = defaultdict(list)
    for r in rows:
        if r.get("sample_id"):
            samples[r["sample_id"]].append(r)
    windows, diagnostics = [], []
    for sample_id, sample in samples.items():
        down_types = {r["text_type"] for r in sample if r["event"] == "down"}
        if "fixed" not in down_types:
            continue
        diagnostic = {"sample_id": sample_id, "accepted_sections": []}
        try:
            if down_types != {"fixed"}:
                raise ValueError("mixed_task_sample")
            buffer, presses, repairs, unverified = replay(sample)
            typed = "".join(char for char, _ in buffer)
            if not size // 2 <= len(typed) <= len(reference) * 2:
                raise ValueError("too_short_or_wrong_task")
            aligned = align_text(typed, reference)
            diagnostic.update(final_characters=len(typed), alignment_error_rate=aligned["error_rate"],
                              unverified_caret_events=unverified)
            if aligned["error_rate"] > 1 - minimum_match:
                raise ValueError("poor_reference_match")
            assigned = {event: aligned["mapping"][i] for i, (_, event) in enumerate(buffer)}
            for deleted, backspace, slot in repairs:
                position = aligned["mapping"][min(slot, len(buffer) - 1)]
                assigned[backspace] = position
                if deleted is not None:
                    assigned[deleted] = position
            for section, start in enumerate(range(0, len(reference) - size + 1, size), 1):
                end = start + size
                if aligned["start"] > start or aligned["end"] < end:
                    continue
                selected = [(event, aligned["mapping"][i]) for i, (_, event) in enumerate(buffer)
                            if aligned["matches"][i] and start <= aligned["mapping"][i] < end]
                if len(selected) / size < minimum_match:
                    continue
                physical = [presses[i] for i, position in assigned.items() if start <= position < end]
                # An interruption inside the section makes its continuous timing ambiguous.
                if len({p["segment"] for p in physical}) != 1:
                    continue
                clean, run, last = [], 0, None
                for event, _ in selected:
                    press = dict(presses[event])
                    if last is None or event != last + 1:
                        run += 1
                    press["block"] = (sample_id, run)
                    clean.append(press)
                    last = event
                f = features(clean)
                if f is None:
                    continue
                f["backspace_fraction"] = sum(p["key"] == "Backspace" for p in physical) / max(1, len(physical))
                errors = sum(start <= p < end for p in aligned["omitted"])
                errors += sum(start <= aligned["mapping"][i] < end and not aligned["matches"][i] for i in range(len(buffer)))
                f["reference_error_fraction"] = errors / size
                f["extra_press_fraction"] = max(0, len(physical) - size) / size
                windows.append({"text_type": "fixed", "section": section, "features": f,
                                "sample_id": sample_id, "physical_keypresses": len(physical),
                                "reference_characters": size, "matched_characters": len(clean),
                                "start_ms": min(p["t"] for p in physical), "end_ms": max(p["up"] for p in physical)})
                diagnostic["accepted_sections"].append(section)
            diagnostic["status"] = "accepted" if diagnostic["accepted_sections"] else "no_complete_reliable_section"
        except (ValueError, TypeError) as error:
            diagnostic["status"] = str(error)
        diagnostics.append(diagnostic)
    return windows, diagnostics
