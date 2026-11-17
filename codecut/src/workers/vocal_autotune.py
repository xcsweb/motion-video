#!/usr/bin/env python3
"""CodeCut WORLD vocal autotune worker. One versioned JSON request on stdin."""

import json
import math
import os
from pathlib import Path
import subprocess
import sys
import wave
from datetime import datetime, timezone

np = None
pyworld = None
uniform_filter1d = None
find_peaks = None


class WorkerFailure(Exception):
    def __init__(self, code, message, diagnostics=None, retryable=False):
        super().__init__(message)
        self.code = code
        self.message = message
        self.diagnostics = diagnostics
        self.retryable = retryable


def load_dependencies():
    global np, pyworld, uniform_filter1d, find_peaks
    missing = []
    try:
        import numpy
        np = numpy
    except (ImportError, OSError):
        missing.append("numpy")
    try:
        from scipy.ndimage import uniform_filter1d as filter1d
        from scipy.signal import find_peaks as signal_find_peaks
        uniform_filter1d = filter1d
        find_peaks = signal_find_peaks
    except (ImportError, OSError):
        missing.append("scipy")
    try:
        import pyworld as world
        pyworld = world
    except (ImportError, OSError):
        missing.append("pyworld")
    if missing:
        raise WorkerFailure(
            "AUTOTUNE_DEPENDENCIES_MISSING",
            "Autotune requires Python packages: " + ", ".join(missing)
            + ". Install them with: python3 -m pip install numpy scipy pyworld",
            {"missing": missing, "python": sys.executable,
             "install": "python3 -m pip install numpy scipy pyworld"},
        )


def midi_frequency(note):
    return 440.0 * 2.0 ** ((note - 69) / 12.0)


def number(value):
    value = float(value)
    if not math.isfinite(value):
        raise WorkerFailure("AUTOTUNE_NUMERIC_ERROR", "Autotune produced a non-finite measurement")
    return round(value, 6)


def decode_audio(source, start, end, sample_rate):
    ffmpeg = os.environ.get("CODECUT_FFMPEG", "ffmpeg")
    command = [
        ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error",
        "-ss", f"{start:.9f}", "-i", source, "-t", f"{end - start:.9f}",
        "-vn", "-ac", "1", "-ar", str(sample_rate), "-f", "f32le", "pipe:1",
    ]
    try:
        result = subprocess.run(command, capture_output=True, check=False, timeout=570)
    except FileNotFoundError as cause:
        raise WorkerFailure(
            "AUTOTUNE_DEPENDENCIES_MISSING",
            "FFmpeg is required to decode autotune source media",
            {"missing": ["ffmpeg"], "command": command}, 
        ) from cause
    except subprocess.TimeoutExpired as cause:
        raise WorkerFailure("AUTOTUNE_SOURCE_DECODE_FAILED", "FFmpeg timed out while decoding source media",
                            {"source": source, "start": start, "end": end}, True) from cause
    if result.returncode != 0:
        raise WorkerFailure(
            "AUTOTUNE_SOURCE_DECODE_FAILED", "FFmpeg could not decode the autotune source media",
            {"source": source, "exitCode": result.returncode,
             "stderrTail": result.stderr.decode("utf-8", "replace")[-8192:]},
        )
    audio = np.frombuffer(result.stdout, dtype="<f4").astype(np.float64).copy()
    required = end - start
    if len(audio) < sample_rate * min(0.02, required):
        raise WorkerFailure("AUTOTUNE_SOURCE_RANGE_INVALID", "Source range contains no decodable audio",
                            {"source": source, "start": start, "end": end})
    return audio


def fill_short_unvoiced(mask, maximum_frames=6):
    result = mask.copy()
    index = 1
    while index < len(result) - 1:
        if result[index]:
            index += 1
            continue
        end = index
        while end < len(result) and not result[end]:
            end += 1
        if result[index - 1] and end < len(result) and result[end] and end - index <= maximum_frames:
            result[index:end] = True
        index = end
    return result


