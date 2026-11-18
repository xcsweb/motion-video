import assert from 'node:assert/strict';
import { execFile } from 'node:child_process';
import {
  appendFile,
  chmod,
  mkdir,
  mkdtemp,
  readFile,
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
import {
  analyzeAsset,
  generateAssetPreview,
} from '../dist/asset-jobs.js';
import {
  addAsset,
  getAssetStatus,
  listAssets,
  probeAsset,
  removeAsset,
} from '../dist/assets.js';
import { applyEdit } from '../dist/edit.js';
import { listHistory, redoProject, undoProject } from '../dist/history.js';
import { JobService } from '../dist/jobs.js';
import { initProject, loadProject } from '../dist/project.js';

const root = dirname(dirname(fileURLToPath(import.meta.url)));
const cliPath = join(root, 'dist', 'cli.js');
const sleep = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds));

function execute(command, args) {
  return new Promise((resolve, reject) => {
    execFile(command, args, { maxBuffer: 4 * 1024 * 1024 }, (error, stdout, stderr) => {
      if (error) reject(new Error(`${command} failed: ${stderr || error.message}`));
      else resolve({ stdout, stderr });
    });
  });
}

function cli(args) {
  return new Promise((resolve, reject) => {
    execFile(process.execPath, [cliPath, ...args], { cwd: root }, (error, stdout, stderr) => {
      if (error && typeof error.code !== 'number') reject(error);
      else resolve({ status: error?.code ?? 0, stdout, stderr });
    });
  });
}

function cliSuccess(result, command) {
  assert.equal(result.status, 0, result.stderr);
  assert.equal(result.stderr, '');
  const value = JSON.parse(result.stdout);
  assert.equal(value.ok, true);
  assert.equal(value.command, command);
  return value;
}

async function temporaryDirectory(t) {
  const directory = await mkdtemp(join(tmpdir(), 'codecut-assets-test-'));
  t.after(() => rm(directory, { recursive: true, force: true }));
  return directory;
}

async function createMedia(path) {
  await execute('ffmpeg', [
    '-v', 'error', '-y',
    '-f', 'lavfi', '-i', 'color=c=black:s=160x120:r=10:d=2',
    '-f', 'lavfi', '-i', 'color=c=white:s=160x120:r=10:d=2',
    '-f', 'lavfi', '-i', 'color=c=black:s=160x120:r=10:d=2',
    '-f', 'lavfi', '-i', 'anullsrc=r=48000:cl=mono:d=1.5',
    '-f', 'lavfi', '-i', 'sine=frequency=1000:sample_rate=48000:duration=1.5',
    '-f', 'lavfi', '-i', 'anullsrc=r=48000:cl=mono:d=1.5',
    '-f', 'lavfi', '-i', 'sine=frequency=1000:sample_rate=48000:duration=1.5',
    '-filter_complex', '[0:v][1:v][2:v]concat=n=3:v=1:a=0[v];[3:a][4:a][5:a][6:a]concat=n=4:v=0:a=1[a]',
    '-map', '[v]', '-map', '[a]',
    '-c:v', 'libx264', '-preset', 'ultrafast', '-pix_fmt', 'yuv420p',
    '-c:a', 'aac', '-shortest', path,
  ]);
}

async function mediaProject(t) {
  const directory = await temporaryDirectory(t);
  const projectDirectory = join(directory, 'project');
  await initProject(projectDirectory);
  const sourcePath = join(projectDirectory, 'source.mp4');
  await createMedia(sourcePath);
  return { directory, projectDirectory, sourcePath };
}

async function probe(path) {
  const { stdout } = await execute('ffprobe', [
    '-v', 'error', '-show_streams', '-show_format', '-of', 'json', path,
  ]);
  return JSON.parse(stdout);
}

async function expectCode(promise, code) {
  await assert.rejects(promise, (error) => {
    assert.equal(error.code, code, error.stack);
    return true;
  });
}

