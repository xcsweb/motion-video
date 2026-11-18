import assert from 'node:assert/strict';
import { execFile } from 'node:child_process';
import { mkdtemp, readFile, readdir, rm, stat, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import test from 'node:test';
import { addAsset } from '../dist/assets.js';
import { applyEdit } from '../dist/edit.js';
import { listHistory } from '../dist/history.js';
import { JobService } from '../dist/jobs.js';
import { initProject } from '../dist/project.js';
import { previewProject } from '../dist/preview.js';
import { renderProject } from '../dist/render.js';

const root = dirname(dirname(fileURLToPath(import.meta.url)));
const cliPath = join(root, 'dist', 'cli.js');
const sleep = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds));

function execute(command, args, options = {}) {
  return new Promise((resolve, reject) => {
    execFile(command, args, {
      encoding: options.buffer ? 'buffer' : 'utf8',
      maxBuffer: 16 * 1024 * 1024,
      ...options,
    }, (error, stdout, stderr) => {
      if (error) reject(new Error(`${command} failed: ${stderr || error.message}`));
      else resolve({ stdout, stderr });
    });
  });
}

function cli(args) {
  return new Promise((resolve, reject) => {
    execFile(process.execPath, [cliPath, ...args], { cwd: root, maxBuffer: 16 * 1024 * 1024 }, (error, stdout, stderr) => {
      if (error && typeof error.code !== 'number') reject(error);
      else resolve({ status: error?.code ?? 0, stdout, stderr });
    });
  });
}

async function temporaryDirectory(t, prefix = 'codecut-preview-test-') {
  const directory = await mkdtemp(join(tmpdir(), prefix));
  t.after(() => rm(directory, { recursive: true, force: true }));
  return directory;
}

async function configureProject(directory, durationOutput = 'formal.mp4') {
  await initProject(directory);
  const path = join(directory, 'project.json');
  const project = JSON.parse(await readFile(path, 'utf8'));
  Object.assign(project.output, { path: durationOutput, width: 64, height: 64, frameRate: 8 });
  await writeFile(path, `${JSON.stringify(project, null, 2)}\n`, 'utf8');
  return path;
}

async function createSources(directory) {
  const visual = join(directory, 'visual.mp4');
  await execute('ffmpeg', [
    '-v', 'error', '-y',
    '-f', 'lavfi', '-i', 'color=c=red:s=64x64:r=8:d=1',
    '-f', 'lavfi', '-i', 'color=c=green:s=64x64:r=8:d=1',
    '-f', 'lavfi', '-i', 'color=c=blue:s=64x64:r=8:d=1',
    '-f', 'lavfi', '-i', 'color=c=yellow:s=64x64:r=8:d=1',
    '-filter_complex', '[0:v][1:v][2:v][3:v]concat=n=4:v=1:a=0[v]',
    '-map', '[v]', '-c:v', 'libx264', '-preset', 'ultrafast', '-pix_fmt', 'yuv420p', visual,
  ]);
  const low = join(directory, 'low.wav');
  const high = join(directory, 'high.wav');
  await execute('ffmpeg', ['-v', 'error', '-y', '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000:duration=2', '-c:a', 'pcm_s16le', low]);
  await execute('ffmpeg', ['-v', 'error', '-y', '-f', 'lavfi', '-i', 'sine=frequency=880:sample_rate=48000:duration=2', '-c:a', 'pcm_s16le', high]);
  return { visual, low, high };
}

