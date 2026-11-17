import assert from 'node:assert/strict';
import { execFile } from 'node:child_process';
import { appendFile, mkdtemp, readFile, readdir, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import test from 'node:test';
import { applyEdit } from '../dist/edit.js';
import {
  diagnoseJob,
  followJobLogs,
  readJobLogs,
  redactDiagnosticText,
  runDoctor,
} from '../dist/diagnostics.js';
import { initProject } from '../dist/project.js';
import { JobService } from '../dist/jobs.js';

const root = dirname(dirname(fileURLToPath(import.meta.url)));
const cliPath = join(root, 'dist', 'cli.js');
const sleep = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds));

function cli(args) {
  return new Promise((resolve, reject) => {
    execFile(process.execPath, [cliPath, ...args], { cwd: root, maxBuffer: 16 * 1024 * 1024 }, (error, stdout, stderr) => {
      if (error && typeof error.code !== 'number') reject(error);
      else resolve({ status: error?.code ?? 0, stdout, stderr });
    });
  });
}

async function temporaryDirectory(t) {
  const directory = await mkdtemp(join(tmpdir(), 'codecut-diagnostics-test-'));
  t.after(() => rm(directory, { recursive: true, force: true }));
  return directory;
}

async function seedJob(directory, options = {}) {
  const { project, path: projectPath } = await initProject(directory);
  const mediaPath = join(directory, 'original-media.mov');
  await writeFile(mediaPath, 'ORIGINAL_MEDIA_SENTINEL', 'utf8');
  project.assets = [{ id: 'source', kind: 'video', path: 'original-media.mov' }];
  await writeFile(projectPath, JSON.stringify(project, null, 2), 'utf8');
  const snapshot = {
    version: 1,
    createdAt: new Date().toISOString(),
    projectRevision: project.revision,
    project,
    assets: [{ id: 'source', path: 'original-media.mov', exists: true, size: 23 }],
  };
  const service = new JobService({ projectDirectory: directory, pollMs: 5 });
  const created = await service.create({
    kind: 'render',
    process: {
      command: 'ffmpeg',
      args: ['--token', 'argument-secret', '-i', 'https://user:url-secret@example.test/source.mov'],
      env: { CODECUT_TEST_TOKEN: 'environment-secret', VISIBLE_VALUE: 'not-a-credential' },
    },
    output: { path: join(directory, 'preview.mp4'), overwrite: true },
    result: { data: { authorization: 'result-secret', outputPath: join(directory, 'preview.mp4') } },
    ...options.request,
  }, snapshot);
  const paths = service.store.paths(created.id);
  const argumentPath = join(paths.diagnostics, 'arguments.json');
  const filterPath = join(paths.diagnostics, 'filter_complex.txt');
  await writeFile(argumentPath, JSON.stringify({
    command: 'ffmpeg',
    args: ['--token', 'argument-secret', '-i', 'https://user:url-secret@example.test/source.mov'],
  }), 'utf8');
  await writeFile(filterPath, '[0:v]scale=1280:720,drawtext=text=\'token=filter-secret\'', 'utf8');
  const job = await service.store.update(created.id, (record) => {
    record.status = options.status ?? 'failed';
    record.stage = 'render.encode';
    record.progress = { percent: 42.5, frame: 12, timeSeconds: 1.5 };
    record.startedAt = record.createdAt;
    record.finishedAt = new Date().toISOString();
    record.heartbeatAt = new Date().toISOString();
    record.error = {
      code: 'MEDIA_PROCESS_FAILED',
      message: 'encoder failed with token=error-secret',
      stage: 'render.encode',
      jobId: record.id,
      retryable: true,
      diagnostics: { apiKey: 'error-key-secret' },
    };
    record.result = {
      exitCode: 1,
      data: { outputPath: join(directory, 'preview.mp4'), password: 'result-secret' },
    };
    record.diagnostics.arguments = argumentPath;
    record.diagnostics.filterGraph = filterPath;
  });
  await writeFile(job.logs.stdout, [
    '[info] ordinary output',
    '[debug] verbose decoder detail',
    JSON.stringify({ message: 'structured warning', stage: 'render.compose', level: 'warn', at: '2026-01-01T00:00:00.000Z' }),
    'token=stdout-secret',
  ].join('\n') + '\n', 'utf8');
  await writeFile(job.logs.stderr, '[warn] stderr warning\n{"token":"stderr-secret"}\n', 'utf8');
  await writeFile(join(paths.logs, 'progress.log'), '{"message":"frame=12","stage":"render.encode","level":"info"}\n', 'utf8');
  job.logs.progress = join(paths.logs, 'progress.log');
  await service.store.update(job.id, (record) => {
    record.logs.progress = job.logs.progress;
  });
  return { service, job: await service.store.get(job.id), projectPath, mediaPath };
}