def detect_vowel_peaks(f0, time_axis, energy, decode_start, frame_period):
    smoothed = uniform_filter1d(energy, size=3, mode="nearest")
    noise = float(np.percentile(smoothed, 10))
    peak_energy = float(np.percentile(smoothed, 95))
    dynamic_range = max(1e-7, peak_energy - noise)
    distance = max(1, int(round(60 / frame_period)))
    peaks, properties = find_peaks(
        smoothed, distance=distance, prominence=max(1e-7, dynamic_range * 0.035),
    )
    candidates = []
    for position, index in enumerate(peaks):
        nearby_f0 = f0[max(0, index - 2):min(len(f0), index + 3)]
        if np.count_nonzero(nearby_f0 > 0) < max(1, len(nearby_f0) * 0.4):
            continue
        if smoothed[index] < noise + dynamic_range * 0.06:
            continue
        candidates.append({
            "index": int(index), "time": float(time_axis[index] + decode_start),
            "prominence": float(properties["prominences"][position]),
            "left": int(properties["left_bases"][position]),
            "right": int(properties["right_bases"][position]),
        })
    return candidates, smoothed, noise, dynamic_range


def ordered_peak_assignment(notes, peaks, dynamic_range, decode_start, decode_end, following_start=None):
    """Assign one strictly ordered vowel peak per note; source ranges are only priors."""
    candidate_lists = []
    for index, note in enumerate(notes):
        start = float(note["source"]["start"])
        end = float(note["source"]["end"])
        lower = max(decode_start, start - 0.12)
        next_start = end
        following = following_start if index + 1 == len(notes) else float(notes[index + 1]["source"]["start"])
        if following is not None and following >= start:
            next_start = following
        upper = min(decode_end, max(end, next_start) + 0.28)
        candidates = []
        for peak in peaks:
            if peak["time"] < lower or peak["time"] > upper:
                continue
            distance_cost = 0.25 * ((peak["time"] - end) / 0.22) ** 2
            outside = max(start - peak["time"], peak["time"] - end, 0)
            range_cost = 0.5 * (outside / 0.1) ** 2
            strength = min(1.5, peak["prominence"] / dynamic_range)
            candidates.append({**peak, "cost": distance_cost + range_cost - 2 * strength, "fallback": False})
        candidates.append({
            "index": None, "time": float(np.clip(end, lower, upper)),
            "left": None, "right": None, "cost": 25.0, "fallback": True,
        })
        candidates.sort(key=lambda candidate: (candidate["time"], candidate["fallback"]))
        candidate_lists.append(candidates)

    costs = [candidate["cost"] for candidate in candidate_lists[0]]
    parents = []
    for index in range(1, len(candidate_lists)):
        current_costs = [math.inf] * len(candidate_lists[index])
        current_parents = [-1] * len(candidate_lists[index])
        for current_index, candidate in enumerate(candidate_lists[index]):
            for previous_index, previous in enumerate(candidate_lists[index - 1]):
                if not math.isfinite(costs[previous_index]):
                    continue
                if candidate["time"] <= previous["time"] + 0.045:
                    continue
                cost = costs[previous_index] + candidate["cost"]
                if cost < current_costs[current_index]:
                    current_costs[current_index] = cost
                    current_parents[current_index] = previous_index
        costs = current_costs
        parents.append(current_parents)

    if not any(math.isfinite(cost) for cost in costs):
        return [min(candidates, key=lambda candidate: candidate["cost"])
                for candidates in candidate_lists], True
    selected = [None] * len(candidate_lists)
    current = min(range(len(costs)), key=lambda index: costs[index])
    selected[-1] = candidate_lists[-1][current]
    for index in range(len(candidate_lists) - 1, 0, -1):
        current = parents[index - 1][current]
        selected[index - 1] = candidate_lists[index - 1][current]
    return selected, False


def fallback_vowel(note, f0, absolute_times, energy):
    start = float(note["source"]["start"])
    end = float(note["source"]["end"])
    segment = (absolute_times >= start - 1e-6) & (absolute_times < end - 1e-6)
    voiced_energy = energy[segment & (f0 > 0)]
    threshold = max(1e-7, float(np.percentile(voiced_energy, 25)) * 0.35) if len(voiced_energy) else 1e-7
    candidates = np.flatnonzero(segment & (f0 > 0) & (energy >= threshold))
    onset = start + min(0.08, (end - start) * 0.25)
    for index in candidates:
        if np.count_nonzero(f0[index:index + 5] > 0) >= 3:
            onset = float(absolute_times[index])
            break
    onset_index = int(np.argmin(np.abs(absolute_times - onset)))
    right_index = int(np.argmin(np.abs(absolute_times - end)))
    return {
        "onset": onset, "peak": min(end, onset + min(0.12, (end - onset) * 0.35)),
        "detection": "fallback", "left": max(0, onset_index - 1), "right": right_index,
        "warning": "No reliable ordered vowel peak was found; used a source vowel fallback. Set source.vowelStart manually for precise control.",
    }


