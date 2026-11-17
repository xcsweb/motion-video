import assert from 'node:assert/strict';
import { execFile } from 'node:child_process';
import {
  copyFile,
  mkdir,
  mkdtemp,
  readFile,
  readdir,
  rename,
  rm,
  stat,
  utimes,
  writeFile,
} from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import test from 'node:test';
import { addAsset } from '../dist/assets.js';
import { applyEdit } from '../dist/edit.js';
import { listHistory } from '../dist/history.js';
import { JobService } from '../dist/jobs.js';
import { initProject, loadProject } from '../dist/project.js';
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

async function temporaryDirectory(t, prefix = 'codecut-render-test-') {
  const directory = await mkdtemp(join(tmpdir(), prefix));
  t.after(() => rm(directory, { recursive: true, force: true }));
  return directory;
}

async function configureProject(directory, output = 'render.mp4', duration = 3) {
  await initProject(directory);
  const path = join(directory, 'project.json');
  const project = JSON.parse(await readFile(path, 'utf8'));
  Object.assign(project.output, {
    path: output, width: 64, height: 64, frameRate: 8,
  });
  await writeFile(path, `${JSON.stringify(project, null, 2)}\n`, 'utf8');
  return { path, duration };
}

async function createSources(directory) {
  const visual = join(directory, 'visual.mp4');
  await execute('ffmpeg', [
    '-v', 'error', '-y',
    '-f', 'lavfi', '-i', 'color=c=red:s=64x48:r=8:d=1',
    '-f', 'lavfi', '-i', 'color=c=green:s=64x48:r=8:d=1',
    '-f', 'lavfi', '-i', 'color=c=blue:s=64x48:r=8:d=1',
    '-f', 'lavfi', '-i', 'color=c=yellow:s=64x48:r=8:d=1',
    '-filter_complex', '[0:v][1:v][2:v][3:v]concat=n=4:v=1:a=0[v]',
    '-map', '[v]', '-c:v', 'libx264', '-preset', 'ultrafast', '-pix_fmt', 'yuv420p', visual,
  ]);
  const sounding = join(directory, 'sounding.mp4');
  await execute('ffmpeg', [
    '-v', 'error', '-y',
    '-f', 'lavfi', '-i', 'color=c=0x800080:s=64x48:r=8:d=2',
    '-f', 'lavfi', '-i', 'sine=frequency=660:sample_rate=48000:duration=2',
    '-map', '0:v', '-map', '1:a', '-c:v', 'libx264', '-preset', 'ultrafast', '-pix_fmt', 'yuv420p',
    '-c:a', 'aac', '-shortest', sounding,
  ]);
  const low = join(directory, 'low.wav');
  const high = join(directory, 'high.wav');
  await execute('ffmpeg', ['-v', 'error', '-y', '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000:duration=1', '-c:a', 'pcm_s16le', low]);
  await execute('ffmpeg', ['-v', 'error', '-y', '-f', 'lavfi', '-i', 'sine=frequency=880:sample_rate=48000:duration=3', '-c:a', 'pcm_s16le', high]);

  const width = 32;
  const height = 32;
  const pixels = Buffer.alloc(width * height * 3);
  const colors = [[255, 0, 0], [0, 255, 0], [0, 0, 255], [255, 255, 255]];
  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) {
      const color = colors[(y >= 16 ? 2 : 0) + (x >= 16 ? 1 : 0)];
      const offset = (y * width + x) * 3;
      pixels[offset] = color[0];
      pixels[offset + 1] = color[1];
      pixels[offset + 2] = color[2];
    }
  }
  const ppm = join(directory, 'pattern.ppm');
  const pattern = join(directory, 'pattern.png');
  await writeFile(ppm, Buffer.concat([Buffer.from(`P6\n${width} ${height}\n255\n`), pixels]));
  await execute('ffmpeg', ['-v', 'error', '-y', '-i', ppm, '-frames:v', '1', pattern]);
  await rm(ppm);
  return { visual, sounding, low, high, pattern };
}

