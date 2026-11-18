import assert from 'node:assert/strict';
import { execFile, spawnSync } from 'node:child_process';
import { mkdtemp, readFile, readdir, rm, stat } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { dirname, isAbsolute, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import test from 'node:test';

const codecutRoot = dirname(dirname(fileURLToPath(import.meta.url)));
const repositoryRoot = dirname(codecutRoot);
const demoPath = join(repositoryRoot, 'examples', 'headless_demo.js');
const sourcePath = join(repositoryRoot, 'media', 'railgun_omr_v4_preview.mp4');
const toolsAvailable = ['ffmpeg', 'ffprobe'].every((tool) => spawnSync(tool, ['-version'], { stdio: 'ignore' }).status === 0);

function execute(command, args, options = {}) {
  return new Promise((resolvePromise, reject) => {
    execFile(command, args, {
      cwd: repositoryRoot,
      encoding: options.buffer ? 'buffer' : 'utf8',
      maxBuffer: 32 * 1024 * 1024,
      timeout: options.timeout ?? 60_000,
      env: options.env ?? process.env,
    }, (error, stdout, stderr) => {
      if (error && typeof error.code !== 'number') {
        reject(error);
        return;
      }
      resolvePromise({ status: error?.code ?? 0, stdout, stderr });
    });
  });
}

async function succeed(command, args, options = {}) {
  const result = await execute(command, args, options);
  assert.equal(result.status, 0, `${command} ${args.join(' ')}\n${result.stderr}`);
  return result;
}

async function probe(path) {
  const { stdout } = await succeed('ffprobe', [
    '-v', 'error', '-show_streams', '-show_format', '-of', 'json', path,
  ]);
  return JSON.parse(stdout);
}

async function decodeCompletely(path) {
  await succeed('ffmpeg', [
    '-nostdin', '-v', 'error', '-i', path,
    '-map', '0:v:0', '-map', '0:a:0', '-f', 'null', '-',
  ]);
}

async function rawFrame(path, width, height, at) {
  const args = ['-nostdin', '-v', 'error'];
  if (at !== undefined) args.push('-ss', String(at));
  args.push('-i', path, '-frames:v', '1', '-f', 'rawvideo', '-pix_fmt', 'rgba', '-');
  const { stdout } = await succeed('ffmpeg', args, { buffer: true });
  assert.equal(stdout.length, width * height * 4, `${path} did not produce the expected RGBA frame`);
  return stdout;
}

function compareFrames(actual, expected) {
  let errorSum = 0;
  let closeChannels = 0;
  let channels = 0;
  let minimum = 255;
  let maximum = 0;
  for (let index = 0; index < actual.length; index += 1) {
    if (index % 4 === 3) continue;
    const difference = Math.abs(actual[index] - expected[index]);
    errorSum += difference;
    if (difference <= 16) closeChannels += 1;
    channels += 1;
    minimum = Math.min(minimum, actual[index]);
    maximum = Math.max(maximum, actual[index]);
  }
  const mean = errorSum / channels;
  const ratio = closeChannels / channels;
  assert.ok(maximum - minimum > 40, 'representative frame should contain real image detail, not a blank canvas');
  assert.ok(mean <= 6, `preview/formal mean RGB error ${mean} should be <= 6`);
  assert.ok(ratio >= 0.97, `${(ratio * 100).toFixed(2)}% channels within 16 should be >= 97%`);
  return { mean, ratio };
}

async function pcm(path, start, duration = 0.24) {
  const { stdout } = await succeed('ffmpeg', [
    '-nostdin', '-v', 'error', '-ss', String(start), '-t', String(duration), '-i', path,
    '-map', '0:a:0', '-ac', '1', '-ar', '48000', '-f', 'f32le', '-',
  ], { buffer: true });
  assert.ok(stdout.length > 4 * 48000 * 0.2, `${path} returned too little representative audio`);
  return new Float32Array(stdout.buffer, stdout.byteOffset, Math.floor(stdout.length / 4));
}

function audioStats(left, right) {
  const length = Math.min(left.length, right.length);
  let leftEnergy = 0;
  let rightEnergy = 0;
  let dot = 0;
  for (let index = 0; index < length; index += 1) {
    leftEnergy += left[index] ** 2;
    rightEnergy += right[index] ** 2;
    dot += left[index] * right[index];
  }
  return {
    leftRms: Math.sqrt(leftEnergy / length),
    rightRms: Math.sqrt(rightEnergy / length),
    correlation: dot / Math.sqrt(leftEnergy * rightEnergy),
  };
}

function collectPathCandidates(value, key = '', candidates = []) {
  if (typeof value === 'string' && /path|directory|bundle/i.test(key)) candidates.push(value);
  else if (Array.isArray(value)) {
    for (const entry of value) collectPathCandidates(entry, key, candidates);
  } else if (value && typeof value === 'object') {
    for (const [childKey, entry] of Object.entries(value)) collectPathCandidates(entry, childKey, candidates);
  }
  return candidates;
}

async function diagnosisDirectory(diagnosis, projectDirectory, outputDirectory, jobId) {
  const candidates = collectPathCandidates(diagnosis);
  const directories = [];
  for (const candidate of candidates) {
    const paths = isAbsolute(candidate)
      ? [candidate]
      : [resolve(projectDirectory, candidate), resolve(outputDirectory, candidate)];
    for (const path of paths) {
      try {
        if ((await stat(path)).isDirectory()) directories.push(path);
      } catch {
        // Most JSON string fields are not diagnosis paths.
      }
    }
  }
  assert.ok(directories.length > 0, `diagnose returned no existing directory: ${JSON.stringify(diagnosis)}`);
  return directories.find((path) => path.includes(jobId)) ?? directories[0];
}

async function filesRecursively(directory) {
  const entries = await readdir(directory, { recursive: true, withFileTypes: true });
  return entries.filter((entry) => entry.isFile()).map((entry) => join(entry.parentPath, entry.name));
}

function assertMediaStreams(media, expected, duration) {
  const video = media.streams.find((stream) => stream.codec_type === 'video');
  const audio = media.streams.find((stream) => stream.codec_type === 'audio');
  assert.ok(video, 'output has a video stream');
  assert.ok(audio, 'output has an audio stream');
  assert.equal(video.codec_name, 'h264');
  assert.equal(video.width, expected.width);
  assert.equal(video.height, expected.height);
  assert.equal(video.pix_fmt, 'yuv420p');
  assert.equal(audio.codec_name, 'aac');
  assert.equal(audio.sample_rate, '48000');
  assert.equal(audio.channels, 2);
  assert.ok(Math.abs(Number(media.format.duration) - duration) <= 1 / 6,
    `media duration ${media.format.duration} should match ${duration}`);
  return { video, audio };
}

test('focused unit suites retain cancellation, timeout, crash, flood, and lock coverage', async () => {
  const [jobs, processTests, edits] = await Promise.all([
    readFile(join(codecutRoot, 'test', 'jobs.test.js'), 'utf8'),
    readFile(join(codecutRoot, 'test', 'process.test.js'), 'utf8'),
    readFile(join(codecutRoot, 'test', 'edit.test.js'), 'utf8'),
  ]);
  assert.match(jobs, /active cancellation preserves/);
  assert.match(jobs, /timeout preserves/);
  assert.match(jobs, /crashed detached worker/);
  assert.match(jobs, /output path lock rejects/);
  assert.match(processTests, /stdout and stderr flood/);
  assert.match(processTests, /cancellation and timeout terminate/);
  assert.match(edits, /project locks reject active and nested writers/);
});

test('offline headless demo produces verified media, history, jobs, and real failure diagnostics', {
  skip: !toolsAvailable && 'ffmpeg and ffprobe are required',
  timeout: 240_000,
}, async (t) => {
  const temporary = await mkdtemp(join(tmpdir(), 'codecut-headless-e2e-'));
  t.after(() => rm(temporary, { recursive: true, force: true }));
  const outputDirectory = join(temporary, 'persistent-demo-output');
  const sourceBefore = await stat(sourcePath);
  const demo = await execute(process.execPath, [demoPath, outputDirectory], {
    timeout: 220_000,
    env: { ...process.env, CI: '1', http_proxy: 'http://127.0.0.1:9', https_proxy: 'http://127.0.0.1:9' },
  });
  assert.equal(demo.status, 0, `headless demo failed; output=${outputDirectory}\n${demo.stderr}\n${demo.stdout}`);
  assert.equal(demo.stderr, '');
  const summary = JSON.parse(demo.stdout);
  assert.equal(summary.ok, true);
  assert.equal(summary.outputDirectory, outputDirectory);
  assert.deepEqual(JSON.parse(await readFile(summary.summaryPath, 'utf8')), summary);
  const sourceAfter = await stat(sourcePath);
  assert.equal(sourceAfter.size, sourceBefore.size, 'demo must not modify the real source');
  assert.equal(sourceAfter.mtimeMs, sourceBefore.mtimeMs, 'demo must not touch the real source timestamps');

  const projectDirectory = summary.projectDirectory;
  const requiredCommands = [
    ['project', 'init'], ['project', 'validate'], ['asset', 'add'], ['asset', 'probe'],
    ['asset', 'analyze', 'scenes'], ['asset', 'analyze', 'silence'], ['edit', 'apply'],
    ['history', 'list'], ['history', 'diff'], ['history', 'undo'], ['history', 'redo'],
    ['preview', 'frame'], ['preview', 'sheet'], ['preview', 'proxy'], ['render'],
    ['jobs', 'wait'], ['jobs', 'show'],
  ];
  for (const required of requiredCommands) {
    assert.ok(summary.commands.some((entry) => required.every((part, index) => entry.args[index] === part)),
      `missing CLI sequence: ${required.join(' ')}`);
  }
  for (const diagnosticArgs of [
    ['doctor', '--project', projectDirectory, '--json'],
    ['logs', summary.failure.job.id, '--project', projectDirectory, '--json'],
    ['diagnose', summary.failure.job.id, '--project', projectDirectory, '--json'],
  ]) {
    assert.ok(summary.commands.some((entry) => JSON.stringify(entry.args) === JSON.stringify(diagnosticArgs)),
      `missing exact diagnostic invocation: ${diagnosticArgs.join(' ')}`);
  }

  assert.ok(summary.source.metadata.duration > 80, 'the real 85-second railgun source must be used');
  assert.equal(summary.source.path, sourcePath);
  assert.ok(summary.source.maximumClipSourceEnd <= 8, 'only short source intervals may be rendered');
  assert.ok(Math.abs(summary.finalTimeline.duration - 2.4) < 1e-9);
  assert.equal(summary.finalProject.output.width, 320);
  assert.equal(summary.finalProject.output.height, 180);
  assert.equal(summary.finalProject.output.frameRate, 12);
  const videoTracks = summary.finalProject.tracks.filter((track) => track.kind === 'video');
  const audioTracks = summary.finalProject.tracks.filter((track) => track.kind === 'audio');
  assert.equal(videoTracks.length, 3);
  assert.equal(audioTracks.length, 2);
  assert.ok(audioTracks.every((track) => track.clips.length === 1));
  assert.ok(videoTracks.flatMap((track) => track.clips).some((clip) => clip.id === 'broll'));
  assert.equal(videoTracks.flatMap((track) => track.clips).filter((clip) => clip.type === 'text').length, 2);

  const diff = JSON.stringify(summary.history.diff.diff);
  assert.match(diff, /broken-transition/);
  assert.match(diff, /codecut_invalid_xfade/);
  assert.ok(!summary.history.undoClipIds.includes('broken-transition'));
  assert.ok(summary.history.redoClipIds.includes('broken-transition'));
  assert.ok(!summary.history.finalClipIds.includes('broken-transition'));
  assert.equal(summary.history.list.currentId, summary.revisions.finalUndo.id);
  assert.equal(summary.finalProject.revision, summary.revisions.finalUndo.projectRevision);
  assert.equal(summary.render.job.projectRevision, summary.finalProject.revision,
    'analysis, previews, and rendering must not add edit revisions');

  for (const analysis of [summary.analysis.scenes, summary.analysis.silence]) {
    assert.equal(analysis.shown.status, 'succeeded', JSON.stringify(analysis.shown.error));
    assert.equal(analysis.shown.kind, 'asset.analyze');
    assert.equal(analysis.shown.result.data.start, 0);
    assert.equal(analysis.shown.result.data.end, 8);
    assert.ok(analysis.shown.workerPid > 0, 'analysis must run in a detached worker');
  }
  assert.ok(Array.isArray(summary.analysis.scenes.result.points));
  assert.ok(Array.isArray(summary.analysis.silence.result.intervals));

  const jobIds = [
    summary.analysis.scenes.jobId,
    summary.analysis.silence.jobId,
    summary.previews.frame.job.id,
    summary.previews.sheet.job.id,
    summary.previews.proxy.job.id,
    summary.render.job.id,
    summary.failure.job.id,
  ];
  assert.equal(new Set(jobIds).size, jobIds.length);
  const persistedJobs = new Map();
  for (const id of jobIds) {
    const job = JSON.parse(await readFile(join(projectDirectory, '.codecut', 'jobs', id, 'job.json'), 'utf8'));
    persistedJobs.set(id, job);
    assert.ok(summary.jobs.some((listed) => listed.id === id), `jobs list omitted ${id}`);
  }
  assert.equal(summary.render.job.status, 'succeeded', JSON.stringify(summary.render.job.error));
  assert.equal(summary.render.shown.id, summary.render.job.id);
  assert.ok(summary.render.job.workerPid > 0, 'formal render must run detached');
  assert.equal(persistedJobs.get(summary.render.job.id).status, 'succeeded');
  assert.equal(persistedJobs.get(summary.render.job.id).validation.completeDecode, true);

  for (const [type, preview] of Object.entries(summary.previews)) {
    assert.equal(preview.job.status, 'succeeded', `${type}: ${JSON.stringify(preview.job.error)}`);
    assert.equal(preview.job.kind, `preview.${type}`);
    assert.equal(preview.job.validation.completeDecode, true);
    assert.equal(persistedJobs.get(preview.job.id).outputPath, preview.outputPath);
    assert.ok((await stat(preview.outputPath)).size > 0);
  }

  const frameProbe = await probe(summary.previews.frame.outputPath);
  assert.equal(frameProbe.streams[0].codec_name, 'png');
  assert.equal(frameProbe.streams[0].width, 320);
  assert.equal(frameProbe.streams[0].height, 180);
  const sheetProbe = await probe(summary.previews.sheet.outputPath);
  assert.equal(sheetProbe.streams[0].codec_name, 'png');
  assert.ok(sheetProbe.streams[0].width > 160);
  assert.ok(sheetProbe.streams[0].height > 90);
  assert.deepEqual(summary.previews.sheet.parameters.sampleTimes, [0, 0.6, 1.2, 1.8]);
  assert.equal(summary.previews.sheet.job.validation.timecodeBase, 'timeline');

  const finalMedia = await probe(summary.render.outputPath);
  assertMediaStreams(finalMedia, { width: 320, height: 180 }, 2.4);
  const proxyMedia = await probe(summary.previews.proxy.outputPath);
  assertMediaStreams(proxyMedia, { width: 160, height: 90 }, 2.4);
  assert.equal(summary.previews.proxy.job.validation.completeAudio, true);
  await decodeCompletely(summary.render.outputPath);
  await decodeCompletely(summary.previews.proxy.outputPath);

  const formalFrame = await rawFrame(summary.render.outputPath, 320, 180, summary.configuration.representativeTime);
  const previewFrame = await rawFrame(summary.previews.frame.outputPath, 320, 180);
  compareFrames(previewFrame, formalFrame);
  const renderPlan = JSON.parse(await readFile(summary.render.job.diagnostics.plan, 'utf8'));
  const filterGraph = await readFile(summary.render.job.diagnostics.filterGraph, 'utf8');
  assert.equal(renderPlan.durationSeconds, 2.4);
  assert.match(filterGraph, /drawtext=/);
  assert.match(filterGraph, /overlay=/);
  assert.match(filterGraph, /amix=inputs=5/);
  assert.equal(renderPlan.textFiles.length, 2);
  assert.ok(renderPlan.textFiles.some((entry) => entry.content === 'RAILGUN // CODECUT'));

  const finalAudio = await pcm(summary.render.outputPath, summary.configuration.representativeTime);
  const proxyAudio = await pcm(summary.previews.proxy.outputPath, summary.configuration.representativeTime);
  const audio = audioStats(finalAudio, proxyAudio);
  assert.ok(audio.leftRms > 0.0001, `formal representative audio is silent: ${JSON.stringify(audio)}`);
  assert.ok(audio.rightRms > 0.0001, `proxy representative audio is silent: ${JSON.stringify(audio)}`);
  assert.ok(audio.correlation > 0.8, `64 kbps proxy audio should track the formal mix: ${JSON.stringify(audio)}`);

  const failedJob = persistedJobs.get(summary.failure.job.id);
  assert.equal(summary.failure.commandStatus, 4);
  assert.equal(failedJob.status, 'failed');
  assert.ok(['MEDIA_PROCESS_FAILED', 'FFMPEG_PROGRESS_INVALID'].includes(failedJob.error.code),
    `unexpected injected failure: ${JSON.stringify(failedJob.error)}`);
  assert.equal(failedJob.projectRevision, summary.revisions.brokenEdit.projectRevision);
  const failureStderr = await readFile(failedJob.logs.stderr, 'utf8');
  assert.match(failureStderr, /codecut_invalid_xfade|xfade|transition/i);
  await assert.rejects(stat(join(projectDirectory, 'artifacts', 'injected-failure.mp4')), { code: 'ENOENT' });
  await assert.rejects(stat(failedJob.temporaryOutputPath), { code: 'ENOENT' });
  assert.equal(summary.failure.logs.command, 'logs');
  assert.ok(JSON.stringify(summary.failure.logs).includes(failedJob.id), 'logs CLI must identify the real failed job');
  assert.equal(summary.failure.diagnosis.command, 'diagnose');
  assert.equal(summary.doctor.command, 'doctor');

  const diagnosisPath = await diagnosisDirectory(
    summary.failure.diagnosis, projectDirectory, outputDirectory, failedJob.id,
  );
  const diagnosticFiles = await filesRecursively(diagnosisPath);
  assert.ok(diagnosticFiles.length >= 3, `diagnosis should contain multiple real artifacts: ${diagnosticFiles}`);
  assert.ok(diagnosticFiles.some((path) => /stderr|log/i.test(path)), 'diagnosis must retain process logs');
  assert.ok(diagnosticFiles.some((path) => /arguments|filter|job|request/i.test(path)),
    'diagnosis must retain the failed request or FFmpeg parameters');
  let diagnosticText = '';
  for (const path of diagnosticFiles) {
    if ((await stat(path)).size <= 2 * 1024 * 1024) diagnosticText += await readFile(path, 'utf8');
  }
  assert.ok(diagnosticText.includes(failedJob.id), 'diagnosis must reference the injected failed job');
  assert.match(diagnosticText, /MEDIA_PROCESS_FAILED|FFMPEG_PROGRESS_INVALID|codecut_invalid_xfade|xfade/i);
});