def provided_vowel(note, peaks, absolute_times):
    onset = float(note["source"]["vowelStart"])
    end = float(note["source"]["end"])
    candidates = [peak for peak in peaks
                  if onset + 0.01 <= peak["time"] <= min(end + 0.28, onset + 0.38)]
    if candidates:
        peak = min(candidates, key=lambda candidate: ((candidate["time"] - end) / 0.24) ** 2
                   - min(1.5, candidate["prominence"]))
        return {"onset": onset, "peak": peak["time"], "detection": "provided",
                "left": peak["left"], "right": peak["right"], "warning": None}
    onset_index = int(np.argmin(np.abs(absolute_times - onset)))
    right_index = int(np.argmin(np.abs(absolute_times - end)))
    return {"onset": onset, "peak": min(end, onset + 0.12), "detection": "provided",
            "left": max(0, onset_index - 1), "right": right_index, "warning": None}


def detected_vowel(note, peak, f0, absolute_times, smoothed, frame_period):
    peak_index = peak["index"]
    left = max(peak["left"], peak_index - int(round(0.32 * 1000 / frame_period)))
    if left < peak_index:
        left += int(np.argmin(smoothed[left:peak_index + 1]))
    valley_energy = float(smoothed[left])
    threshold = valley_energy + 0.14 * (float(smoothed[peak_index]) - valley_energy)
    rises = np.flatnonzero(smoothed[left:peak_index + 1] >= threshold)
    onset_index = left + int(rises[0]) if len(rises) else left
    for index in range(onset_index, peak_index + 1):
        if np.count_nonzero(f0[index:index + 5] > 0) >= 3:
            onset_index = index
            break
    if onset_index >= peak_index:
        onset_index = max(left, peak_index - 1)
    onset = float(absolute_times[onset_index])
    start = float(note["source"]["start"])
    end = float(note["source"]["end"])
    warning = None
    if onset < start - 0.02 or onset > end + 0.02 or peak["time"] < start - 0.02 or peak["time"] > end + 0.02:
        warning = "Detected vowel extends beyond the supplied source range; timestamps were treated as alignment priors. Verify this syllable and set source.vowelStart if needed."
    return {"onset": onset, "peak": peak["time"], "detection": "detected",
            "left": left, "right": peak["right"], "warning": warning}


