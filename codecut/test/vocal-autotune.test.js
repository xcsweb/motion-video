import assert from 'node:assert/strict';
import { execFile, spawnSync } from 'node:child_process';
import { chmod, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import test from 'node:test';

const root = dirname(dirname(fileURLToPath(import.meta.url)));
const cliPath = join(root, 'dist', 'cli.js');
const require = createRequire(import.meta.url);
const Ajv2020 = require('ajv/dist/2020.js');
const addFormats = require('ajv-formats');
const pythonDependencies = spawnSync('python3', ['-c', 'import numpy, scipy, pyworld'], { stdio: 'ignore' }).status === 0;
const ffmpegAvailable = spawnSync('ffmpeg', ['-version'], { stdio: 'ignore' }).status === 0;

function cli(args, options = {}) {
  return new Promise((resolve, reject) => {
    execFile(process.execPath, [cliPath, ...args], {
      cwd: root,
      env: options.env ?? process.env,
      timeout: options.timeout ?? 120_000,
      maxBuffer: 32 * 1024 * 1024,
    }, (error, stdout, stderr) => {
      if (error && typeof error.code !== 'number') {
        reject(error);
        return;
      }
      resolve({ status: error?.code ?? 0, stdout, stderr });
    });
  });
}

async function temporaryDirectory(t) {
  const directory = await mkdtemp(join(tmpdir(), 'codecut-autotune-test-'));
  t.after(() => rm(directory, { recursive: true, force: true }));
  return directory;
}

function request() {
  return {
    schemaVersion: 1,
    source: 'source.wav',
    output: 'tuned.wav',
    report: 'tuned.report.json',
    sampleRate: 16000,
    framePeriodMs: 5,
    f0Floor: 70,
    f0Ceil: 500,
    consonantLeadMs: 25,
    portamentoMs: 35,
    duration: 1.2,
    phrases: [{
      id: 'phrase',
      notes: [
        { id: 'n1', text: '啊', source: { start: 0, end: 0.6 }, target: { start: 0, duration: 0.5, midi: 60 } },
        { id: 'n2', text: '哦', source: { start: 0.6, end: 1.2 }, target: { start: 0.5, duration: 0.5, midi: 64 } },
      ],
    }],
  };
}

async function writeRequest(directory, value = request()) {
  const path = join(directory, 'autotune.json');
  await writeFile(path, JSON.stringify(value), 'utf8');
  return path;
}

function syntheticWav() {
  const sampleRate = 16000;
  const samples = new Int16Array(sampleRate * 1.2);
  for (let index = 0; index < samples.length; index += 1) {
    const time = index / sampleRate;
    const local = time < 0.6 ? time : time - 0.6;
    const lead = time < 0.6 ? 0.06 : 0.04;
    if (local < lead || local >= 0.56) continue;
    const frequency = time < 0.6 ? 180 : 240;
    const phaseTime = local - lead;
    const envelope = Math.min(1, (local - lead) / 0.015, (0.56 - local) / 0.02);
    const value = 0.18 * envelope * (
      Math.sin(2 * Math.PI * frequency * phaseTime)
      + 0.32 * Math.sin(2 * Math.PI * frequency * 2 * phaseTime)
      + 0.14 * Math.sin(2 * Math.PI * frequency * 3 * phaseTime)
    );
    samples[index] = Math.round(value * 32767);
  }
  const buffer = Buffer.alloc(44 + samples.length * 2);
  buffer.write('RIFF', 0);
  buffer.writeUInt32LE(36 + samples.length * 2, 4);
  buffer.write('WAVEfmt ', 8);
  buffer.writeUInt32LE(16, 16);
  buffer.writeUInt16LE(1, 20);
  buffer.writeUInt16LE(1, 22);
  buffer.writeUInt32LE(sampleRate, 24);
  buffer.writeUInt32LE(sampleRate * 2, 28);
  buffer.writeUInt16LE(2, 32);
  buffer.writeUInt16LE(16, 34);
  buffer.write('data', 36);
  buffer.writeUInt32LE(samples.length * 2, 40);
  Buffer.from(samples.buffer).copy(buffer, 44);
  return buffer;
}

function misalignedSyntheticWav() {
  const sampleRate = 16000;
  const duration = 2.3;
  const samples = new Int16Array(sampleRate * duration);
  const syllables = [
    { onset: 0.10, frequency: 180 },
    { onset: 0.72, frequency: 210 },
    { onset: 1.25, frequency: 240 },
    { onset: 1.75, frequency: 200 },
  ];
  for (let index = 0; index < samples.length; index += 1) {
    const time = index / sampleRate;
    let value = 0;
    for (const syllable of syllables) {
      const local = time - syllable.onset;
      const length = 0.46;
      if (local < 0 || local >= length) continue;
      const envelope = local < 0.14 ? local / 0.14 : (length - local) / (length - 0.14);
      value += 0.16 * envelope * (
        Math.sin(2 * Math.PI * syllable.frequency * local)
        + 0.3 * Math.sin(2 * Math.PI * syllable.frequency * 2 * local)
        + 0.12 * Math.sin(2 * Math.PI * syllable.frequency * 3 * local)
      );
    }
    samples[index] = Math.round(Math.max(-1, Math.min(1, value)) * 32767);
  }
  const buffer = Buffer.alloc(44 + samples.length * 2);
  buffer.write('RIFF', 0);
  buffer.writeUInt32LE(36 + samples.length * 2, 4);
  buffer.write('WAVEfmt ', 8);
  buffer.writeUInt32LE(16, 16);
  buffer.writeUInt16LE(1, 20);
  buffer.writeUInt16LE(1, 22);
  buffer.writeUInt32LE(sampleRate, 24);
  buffer.writeUInt32LE(sampleRate * 2, 28);
  buffer.writeUInt16LE(2, 32);
  buffer.writeUInt16LE(16, 34);
  buffer.write('data', 36);
  buffer.writeUInt32LE(samples.length * 2, 40);
  Buffer.from(samples.buffer).copy(buffer, 44);
  return buffer;
}

test('autotune schemas and capabilities are exposed and compilable', async () => {
  const schemas = JSON.parse((await cli(['schema', '--json'])).stdout);
  const ajv = new Ajv2020({ allErrors: true, strict: true });
  addFormats(ajv);
  assert.ok(ajv.compile(schemas.vocalAutotuneRequest));
  assert.ok(ajv.compile(schemas.vocalAutotuneReport));
  const capabilities = JSON.parse((await cli(['capabilities', '--json'])).stdout).capabilities;
  assert.ok(capabilities.commands.available.includes('vocal autotune'));
  assert.deepEqual(capabilities.vocal.autotune.dependencies, ['python3', 'numpy', 'scipy', 'pyworld', 'ffmpeg']);
});

test('invalid MIDI, source ranges, and phrase gaps produce structured validation errors', async (t) => {
  const directory = await temporaryDirectory(t);
  const invalidMidi = request();
  invalidMidi.phrases[0].notes[0].target.midi = 128;
  let result = await cli(['vocal', 'autotune', await writeRequest(directory, invalidMidi), '--json']);
  assert.equal(result.status, 3);
  assert.equal(result.stdout, '');
  assert.equal(JSON.parse(result.stderr).error.code, 'AUTOTUNE_REQUEST_INVALID');
  assert.equal(JSON.parse(result.stderr).error.diagnostics.issues[0].path, '/phrases/0/notes/0/target/midi');

  const invalidRange = request();
  invalidRange.phrases[0].notes[0].source.end = 0;
  result = await cli(['vocal', 'autotune', await writeRequest(directory, invalidRange), '--json']);
  assert.equal(result.status, 3);
  assert.equal(JSON.parse(result.stderr).error.diagnostics.issues[0].path, '/phrases/0/notes/0/source/end');

  const gap = request();
  gap.phrases[0].notes[1].target.start = 0.55;
  result = await cli(['vocal', 'autotune', await writeRequest(directory, gap), '--json']);
  assert.equal(result.status, 3);
  assert.match(JSON.parse(result.stderr).error.diagnostics.issues[0].message, /contiguous/);
});

test('missing Python and worker dependency failures stay machine-readable', async (t) => {
  const directory = await temporaryDirectory(t);
  await writeFile(join(directory, 'source.wav'), syntheticWav());
  const path = await writeRequest(directory);
  const missing = await cli(['vocal', 'autotune', path, '--python', join(directory, 'missing-python'), '--json']);
  assert.equal(missing.status, 4);
  assert.equal(missing.stdout, '');
  assert.equal(JSON.parse(missing.stderr).error.code, 'AUTOTUNE_PYTHON_NOT_FOUND');

  const fakePython = join(directory, 'fake-python');
  await writeFile(fakePython, `#!/bin/sh\nprintf '%s\\n' '{"ok":false,"error":{"code":"AUTOTUNE_DEPENDENCIES_MISSING","message":"pyworld is missing","diagnostics":{"missing":["pyworld"]}}}'\nexit 1\n`, { mode: 0o755 });
  await chmod(fakePython, 0o755);
  const dependencies = await cli(['vocal', 'autotune', path, '--python', fakePython, '--json']);
  assert.equal(dependencies.status, 4);
  assert.equal(JSON.parse(dependencies.stderr).error.code, 'AUTOTUNE_DEPENDENCIES_MISSING');
  assert.deepEqual(JSON.parse(dependencies.stderr).error.diagnostics.missing, ['pyworld']);
});

test('existing outputs require --force before media processing starts', async (t) => {
  const directory = await temporaryDirectory(t);
  await writeFile(join(directory, 'source.wav'), syntheticWav());
  await writeFile(join(directory, 'tuned.wav'), 'do not replace', 'utf8');
  const path = await writeRequest(directory);
  const result = await cli(['vocal', 'autotune', path, '--json']);
  assert.equal(result.status, 2);
  assert.equal(JSON.parse(result.stderr).error.code, 'AUTOTUNE_OUTPUT_EXISTS');
  assert.equal(await readFile(join(directory, 'tuned.wav'), 'utf8'), 'do not replace');
});

test('WORLD autotune writes an exact-duration WAV and verified per-note report', {
  skip: (!pythonDependencies || !ffmpegAvailable) && 'python numpy/scipy/pyworld and ffmpeg are required',
  timeout: 180_000,
}, async (t) => {
  const directory = await temporaryDirectory(t);
  await writeFile(join(directory, 'source.wav'), syntheticWav());
  const path = await writeRequest(directory);
  const result = await cli(['vocal', 'autotune', path, '--json'], { timeout: 170_000 });
  assert.equal(result.status, 0, result.stderr);
  assert.equal(result.stderr, '');
  const value = JSON.parse(result.stdout);
  assert.equal(value.command, 'vocal.autotune');
  assert.equal(value.report.schemaVersion, 1);
  assert.equal(value.report.engine, 'WORLD');
  assert.equal(value.report.summary.noteCount, 2);
  assert.ok(value.report.summary.reliablePitchNoteCount >= 1);
  assert.ok(value.report.summary.medianAbsoluteCentsError < 80);
  assert.equal(value.report.notes[0].targetVowelStart, 0.025);
  assert.equal(value.report.notes[1].targetVowelStart, 0.525);
  assert.ok(value.report.notes.every((note) => note.measurement), JSON.stringify(value.report, null, 2));
  assert.deepEqual(JSON.parse(await readFile(value.reportPath, 'utf8')), value.report);

  const wav = await readFile(value.outputPath);
  assert.equal(wav.toString('ascii', 0, 4), 'RIFF');
  assert.equal(wav.readUInt16LE(22), 1);
  assert.equal(wav.readUInt32LE(24), 16000);
  assert.ok(Math.abs(wav.readUInt32LE(40) / 2 / 16000 - 1.2) <= 1 / 16000);
});

test('ordered vowel alignment escapes bad timestamps and preserves manual anchors', {
  skip: (!pythonDependencies || !ffmpegAvailable) && 'python numpy/scipy/pyworld and ffmpeg are required',
  timeout: 180_000,
}, async (t) => {
  const directory = await temporaryDirectory(t);
  await writeFile(join(directory, 'source.wav'), misalignedSyntheticWav());
  const value = request();
  value.duration = 1.6;
  value.phrases[0].notes = [
    { id: 'n1', text: '一', source: { start: 0, end: 0.45 }, target: { start: 0, duration: 0.4, midi: 60 } },
    { id: 'n2', text: '二', source: { start: 0.45, end: 0.65 }, target: { start: 0.4, duration: 0.4, midi: 62 } },
    { id: 'n3', text: '三', source: { start: 0.65, end: 1.10 }, target: { start: 0.8, duration: 0.4, midi: 64 } },
    { id: 'n4', text: '四', source: { start: 1.30, end: 2.10, vowelStart: 1.75 }, target: { start: 1.2, duration: 0.4, midi: 65 } },
  ];
  const path = await writeRequest(directory, value);
  const result = await cli(['vocal', 'autotune', path, '--json'], { timeout: 170_000 });
  assert.equal(result.status, 0, result.stderr);
  const report = JSON.parse(result.stdout).report;
  assert.deepEqual(report.notes.slice(0, 3).map((note) => note.sourceVowelDetection), ['detected', 'detected', 'detected']);
  assert.ok(report.notes[1].sourceVowelStart > 0.68, JSON.stringify(report.notes, null, 2));
  assert.ok(report.notes[1].sourceVowelStart < 1.10);
  assert.ok(report.notes[2].sourceVowelStart > 1.18);
  assert.ok(report.notes[2].sourceVowelStart < 1.65);
  assert.ok(report.notes[0].sourceVowelStart < report.notes[1].sourceVowelStart);
  assert.ok(report.notes[1].sourceVowelStart < report.notes[2].sourceVowelStart);
  assert.equal(report.notes[3].sourceVowelStart, 1.75);
  assert.equal(report.notes[3].sourceVowelDetection, 'provided');
});