async function waitForStatus(service, id, wanted, timeout = 10_000) {
  const deadline = Date.now() + timeout;
  for (;;) {
    const job = await service.get(id);
    if (wanted.includes(job.status)) return job;
    if (['succeeded', 'failed', 'cancelled', 'timedOut', 'interrupted'].includes(job.status)) {
      assert.fail(`Job reached ${job.status} while waiting for ${wanted.join('/')}: ${JSON.stringify(job.error)}`);
    }
    if (Date.now() > deadline) assert.fail(`Timed out waiting for ${wanted.join('/')}; last status: ${job.status}`);
    await sleep(20);
  }
}

function closeTo(actual, expected, tolerance, message) {
  assert.ok(Math.abs(actual - expected) <= tolerance, message ?? `${actual} was not within ${tolerance} of ${expected}`);
}

test('asset registration, metadata, dry-runs, status, reference protection, and removal share project history', async (t) => {
  const { directory, projectDirectory, sourcePath } = await mediaProject(t);
  const initialHistory = await listHistory(projectDirectory);
  assert.equal(initialHistory.revisions.length, 0);

  const dryAdd = await addAsset(projectDirectory, { id: 'dry', path: 'source.mp4', dryRun: true });
  assert.equal(dryAdd.dryRun, true);
  assert.equal(dryAdd.project.assets.length, 1);
  assert.equal((await loadProject(projectDirectory)).project.revision, 0);
  assert.equal((await listHistory(projectDirectory)).revisions.length, 0);

  await expectCode(addAsset(projectDirectory, { id: 'missing', path: 'missing.mp4' }), 'ASSET_FILE_MISSING');
  const notesPath = join(projectDirectory, 'notes.txt');
  await writeFile(notesPath, 'not media', 'utf8');
  await expectCode(addAsset(projectDirectory, { id: 'notes', path: 'notes.txt' }), 'ASSET_NOT_MEDIA');
  await mkdir(join(directory, 'directory-source'));
  await expectCode(addAsset(projectDirectory, { id: 'directory', path: '../directory-source' }), 'ASSET_NOT_FILE');

  const added = await addAsset(projectDirectory, { id: 'source', path: 'source.mp4' });
  assert.equal(added.dryRun, false);
  assert.equal(added.project.revision, 1);
  assert.equal(added.revision.operations[0].type, 'addAsset');
  assert.equal(added.asset.path, 'source.mp4');
  assert.equal(added.asset.kind, 'video');
  assert.equal(added.asset.metadata.size, (await stat(sourcePath)).size);
  assert.ok(added.asset.metadata.duration >= 5.9);
  const video = added.asset.metadata.streams.find((stream) => stream.codecType === 'video');
  const audio = added.asset.metadata.streams.find((stream) => stream.codecType === 'audio');
  assert.equal(video.width, 160);
  assert.equal(video.height, 120);
  closeTo(video.frameRate, 10, 0.01);
  assert.equal(audio.sampleRate, 48000);
  assert.equal(audio.channels, 1);

  await expectCode(addAsset(projectDirectory, { id: 'source', path: 'source.mp4' }), 'ASSET_ID_EXISTS');
  await expectCode(addAsset(projectDirectory, { id: 'other', path: './source.mp4' }), 'ASSET_PATH_EXISTS');

  const changedTime = new Date(Date.now() + 5_000);
  await utimes(sourcePath, changedTime, changedTime);
  const changed = await getAssetStatus(projectDirectory, 'source');
  assert.equal(changed.assets[0].state, 'changed');
  assert.equal(changed.assets[0].metadataStale, true);
  assert.equal((await listAssets(projectDirectory)).assets.length, 1);
  assert.equal((await loadProject(projectDirectory)).project.revision, 1);
  assert.equal((await listHistory(projectDirectory)).revisions.length, 1);

  const dryProbe = await probeAsset(projectDirectory, 'source', { dryRun: true });
  assert.equal(dryProbe.dryRun, true);
  assert.equal(dryProbe.project.revision, 2);
  assert.equal((await loadProject(projectDirectory)).project.revision, 1);
  assert.equal((await listHistory(projectDirectory)).revisions.length, 1);
  const probed = await probeAsset(projectDirectory, 'source');
  assert.equal(probed.project.revision, 2);
  assert.equal(probed.revision.operations[0].type, 'probeAsset');
  assert.equal((await getAssetStatus(projectDirectory, 'source')).assets[0].state, 'ok');

  const movedPath = join(projectDirectory, 'moved.mp4');
  await rename(sourcePath, movedPath);
  assert.equal((await getAssetStatus(projectDirectory, 'source')).assets[0].state, 'missing');
  await rename(movedPath, sourcePath);

  const withClip = await applyEdit(projectDirectory, [{
    type: 'addClip',
    trackId: 'v1',
    clip: { id: 'clip-1', type: 'video', assetId: 'source', start: 0, duration: 1 },
  }]);
  assert.equal(withClip.project.revision, 3);
  await expectCode(removeAsset(projectDirectory, 'source', { dryRun: true }), 'ASSET_IN_USE');
  assert.equal((await loadProject(projectDirectory)).project.revision, 3);
  await applyEdit(projectDirectory, [{ type: 'removeClip', clipId: 'clip-1' }]);

  const dryRemove = await removeAsset(projectDirectory, 'source', { dryRun: true });
  assert.equal(dryRemove.project.assets.length, 0);
  assert.equal((await loadProject(projectDirectory)).project.assets.length, 1);
  assert.equal((await loadProject(projectDirectory)).project.revision, 4);
  const removed = await removeAsset(projectDirectory, 'source');
  assert.equal(removed.project.assets.length, 0);
  assert.equal(removed.project.revision, 5);
  assert.equal(removed.revision.operations[0].type, 'removeAsset');
  assert.equal((await listHistory(projectDirectory)).revisions.length, 5);
  const undone = await undoProject(projectDirectory);
  assert.equal(undone.project.assets[0].id, 'source');
  const redone = await redoProject(projectDirectory);
  assert.equal(redone.project.assets.length, 0);
  assert.equal((await listHistory(projectDirectory)).revisions.length, 7);
});