def align_sources(notes, f0, time_axis, energy, decode_start, frame_period):
    absolute_times = time_axis + decode_start
    decode_end = float(absolute_times[-1])
    peaks, smoothed, noise, dynamic_range = detect_vowel_peaks(
        f0, time_axis, energy, decode_start, frame_period,
    )
    alignments = [None] * len(notes)
    index = 0
    while index < len(notes):
        if notes[index]["source"].get("vowelStart") is not None:
            alignments[index] = provided_vowel(notes[index], peaks, absolute_times)
            index += 1
            continue
        run_end = index + 1
        while run_end < len(notes):
            if notes[run_end]["source"].get("vowelStart") is not None:
                break
            if float(notes[run_end]["source"]["start"]) < float(notes[run_end - 1]["source"]["start"]):
                break
            run_end += 1
        following_start = None
        if run_end < len(notes):
            candidate_start = float(notes[run_end]["source"]["start"])
            if candidate_start >= float(notes[run_end - 1]["source"]["start"]):
                following_start = candidate_start
        selected, unordered = ordered_peak_assignment(
            notes[index:run_end], peaks, dynamic_range, decode_start, decode_end, following_start,
        )
        for offset, peak in enumerate(selected):
            note_index = index + offset
            if peak["fallback"]:
                alignments[note_index] = fallback_vowel(notes[note_index], f0, absolute_times, smoothed)
            else:
                alignments[note_index] = detected_vowel(
                    notes[note_index], peak, f0, absolute_times, smoothed, frame_period,
                )
            if unordered:
                warning = "Ordered vowel alignment was ambiguous; verify this source segment manually."
                alignments[note_index]["warning"] = (
                    alignments[note_index]["warning"] + " " + warning
                    if alignments[note_index]["warning"] else warning
                )
        index = run_end

    for index in range(1, len(alignments)):
        previous = alignments[index - 1]
        alignment = alignments[index]
        minimum_onset = previous["peak"] + frame_period / 1000
        if (alignment["detection"] == "provided" or alignment["peak"] <= previous["peak"]
                or alignment["onset"] >= minimum_onset):
            continue
        left = int(np.argmin(np.abs(absolute_times - minimum_onset)))
        peak_index = int(np.argmin(np.abs(absolute_times - alignment["peak"])))
        if left >= peak_index:
            continue
        left += int(np.argmin(smoothed[left:peak_index + 1]))
        valley_energy = float(smoothed[left])
        threshold = valley_energy + 0.14 * (float(smoothed[peak_index]) - valley_energy)
        rises = np.flatnonzero(smoothed[left:peak_index + 1] >= threshold)
        onset_index = left + int(rises[0]) if len(rises) else left
        for candidate in range(onset_index, peak_index + 1):
            if np.count_nonzero(f0[candidate:candidate + 5] > 0) >= 3:
                onset_index = candidate
                break
        alignment["onset"] = max(minimum_onset, float(absolute_times[onset_index]))
        alignment["left"] = left
        warning = "Vowel onset was moved after the previous syllable peak to avoid overlapping source segments."
        alignment["warning"] = alignment["warning"] + " " + warning if alignment["warning"] else warning

    for index, alignment in enumerate(alignments):
        onset_index = int(np.argmin(np.abs(absolute_times - alignment["onset"])))
        peak_index = int(np.argmin(np.abs(absolute_times - alignment["peak"])))
        left_limit = max(0, alignment["left"], onset_index - int(round(0.18 * 1000 / frame_period)))
        consonant_threshold = noise + 0.06 * max(0, float(smoothed[peak_index]) - noise)
        start_index = onset_index
        while start_index > left_limit and smoothed[start_index - 1] > consonant_threshold:
            start_index -= 1
        start_index = max(left_limit, start_index - 1)
        alignment["sampleStart"] = min(alignment["onset"], float(absolute_times[start_index]))
        right_index = max(alignment["right"], peak_index + 1)
        right_index = min(right_index, len(absolute_times) - 1)
        sample_end = min(float(absolute_times[right_index]), alignment["peak"] + 0.45)
        alignment["sampleEnd"] = max(alignment["onset"] + 3 * frame_period / 1000, sample_end)

    for index in range(len(alignments) - 1):
        current = alignments[index]
        following = alignments[index + 1]
        if following["onset"] <= current["onset"]:
            continue
        boundary = following["sampleStart"]
        if boundary > current["onset"] + 3 * frame_period / 1000:
            current["sampleEnd"] = min(current["sampleEnd"], boundary)

    for alignment in alignments:
        duration = max(3 * frame_period / 1000, alignment["sampleEnd"] - alignment["onset"])
        attack = min(0.12, max(2 * frame_period / 1000,
                              (alignment["peak"] - alignment["onset"]) * 0.6), duration * 0.4)
        release = min(0.08, max(2 * frame_period / 1000,
                               (alignment["sampleEnd"] - alignment["peak"]) * 0.35), duration * 0.3)
        if attack + release > duration * 0.7:
            scale = duration * 0.7 / (attack + release)
            attack *= scale
            release *= scale
        alignment["sustainStart"] = alignment["onset"] + attack
        alignment["releaseStart"] = alignment["sampleEnd"] - release
    return alignments


def map_source_segment(local, target_anchors, source_anchors):
    mapped = np.full(len(local), source_anchors[-1], dtype=np.float64)
    for index in range(len(target_anchors) - 1):
        target_start, target_end = target_anchors[index:index + 2]
        source_start, source_end = source_anchors[index:index + 2]
        selected = (local >= target_start - 1e-12) & (local < target_end - 1e-12)
        if index == len(target_anchors) - 2:
            selected |= local >= target_end - 1e-12
        if target_end <= target_start + 1e-12:
            mapped[selected] = source_start
        else:
            mapped[selected] = source_start + np.clip(
                (local[selected] - target_start) / (target_end - target_start), 0, 1,
            ) * (source_end - source_start)
    return mapped


