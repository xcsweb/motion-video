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


class WorkerFailure(Exception):
    def __init__(self, code, message, diagnostics=None, retryable=False):
        super().__init__(message)
        self.code = code
        self.message = message
        self.diagnostics = diagnostics
        self.retryable = retryable


def load_dependencies():
    global np, pyworld, uniform_filter1d
    missing = []
    try:
        import numpy
        np = numpy
    except (ImportError, OSError):
        missing.append("numpy")
    try:
        from scipy.ndimage import uniform_filter1d as filter1d
        uniform_filter1d = filter1d
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


def source_vowel(note, f0, time_axis, energy, decode_start):
    if note["source"].get("vowelStart") is not None:
        return float(note["source"]["vowelStart"]), "provided", None
    start = float(note["source"]["start"])
    end = float(note["source"]["end"])
    absolute_times = time_axis + decode_start
    segment = (absolute_times >= start - 1e-6) & (absolute_times < end - 1e-6)
    voiced_energy = energy[segment & (f0 > 0)]
    threshold = max(1e-7, float(np.percentile(voiced_energy, 25)) * 0.35) if len(voiced_energy) else 1e-7
    candidates = np.flatnonzero(segment & (f0 > 0) & (energy >= threshold))
    for index in candidates:
        if np.count_nonzero(f0[index:index + 5] > 0) >= 3:
            return float(absolute_times[index]), "detected", None
    fallback = start + min(0.08, (end - start) * 0.25)
    return fallback, "fallback", "No stable voiced onset detected; used a source vowel fallback. Set source.vowelStart manually for precise control."


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
    source_min = max(0.0, min(float(note["source"]["start"]) for note in notes) - 0.08)
    source_max = max(float(note["source"]["end"]) for note in notes) + 0.12
    audio = decode_audio(request["source"], source_min, source_max, sample_rate)
    required_samples = int(math.ceil((max(float(note["source"]["end"]) for note in notes) - source_min) * sample_rate))
    if len(audio) < required_samples - int(0.02 * sample_rate):
        raise WorkerFailure(
            "AUTOTUNE_SOURCE_RANGE_INVALID", "A note source range exceeds the decodable source media duration",
            {"phraseId": phrase["id"], "sourceEnd": max(float(note["source"]["end"]) for note in notes),
             "decodedDuration": len(audio) / sample_rate, "decodeStart": source_min},
        )
    source_f0, source_times, spectral, aperiodicity, energy = analyze_source(
        audio, sample_rate, frame_period, f0_floor, f0_ceil,
    )
    if len(source_f0) < 2:
        raise WorkerFailure("AUTOTUNE_SOURCE_RANGE_INVALID", "Phrase source range has too few analysis frames",
                            {"phraseId": phrase["id"]})

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
    default_lead = float(request.get("consonantLeadMs", 25)) / 1000
    vibrato = request.get("vibrato")

    for note in notes:
        source_start = float(note["source"]["start"])
        source_end = float(note["source"]["end"])
        target_start = float(note["target"]["start"])
        target_duration = float(note["target"]["duration"])
        target_end = target_start + target_duration
        vowel_start, detection, warning = source_vowel(note, source_f0, source_times, energy, source_min)
        vowel_offset = note["target"].get("vowelOffset")
        if vowel_offset is None:
            vowel_offset = min(default_lead, target_duration * 0.25)
        target_vowel = target_start + float(vowel_offset)
        indices = np.flatnonzero((target_times >= target_start - 1e-9) & (target_times < target_end - 1e-9))
        local = target_times[indices]
        before = local < target_vowel - 1e-12
        mapped = np.empty(len(indices), dtype=np.float64)
        if target_vowel > target_start + 1e-12:
            mapped[before] = source_start + (local[before] - target_start) / (target_vowel - target_start) * (vowel_start - source_start)
        else:
            before[:] = False
        mapped[~before] = vowel_start + (local[~before] - target_vowel) / (target_end - target_vowel) * (source_end - vowel_start)
        source_positions_time[indices] = np.clip(mapped, source_start, source_end)
        target_frequency[indices] = midi_frequency(int(note["target"]["midi"]))
        if vibrato and float(vibrato.get("depthCents", 0)) > 0:
            elapsed = local - target_vowel
            delay = float(vibrato.get("delayMs", 160)) / 1000
            envelope = np.clip((elapsed - delay) / 0.24, 0, 1)
            vibrato_cents[indices] = (
                float(vibrato.get("depthCents", 0)) * envelope
                * np.sin(2 * np.pi * float(vibrato.get("rateHz", 5.2)) * np.maximum(elapsed, 0))
            )
        warnings = [warning] if warning else []
        note_reports.append((target_start, {
            "id": note["id"], "phraseId": phrase["id"], "text": note["text"],
            "targetMidi": int(note["target"]["midi"]),
            "targetFrequencyHz": number(midi_frequency(int(note["target"]["midi"]))),
            "sourceVowelStart": number(vowel_start), "sourceVowelDetection": detection,
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
            affected = (target_times >= start - 1e-9) & (target_times < min(end, start + portamento) - 1e-9)
            blend = np.clip((target_times[affected] - start) / portamento, 0, 1)
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