test('doctor reports runtimes, filters, fonts, permissions, space, and locks without cleanup', async (t) => {
  const directory = await temporaryDirectory(t);
  await initProject(directory);
  const report = await runDoctor(directory);
  assert.equal(report.projectDirectory, directory);
  assert.equal(typeof report.ok, 'boolean');
  const names = new Set(report.checks.map((entry) => entry.name));
  for (const name of ['node', 'ffmpeg', 'ffprobe', 'project', 'fonts.default', 'permissions.project', 'permissions.temporary', 'lock.project', 'lock.jobs']) {
    assert.ok(names.has(name), `missing doctor check ${name}`);
  }
  if (report.checks.find((entry) => entry.name === 'ffmpeg')?.status === 'ok') assert.ok(names.has('ffmpeg.filters'));
  for (const entry of report.checks) assert.ok(['ok', 'warning', 'error'].includes(entry.status));
  assert.equal(report.checks.find((entry) => entry.name === 'node')?.status, 'ok');
  assert.equal(report.checks.find((entry) => entry.name === 'project')?.status, 'ok');
  assert.ok(report.checks.filter((entry) => entry.name.startsWith('permissions.')).every((entry) => typeof entry.details?.freeBytes === 'number'));
});

test('logs parse structured entries, filter every dimension, and retain only a bounded tail during a flood', async (t) => {
  const directory = await temporaryDirectory(t);
  const { job } = await seedJob(directory);
  const debug = await readJobLogs(directory, { jobId: job.id, stream: 'stdout', level: 'debug' });
  assert.deepEqual(debug.logs.map((entry) => entry.line), ['verbose decoder detail']);
  const staged = await readJobLogs(directory, { jobId: job.id, stage: 'render.compose' });
  assert.equal(staged.logs.length, 1);
  assert.equal(staged.logs[0].level, 'warn');
  assert.equal(staged.logs[0].at, '2026-01-01T00:00:00.000Z');
  const progress = await readJobLogs(directory, { jobId: job.id, stream: 'progress' });
  assert.deepEqual(progress.logs.map((entry) => entry.line), ['frame=12']);
  const empty = await readJobLogs(directory, { jobId: job.id, tail: 0 });
  assert.deepEqual(empty.logs, []);
  assert.equal(empty.truncated, true);

  const flood = Array.from({ length: 6000 }, (_, index) => `[info] flood-${index}`);
  await writeFile(job.logs.stdout, flood.join('\n') + '\n', 'utf8');
  const bounded = await readJobLogs(directory, { jobId: job.id, stream: 'stdout', tail: 25 });
  assert.equal(bounded.logs.length, 25);
  assert.equal(bounded.logs[0].line, 'flood-5975');
  assert.equal(bounded.logs.at(-1).line, 'flood-5999');
  assert.equal(bounded.truncated, true);
  assert.ok(bounded.logs.length <= 25);
});

test('follow emits appended lines, drains a terminal flood larger than one read chunk, and keeps JSON stdout as NDJSON', async (t) => {
  const directory = await temporaryDirectory(t);
  const { service, job } = await seedJob(directory, { status: 'running' });
  await writeFile(job.logs.stdout, '[info] initial\n', 'utf8');
  const observed = [];
  const following = (async () => {
    for await (const entry of followJobLogs(directory, { jobId: job.id, stream: 'stdout', tail: 1, pollMs: 2 })) {
      observed.push(entry.line);
    }
  })();
  await sleep(25);
  const flood = Array.from({ length: 9000 }, (_, index) => `[info] appended-${index}`);
  await appendFile(job.logs.stdout, flood.join('\n') + '\n', 'utf8');
  await service.store.update(job.id, (record) => {
    record.status = 'succeeded';
    record.stage = 'succeeded';
    record.error = undefined;
  });
  await Promise.race([
    following,
    sleep(5000).then(() => { throw new Error('follow did not drain and terminate'); }),
  ]);
  assert.equal(observed[0], 'initial');
  assert.ok(observed.includes('appended-0'));
  assert.equal(observed.at(-1), 'appended-8999');
  assert.equal(new Set(observed).size, observed.length, 'follow must not duplicate lines');

  const followed = await cli(['logs', job.id, '--project', directory, '--stream', 'stdout', '--tail', '3', '--follow', '--json']);
  assert.equal(followed.status, 0, followed.stderr);
  const lines = followed.stdout.trim().split('\n');
  assert.equal(lines.length, 3);
  for (const line of lines) {
    const value = JSON.parse(line);
    assert.equal(value.ok, true);
    assert.equal(value.command, 'logs');
    assert.equal(value.jobId, job.id);
  }
});