def analyze_source(audio, sample_rate, frame_period, f0_floor, f0_ceil):
    if len(audio) < 32:
        raise WorkerFailure("AUTOTUNE_SOURCE_RANGE_INVALID", "Source audio is too short for WORLD analysis")
    raw_harvest, time_axis = pyworld.harvest(
        audio, sample_rate, f0_floor=f0_floor, f0_ceil=f0_ceil, frame_period=frame_period,
    )
    harvest = pyworld.stonemask(audio, raw_harvest, time_axis, sample_rate)
    raw_dio, dio_times = pyworld.dio(
        audio, sample_rate, f0_floor=f0_floor, f0_ceil=f0_ceil, frame_period=frame_period,
    )
    dio = pyworld.stonemask(audio, raw_dio, dio_times, sample_rate)
    # Harvest can drop an entire stable tone on both speech and simple harmonic sources.
    # Fill only its unvoiced frames from the independent DIO track; retain Harvest otherwise.
    f0 = np.where(harvest > 0, harvest, dio) if len(dio) == len(harvest) else harvest
    spectral = pyworld.cheaptrick(audio, f0, time_axis, sample_rate)
    aperiodicity = pyworld.d4c(audio, f0, time_axis, sample_rate)
    window = max(3, int(round(sample_rate * 0.025)))
    sample_energy = np.sqrt(np.maximum(uniform_filter1d(audio * audio, size=window, mode="nearest"), 0))
    energy = np.interp(time_axis, np.arange(len(audio)) / sample_rate, sample_energy)
    return f0, time_axis, spectral, aperiodicity, energy