async function buildTimeline(project, sources) {
  for (const [id, path] of Object.entries(sources)) await addAsset(project, { id, path });
  const edited = await applyEdit(project, [
    { type: 'addTrack', track: { id: 'v3', kind: 'video', clips: [] } },
    { type: 'addTrack', track: { id: 'v4', kind: 'video', clips: [] } },
    { type: 'addClip', trackId: 'v1', clip: { id: 'red', type: 'video', assetId: 'visual', start: 0, duration: 1, sourceStart: 0 } },
    { type: 'addClip', trackId: 'v1', clip: { id: 'green-blue', type: 'video', assetId: 'visual', start: 0.75, duration: 1.25, sourceStart: 1, transition: { type: 'xfade', duration: 0.25, name: 'fade' } } },
    { type: 'addClip', trackId: 'v2', clip: { id: 'wash', type: 'color', color: '#FFFF0040', start: 0, duration: 2, opacity: 0.5 } },
    { type: 'addText', trackId: 'v3', clip: { id: 'title', type: 'text', text: 'TIMELINE', fontSize: 12, color: '#FFFFFF', start: 0.5, duration: 1.5 } },
    { type: 'addClip', trackId: 'v4', clip: { id: 'fast-overlay', type: 'video', assetId: 'visual', start: 1, duration: 0.5, sourceStart: 3, speed: 2, scale: 0.5, position: { x: 32, y: 32 }, opacity: 0.5 } },
    { type: 'addClip', trackId: 'a1', clip: { id: 'low', type: 'audio', assetId: 'low', start: 0, duration: 2, volume: 0.3 } },
    { type: 'addClip', trackId: 'a2', clip: { id: 'high', type: 'audio', assetId: 'high', start: 0.5, duration: 1, speed: 2, volume: 0.3 } },
  ], { summary: 'Build timeline preview fixture' });
  return edited.project.revision;
}

async function rawFrame(path, width, height, at) {
  const args = ['-v', 'error'];
  if (at !== undefined) args.push('-ss', String(at));
  args.push('-i', path, '-frames:v', '1', '-f', 'rawvideo', '-pix_fmt', 'rgba', '-');
  const { stdout } = await execute('ffmpeg', args, { buffer: true });
  assert.equal(stdout.length, width * height * 4);
  return stdout;
}

function assertApproximatePixels(actual, expected) {
  let sum = 0;
  let within12 = 0;
  let channels = 0;
  for (let index = 0; index < actual.length; index += 1) {
    if (index % 4 === 3) continue;
    const difference = Math.abs(actual[index] - expected[index]);
    sum += difference;
    if (difference <= 12) within12 += 1;
    channels += 1;
  }
  const mean = sum / channels;
  const ratio = within12 / channels;
  assert.ok(mean <= 4, `mean RGB channel error ${mean} should be <= 4`);
  assert.ok(ratio >= 0.98, `${(ratio * 100).toFixed(2)}% channels within 12 should be >= 98%`);
  return { mean, ratio };
}

async function probe(path) {
  const { stdout } = await execute('ffprobe', ['-v', 'error', '-show_streams', '-show_format', '-of', 'json', path]);
  return JSON.parse(stdout);
}

async function pcm(path, start, duration = 0.08) {
  const { stdout } = await execute('ffmpeg', [
    '-v', 'error', '-ss', String(start), '-t', String(duration), '-i', path,
    '-map', '0:a:0', '-ac', '1', '-ar', '48000', '-f', 'f32le', '-',
  ], { buffer: true });
  return new Float32Array(stdout.buffer, stdout.byteOffset, Math.floor(stdout.length / 4));
}

function amplitude(samples, frequency, sampleRate = 48000) {
  let real = 0;
  let imaginary = 0;
  for (let index = 0; index < samples.length; index += 1) {
    const angle = 2 * Math.PI * frequency * index / sampleRate;
    real += samples[index] * Math.cos(angle);
    imaginary -= samples[index] * Math.sin(angle);
  }
  return 2 * Math.hypot(real, imaginary) / samples.length;
}

function timecodeSignature(sheet, sheetWidth, column) {
  const originX = 8 + column * 68;
  const originY = 8;
  let signature = '';
  let whitePixels = 0;
  for (let y = 4; y < 25; y += 1) {
    for (let x = 0; x < 64; x += 1) {
      const offset = ((originY + y) * sheetWidth + originX + x) * 4;
      const white = sheet[offset] > 180 && sheet[offset + 1] > 180 && sheet[offset + 2] > 180;
      signature += white ? '1' : '0';
      if (white) whitePixels += 1;
    }
  }
  assert.ok(whitePixels > 10, `cell ${column} should contain a rendered timecode`);
  return signature;
}

