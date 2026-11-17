import assert from 'node:assert/strict';
import { execFile } from 'node:child_process';
import { mkdtemp, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import test from 'node:test';
import { nextTick } from 'vue';
import { applyEdit } from '../dist/edit.js';
import { readJobLogs } from '../dist/diagnostics.js';
import { listHistory } from '../dist/history.js';
import { JobService } from '../dist/jobs.js';
import { initProject } from '../dist/project.js';
import { createDashboardSession } from '../dist/ui.js';
import { createUiLogAdapter } from '../dist/ui-log.js';

const root = dirname(dirname(fileURLToPath(import.meta.url)));
const cliPath = join(root, 'dist', 'cli.js');
const sleep = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds));

function cli(args) {
  return new Promise((resolve, reject) => {
    execFile(process.execPath, [cliPath, ...args], { cwd: root, maxBuffer: 8 * 1024 * 1024 }, (error, stdout, stderr) => {
      if (error && typeof error.code !== 'number') reject(error);
      else resolve({ status: error?.code ?? 0, stdout, stderr });
    });
  });
}

async function temporaryDirectory(t) {
  const directory = await mkdtemp(join(tmpdir(), 'codecut-ui-test-'));
  t.after(() => rm(directory, { recursive: true, force: true }));
  return directory;
}

async function waitFor(predicate, message, timeout = 5000) {
  const deadline = Date.now() + timeout;
  for (;;) {
    const value = await predicate();
    if (value) return value;
    if (Date.now() > deadline) throw new Error(message);
    await sleep(15);
  }
}

async function flushDashboard(session) {
  await nextTick();
  session.app.scheduler.flushNow();
  await nextTick();
  session.app.scheduler.flushNow();
}

async function press(session, key, extra = {}) {
  session.app.events.dispatch({ type: 'keydown', key, ...extra });
  await flushDashboard(session);
}

async function seedProject(directory, withHistory = false) {
  const initialized = await initProject(directory);
  let project = initialized.project;
  if (withHistory) {
    await applyEdit(directory, [{
      type: 'addClip', trackId: 'v1',
      clip: { id: 'background', type: 'color', color: '#010203', start: 0, duration: 2 },
    }], { summary: 'Add background' });
    const second = await applyEdit(directory, [{
      type: 'addText', trackId: 'v1',
      clip: { id: 'title', type: 'text', text: 'Dashboard title', start: 2, duration: 2 },
    }], { summary: 'Add dashboard title' });
    project = second.project;
  }
  return project;
}

function snapshotFor(project) {
  return {
    version: 1,
    createdAt: new Date().toISOString(),
    projectRevision: project.revision,
    project,
    assets: [],
  };
}

function request(source = '') {
  return {
    kind: 'render',
    process: { command: process.execPath, args: ['-e', source] },
  };
}

const fallbackLogs = { maxLines: 30, loadExperimental: async () => { throw new Error('intentional adapter fallback'); } };

test('codecut ui rejects non-TTY execution with a JSON usage error and automation alternatives', async () => {
  const result = await cli(['ui', '--json']);
  assert.equal(result.status, 2);
  assert.equal(result.stdout, '');
  const payload = JSON.parse(result.stderr);
  assert.equal(payload.error.code, 'USAGE_ERROR');
  assert.equal(payload.error.stage, 'ui');
  assert.match(payload.error.message, /interactive TTY/);
  assert.match(payload.error.message, /jobs list --json/);
  assert.match(payload.error.message, /logs --json/);
});

test('the real experimental log store and isolated fallback both enforce bounded retention', async () => {
  const experimental = await createUiLogAdapter({ maxLines: 3 });
  assert.equal(experimental.mode, 'experimental');
  experimental.appendLines(Array.from({ length: 5000 }, (_, index) => `line-${index}`));
  assert.equal(experimental.source.lineCount(), 3);
  assert.deepEqual(experimental.lines(), ['line-4997', 'line-4998', 'line-4999']);
  experimental.dispose();
  assert.equal(experimental.source.lineCount(), 0);

  for (const loadExperimental of [
    async () => { throw new Error('experimental API unavailable'); },
    async () => ({ incompatible: true }),
  ]) {
    const fallback = await createUiLogAdapter({ maxLines: 3, loadExperimental });
    assert.equal(fallback.mode, 'fallback');
    assert.equal(fallback.component, undefined);
    fallback.appendLines(['one', 'two', 'three', 'four']);
    assert.deepEqual(fallback.lines(), ['two', 'three', 'four']);
    assert.equal(fallback.source.lineCount(), 3);
    fallback.clear();
    assert.deepEqual(fallback.lines(), []);
    fallback.dispose();
  }
});

