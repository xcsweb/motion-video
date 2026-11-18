import assert from 'node:assert/strict';
import { mkdtemp, readFile, rm, stat } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { spawnSync } from 'node:child_process';
import test from 'node:test';
import {
  BoundedLogTail,
  executeControlledProcess,
  FfmpegProgressParser,
  ProcessController,
} from '../dist/process.js';

async function temporaryDirectory(t) {
  const directory = await mkdtemp(join(tmpdir(), 'codecut-process-test-'));
  t.after(() => rm(directory, { recursive: true, force: true }));
  return directory;
}

function nodeSpec(source, args = [], extra = {}) {
  return { command: process.execPath, args: ['-e', source, ...args], ...extra };
}

async function waitForLog(path, text) {
  for (let attempt = 0; attempt < 200; attempt += 1) {
    const output = await readFile(path, 'utf8').catch((error) => {
      if (error.code === 'ENOENT') return '';
      throw error;
    });
    if (output.includes(text)) return;
    await new Promise((resolve) => setTimeout(resolve, 10));
  }
  throw new Error('Child did not become ready');
}

test('FFmpeg progress parses frame, time, speed and end with stable validation errors', () => {
  const parser = new FfmpegProgressParser(4);
  assert.equal(parser.pushLine('frame=24'), undefined);
  parser.pushLine('out_time_us=2000000');
  parser.pushLine('speed=1.25x');
  assert.deepEqual(parser.pushLine('progress=continue'), {
    percent: 50, frame: 24, timeSeconds: 2, speed: 1.25, end: false,
  });
  parser.pushLine('speed=   0x');
  assert.equal(parser.state.speed, 0);
  parser.pushLine('out_time=00:00:04.000000');
  assert.equal(parser.pushLine('progress=end').percent, 100);
  assert.equal(parser.state.end, true);

  for (const line of ['not-progress', 'frame=NaN', 'out_time=bad', 'speed=fast', 'progress=done']) {
    const invalid = new FfmpegProgressParser();
    assert.throws(() => invalid.pushLine(line), (error) => {
      assert.equal(error.code, 'FFMPEG_PROGRESS_INVALID');
      assert.equal(error.stage, 'ffmpeg.progress');
      return true;
    });
  }
  assert.throws(() => new FfmpegProgressParser().finish(), /progress=end/);
});

test('FFmpeg N/A fields preserve the last valid progress values', () => {
  const parser = new FfmpegProgressParser(4);
  parser.pushLine('frame=24');
  parser.pushLine('out_time_us=2000000');
  parser.pushLine('speed=1.25x');
  parser.pushLine('progress=continue');
  parser.pushLine('frame=N/A');
  parser.pushLine('out_time_us=N/A');
  parser.pushLine('out_time_ms=N/A');
  parser.pushLine('out_time=N/A');
  parser.pushLine('speed=N/A');
  assert.deepEqual(parser.pushLine('progress=continue'), {
    percent: 50, frame: 24, timeSeconds: 2, speed: 1.25, end: false,
  });
});

test('stdout and stderr flood is fully persisted while memory tails stay bounded', async (t) => {
  const directory = await temporaryDirectory(t);
  const source = `
    const chunk = 'x'.repeat(8192) + '\\n';
    for (let i = 0; i < 160; i++) process.stdout.write(chunk);
    const error = 'e'.repeat(4096) + '\\n';
    for (let i = 0; i < 80; i++) process.stderr.write(error);
  `;
  const result = await executeControlledProcess({
    spec: nodeSpec(source), logDirectory: directory, tailBytes: 1024,
  });
  assert.equal(result.exitCode, 0);
  assert.ok((await stat(result.logs.stdout)).size >= 160 * 8193);
  assert.ok((await stat(result.logs.stderr)).size >= 80 * 4097);
  assert.ok(result.tails.stdout.length < 1200);
  assert.ok(result.tails.stderr.length < 1200);
  assert.match(result.tails.stdout, /truncated/);
  assert.match(result.tails.stderr, /truncated/);
  assert.ok((await readFile(result.logs.stdout, 'utf8')).startsWith('xxxx'));
  const tail = new BoundedLogTail(10);
  tail.append('123456789012345');
  assert.match(tail.toString(), /truncated/);
  assert.ok(tail.toString().endsWith('6789012345'));
});