async function waitForStatus(service, id, wanted, timeout = 10_000) {
  const deadline = Date.now() + timeout;
  for (;;) {
    const job = await service.get(id);
    if (wanted.includes(job.status)) return job;
    if (['succeeded', 'failed', 'cancelled', 'timedOut', 'interrupted'].includes(job.status)) {
      assert.fail(`Job reached ${job.status}: ${JSON.stringify(job.error)}`);
    }
    if (Date.now() > deadline) assert.fail(`Timed out waiting for ${wanted}; last=${job.status}/${job.stage}`);
    await sleep(20);
  }
}

test('timeline previews match formal composition, sampling plan, complete audio, diagnostics, and immutable revision', { timeout: 120_000 }, async (t) => {
  const directory = await temporaryDirectory(t);
  const project = join(directory, 'project');
  const projectPath = await configureProject(project);
  const sources = await createSources(project);
  const revision = await buildTimeline(project, sources);
  const service = new JobService({ projectDirectory: project, pollMs: 20, gracePeriodMs: 50 });

  const beforeDry = await readdir(project, { recursive: true });
  const dry = await previewProject(project, { type: 'frame', at: 1.25 }, { revision, dryRun: true }, service);
  assert.equal(dry.dryRun, true);
  assert.equal(dry.job, undefined);
  assert.match(dry.preview.outputPath, /\.codecut[\/\\]previews[\/\\]frame-r\d+-t1\.250\.png$/);
  assert.deepEqual(await readdir(project, { recursive: true }), beforeDry);

  const rendered = await renderProject(project, { revision }, service);
  assert.equal(rendered.job.status, 'succeeded', JSON.stringify(rendered.job.error));
  const frame = await previewProject(project, { type: 'frame', at: 1.25, output: 'frame.png' }, { revision }, service);
  assert.equal(frame.job.status, 'succeeded', JSON.stringify({ error: frame.job.error, stderr: frame.job.logTail?.stderr }));
  assert.equal(frame.job.kind, 'preview.frame');
  assert.equal(frame.job.projectRevision, revision);
  assert.equal(frame.job.preview.type, 'frame');
  assert.equal(frame.job.preview.parameters.at, 1.25);
  assert.equal(frame.job.validation.completeDecode, true);
  assert.equal(frame.job.validation.timelineTimeSeconds, 1.25);
  assert.match(frame.plan.filter_graph, /xfade=transition=fade/);
  assert.match(frame.plan.filter_graph, /drawtext=/);
  assert.match(frame.plan.filter_graph, /atempo=2/);
  assert.match(frame.plan.filter_graph, /amix=inputs=/);
  assert.ok(!frame.plan.args.includes('-ss'));

  const formalPixels = await rawFrame(join(project, 'formal.mp4'), 64, 64, 1.25);
  const previewPixels = await rawFrame(join(project, 'frame.png'), 64, 64);
  const comparison = assertApproximatePixels(previewPixels, formalPixels);
  assert.ok(comparison.mean < 1, `PNG and CRF18 representative frame should be nearly identical: ${comparison.mean}`);

  const sheet = await previewProject(project, {
    type: 'sheet', start: 0.25, end: 1.75, interval: 0.5, columns: 3, rows: 1, width: 64, height: 64, output: 'sheet.png',
  }, { revision }, service);
  assert.equal(sheet.job.status, 'succeeded', JSON.stringify({ error: sheet.job.error, stderr: sheet.job.logTail?.stderr }));
  assert.deepEqual(sheet.job.preview.parameters.sampleTimes, [0.25, 0.75, 1.25]);
  assert.equal(sheet.job.validation.sampleCount, 3);
  assert.equal(sheet.job.validation.timecodeBase, 'timeline');
  assert.equal(sheet.job.validation.width, 216);
  assert.equal(sheet.job.validation.height, 80);
  assert.match(sheet.plan.filter_graph, /setpts=PTS\+0\.25\/TB,drawtext/);
  const sheetProbe = await probe(join(project, 'sheet.png'));
  assert.equal(sheetProbe.streams[0].width, 216);
  assert.equal(sheetProbe.streams[0].height, 80);
  const sheetPixels = await rawFrame(join(project, 'sheet.png'), 216, 80);
  const signatures = [0, 1, 2].map((column) => timecodeSignature(sheetPixels, 216, column));
  assert.equal(new Set(signatures).size, 3, 'timecode pixels must change at each timeline sample');

  const proxy = await previewProject(project, {
    type: 'proxy', width: 32, height: 32, crf: 35, audioBitrateKbps: 64, output: 'proxy.mp4',
  }, { revision }, service);
  assert.equal(proxy.job.status, 'succeeded', JSON.stringify({ error: proxy.job.error, stderr: proxy.job.logTail?.stderr }));
  assert.equal(proxy.job.validation.type, 'preview.proxy');
  assert.equal(proxy.job.validation.completeDecode, true);
  assert.equal(proxy.job.validation.completeAudio, true);
  assert.equal(proxy.job.validation.video.width, 32);
  assert.equal(proxy.job.validation.video.height, 32);
  assert.equal(proxy.job.validation.audio.codec_name, 'aac');
  assert.equal(proxy.job.validation.audio.sample_rate, '48000');
  assert.equal(proxy.job.validation.audio.channels, 2);
  const proxyProbe = await probe(join(project, 'proxy.mp4'));
  assert.ok(Math.abs(Number(proxyProbe.format.duration) - 2) <= 0.125);
  const mixed = await pcm(join(project, 'proxy.mp4'), 0.72);
  assert.ok(amplitude(mixed, 440) > 0.005, 'proxy must preserve the first audio track');
  assert.ok(amplitude(mixed, 880) > 0.005, 'proxy must preserve the sped second audio track');

  const history = await listHistory(project);
  assert.equal(history.revisions.at(-1).projectRevision, revision);
  assert.equal(JSON.parse(await readFile(projectPath, 'utf8')).revision, revision);
  for (const job of [frame.job, sheet.job, proxy.job]) {
    const shown = await service.show(job.id);
    assert.equal(shown.preview.type, job.preview.type);
    assert.equal(shown.outputPath, job.outputPath);
    assert.deepEqual(shown.preview.parameters, job.preview.parameters);
    assert.equal(shown.validation.completeDecode, true);
    assert.ok(shown.result.data.parameters);
  }

  const beforeConflict = await stat(join(project, 'frame.png'));
  const conflict = await previewProject(project, { type: 'frame', at: 1.25, output: 'frame.png' }, { revision }, service);
  assert.equal(conflict.job.status, 'failed');
  assert.equal(conflict.job.error.code, 'OUTPUT_EXISTS');
  assert.equal((await stat(join(project, 'frame.png'))).ino, beforeConflict.ino);
  const forced = await previewProject(project, { type: 'frame', at: 1.25, output: 'frame.png', force: true }, { revision }, service);
  assert.equal(forced.job.status, 'succeeded', JSON.stringify(forced.job.error));
  assert.notEqual((await stat(join(project, 'frame.png'))).ino, beforeConflict.ino);
  const retried = await service.retry(forced.job.id);
  assert.equal(retried.status, 'succeeded', JSON.stringify(retried.error));
  assert.equal(retried.retryOf, forced.job.id);
  assert.equal(retried.kind, 'preview.frame');

  const shown = await cli(['jobs', 'show', sheet.job.id, '--project', project, '--json']);
  assert.equal(shown.status, 0, shown.stderr);
  const shownSheet = JSON.parse(shown.stdout).job;
  assert.equal(shownSheet.kind, 'preview.sheet');
  assert.deepEqual(shownSheet.preview.parameters.sampleTimes, [0.25, 0.75, 1.25]);
  assert.equal(shownSheet.validation.sampleCount, 3);
  const schema = await cli(['schema', '--json']);
  assert.ok(JSON.parse(schema.stdout).timelinePreviewRequest);
  assert.ok(JSON.parse(schema.stdout).timelinePreviewResult);
  const capabilities = await cli(['capabilities', '--json']);
  assert.ok(JSON.parse(capabilities.stdout).capabilities.commands.available.includes('preview frame/sheet/proxy'));
});