test('thumbnail and timestamped sheet jobs publish PNGs, protect outputs, and invalidate every cached identity input', async (t) => {
  const { projectDirectory, sourcePath } = await mediaProject(t);
  await addAsset(projectDirectory, { id: 'source', path: 'source.mp4' });
  const request = { type: 'thumbnail', assetId: 'source', at: 2.5, width: 120, height: 90 };
  const first = await generateAssetPreview(projectDirectory, request);
  assert.equal(first.status, 'succeeded', JSON.stringify(first.error));
  assert.equal(first.kind, 'asset.thumbnail');
  assert.equal(first.result.data.cacheHit, false);
  const firstOutput = first.result.data.outputPath;
  const png = await readFile(firstOutput);
  assert.equal(png.subarray(1, 4).toString(), 'PNG');
  const thumbnailProbe = await probe(firstOutput);
  assert.equal(thumbnailProbe.streams[0].codec_name, 'png');
  assert.equal(thumbnailProbe.streams[0].width, 120);
  assert.equal(thumbnailProbe.streams[0].height, 90);
  assert.equal((await loadProject(projectDirectory)).project.revision, 1);
  assert.equal((await listHistory(projectDirectory)).revisions.length, 1);

  const cached = await generateAssetPreview(projectDirectory, request);
  assert.equal(cached.status, 'succeeded', JSON.stringify(cached.error));
  assert.equal(cached.result.data.cacheHit, true);
  assert.equal(cached.result.data.cacheKey, first.result.data.cacheKey);
  assert.notEqual(cached.id, first.id);
  assert.equal(cached.logs.progress, undefined);

  const changedParameters = await generateAssetPreview(projectDirectory, { ...request, at: 3.5 });
  assert.equal(changedParameters.status, 'succeeded', JSON.stringify(changedParameters.error));
  assert.equal(changedParameters.result.data.cacheHit, false);
  assert.notEqual(changedParameters.result.data.cacheKey, first.result.data.cacheKey);

  const oldSize = first.result.data.source.size;
  await appendFile(sourcePath, Buffer.from([0]));
  const changedSource = await generateAssetPreview(projectDirectory, request);
  assert.equal(changedSource.status, 'succeeded', JSON.stringify(changedSource.error));
  assert.equal(changedSource.result.data.cacheHit, false);
  assert.equal(changedSource.result.data.source.size, oldSize + 1);
  assert.notEqual(changedSource.result.data.cacheKey, first.result.data.cacheKey);
  const projectAfterJobs = await loadProject(projectDirectory);
  assert.equal(projectAfterJobs.project.revision, 1);
  assert.equal(projectAfterJobs.project.assets[0].metadata.size, oldSize, 'read-only media jobs must not commit refreshed metadata');
  assert.equal((await listHistory(projectDirectory)).revisions.length, 1);

  const sheet = await generateAssetPreview(projectDirectory, {
    type: 'sheet', assetId: 'source', start: 0, end: 5.5, interval: 1,
    columns: 3, rows: 2, width: 96, height: 72,
  });
  assert.equal(sheet.status, 'succeeded', JSON.stringify(sheet.error));
  assert.equal(sheet.kind, 'asset.sheet');
  assert.equal(sheet.result.data.cacheHit, false);
  const sheetProbe = await probe(sheet.result.data.outputPath);
  assert.equal(sheetProbe.streams[0].codec_name, 'png');
  assert.ok(sheetProbe.streams[0].width > 96);
  assert.ok(sheetProbe.streams[0].height > 72);
  const sheetRequest = JSON.parse(await readFile(sheet.diagnostics.request, 'utf8'));
  const sheetFilter = sheetRequest.process.args.find((argument) => argument.includes('drawtext='));
  assert.ok(sheetFilter.includes('%{pts\\:hms}'));
  assert.ok(sheetFilter.includes('setpts=PTS+0/TB'));
  assert.ok(sheetFilter.includes('tile=3x2'));

  const custom = { type: 'thumbnail', assetId: 'source', at: 1, width: 64, output: 'custom/thumb.png' };
  const customFirst = await generateAssetPreview(projectDirectory, custom);
  assert.equal(customFirst.status, 'succeeded', JSON.stringify(customFirst.error));
  const customPath = customFirst.result.data.outputPath;
  const original = await readFile(customPath);
  const protectedResult = await generateAssetPreview(projectDirectory, { ...custom, at: 3 });
  assert.equal(protectedResult.status, 'failed');
  assert.equal(protectedResult.error.code, 'OUTPUT_EXISTS');
  assert.deepEqual(await readFile(customPath), original);
  const forced = await generateAssetPreview(projectDirectory, { ...custom, at: 3, force: true });
  assert.equal(forced.status, 'succeeded', JSON.stringify(forced.error));
  assert.equal(forced.result.data.cacheHit, false);
  assert.notDeepEqual(await readFile(customPath), original);

  await expectCode(generateAssetPreview(projectDirectory, { ...request, width: 15 }), 'PREVIEW_SIZE_INVALID');
  await expectCode(generateAssetPreview(projectDirectory, {
    type: 'sheet', assetId: 'source', columns: 20, rows: 20,
  }), 'PREVIEW_SHEET_LAYOUT_INVALID');
  await expectCode(generateAssetPreview(projectDirectory, { ...request, at: 100 }), 'PREVIEW_TIME_INVALID');
  await rename(sourcePath, `${sourcePath}.missing`);
  await expectCode(generateAssetPreview(projectDirectory, request), 'ASSET_FILE_MISSING');
});