async function addTimeline(project, sources) {
  for (const [id, path] of Object.entries(sources)) {
    await addAsset(project, { id, path });
  }
  const text = "Hello, 世界:\n50% %{pts} [x] $HOME ; 'quote' \\ back";
  const { stdout: fontPath } = await execute('fc-match', ['-f', '%{file}', 'sans']);
  await mkdir(join(project, 'fonts'), { recursive: true });
  const fontFile = "fonts/Font ' : , [ ] ; \\ special.ttf";
  await copyFile(fontPath.trim(), join(project, fontFile));
  const operations = [
    { type: 'addTrack', track: { id: 'v3', kind: 'video', clips: [] } },
    { type: 'addTrack', track: { id: 'hidden', kind: 'video', hidden: true, clips: [] } },
    { type: 'addTrack', track: { id: 'muted', kind: 'audio', muted: true, clips: [] } },
    { type: 'addClip', trackId: 'v1', clip: { id: 'red', type: 'video', assetId: 'visual', start: 0, duration: 1, sourceStart: 0 } },
    { type: 'addClip', trackId: 'v1', clip: { id: 'green', type: 'video', assetId: 'visual', start: 1, duration: 1, sourceStart: 1 } },
    { type: 'addClip', trackId: 'v1', clip: { id: 'blue', type: 'video', assetId: 'visual', start: 1.75, duration: 1.25, sourceStart: 2, transition: { type: 'xfade', duration: 0.25, name: 'fade' } } },
    { type: 'addClip', trackId: 'v2', clip: { id: 'translucent', type: 'color', color: '#FFFF0080', start: 0, duration: 0.5 } },
    { type: 'addClip', trackId: 'v2', clip: { id: 'image', type: 'image', assetId: 'pattern', start: 0.5, duration: 0.5, crop: { x: 16, y: 0, width: 16, height: 16 }, scale: 0.25, position: { x: 32, y: 32 } } },
    { type: 'addText', trackId: 'v2', clip: { id: 'title', type: 'text', text, fontFile, fontSize: 12, color: '#FFFFFF', start: 1, duration: 1 } },
    { type: 'addClip', trackId: 'v2', clip: { id: 'fast', type: 'video', assetId: 'visual', start: 2, duration: 0.5, sourceStart: 3, speed: 2, crop: { x: 0, y: 0, width: 32, height: 24 }, scale: 0.5, position: { x: 32, y: 32 }, opacity: 0.5 } },
    { type: 'addClip', trackId: 'v3', clip: { id: 'original-audio', type: 'video', assetId: 'sounding', start: 1.5, duration: 0.5, scale: 0.25, position: { x: 0, y: 52 } } },
    { type: 'addClip', trackId: 'hidden', clip: { id: 'hidden-white', type: 'color', color: '#FFFFFF', start: 0, duration: 3 } },
    { type: 'addClip', trackId: 'a1', clip: { id: 'low-tone', type: 'audio', assetId: 'low', start: 0, duration: 1, volume: 0.25, fadeIn: 0.2, fadeOut: 0.2 } },
    { type: 'addClip', trackId: 'a2', clip: { id: 'fast-high', type: 'audio', assetId: 'high', start: 0.5, duration: 1, speed: 2, volume: 0.5 } },
    { type: 'addClip', trackId: 'muted', clip: { id: 'muted-tone', type: 'audio', assetId: 'high', start: 2, duration: 1, volume: 1 } },
  ];
  const edited = await applyEdit(project, operations, { summary: 'Build offline multitrack render fixture' });
  return { text, revision: edited.project.revision };
}

async function rawFrame(path, at) {
  const { stdout } = await execute('ffmpeg', [
    '-v', 'error', '-ss', String(at), '-i', path, '-frames:v', '1', '-f', 'rawvideo', '-pix_fmt', 'rgba', '-',
  ], { buffer: true });
  assert.equal(stdout.length, 64 * 64 * 4);
  return stdout;
}

function pixel(frame, x, y) {
  const offset = (y * 64 + x) * 4;
  return [...frame.subarray(offset, offset + 4)];
}