test('timeline preview validates time, range, density, dimensions, encoding, empty timelines, and dry-run writes', { timeout: 60_000 }, async (t) => {
  const directory = await temporaryDirectory(t);
  const empty = join(directory, 'empty');
  await configureProject(empty);
  await assert.rejects(previewProject(empty, { type: 'frame' }, { dryRun: true }), (error) => error.code === 'TIMELINE_EMPTY');

  const project = join(directory, 'project');
  await configureProject(project);
  await applyEdit(project, [{ type: 'addClip', trackId: 'v1', clip: { id: 'color', type: 'color', color: '#204060', start: 0, duration: 2 } }]);
  const service = new JobService(project);
  const invalidRequests = [
    [{ type: 'frame', at: -1 }, 'PREVIEW_TIME_INVALID'],
    [{ type: 'frame', at: 2 }, 'PREVIEW_TIME_INVALID'],
    [{ type: 'frame', width: 15 }, 'PREVIEW_SIZE_INVALID'],
    [{ type: 'frame', width: 33 }, 'PREVIEW_SIZE_INVALID'],
    [{ type: 'sheet', start: 1, end: 1 }, 'PREVIEW_RANGE_INVALID'],
    [{ type: 'sheet', start: 0, end: 3 }, 'PREVIEW_RANGE_INVALID'],
    [{ type: 'sheet', interval: 0 }, 'PREVIEW_INTERVAL_INVALID'],
    [{ type: 'sheet', interval: 0.001 }, 'PREVIEW_SHEET_DENSITY_INVALID'],
    [{ type: 'sheet', interval: 0.25, columns: 2, rows: 2 }, 'PREVIEW_SHEET_DENSITY_INVALID'],
    [{ type: 'sheet', columns: 0 }, 'PREVIEW_SHEET_LAYOUT_INVALID'],
    [{ type: 'proxy', crf: 52 }, 'PREVIEW_PROXY_ENCODING_INVALID'],
    [{ type: 'proxy', crf: 30, videoBitrateKbps: 100 }, 'PREVIEW_PROXY_ENCODING_INVALID'],
  ];
  for (const [request, code] of invalidRequests) {
    await assert.rejects(previewProject(project, request, { dryRun: true }, service), (error) => {
      assert.equal(error.code, code);
      assert.equal(error.stage, `preview.${request.type}.plan`);
      return true;
    });
  }
  assert.deepEqual(await service.list(), []);
  await assert.rejects(stat(join(project, '.codecut', 'previews')), { code: 'ENOENT' });
});