test('FFmpeg scene and silence analysis return absolute structured times and bounded persistent job concurrency', async (t) => {
  const { projectDirectory } = await mediaProject(t);
  await addAsset(projectDirectory, { id: 'source', path: 'source.mp4' });

  const scenes = await analyzeAsset(projectDirectory, {
    type: 'scenes', assetId: 'source', start: 1, end: 5, threshold: 0.05,
  });
  assert.equal(scenes.status, 'succeeded', JSON.stringify(scenes.error));
  assert.equal(scenes.result.data.type, 'scenes');
  assert.equal(scenes.result.data.threshold, 0.05);
  assert.ok(scenes.result.data.points.some((point) => Math.abs(point.time - 2) < 0.15), JSON.stringify(scenes.result.data.points));
  assert.ok(scenes.result.data.points.some((point) => Math.abs(point.time - 4) < 0.15), JSON.stringify(scenes.result.data.points));
  assert.ok(scenes.result.data.points.every((point) => point.score > 0 && point.score <= 1));
  assert.equal(scenes.diagnostics.result, scenes.result.data.resultPath);
  const sceneResultFile = JSON.parse(await readFile(scenes.diagnostics.result, 'utf8'));
  assert.deepEqual(sceneResultFile.points, scenes.result.data.points);

  const silence = await analyzeAsset(projectDirectory, {
    type: 'silence', assetId: 'source', start: 0.5, end: 5.5,
    noiseDb: -45, minimumDuration: 0.3,
  });
  assert.equal(silence.status, 'succeeded', JSON.stringify(silence.error));
  assert.equal(silence.result.data.type, 'silence');
  assert.equal(silence.result.data.noiseDb, -45);
  assert.ok(silence.result.data.intervals.some((interval) => Math.abs(interval.end - 1.5) < 0.2), JSON.stringify(silence.result.data.intervals));
  assert.ok(silence.result.data.intervals.some((interval) => Math.abs(interval.start - 3) < 0.2), JSON.stringify(silence.result.data.intervals));
  assert.ok(silence.result.data.intervals.every((interval) => interval.start >= 0.5 && interval.end <= 5.5 && interval.duration > 0));
  assert.equal((await loadProject(projectDirectory)).project.revision, 1);
  assert.equal((await listHistory(projectDirectory)).revisions.length, 1);

  await expectCode(analyzeAsset(projectDirectory, {
    type: 'scenes', assetId: 'source', threshold: 0,
  }), 'SCENE_THRESHOLD_INVALID');
  await expectCode(analyzeAsset(projectDirectory, {
    type: 'silence', assetId: 'source', minimumDuration: 0,
  }), 'SILENCE_DURATION_INVALID');
  await expectCode(analyzeAsset(projectDirectory, {
    type: 'scenes', assetId: 'source', start: 5, end: 4,
  }), 'ANALYSIS_RANGE_INVALID');

  const parallelTool = join(projectDirectory, 'parallel-ffmpeg.cjs');
  await writeFile(parallelTool, `#!/usr/bin/env node
const fs = require('fs');
const path = require('path');
const marker = path.join(__dirname, 'active-' + process.pid);
fs.writeFileSync(marker, '');
const active = fs.readdirSync(__dirname).filter((name) => name.startsWith('active-')).length;
fs.appendFileSync(path.join(__dirname, 'observed.txt'), String(active) + '\\n');
setTimeout(() => {
  fs.unlinkSync(marker);
  process.stdout.write('progress=end\\n', () => process.exit(0));
}, 140);
`, 'utf8');
  await chmod(parallelTool, 0o755);
  const service = new JobService({ projectDirectory, maxConcurrency: 2, pollMs: 10 });
  const parallel = await Promise.all(Array.from({ length: 5 }, () => analyzeAsset(projectDirectory, {
    type: 'scenes', assetId: 'source', threshold: 0.2,
  }, { ffmpegPath: parallelTool }, service)));
  assert.deepEqual(parallel.map((job) => job.status), Array(5).fill('succeeded'));
  const observed = (await readFile(join(projectDirectory, 'observed.txt'), 'utf8')).trim().split('\n').map(Number);
  assert.equal(observed.length, 5);
  assert.ok(Math.max(...observed) <= 2, `observed concurrency: ${observed}`);
  assert.ok(Math.max(...observed) > 1, 'jobs should be able to run in parallel');

  const controlledTool = join(projectDirectory, 'controlled-ffmpeg.cjs');
  await writeFile(controlledTool, `#!/usr/bin/env node
const fs = require('fs');
const path = require('path');
function finish() { process.stdout.write('progress=end\\n', () => process.exit(0)); }
if (fs.existsSync(path.join(__dirname, 'finish'))) finish();
else setInterval(() => { if (fs.existsSync(path.join(__dirname, 'finish'))) finish(); }, 20);
`, 'utf8');
  await chmod(controlledTool, 0o755);
  const detached = await analyzeAsset(projectDirectory, {
    type: 'scenes', assetId: 'source', threshold: 0.2,
  }, { ffmpegPath: controlledTool, detach: true }, service);
  assert.ok(detached.id);
  await waitForStatus(service, detached.id, ['running']);
  const stopping = await service.cancel(detached.id);
  assert.ok(['stopping', 'cancelled'].includes(stopping.status));
  const cancelled = await service.wait(detached.id);
  assert.equal(cancelled.status, 'cancelled');
  assert.equal(cancelled.error.code, 'JOB_CANCELLED');

  await writeFile(join(projectDirectory, 'finish'), 'finish', 'utf8');
  const retried = await service.retry(detached.id);
  assert.equal(retried.status, 'succeeded', JSON.stringify(retried.error));
  assert.equal(retried.retryOf, detached.id);
  assert.deepEqual(retried.result.data.points, []);
  assert.equal((await loadProject(projectDirectory)).project.revision, 1);
  assert.equal((await listHistory(projectDirectory)).revisions.length, 1);
});