test('startup, media exit and malformed progress failures remain distinct', async (t) => {
  const directory = await temporaryDirectory(t);
  await assert.rejects(executeControlledProcess({
    spec: { command: join(directory, 'missing-executable'), args: [] },
    logDirectory: directory,
  }), (error) => {
    assert.equal(error.code, 'PROCESS_START_FAILED');
    assert.equal(error.stage, 'process.spawn');
    return true;
  });
  await assert.rejects(executeControlledProcess({
    spec: nodeSpec("process.stderr.write('bad media'); process.exit(23)"),
    logDirectory: directory,
  }), (error) => {
    assert.equal(error.code, 'MEDIA_PROCESS_FAILED');
    assert.equal(error.diagnostics.exitCode, 23);
    assert.match(error.diagnostics.stderrTail, /bad media/);
    return true;
  });
  await assert.rejects(executeControlledProcess({
    spec: nodeSpec("process.stdout.write('frame=invalid\\nprogress=end\\n')", [], { progress: 'ffmpeg' }),
    logDirectory: directory,
  }), (error) => {
    assert.equal(error.code, 'FFMPEG_PROGRESS_INVALID');
    return true;
  });
});

test('cancellation and timeout terminate, force-kill after grace, and wait for exit', async (t) => {
  const directory = await temporaryDirectory(t);
  const ignoringTerm = "process.on('SIGTERM', () => {}); process.stdout.write('ready\\n'); setInterval(() => {}, 1000)";
  const controller = new ProcessController();
  const cancelling = executeControlledProcess({
    spec: nodeSpec(ignoringTerm),
    logDirectory: directory,
    controller,
    gracePeriodMs: 40,
  });
  await waitForLog(join(directory, 'stdout.log'), 'ready');
  controller.stop('cancelled');
  const cancelled = await cancelling;
  assert.equal(cancelled.stopReason, 'cancelled');
  assert.equal(cancelled.forcefullyTerminated, true);
  assert.equal(cancelled.signal, 'SIGKILL');
  assert.throws(() => process.kill(cancelled.pid, 0), (error) => error.code === 'ESRCH');

  const timedOut = await executeControlledProcess({
    spec: nodeSpec(ignoringTerm),
    logDirectory: directory,
    timeoutMs: 40,
    gracePeriodMs: 40,
    onSpawn: () => waitForLog(join(directory, 'stdout.log'), 'ready'),
  });
  assert.equal(timedOut.stopReason, 'timedOut');
  assert.equal(timedOut.forcefullyTerminated, true);
  assert.equal(timedOut.signal, 'SIGKILL');
  assert.throws(() => process.kill(timedOut.pid, 0), (error) => error.code === 'ESRCH');
});

test('real FFmpeg emits separated machine progress and a valid small output', { skip: spawnSync('ffmpeg', ['-version']).status !== 0 }, async (t) => {
  const directory = await temporaryDirectory(t);
  const output = join(directory, 'tiny.mp4');
  const result = await executeControlledProcess({
    spec: {
      command: 'ffmpeg',
      args: [
        '-hide_banner', '-loglevel', 'error', '-f', 'lavfi', '-i', 'color=c=black:s=32x32:r=10',
        '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000', '-t', '0.3',
        '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-progress', 'pipe:1', '-nostats', '-y', output,
      ],
      progress: 'ffmpeg',
      durationSeconds: 0.3,
    },
    logDirectory: directory,
    timeoutMs: 20_000,
  });
  assert.equal(result.progress.end, true);
  assert.equal(result.progress.percent, 100);
  assert.ok(result.progress.frame > 0);
  assert.ok(result.progress.timeSeconds >= 0);
  assert.match(await readFile(result.logs.progress, 'utf8'), /progress=end/);
  assert.match(await readFile(result.logs.progressEvents, 'utf8'), /"end":true/);
  assert.ok((await stat(output)).size > 0);
});