test('diagnose writes selective revision and asset diagnostics while omitting media, environment, and credentials', async (t) => {
  const directory = await temporaryDirectory(t);
  const { job } = await seedJob(directory);
  await applyEdit(directory, [{
    type: 'addClip', trackId: 'v1',
    clip: { id: 'background', type: 'color', color: '#010203', start: 0, duration: 2 },
  }], { summary: 'Add background' });
  await applyEdit(directory, [{
    type: 'addText', trackId: 'v1',
    clip: { id: 'title', type: 'text', text: 'Diagnostic title', start: 2, duration: 2 },
  }], { summary: 'Add title' });

  const result = await diagnoseJob({ projectDirectory: directory, jobId: job.id });
  t.after(() => rm(result.directory, { recursive: true, force: true }));
  const expected = ['environment.json', 'job.json', 'error.json', 'request.json', 'snapshot.json', 'assets.json', 'arguments.json', 'filter_complex.txt', 'stderr.log', 'stdout.log', 'progress.log', 'revisions.json', 'manifest.json'];
  for (const name of expected) assert.ok(result.files.includes(name), `missing ${name}`);
  assert.equal(new Set(result.files).size, result.files.length, 'manifest must not be duplicated');
  const diskFiles = await readdir(result.directory);
  assert.deepEqual([...diskFiles].sort(), result.files);
  assert.ok(diskFiles.every((name) => !/\.(?:mov|mp4|mp3|wav|png|jpg)$/i.test(name)));

  const request = JSON.parse(await readFile(join(result.directory, 'request.json'), 'utf8'));
  assert.equal(request.process.env, undefined);
  assert.deepEqual(request.process.args.slice(0, 2), ['--token', '[REDACTED]']);
  const environment = JSON.parse(await readFile(join(result.directory, 'environment.json'), 'utf8'));
  assert.equal(environment.env, undefined);
  assert.equal(environment.node, process.version);
  const assets = JSON.parse(await readFile(join(result.directory, 'assets.json'), 'utf8'));
  assert.equal(assets.capturedFiles[0].path, 'original-media.mov');
  const revisions = JSON.parse(await readFile(join(result.directory, 'revisions.json'), 'utf8'));
  assert.equal(revisions.revisions.length, 2);
  assert.equal(revisions.jobRevision, job.projectRevision);
  assert.equal(revisions.currentId, revisions.revisions.at(-1).id);
  const manifest = JSON.parse(await readFile(join(result.directory, 'manifest.json'), 'utf8'));
  assert.equal(manifest.sourceMediaIncluded, false);
  assert.equal(manifest.environmentVariablesIncluded, false);
  assert.ok(!manifest.files.includes('manifest.json'));

  const copied = await Promise.all(diskFiles.map((name) => readFile(join(result.directory, name), 'utf8')));
  const combined = copied.join('\n');
  for (const secret of ['argument-secret', 'url-secret', 'environment-secret', 'result-secret', 'error-secret', 'error-key-secret', 'filter-secret', 'stdout-secret', 'stderr-secret', 'ORIGINAL_MEDIA_SENTINEL']) {
    assert.ok(!combined.includes(secret), `diagnostics leaked ${secret}`);
  }
  assert.ok(combined.includes('[REDACTED]'));
  const redactedAuthorization = redactDiagnosticText('Authorization: Bearer bearer-secret');
  assert.ok(!redactedAuthorization.includes('bearer-secret'));
  assert.ok(redactedAuthorization.includes('[REDACTED]'));
});

test('normal, verbose, and debug output differ while successful JSON and error streams stay machine-safe', async (t) => {
  const directory = await temporaryDirectory(t);
  const { job } = await seedJob(directory);
  const normal = await cli(['logs', job.id, '--project', directory, '--stream', 'stdout', '--level', 'debug', '--json']);
  const verbose = await cli(['logs', job.id, '--project', directory, '--stream', 'stdout', '--level', 'debug', '--json', '--verbose']);
  const debug = await cli(['logs', job.id, '--project', directory, '--stream', 'stdout', '--level', 'debug', '--json', '--debug']);
  for (const result of [normal, verbose, debug]) {
    assert.equal(result.status, 0, result.stderr);
    assert.deepEqual(JSON.parse(result.stdout).logs.map((entry) => entry.line), ['verbose decoder detail']);
  }
  assert.equal(normal.stderr, '');
  assert.ok(verbose.stderr.includes('[verbose] logs completed'));
  assert.ok(!verbose.stderr.includes('[debug]'));
  assert.ok(debug.stderr.includes('[verbose] logs completed'));
  assert.ok(debug.stderr.includes('[debug] result fields:'));
  assert.ok(debug.stderr.length > verbose.stderr.length);

  const plainError = await cli(['not-a-command', '--json']);
  const verboseError = await cli(['not-a-command', '--json', '--verbose']);
  const debugError = await cli(['not-a-command', '--json', '--debug']);
  for (const result of [plainError, verboseError, debugError]) {
    assert.equal(result.status, 2);
    assert.equal(result.stdout, '');
    assert.equal(JSON.parse(result.stderr.split('\n[verbose]')[0].split('\n[debug]')[0]).error.code, 'USAGE_ERROR');
  }
  assert.ok(verboseError.stderr.length > plainError.stderr.length);
  assert.ok(debugError.stderr.length > verboseError.stderr.length);
  assert.match(debugError.stderr, /\[debug\][\s\S]*CodeCutError/);
});