test('headless Vue TUI matches CLI job/log/revision state, renders paths, resizes, and cleans up', async (t) => {
  const directory = await temporaryDirectory(t);
  const project = await seedProject(directory, true);
  const service = new JobService({ projectDirectory: directory, pollMs: 5 });
  const created = await service.create(request(), snapshotFor(project));
  const filterGraph = join(service.store.paths(created.id).diagnostics, 'filter_complex.txt');
  await writeFile(filterGraph, '[0:v]scale=640:360', 'utf8');
  const outputPath = join(directory, 'preview.mp4');
  const seeded = await service.store.update(created.id, (job) => {
    job.status = 'failed';
    job.stage = 'render.encode';
    job.progress = { percent: 67.5, frame: 30 };
    job.error = { code: 'MEDIA_PROCESS_FAILED', message: 'expected fixture failure', stage: 'render.encode', jobId: job.id };
    job.outputPath = outputPath;
    job.result = { exitCode: 1, outputPath, data: { outputPath } };
    job.diagnostics.filterGraph = filterGraph;
  });
  await writeFile(seeded.logs.stdout, '[info] dashboard stdout\n[debug] dashboard debug\n', 'utf8');
  await writeFile(seeded.logs.stderr, '[error] dashboard stderr\n', 'utf8');

  const session = await createDashboardSession({ projectDirectory: directory, cols: 180, rows: 48, logAdapter: { maxLines: 20 } });
  t.after(() => session.dispose());
  assert.equal(session.logAdapter.mode, 'experimental');
  const cliJob = JSON.parse((await cli(['jobs', 'show', seeded.id, '--project', directory, '--json'])).stdout).job;
  const selected = session.controller.state.selectedJob;
  assert.equal(selected.id, cliJob.id);
  assert.equal(selected.status, cliJob.status);
  assert.equal(selected.stage, cliJob.stage);
  assert.deepEqual(selected.progress, cliJob.progress);
  assert.equal(selected.diagnostics.directory, cliJob.diagnostics.directory);
  assert.equal(selected.diagnostics.filterGraph, cliJob.diagnostics.filterGraph);
  assert.equal(selected.outputPath, cliJob.outputPath);
  assert.deepEqual(selected.logTail, cliJob.logTail);

  const expectedLogs = await readJobLogs(directory, { jobId: seeded.id, tail: 20 });
  assert.deepEqual(session.logAdapter.lines(), expectedLogs.logs.map((entry) => `[${entry.level}] ${entry.stream}: ${entry.line}`));
  const history = await listHistory(directory);
  const current = history.revisions.find((revision) => revision.id === history.currentId);
  const cliDiff = JSON.parse((await cli(['history', 'diff', current.parentId, current.id, '--project', directory, '--json'])).stdout).diff;
  assert.deepEqual(session.controller.state.revisionDiff, cliDiff);
  assert.match(session.controller.state.revisions, /Add dashboard title/);

  await flushDashboard(session);
  let snapshot = session.app.terminal.snapshot().lines.join('\n');
  assert.match(snapshot, /CodeCut diagnostics/);
  assert.match(snapshot, new RegExp(seeded.id));
  assert.match(snapshot, /Status: failed/);
  assert.match(snapshot, /Progress: 67\.5%/);
  assert.match(snapshot, /Diagnostics:/);
  assert.match(snapshot, /Preview\/output:/);
  assert.match(snapshot, /Revision:/);
  assert.match(snapshot, /Logs \(experimental\)/);

  session.app.terminal.resize(96, 34);
  await flushDashboard(session);
  assert.deepEqual(session.app.terminal.size(), { cols: 96, rows: 34 });
  snapshot = session.app.terminal.snapshot();
  assert.equal(snapshot.lines.length, 34);
  assert.ok(snapshot.lines.every((line) => line.length <= 96));
  assert.match(snapshot.lines.join('\n'), /CodeCut diagnostics/);

  const nodesBeforeDispose = session.app.events.debugNodes().length;
  assert.ok(nodesBeforeDispose > 0);
  await press(session, 'q');
  await session.closed;
  assert.equal(session.controller.state.closed, true);
  session.dispose();
  assert.equal(session.app.events.debugNodes().length, 0);
  assert.equal(session.app.events.getFocused(), null);
  assert.equal(session.logAdapter.source.lineCount(), 0);
});