test('asset CLI keeps JSON stdout clean and exposes detached preview results through jobs show', async (t) => {
  const { projectDirectory } = await mediaProject(t);
  cliSuccess(await cli(['asset', 'add', 'source.mp4', '--id', 'source', '--project', projectDirectory, '--dry-run', '--json']), 'asset.add');
  assert.equal((await loadProject(projectDirectory)).project.revision, 0);
  cliSuccess(await cli(['asset', 'add', 'source.mp4', '--id', 'source', '--project', projectDirectory, '--json']), 'asset.add');
  const listed = cliSuccess(await cli(['asset', 'list', '--project', projectDirectory, '--json']), 'asset.list');
  assert.equal(listed.assets[0].id, 'source');
  const status = cliSuccess(await cli(['asset', 'status', 'source', '--project', projectDirectory, '--json']), 'asset.status');
  assert.equal(status.assets[0].state, 'ok');

  const detached = cliSuccess(await cli([
    'asset', 'thumbnail', 'source', '--at', '1', '--width', '64',
    '--detach', '--project', projectDirectory, '--json',
  ]), 'asset.thumbnail');
  assert.ok(detached.job.id);
  const waited = cliSuccess(await cli(['jobs', 'wait', detached.job.id, '--project', projectDirectory, '--json']), 'jobs.wait');
  assert.equal(waited.job.status, 'succeeded');
  assert.equal(waited.job.result.data.cacheHit, false);
  assert.ok(waited.job.result.data.outputPath);
  const shown = cliSuccess(await cli(['jobs', 'show', detached.job.id, '--project', projectDirectory, '--json']), 'jobs.show');
  assert.equal(shown.job.result.data.outputPath, waited.job.result.data.outputPath);
  assert.equal((await stat(shown.job.result.data.outputPath)).size > 0, true);
  assert.equal((await loadProject(projectDirectory)).project.revision, 1);

  const scenes = cliSuccess(await cli([
    'asset', 'analyze', 'scenes', 'source', '--start', '1', '--end', '3',
    '--threshold', '0.05', '--project', projectDirectory, '--json',
  ]), 'asset.analyze.scenes');
  assert.equal(scenes.job.status, 'succeeded');
  assert.ok(scenes.result.points.some((point) => Math.abs(point.time - 2) < 0.15));
  const shownAnalysis = cliSuccess(await cli([
    'jobs', 'show', scenes.job.id, '--project', projectDirectory, '--json',
  ]), 'jobs.show');
  assert.deepEqual(shownAnalysis.job.result.data.points, scenes.result.points);

  const missing = await cli(['asset', 'add', 'missing.mp4', '--id', 'missing', '--project', projectDirectory, '--json']);
  assert.equal(missing.status, 4);
  assert.equal(missing.stdout, '');
  assert.equal(JSON.parse(missing.stderr).error.code, 'ASSET_FILE_MISSING');
  const duplicate = await cli(['asset', 'add', 'source.mp4', '--id', 'source', '--project', projectDirectory, '--json']);
  assert.equal(duplicate.status, 3);
  assert.equal(duplicate.stdout, '');
  assert.equal(JSON.parse(duplicate.stderr).error.code, 'ASSET_ID_EXISTS');
});