test('detached timeline proxy cancel, retry, timeout, and forced output preservation use normal job controls', { timeout: 90_000 }, async (t) => {
  const directory = await temporaryDirectory(t);
  const project = join(directory, 'project');
  await configureProject(project);
  await applyEdit(project, [{ type: 'addClip', trackId: 'v1', clip: { id: 'long', type: 'color', color: '#204060', start: 0, duration: 120 } }]);
  const output = join(project, 'cancel.mp4');
  await writeFile(output, 'original-output');
  const service = new JobService({ projectDirectory: project, pollMs: 20, gracePeriodMs: 50, heartbeatMs: 50, staleAfterMs: 1000 });
  const detached = await previewProject(project, { type: 'proxy', width: 32, height: 32, output: 'cancel.mp4', force: true }, { detach: true }, service);
  assert.equal(detached.job.kind, 'preview.proxy');
  await waitForStatus(service, detached.job.id, ['running', 'stopping']);
  await service.cancel(detached.job.id);
  const cancelled = await service.wait(detached.job.id);
  assert.equal(cancelled.status, 'cancelled', JSON.stringify(cancelled.error));
  assert.equal(await readFile(output, 'utf8'), 'original-output');

  const retry = await service.retry(detached.job.id, { detach: true });
  assert.equal(retry.retryOf, detached.job.id);
  assert.equal(retry.preview.type, 'proxy');
  await waitForStatus(service, retry.id, ['running', 'stopping']);
  await service.cancel(retry.id);
  assert.equal((await service.wait(retry.id)).status, 'cancelled');
  assert.equal(await readFile(output, 'utf8'), 'original-output');

  const timed = await previewProject(project, { type: 'proxy', width: 32, height: 32, output: 'timeout.mp4' }, { timeoutMs: 25 }, service);
  assert.equal(timed.job.status, 'timedOut', JSON.stringify(timed.job.error));
  assert.equal(timed.job.error.code, 'JOB_TIMED_OUT');
  await assert.rejects(stat(join(project, 'timeout.mp4')), { code: 'ENOENT' });
});