def synthesize_phrase(phrase, request, sample_rate, frame_period, f0_floor, f0_ceil):
    notes = phrase["notes"]
    original_source_end = max(float(note["source"]["end"]) for note in notes)
    source_min = max(0.0, min(float(note["source"]["start"]) for note in notes) - 0.2)
    source_max = original_source_end + 0.4
    audio = decode_audio(request["source"], source_min, source_max, sample_rate)
    required_samples = int(math.ceil((original_source_end - source_min) * sample_rate))
    if len(audio) < required_samples - int(0.02 * sample_rate):
        raise WorkerFailure(
            "AUTOTUNE_SOURCE_RANGE_INVALID", "A note source range exceeds the decodable source media duration",
            {"phraseId": phrase["id"], "sourceEnd": original_source_end,
             "decodedDuration": len(audio) / sample_rate, "decodeStart": source_min},
        )
    source_f0, source_times, spectral, aperiodicity, energy = analyze_source(
        audio, sample_rate, frame_period, f0_floor, f0_ceil,
    )
    if len(source_f0) < 2:
        raise WorkerFailure("AUTOTUNE_SOURCE_RANGE_INVALID", "Phrase source range has too few analysis frames",
                            {"phraseId": phrase["id"]})
    alignments = align_sources(notes, source_f0, source_times, energy, source_min, frame_period)

    phrase_start = float(notes[0]["target"]["start"])
    phrase_end = max(float(note["target"]["start"]) + float(note["target"]["duration"]) for note in notes)
    duration = phrase_end - phrase_start
    frame_count = max(1, int(round(duration * 1000 / frame_period)))
    local_times = np.arange(frame_count, dtype=np.float64) * frame_period / 1000
    target_times = phrase_start + local_times
    source_positions_time = np.zeros(frame_count, dtype=np.float64)
    target_frequency = np.zeros(frame_count, dtype=np.float64)
    vibrato_cents = np.zeros(frame_count, dtype=np.float64)
    note_reports = []
    target_vowels = []
    default_lead = float(request.get("consonantLeadMs", 25)) / 1000
    vibrato = request.get("vibrato")

    for note, alignment in zip(notes, alignments):
        target_start = float(note["target"]["start"])
        target_duration = float(note["target"]["duration"])
        target_end = target_start + target_duration
        vowel_start = alignment["onset"]
        vowel_offset = note["target"].get("vowelOffset")
        if vowel_offset is None:
            natural_lead = max(0, vowel_start - alignment["sampleStart"])
            base_lead = min(default_lead, target_duration * 0.25)
            vowel_offset = min(target_duration * 0.35, 0.18, max(base_lead, natural_lead))
        target_vowel = target_start + float(vowel_offset)
        target_vowels.append(target_vowel)
        target_attack_end = target_vowel + min(
            alignment["sustainStart"] - vowel_start, (target_end - target_vowel) * 0.4,
        )
        target_release_start = target_end - min(
            alignment["sampleEnd"] - alignment["releaseStart"],
            max(0, target_end - target_attack_end) * 0.35,
        )
        if target_release_start <= target_attack_end:
            target_release_start = (target_attack_end + target_end) / 2
        indices = np.flatnonzero((target_times >= target_start - 1e-9) & (target_times < target_end - 1e-9))
        local = target_times[indices]
        mapped = map_source_segment(
            local,
            [target_start, target_vowel, target_attack_end, target_release_start, target_end],
            [alignment["sampleStart"], vowel_start, alignment["sustainStart"],
             alignment["releaseStart"], alignment["sampleEnd"]],
        )
        source_positions_time[indices] = np.clip(mapped, alignment["sampleStart"], alignment["sampleEnd"])
        target_frequency[indices] = midi_frequency(int(note["target"]["midi"]))
        if vibrato and float(vibrato.get("depthCents", 0)) > 0:
            elapsed = local - target_vowel
            delay = float(vibrato.get("delayMs", 160)) / 1000
            envelope = np.clip((elapsed - delay) / 0.24, 0, 1)
            vibrato_cents[indices] = (
                float(vibrato.get("depthCents", 0)) * envelope
                * np.sin(2 * np.pi * float(vibrato.get("rateHz", 5.2)) * np.maximum(elapsed, 0))
            )
        warnings = [alignment["warning"]] if alignment["warning"] else []
        note_reports.append((target_start, {
            "id": note["id"], "phraseId": phrase["id"], "text": note["text"],
            "targetMidi": int(note["target"]["midi"]),
            "targetFrequencyHz": number(midi_frequency(int(note["target"]["midi"]))),
            "sourceVowelStart": number(vowel_start), "sourceVowelDetection": alignment["detection"],
            "targetVowelStart": number(target_vowel), "warnings": warnings,
        }))

    positions = np.clip((source_positions_time - source_min) * 1000 / frame_period, 0, len(source_f0) - 1.000001)
    lower = np.floor(positions).astype(int)
    upper = np.minimum(lower + 1, len(source_f0) - 1)
    fraction = positions - lower
    nearest = np.rint(positions).astype(int)
    target_spectral = spectral[lower] * (1 - fraction[:, None]) + spectral[upper] * fraction[:, None]
    target_aperiodicity = aperiodicity[lower] * (1 - fraction[:, None]) + aperiodicity[upper] * fraction[:, None]
    voiced = fill_short_unvoiced(source_f0[nearest] > 0)

    log_pitch = np.log2(np.maximum(target_frequency, 1e-6))
    portamento = float(request.get("portamentoMs", 35)) / 1000
    if portamento > 0:
        for index in range(1, len(notes)):
            previous = notes[index - 1]
            note = notes[index]
            start = float(note["target"]["start"])
            end = start + float(note["target"]["duration"])
            transition_start = max(start, target_vowels[index] - portamento * 0.35)
            transition_end = min(end, transition_start + portamento)
            affected = (target_times >= start - 1e-9) & (target_times < transition_end - 1e-9)
            blend = np.clip((target_times[affected] - transition_start) / portamento, 0, 1)
            previous_log = math.log2(midi_frequency(int(previous["target"]["midi"])))
            current_log = math.log2(midi_frequency(int(note["target"]["midi"])))
            log_pitch[affected] = previous_log * (1 - blend) + current_log * blend
    target_f0 = 2 ** log_pitch * 2 ** (vibrato_cents / 1200)
    target_f0[~voiced] = 0
    target_f0[target_frequency <= 0] = 0

    synthesized = pyworld.synthesize(
        np.ascontiguousarray(target_f0, dtype=np.float64),
        np.ascontiguousarray(target_spectral, dtype=np.float64),
        np.ascontiguousarray(target_aperiodicity, dtype=np.float64),
        sample_rate, frame_period,
    )
    expected = int(round(duration * sample_rate))
    synthesized = synthesized[:expected]
    if len(synthesized) < expected:
        synthesized = np.pad(synthesized, (0, expected - len(synthesized)))
    fade_in = min(len(synthesized) // 2, int(sample_rate * 0.006))
    fade_out = min(len(synthesized) // 2, int(sample_rate * 0.02))
    if fade_in:
        synthesized[:fade_in] *= np.linspace(0, 1, fade_in)
    if fade_out:
        synthesized[-fade_out:] *= np.linspace(1, 0, fade_out)
    phrase_report = {
        "id": phrase["id"], "start": number(phrase_start), "duration": number(duration),
        "noteCount": len(notes), "voicedRatio": number(np.mean(voiced)),
    }
    return synthesized, phrase_report, note_reports


def stable_onset(f0, time_axis, start, end):
    candidates = np.flatnonzero((time_axis >= start - 1e-9) & (time_axis < end - 1e-9) & (f0 > 0))
    for index in candidates:
        if np.count_nonzero(f0[index:index + 5] > 0) >= 3:
            return float(time_axis[index])
    return None


def percentile(values, percentile_value):
    return float(np.percentile(np.asarray(values, dtype=np.float64), percentile_value)) if values else None


def verify_audio(mix, request, sample_rate, frame_period, f0_floor, f0_ceil, note_reports):
    raw_f0, time_axis = pyworld.dio(
        mix, sample_rate, f0_floor=f0_floor, f0_ceil=f0_ceil, frame_period=frame_period,
    )
    f0 = pyworld.stonemask(mix, raw_f0, time_axis, sample_rate)
    portamento = float(request.get("portamentoMs", 35)) / 1000
    global_warnings = []
    for target_start, report in note_reports:
        note = next(note for phrase in request["phrases"] for note in phrase["notes"] if note["id"] == report["id"])
        duration = float(note["target"]["duration"])
        target_end = target_start + duration
        target_vowel = float(report["targetVowelStart"])
        core_start = max(target_start + min(0.12, duration * 0.25), target_vowel + portamento)
        core_end = target_end - min(0.06, duration * 0.15)
        if core_end <= core_start:
            core_start = target_vowel
            core_end = target_end
        core = (time_axis >= core_start - 1e-9) & (time_axis < core_end - 1e-9)
        measured = f0[core & (f0 > 0)]
        target_frequency = float(report["targetFrequencyHz"])
        if len(measured):
            median_frequency = float(np.median(measured))
            cents = 1200 * math.log2(median_frequency / target_frequency)
            folded = (cents + 600) % 1200 - 600
            coverage = float(len(measured) / max(1, np.count_nonzero(core)))
            onset = stable_onset(f0, time_axis, target_start, min(target_end, target_start + max(0.4, duration * 0.7)))
            previous = (time_axis >= target_start - 0.025) & (time_axis < target_start - 0.005)
            continuous_voicing = target_start > 0 and np.any(f0[previous] > 0)
            octave_suspect = abs(cents) > 600 and abs(folded) < 100
            pitch_confidence = "high" if len(measured) >= 4 and coverage >= 0.55 and not octave_suspect else "low"
            onset_confidence = "low" if continuous_voicing or onset is None else "high"
            measurement = {
                "medianFrequencyHz": number(median_frequency), "centsError": number(cents),
                "octaveFoldedCentsError": number(folded), "voicedCoverage": number(coverage),
                "pitchConfidence": pitch_confidence, "onsetConfidence": onset_confidence,
            }
            if onset is not None:
                measurement["voicedOnset"] = number(onset)
                measurement["onsetErrorMs"] = number((onset - target_vowel) * 1000)
            report["measurement"] = measurement
            if octave_suspect:
                report["warnings"].append("Possible octave tracking error; raw cents were retained and excluded from reliable pitch summary.")
            elif pitch_confidence == "low":
                report["warnings"].append("Pitch measurement has low coverage or too few voiced frames; no automatic second-pass correction was applied.")
            elif abs(cents) > 50:
                report["warnings"].append("Reliable measured pitch differs from the target by more than 50 cents.")
            if continuous_voicing:
                report["warnings"].append("Voicing crosses this syllable boundary; F0 alone cannot reliably verify the new vowel onset.")
            elif onset is None:
                report["warnings"].append("No stable voiced onset was found in the target note.")
            elif abs((onset - target_vowel) * 1000) > 60:
                report["warnings"].append("Reliable measured vowel onset differs from the target by more than 60 ms.")
        else:
            report["warnings"].append("No reliable voiced frames were measured; no automatic second-pass correction was applied.")
            global_warnings.append(f'Note "{report["id"]}" has no measurable voiced pitch.')

    measured_notes = [report for _, report in note_reports if "measurement" in report]
    pitch = [abs(report["measurement"]["centsError"]) for report in measured_notes
             if report["measurement"]["pitchConfidence"] == "high"]
    onsets = [abs(report["measurement"]["onsetErrorMs"]) for report in measured_notes
              if report["measurement"]["onsetConfidence"] == "high" and "onsetErrorMs" in report["measurement"]]
    low_confidence = sum(1 for _, report in note_reports if "measurement" not in report
                         or report["measurement"]["pitchConfidence"] == "low"
                         or report["measurement"]["onsetConfidence"] == "low")
    summary = {
        "noteCount": len(note_reports), "measuredNoteCount": len(measured_notes),
        "reliablePitchNoteCount": len(pitch), "reliableOnsetNoteCount": len(onsets),
        "lowConfidenceNoteCount": low_confidence,
        "warningCount": sum(len(report["warnings"]) for _, report in note_reports) + len(global_warnings),
    }
    for key, values, percentile_value in (
        ("medianAbsoluteCentsError", pitch, 50), ("p95AbsoluteCentsError", pitch, 95),
        ("medianAbsoluteOnsetErrorMs", onsets, 50), ("p95AbsoluteOnsetErrorMs", onsets, 95),
    ):
        value = percentile(values, percentile_value)
        if value is not None:
            summary[key] = number(value)
    return summary, global_warnings


def write_wav(path, audio, sample_rate):
    pcm = (np.clip(audio, -0.999, 0.999) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        output.writeframes(pcm.tobytes())


def run(request):
    load_dependencies()
    sample_rate = int(request.get("sampleRate", 48000))
    frame_period = float(request.get("framePeriodMs", 5))
    f0_floor = float(request.get("f0Floor", 50))
    f0_ceil = float(request.get("f0Ceil", 1000))
    last_target = max(float(note["target"]["start"]) + float(note["target"]["duration"])
                      for phrase in request["phrases"] for note in phrase["notes"])
    duration = float(request.get("duration", last_target))
    mix = np.zeros(int(round(duration * sample_rate)), dtype=np.float64)
    phrase_reports = []
    note_reports = []
    for phrase in request["phrases"]:
        synthesized, phrase_report, reports = synthesize_phrase(
            phrase, request, sample_rate, frame_period, f0_floor, f0_ceil,
        )
        start = int(round(float(phrase["notes"][0]["target"]["start"]) * sample_rate))
        count = min(len(synthesized), len(mix) - start)
        if count > 0:
            mix[start:start + count] += synthesized[:count]
        phrase_reports.append(phrase_report)
        note_reports.extend(reports)
    note_reports.sort(key=lambda entry: entry[0])

    peak = float(np.max(np.abs(mix))) if len(mix) else 0
    normalization_warning = None
    if peak > 0.95:
        mix *= 0.95 / peak
        normalization_warning = f"Output peak was normalized from {peak:.3f} to 0.95."
    summary, verification_warnings = verify_audio(
        mix, request, sample_rate, frame_period, f0_floor, f0_ceil, note_reports,
    )
    global_warnings = verification_warnings
    if normalization_warning:
        global_warnings.append(normalization_warning)
        summary["warningCount"] += 1
    report = {
        "schemaVersion": 1, "engine": "WORLD", "source": request["source"], "output": request["output"],
        "generatedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "sampleRate": sample_rate, "duration": number(duration), "framePeriodMs": number(frame_period),
        "dependencies": {"numpy": np.__version__, "scipy": __import__("scipy").__version__, "pyworld": pyworld.__version__},
        "phrases": phrase_reports, "notes": [entry[1] for entry in note_reports],
        "summary": summary, "warnings": global_warnings,
    }

    output = Path(request["output"])
    report_path = Path(request["report"])
    temporary_output = output.with_name(f".{output.name}.{os.getpid()}.tmp.wav")
    temporary_report = report_path.with_name(f".{report_path.name}.{os.getpid()}.tmp.json")
    try:
        write_wav(temporary_output, mix, sample_rate)
        temporary_report.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        os.replace(temporary_output, output)
        os.replace(temporary_report, report_path)
    finally:
        for path in (temporary_output, temporary_report):
            try:
                path.unlink()
            except FileNotFoundError:
                pass
    return report


def main():
    try:
        request = json.load(sys.stdin)
        report = run(request)
        response = {"ok": True, "report": report}
        status = 0
    except WorkerFailure as failure:
        error = {"code": failure.code, "message": failure.message, "retryable": failure.retryable}
        if failure.diagnostics is not None:
            error["diagnostics"] = failure.diagnostics
        response = {"ok": False, "error": error}
        status = 1
    except Exception as failure:  # Keep CLI failures machine-readable without hiding the exception type.
        response = {"ok": False, "error": {
            "code": "AUTOTUNE_WORKER_FAILED", "message": str(failure),
            "diagnostics": {"exception": type(failure).__name__}, "retryable": False,
        }}
        status = 1
    sys.stdout.write(json.dumps(response, ensure_ascii=False, allow_nan=False) + "\n")
    return status


if __name__ == "__main__":
    sys.exit(main())