function closeChannel(actual, expected, tolerance = 40) {
  assert.ok(Math.abs(actual - expected) <= tolerance, `${actual} was not within ${tolerance} of ${expected}`);
}

async function pcm(path, start, duration = 0.08) {
  const { stdout } = await execute('ffmpeg', [
    '-v', 'error', '-ss', String(start), '-t', String(duration), '-i', path,
    '-map', '0:a:0', '-ac', '1', '-ar', '48000', '-f', 'f32le', '-',
  ], { buffer: true });
  const samples = new Float32Array(stdout.buffer, stdout.byteOffset, Math.floor(stdout.length / 4));
  return samples;
}

function rms(samples) {
  let sum = 0;
  for (const sample of samples) sum += sample * sample;
  return Math.sqrt(sum / samples.length);
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

test('offline multitrack rendering verifies pixels, PCM, diagnostics, dry-run, immutable revision, and overwrite safety', { timeout: 120_000 }, async (t) => {
  const directory = await temporaryDirectory(t);
  const project = join(directory, 'project');
  const { path: projectPath } = await configureProject(project);
  const sources = await createSources(project);
  const { text, revision } = await addTimeline(project, sources);
  const service = new JobService({ projectDirectory: project, pollMs: 20, gracePeriodMs: 50 });
  const beforeDryEntries = await readdir(project, { recursive: true });
  const beforeDryProject = await readFile(projectPath, 'utf8');
  const dry = await cli(['render', '--project', project, '--revision', String(revision), '--dry-run', '--json']);
  assert.equal(dry.status, 0, dry.stderr);
  assert.equal(dry.stderr, '');
  const dryResult = JSON.parse(dry.stdout);
  assert.equal(dryResult.ok, true);
  assert.equal(dryResult.command, 'render');
  assert.equal(dryResult.dryRun, true);
  assert.equal(dryResult.plan.revision, revision);
  assert.ok(dryResult.revisionId);
  assert.equal(dryResult.plan.inputs.length, 5);
  assert.match(dryResult.plan.filter_graph, /xfade=transition=fade/);
  assert.match(dryResult.plan.filter_graph, /atempo=2/);
  assert.match(dryResult.plan.filter_graph, /amix=inputs=/);
  assert.ok(dryResult.plan.args.includes('-filter_complex_script'));
  assert.deepEqual(await readdir(project, { recursive: true }), beforeDryEntries);
  assert.equal(await readFile(projectPath, 'utf8'), beforeDryProject);
  await assert.rejects(stat(join(project, 'render.mp4')), { code: 'ENOENT' });

  const changed = await applyEdit(project, [{ type: 'setClipParams', clipId: 'title', params: { opacity: 0.9 } }]);
  const rendered = await renderProject(project, { revision }, service);
  assert.equal(rendered.dryRun, false);
  const job = rendered.job;
  assert.equal(job.status, 'succeeded', JSON.stringify({ error: job.error, stderr: job.logTail?.stderr }));
  assert.equal(job.projectRevision, revision);
  assert.equal((await loadProject(project)).project.revision, changed.project.revision);
  assert.equal(job.diagnostics.textFiles.length, 1);
  assert.equal(await readFile(job.diagnostics.textFiles[0], 'utf8'), text);
  const argumentsDocument = JSON.parse(await readFile(job.diagnostics.arguments, 'utf8'));
  assert.equal(argumentsDocument.command, 'ffmpeg');
  assert.ok(argumentsDocument.args.every((argument) => !argument.includes('{jobDirectory}') && !argument.includes('{output}')));
  const persistedGraph = await readFile(job.diagnostics.filterGraph, 'utf8');
  assert.ok(persistedGraph.includes(job.diagnostics.directory));
  const persistedPlan = JSON.parse(await readFile(job.diagnostics.plan, 'utf8'));
  assert.equal(persistedPlan.textFiles[0].content, text);
  const validation = JSON.parse(await readFile(job.diagnostics.validation, 'utf8'));
  assert.equal(validation.completeDecode, true);
  assert.equal(validation.video.codec_name, 'h264');
  assert.equal(validation.audio.codec_name, 'aac');
  assert.equal(validation.video.width, 64);
  assert.equal(validation.video.height, 64);
  assert.equal(validation.audio.sample_rate, '48000');
  assert.equal(validation.audio.channels, 2);
  assert.ok(Math.abs(Number(validation.format.duration) - 3) <= 0.125);

  const output = join(project, 'render.mp4');
  const red = await rawFrame(output, 0.25);
  const redPixel = pixel(red, 2, 2);
  closeChannel(redPixel[0], 255);
  closeChannel(redPixel[1], 127);
  closeChannel(redPixel[2], 0);
  const image = await rawFrame(output, 0.75);
  const cropped = pixel(image, 40, 40);
  closeChannel(cropped[0], 0);
  closeChannel(cropped[1], 255);
  closeChannel(cropped[2], 0);
  const green = await rawFrame(output, 1.25);
  closeChannel(pixel(green, 2, 2)[1], 128);
  assert.ok(green.some((value, index) => index % 4 === 0 && value > 180
    && green[index + 1] > 180 && green[index + 2] > 180), 'drawtext should produce light neutral pixels');
  const transition = pixel(await rawFrame(output, 1.875), 32, 20);
  closeChannel(transition[1], 64);
  closeChannel(transition[2], 128);
  const fast = pixel(await rawFrame(output, 2.25), 40, 40);
  assert.ok(fast[0] > 75 && fast[1] > 75 && fast[2] > 75, `50% yellow overlay should blend with blue: ${fast}`);
  const finalBlue = pixel(await rawFrame(output, 2.625), 2, 2);
  closeChannel(finalBlue[0], 0);
  closeChannel(finalBlue[1], 0);
  closeChannel(finalBlue[2], 255);

  const early = await pcm(output, 0.02);
  const middle = await pcm(output, 0.28);
  const mixed = await pcm(output, 0.72);
  const late = await pcm(output, 0.9);
  const original = await pcm(output, 1.72);
  const sped = await pcm(output, 1.22);
  const silence = await pcm(output, 2.25);
  const middle440 = amplitude(middle, 440);
  assert.ok(amplitude(early, 440) < middle440 * 0.65, 'fade-in should attenuate the start');
  assert.ok(amplitude(late, 440) < middle440 * 0.65, 'fade-out should attenuate the end');
  assert.ok(amplitude(mixed, 440) > 0.005 && amplitude(mixed, 880) > 0.005, 'both audio tracks should be mixed');
  assert.ok(amplitude(original, 660) > 0.005, 'video source audio should be mixed');
  const sped880 = amplitude(sped, 880);
  assert.ok(sped880 > 0.005, `atempo should preserve pitch during speed changes: amplitude=${sped880}, rms=${rms(sped)}`);
  assert.ok(rms(silence) < 0.001, `muted track and gaps should be silent, rms=${rms(silence)}`);

  const beforeConflict = await stat(output);
  const conflict = await renderProject(project, { revision }, service);
  assert.equal(conflict.job.status, 'failed');
  assert.equal(conflict.job.error.code, 'OUTPUT_EXISTS');
  assert.equal((await stat(output)).ino, beforeConflict.ino);
  const forced = await renderProject(project, { revision, force: true }, service);
  assert.equal(forced.job.status, 'succeeded', JSON.stringify(forced.job.error));
  assert.notEqual((await stat(output)).ino, beforeConflict.ino);

  const shown = await cli(['jobs', 'show', job.id, '--project', project, '--json']);
  assert.equal(shown.status, 0, shown.stderr);
  const shownJob = JSON.parse(shown.stdout).job;
  assert.equal(shownJob.diagnostics.arguments, job.diagnostics.arguments);
  assert.equal(shownJob.diagnostics.filterGraph, job.diagnostics.filterGraph);
  const schema = await cli(['schema', '--json']);
  assert.ok(JSON.parse(schema.stdout).renderPlan);
  const capabilities = await cli(['capabilities', '--json']);
  assert.equal(JSON.parse(capabilities.stdout).capabilities.export.status, 'available');
});

test('render source preflight and fixed job snapshots report missing and changed assets without publishing', { timeout: 60_000 }, async (t) => {
  const directory = await temporaryDirectory(t);
  const project = join(directory, 'project');
  await configureProject(project, 'source-check.mp4');
  const source = join(project, 'source.mp4');
  await execute('ffmpeg', ['-v', 'error', '-y', '-f', 'lavfi', '-i', 'color=c=red:s=64x64:r=8:d=1', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', source]);
  await addAsset(project, { id: 'source', path: 'source.mp4' });
  await applyEdit(project, [{ type: 'addClip', trackId: 'v1', clip: { id: 'source', type: 'video', assetId: 'source', start: 0, duration: 1 } }]);
  const originalMtime = (await stat(source)).mtimeMs;
  const future = new Date(Date.now() + 5000);
  await utimes(source, future, future);
  await assert.rejects(renderProject(project, { dryRun: true }), (error) => error.code === 'ASSET_FILE_CHANGED');

  const moved = join(project, 'moved.mp4');
  await rename(source, moved);
  await assert.rejects(renderProject(project, { dryRun: true }), (error) => error.code === 'ASSET_FILE_MISSING');
  await rename(moved, source);
  await utimes(source, originalMtime / 1000, originalMtime / 1000);
  const plan = (await renderProject(project, { dryRun: true })).plan;
  const service = new JobService({ projectDirectory: project, pollMs: 20, gracePeriodMs: 50 });
  const created = await service.create({
    kind: 'render', projectPath: join(project, 'project.json'),
    process: { command: plan.command, args: plan.args, progress: 'ffmpeg', durationSeconds: 1 },
    output: { path: plan.output.path, validation: 'ffprobe' },
    render: { plan },
  });
  await utimes(source, future, future);
  const failed = await service.runJob(created.id);
  assert.equal(failed.status, 'failed');
  assert.equal(failed.error.code, 'ASSET_SNAPSHOT_CHANGED');
  await assert.rejects(stat(plan.output.path), { code: 'ENOENT' });
  assert.equal((await listHistory(project)).revisions.length, 2);
});

test('detached render cancel, timeout, and retry reuse persistent plans and diagnostics', { timeout: 90_000 }, async (t) => {
  const directory = await temporaryDirectory(t);
  const project = join(directory, 'project');
  await configureProject(project, 'detached.mp4');
  await applyEdit(project, [{ type: 'addClip', trackId: 'v1', clip: { id: 'long', type: 'color', color: '#204060', start: 0, duration: 120 } }]);
  const service = new JobService({ projectDirectory: project, pollMs: 20, gracePeriodMs: 50, heartbeatMs: 50, staleAfterMs: 1000 });
  const detached = await renderProject(project, { detach: true }, service);
  const running = await waitForStatus(service, detached.job.id, ['running', 'stopping']);
  assert.equal(running.kind, 'render');
  const cancelled = await service.cancel(detached.job.id);
  assert.ok(['stopping', 'cancelled'].includes(cancelled.status));
  const cancelledFinal = await service.wait(detached.job.id);
  assert.equal(cancelledFinal.status, 'cancelled', JSON.stringify(cancelledFinal.error));
  await assert.rejects(stat(join(project, 'detached.mp4')), { code: 'ENOENT' });

  const retried = await service.retry(detached.job.id);
  assert.equal(retried.status, 'succeeded', JSON.stringify(retried.error));
  assert.equal(retried.retryOf, detached.job.id);
  assert.notEqual(retried.diagnostics.arguments, detached.job.diagnostics.arguments);
  assert.ok(JSON.parse(await readFile(retried.diagnostics.arguments, 'utf8')).args.length > 10);
  assert.equal(JSON.parse(await readFile(retried.diagnostics.validation, 'utf8')).completeDecode, true);

  const timed = await renderProject(project, { output: 'timeout.mp4', timeoutMs: 25 }, service);
  assert.equal(timed.job.status, 'timedOut', JSON.stringify(timed.job.error));
  assert.equal(timed.job.error.code, 'JOB_TIMED_OUT');
  await assert.rejects(stat(join(project, 'timeout.mp4')), { code: 'ENOENT' });
});
