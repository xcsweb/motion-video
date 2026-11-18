import assert from 'node:assert/strict';
import { execFile } from 'node:child_process';
import { mkdir, mkdtemp, readFile, readdir, rm, stat, utimes, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import test from 'node:test';
import { initProject } from '../dist/project.js';
import { JobService } from '../dist/jobs.js';

const root = dirname(dirname(fileURLToPath(import.meta.url)));
const cliPath = join(root, 'dist', 'cli.js');

function cli(args) {
  return new Promise((resolve, reject) => {
    execFile(process.execPath, [cliPath, ...args], { cwd: root }, (error, stdout, stderr) => {
      if (error && typeof error.code !== 'number') reject(error);
      else resolve({ status: error?.code ?? 0, stdout, stderr });
    });
  });
}

async function temporaryDirectory(t) {
  const directory = await mkdtemp(join(tmpdir(), 'codecut-jobs-test-'));
  t.after(() => rm(directory, { recursive: true, force: true }));
  return directory;
}

function processSpec(source, args = [], extra = {}) {
  return { command: process.execPath, args: ['-e', source, ...args], ...extra };
}

function jobRequest(source, args = [], extra = {}) {
  return { kind: 'render', process: processSpec(source, args, extra.process), ...extra };
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function waitStatus(service, id, status, timeout = 5000) {
  const deadline = Date.now() + timeout;
  for (;;) {
    const job = await service.get(id);
    if (job.status === status || ['succeeded', 'failed', 'cancelled', 'timedOut', 'interrupted'].includes(job.status) && job.status !== status) return job;
    if (Date.now() > deadline) throw new Error(`Timed out waiting for ${status}: ${JSON.stringify(job)}`);
    await sleep(20);
  }
}

test('bounded concurrency is shared by all jobs and successful outputs are published', async (t) => {
  const directory = await temporaryDirectory(t);
  const service = new JobService({ projectDirectory: directory, maxConcurrency: 2, pollMs: 10 });
  const source = `
    const fs = require('fs'); const path = require('path');
    const directory = process.argv[1]; const output = process.argv[2];
    const marker = path.join(directory, 'active-' + process.pid);
    fs.writeFileSync(marker, '');
    const active = fs.readdirSync(directory).filter(name => name.startsWith('active-')).length;
    fs.appendFileSync(path.join(directory, 'observed'), String(active) + '\\n');
    setTimeout(() => { fs.writeFileSync(output, 'ok'); fs.unlinkSync(marker); }, 120);
  `;
  const jobs = await Promise.all(Array.from({ length: 6 }, (_, index) => service.enqueue(jobRequest(source, [directory, '{output}'], {
    output: { path: `parallel-${index}.txt` },
  }))));
  assert.deepEqual(jobs.map((job) => job.status), Array(6).fill('succeeded'));
  const observed = (await readFile(join(directory, 'observed'), 'utf8')).trim().split('\n').map(Number);
  assert.equal(observed.length, 6);
  assert.ok(Math.max(...observed) <= 2, `observed concurrency: ${observed}`);
  for (let index = 0; index < 6; index += 1) assert.equal(await readFile(join(directory, `parallel-${index}.txt`), 'utf8'), 'ok');
});

test('active cancellation preserves the old target and cleans temporary output', async (t) => {
  const directory = await temporaryDirectory(t);
  const output = join(directory, 'cancel.txt');
  await writeFile(output, 'old-output', 'utf8');
  const service = new JobService({ projectDirectory: directory, pollMs: 10, gracePeriodMs: 30 });
  const job = await service.create(jobRequest("const fs=require('fs');fs.writeFileSync(process.argv[1],'partial');setInterval(()=>{},1000)", ['{output}'], {
    output: { path: output, overwrite: true },
  }));
  const running = service.start(job.id);
  assert.equal((await waitStatus(service, job.id, 'running')).status, 'running');
  const stopping = await service.cancel(job.id);
  assert.ok(['stopping', 'cancelled'].includes(stopping.status));
  const cancelled = await running;
  assert.equal(cancelled.status, 'cancelled');
  assert.equal(cancelled.error.code, 'JOB_CANCELLED');
  assert.equal(await readFile(output, 'utf8'), 'old-output');
  await assert.rejects(stat(cancelled.temporaryOutputPath));
});

test('timeout preserves the old target and reaches the timedOut terminal state', async (t) => {
  const directory = await temporaryDirectory(t);
  const output = join(directory, 'timeout.txt');
  await writeFile(output, 'stable', 'utf8');
  const service = new JobService({ projectDirectory: directory, pollMs: 10 });
  const job = await service.enqueue({
    kind: 'render',
    process: {
      command: '/bin/sh',
      args: ['-c', 'trap "" TERM; printf partial > "$1"; while :; do :; done', 'sh', '{output}'],
    },
    output: { path: output, overwrite: true }, timeoutMs: 250, gracePeriodMs: 40,
  });
  assert.equal(job.status, 'timedOut');
  assert.equal(job.error.code, 'JOB_TIMED_OUT');
  assert.equal(job.result.forcefullyTerminated, true);
  assert.equal(job.result.signal, 'SIGKILL');
  assert.equal(await readFile(output, 'utf8'), 'stable');
  await assert.rejects(stat(job.temporaryOutputPath));
});

test('queued cancellation and worker startup failure have distinct terminal outcomes', async (t) => {
  const directory = await temporaryDirectory(t);
  const service = new JobService(directory);
  const queued = await service.create(jobRequest('setInterval(()=>{},1000)'));
  assert.equal((await service.cancel(queued.id)).status, 'cancelled');
  const started = await service.enqueue(jobRequest(''), {
    // Exercise the public enqueue shape without changing the queued request above.
  });
  assert.equal(started.status, 'succeeded');
  const missing = await service.enqueue({
    kind: 'render', process: { command: join(directory, 'not-found'), args: [] },
  });
  assert.equal(missing.status, 'failed');
  assert.equal(missing.error.code, 'PROCESS_START_FAILED');
  assert.equal(missing.startedAt, undefined);
});

test('stale heartbeat alone is not interrupted; a confirmed dead worker is', async (t) => {
  const directory = await temporaryDirectory(t);
  const service = new JobService({ projectDirectory: directory, heartbeatMs: 10, staleAfterMs: 20 });
  const stale = await service.create(jobRequest(''));
  await service.store.update(stale.id, (job) => {
    job.status = 'running';
    job.workerPid = process.pid;
    job.pid = process.pid;
    job.startedAt = new Date().toISOString();
    job.heartbeatAt = new Date(Date.now() - 1000).toISOString();
  });
  const marked = await service.get(stale.id);
  assert.equal(marked.status, 'running');
  assert.equal(marked.health, 'stale');

  const crashed = await service.create(jobRequest('setInterval(()=>{},1000)'));
  await service.store.update(crashed.id, (job) => {
    job.status = 'running';
    job.workerPid = 2147480000;
    job.pid = 2147480000;
    job.startedAt = new Date().toISOString();
    job.heartbeatAt = new Date().toISOString();
  });
  await writeFile(crashed.logs.stderr, 'crash diagnostics', 'utf8');
  const interrupted = await service.get(crashed.id);
  assert.equal(interrupted.status, 'interrupted');
  assert.equal(interrupted.error.code, 'WORKER_INTERRUPTED');
  assert.equal(await readFile(interrupted.logs.stderr, 'utf8'), 'crash diagnostics');
});

test('output path lock rejects concurrent replacement without nesting a project lock', async (t) => {
  const directory = await temporaryDirectory(t);
  const output = join(directory, 'locked.txt');
  await writeFile(output, 'original', 'utf8');
  const service = new JobService({ projectDirectory: directory, pollMs: 10 });
  const first = await service.create(jobRequest("const fs=require('fs');fs.writeFileSync(process.argv[1],'first');setInterval(()=>{},1000)", ['{output}'], {
    output: { path: output, overwrite: true },
  }));
  const running = service.start(first.id);
  await waitStatus(service, first.id, 'running');
  const second = await service.enqueue(jobRequest("require('fs').writeFileSync(process.argv[1],'second')", ['{output}'], {
    output: { path: output, overwrite: true },
  }));
  assert.equal(second.status, 'failed');
  assert.equal(second.error.code, 'OUTPUT_LOCKED');
  await service.cancel(first.id);
  assert.equal((await running).status, 'cancelled');
  assert.equal(await readFile(output, 'utf8'), 'original');
});

test('retry creates a new ID and replays the fixed project snapshot through the CLI', async (t) => {
  const directory = await temporaryDirectory(t);
  const { project, path } = await initProject(directory);
  project.revision = 7;
  project.assets = [{ id: 'source', kind: 'video', path: 'source.bin' }];
  await writeFile(join(directory, 'source.bin'), 'unchanged-source', 'utf8');
  await writeFile(path, JSON.stringify(project), 'utf8');
  const service = new JobService({ projectDirectory: directory, pollMs: 10 });
  const source = "const fs=require('fs');const p=JSON.parse(fs.readFileSync(process.argv[1]));fs.writeFileSync(process.argv[2],String(p.revision))";
  const original = await service.enqueue(jobRequest(source, ['{projectSnapshot}', '{output}'], {
    projectPath: path, output: { path: 'retry.txt', overwrite: true },
  }));
  assert.equal(original.status, 'succeeded');
  assert.equal(original.projectRevision, 7);
  const oldLog = await readFile(original.logs.stdout, 'utf8');
  project.revision = 99;
  await writeFile(path, JSON.stringify(project), 'utf8');

  const retried = await cli(['jobs', 'retry', original.id, '--project', directory, '--json']);
  assert.equal(retried.status, 0, retried.stderr);
  const replacement = JSON.parse(retried.stdout).job;
  assert.notEqual(replacement.id, original.id);
  assert.equal(replacement.retryOf, original.id);
  assert.equal(replacement.projectRevision, 7);
  assert.equal(replacement.status, 'succeeded');
  assert.equal(await readFile(join(directory, 'retry.txt'), 'utf8'), '7');
  assert.notEqual(replacement.logs.stdout, original.logs.stdout);
  assert.equal((await service.get(original.id)).status, 'succeeded');
  assert.equal(await readFile(original.logs.stdout, 'utf8'), oldLog);
});

test('detached worker runs across CLI processes; show/wait do not create jobs', async (t) => {
  const directory = await temporaryDirectory(t);
  const service = new JobService({ projectDirectory: directory, pollMs: 20, heartbeatMs: 20, staleAfterMs: 100 });
  const queued = await service.enqueue(jobRequest("setTimeout(()=>require('fs').writeFileSync(process.argv[1],'detached'),120)", ['{output}'], {
    output: { path: 'detached.txt' },
  }), { detach: true });
  assert.notEqual(queued.workerPid, process.pid);
  const completed = await service.wait(queued.id);
  assert.equal(completed.status, 'succeeded');
  assert.equal(await readFile(join(directory, 'detached.txt'), 'utf8'), 'detached');

  const shown = await cli(['jobs', 'show', queued.id, '--project', directory, '--json']);
  assert.equal(shown.status, 0, shown.stderr);
  const showData = JSON.parse(shown.stdout).job;
  assert.equal(showData.pid > 0, true);
  assert.equal(showData.workerPid > 0, true);
  assert.equal(showData.projectRevision, 0);
  assert.equal(showData.stage, 'succeeded');
  assert.equal(showData.logs.stdout.includes(queued.id), true);

  const before = (await service.list()).length;
  const waited = await cli(['jobs', 'wait', queued.id, '--project', directory, '--json']);
  assert.equal(waited.status, 0, waited.stderr);
  assert.equal(JSON.parse(waited.stdout).job.id, queued.id);
  assert.equal((await service.list()).length, before);
  const listed = await cli(['jobs', 'list', '--project', directory, '--status', 'succeeded', '--json']);
  assert.equal(listed.status, 0, listed.stderr);
  assert.equal(JSON.parse(listed.stdout).jobs.length, before);
});

test('jobs cancel terminates a detached worker through the shared service', async (t) => {
  const directory = await temporaryDirectory(t);
  const service = new JobService({ projectDirectory: directory, pollMs: 20, heartbeatMs: 20, staleAfterMs: 100 });
  const queued = await service.enqueue(jobRequest('setInterval(()=>{},1000)'), { detach: true });
  const running = await waitStatus(service, queued.id, 'running');
  assert.equal(running.status, 'running');
  const cancelled = await cli(['jobs', 'cancel', queued.id, '--project', directory, '--json']);
  assert.equal(cancelled.status, 0, cancelled.stderr);
  const waited = await cli(['jobs', 'wait', queued.id, '--project', directory, '--json']);
  assert.equal(waited.status, 6, `${waited.stdout}\n${waited.stderr}`);
  const job = JSON.parse(waited.stdout).job;
  assert.equal(job.status, 'cancelled');
  assert.equal(job.error.code, 'JOB_CANCELLED');
});

test('a crashed detached worker becomes interrupted, terminates its child, and retains logs', async (t) => {
  const directory = await temporaryDirectory(t);
  const service = new JobService({ projectDirectory: directory, pollMs: 20, heartbeatMs: 20, staleAfterMs: 100 });
  const queued = await service.enqueue(jobRequest("process.stderr.write('worker started');setInterval(()=>{},1000)"), { detach: true });
  const running = await waitStatus(service, queued.id, 'running');
  assert.equal(running.status, 'running');
  const mediaPid = running.pid;
  if (mediaPid) t.after(() => { try { process.kill(mediaPid, 'SIGKILL'); } catch { /* already exited */ } });
  for (let attempt = 0; attempt < 100; attempt += 1) {
    if ((await readFile(running.logs.stderr, 'utf8')).includes('worker started')) break;
    await sleep(20);
  }
  process.kill(running.workerPid, 'SIGKILL');
  const interrupted = await service.wait(queued.id);
  assert.equal(interrupted.status, 'interrupted');
  assert.equal(interrupted.error.code, 'WORKER_INTERRUPTED');
  const shown = await service.show(queued.id);
  assert.match(shown.logTail.stderr, /worker started/);
  if (mediaPid) {
    let alive = true;
    for (let attempt = 0; attempt < 100 && alive; attempt += 1) {
      try { process.kill(mediaPid, 0); } catch { alive = false; }
      if (alive) await sleep(10);
    }
    assert.equal(alive, false, 'orphaned media process should be terminated');
  }
});

test('ownerless job and concurrency locks are recovered after the initialization crash window', async (t) => {
  const directory = await temporaryDirectory(t);
  const service = new JobService({ projectDirectory: directory, maxConcurrency: 1, pollMs: 10 });
  const queued = await service.create(jobRequest(''));
  const old = new Date(Date.now() - 2_000);
  const jobLock = join(directory, '.codecut', 'locks', 'jobs', `${queued.id}.lock`);
  await mkdir(jobLock, { recursive: true });
  await utimes(jobLock, old, old);
  const updated = await service.store.update(queued.id, (job) => { job.stage = 'recovered'; });
  assert.equal(updated.stage, 'recovered');

  const slotLock = join(directory, '.codecut', 'locks', 'slots', '0.lock');
  await mkdir(slotLock, { recursive: true });
  await utimes(slotLock, old, old);
  const completed = await service.start(queued.id);
  assert.equal(completed.status, 'succeeded');
  await assert.rejects(stat(slotLock));
});

test('output directory and validation diagnostic write failures are stable disk errors', async (t) => {
  const directory = await temporaryDirectory(t);
  const service = new JobService({ projectDirectory: directory, pollMs: 10 });
  const blocked = join(directory, 'blocked');
  await writeFile(blocked, 'not a directory', 'utf8');
  const preflight = await service.enqueue(jobRequest('', [], {
    output: { path: join(blocked, 'output.txt') },
  }));
  assert.equal(preflight.status, 'failed');
  assert.equal(preflight.error.code, 'DISK_WRITE_FAILED');
  assert.equal(preflight.stage, 'jobs.preflight');

  const queued = await service.create(jobRequest("require('fs').writeFileSync(process.argv[1],'complete')", ['{output}'], {
    output: { path: 'validated.txt' },
  }));
  const diagnostics = service.store.paths(queued.id).diagnostics;
  await rm(diagnostics, { recursive: true, force: true });
  await writeFile(diagnostics, 'not a directory', 'utf8');
  const validation = await service.start(queued.id);
  assert.equal(validation.status, 'failed');
  assert.equal(validation.error.code, 'DISK_WRITE_FAILED');
  assert.equal(validation.error.stage, 'output.validate');
  assert.equal(validation.stage, 'output.validate');
  await assert.rejects(stat(validation.temporaryOutputPath));
});

test('invalid ffprobe JSON is an output validation failure', async (t) => {
  const directory = await temporaryDirectory(t);
  const service = new JobService({ projectDirectory: directory, pollMs: 10 });
  const job = await service.enqueue(jobRequest("require('fs').writeFileSync(process.argv[1],'media')", ['{output}'], {
    output: { path: 'probe.bin', validation: 'ffprobe', ffprobePath: process.execPath },
  }));
  assert.equal(job.status, 'failed');
  assert.equal(job.error.code, 'OUTPUT_VALIDATION_FAILED');
  assert.equal(job.error.stage, 'output.validate');
  assert.match(job.error.message, /invalid JSON/);
});

test('SIGINT to a detached worker uses the shared cancellation lifecycle', async (t) => {
  const directory = await temporaryDirectory(t);
  const service = new JobService({ projectDirectory: directory, pollMs: 20, heartbeatMs: 20, staleAfterMs: 100 });
  const queued = await service.enqueue(jobRequest('setInterval(()=>{},1000)'), { detach: true });
  const running = await waitStatus(service, queued.id, 'running');
  assert.equal(running.status, 'running');
  const workerPid = running.workerPid;
  const mediaPid = running.pid;
  t.after(() => {
    for (const pid of [workerPid, mediaPid]) {
      if (pid) try { process.kill(pid, 'SIGKILL'); } catch { /* already exited */ }
    }
  });
  process.kill(workerPid, 'SIGINT');
  const cancelled = await service.wait(queued.id);
  assert.equal(cancelled.status, 'cancelled');
  assert.equal(cancelled.error.code, 'JOB_CANCELLED');
  assert.equal(cancelled.stage, 'cancelled');
});