test('real keyboard events select jobs, cancel and retry through JobService, then dispose terminal resources', async (t) => {
  const directory = await temporaryDirectory(t);
  const project = await seedProject(directory);
  const service = new JobService({ projectDirectory: directory, pollMs: 10, heartbeatMs: 20, staleAfterMs: 100 });
  const first = await service.create(request(), snapshotFor(project));
  const second = await service.create(request(), snapshotFor(project));
  assert.ok(first.id && second.id);
  const session = await createDashboardSession({ projectDirectory: directory, service, cols: 120, rows: 40, logAdapter: fallbackLogs });
  t.after(() => session.dispose());
  await waitFor(() => session.controller.state.jobs.length === 2, 'dashboard did not list jobs');
  const initialIndex = session.controller.state.selectedIndex;
  await press(session, 'ArrowDown');
  assert.equal(session.controller.state.selectedIndex, (initialIndex + 1) % 2);
  await session.refresh();
  await press(session, 'k');
  assert.equal(session.controller.state.selectedIndex, initialIndex);
  await session.refresh();

  const targetId = session.controller.state.selectedJob.id;
  await press(session, 'c');
  await waitFor(async () => (await service.get(targetId)).status === 'cancelled', 'keyboard cancel did not call JobService');
  assert.equal((await service.get(targetId)).error.code, 'JOB_CANCELLED');

  await press(session, 'r');
  const replacement = await waitFor(async () => {
    const jobs = await service.list();
    return jobs.find((job) => job.retryOf === targetId);
  }, 'keyboard retry did not create a detached replacement');
  assert.notEqual(replacement.id, targetId);
  assert.equal(replacement.retryOf, targetId);
  const completed = await service.wait(replacement.id);
  assert.equal(completed.status, 'succeeded');
  assert.equal((await service.get(targetId)).status, 'cancelled');

  await session.refresh();
  await flushDashboard(session);
  assert.equal(session.controller.state.selectedJob.id, replacement.id);
  await press(session, 'R');
  await press(session, 'q');
  await session.closed;
  session.dispose();
  assert.equal(session.app.events.debugNodes().length, 0);
  assert.equal(session.logAdapter.source.lineCount(), 0);
  const selectedAfterDispose = session.controller.state.selectedJob.id;
  await press(session, 'ArrowDown');
  assert.equal(session.controller.state.selectedJob.id, selectedAfterDispose);
});

test('quitting the dashboard leaves a real detached job running to successful completion', async (t) => {
  const directory = await temporaryDirectory(t);
  const project = await seedProject(directory);
  const service = new JobService({ projectDirectory: directory, pollMs: 10, heartbeatMs: 20, staleAfterMs: 100 });
  const detached = await service.create(request('setTimeout(() => {}, 350)'), snapshotFor(project));
  await service.start(detached.id, { detach: true });
  t.after(async () => {
    try {
      const job = await service.store.get(detached.id);
      if (!['succeeded', 'failed', 'cancelled', 'timedOut', 'interrupted'].includes(job.status)) await service.cancel(detached.id);
    } catch (error) {
      if (error?.code !== 'JOB_NOT_FOUND') throw error;
    }
  });
  assert.notEqual((await service.get(detached.id)).workerPid, process.pid);

  const session = await createDashboardSession({ projectDirectory: directory, service, jobId: detached.id, cols: 110, rows: 36, logAdapter: fallbackLogs });
  await press(session, 'q');
  await session.closed;
  session.dispose();
  const afterExit = await service.get(detached.id);
  assert.notEqual(afterExit.status, 'cancelled');
  assert.notEqual(afterExit.cancelReason, 'cancelled');
  const completed = await service.wait(detached.id);
  assert.equal(completed.status, 'succeeded');
});
