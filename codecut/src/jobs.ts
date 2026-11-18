import { execa } from 'execa';
import { spawn } from 'node:child_process';
import { randomBytes } from 'node:crypto';
import {
  link,
  mkdir,
  readFile,
  rename,
  rm,
  stat,
  unlink,
  writeFile,
} from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { dirname, join, resolve } from 'node:path';
import { parseAnalysisLog } from './analysis.js';
import { asCodeCutError, CodeCutError, ExitCode } from './errors.js';
import { acquireOutputLock, processExists, type OutputLock } from './output-lock.js';
import {
  executeControlledProcess,
  ProcessController,
  readBoundedLogTail,
  type ProcessExecutionResult,
  type ProcessSpec,
  type ProgressState,
  type StopReason,
} from './process.js';
import { loadProject } from './project.js';
import { validateRenderOutput, validateTimelinePreviewOutput } from './render-runtime.js';
import {
  isTerminalJob,
  JobStore,
  type AssetSnapshot,
  type JobRecord,
  type JobRequest,
  type JobStatus,
  type ProjectSnapshot,
} from './jobs-store.js';

export interface JobServiceOptions {
  projectDirectory: string;
  storeDirectory?: string;
  maxConcurrency?: number;
  heartbeatMs?: number;
  staleAfterMs?: number;
  pollMs?: number;
  gracePeriodMs?: number;
  tailBytes?: number;
}

export interface StartOptions {
  detach?: boolean;
}

export interface RetryOptions extends StartOptions {}

export interface WaitOptions {
  signal?: AbortSignal;
}

export interface JobRunHooks {
  validateOutput?: (temporaryPath: string, job: JobRecord) => Promise<unknown>;
}

interface Lease {
  release(): Promise<void>;
}

const sleep = (milliseconds: number) => new Promise<void>((resolveSleep) => setTimeout(resolveSleep, milliseconds));

function now(): string {
  return new Date().toISOString();
}

function jobErrorPayload(error: unknown, id: string, diagnostics?: unknown): NonNullable<JobRecord['error']> {
  const normalized = asCodeCutError(error, 'jobs.run');
  const payload = normalized.toJSON();
  const originalDiagnostics = payload.diagnostics;
  return {
    ...payload,
    jobId: id,
    ...(diagnostics === undefined ? {} : {
      diagnostics: {
        ...(typeof originalDiagnostics === 'object' && originalDiagnostics !== null ? originalDiagnostics : {}),
        ...diagnostics as Record<string, unknown>,
      },
    }),
  };
}

function cancellationError(reason: StopReason, id: string): CodeCutError {
  return reason === 'timedOut'
    ? new CodeCutError('JOB_TIMED_OUT', 'Job exceeded its execution timeout and was terminated', ExitCode.Timeout, {
      stage: 'process.timeout', jobId: id, retryable: true,
    })
    : new CodeCutError('JOB_CANCELLED', 'Job was cancelled and its process was terminated', ExitCode.Cancelled, {
      stage: 'process.cancel', jobId: id, retryable: false,
    });
}

export function exitCodeForJob(job: JobRecord): ExitCode {
  if (job.status === 'succeeded') return ExitCode.Success;
  if (job.status === 'timedOut') return ExitCode.Timeout;
  if (job.status === 'cancelled') return ExitCode.Cancelled;
  if (job.status === 'failed' && (['MEDIA_PROCESS_FAILED', 'WORKER_START_FAILED', 'PROCESS_START_FAILED', 'FFMPEG_PROGRESS_INVALID', 'OUTPUT_VALIDATION_FAILED', 'ASSET_SNAPSHOT_CHANGED', 'ASSET_SNAPSHOT_MISSING', 'OUTPUT_LOCKED', 'ANALYSIS_RESULT_INVALID'].includes(job.error?.code ?? '') || job.error?.code.startsWith('ASSET_FILE_'))) {
    return ExitCode.Media;
  }
  if (job.status === 'failed' && ['OUTPUT_EXISTS', 'USAGE_ERROR', 'JOB_NOT_FOUND'].includes(job.error?.code ?? '')) return ExitCode.Usage;
  return ExitCode.Internal;
}

export function errorForJob(job: JobRecord): CodeCutError | undefined {
  if (!job.error || job.status === 'succeeded') return undefined;
  return new CodeCutError(job.error.code, job.error.message, exitCodeForJob(job), {
    stage: job.error.stage,
    jobId: job.id,
    ...(job.error.path === undefined ? {} : { path: job.error.path }),
    ...(job.error.retryable === undefined ? {} : { retryable: job.error.retryable }),
    ...(job.error.diagnostics === undefined ? {} : { diagnostics: job.error.diagnostics }),
  });
}

export class JobService {
  readonly store: JobStore;
  readonly maxConcurrency: number;
  private readonly heartbeatMs: number;
  private readonly staleAfterMs: number;
  private readonly pollMs: number;
  private readonly gracePeriodMs: number;
  private readonly tailBytes: number;
  private readonly active = new Map<string, ProcessController>();

  constructor(options: JobServiceOptions | string) {
    const normalized = typeof options === 'string' ? { projectDirectory: options } : options;
    this.store = new JobStore(normalized.projectDirectory, normalized.storeDirectory);
    this.maxConcurrency = Math.max(1, Math.floor(normalized.maxConcurrency ?? 2));
    this.heartbeatMs = Math.max(10, normalized.heartbeatMs ?? 1_000);
    this.staleAfterMs = Math.max(this.heartbeatMs * 2, normalized.staleAfterMs ?? 10_000);
    this.pollMs = Math.max(10, normalized.pollMs ?? 100);
    this.gracePeriodMs = Math.max(0, normalized.gracePeriodMs ?? 5_000);
    this.tailBytes = Math.max(256, normalized.tailBytes ?? 64 * 1024);
  }

  private async captureSnapshot(projectPath: string): Promise<ProjectSnapshot> {
    const { project, path } = await loadProject(projectPath, 'jobs.snapshot');
    const projectDirectory = dirname(path);
    const assets: AssetSnapshot[] = [];
    for (const asset of project.assets) {
      const assetPath = resolve(projectDirectory, asset.path);
      try {
        const information = await stat(assetPath);
        assets.push({ id: asset.id, path: asset.path, exists: true, size: information.size, mtimeMs: information.mtimeMs });
      } catch (error) {
        if ((error as NodeJS.ErrnoException).code !== 'ENOENT') throw error;
        assets.push({ id: asset.id, path: asset.path, exists: false });
      }
    }
    return {
      version: 1,
      createdAt: now(),
      projectRevision: project.revision,
      project,
      assets,
    };
  }

  private prepareRequest(request: JobRequest): JobRequest {
    return {
      ...request,
      ...(request.projectPath ? { projectPath: resolve(this.store.projectDirectory, request.projectPath) } : {}),
      process: {
        ...request.process,
        args: [...request.process.args],
        ...(request.process.env ? { env: { ...request.process.env } } : {}),
      },
      ...(request.output ? {
        output: {
          ...request.output,
          path: resolve(this.store.projectDirectory, request.output.path),
        },
      } : {}),
      ...(request.result ? {
        result: {
          ...request.result,
          ...(request.result.data ? { data: { ...request.result.data } } : {}),
          ...(request.result.cacheManifestPath ? {
            cacheManifestPath: resolve(this.store.projectDirectory, request.result.cacheManifestPath),
          } : {}),
          ...(request.result.cacheManifest ? { cacheManifest: { ...request.result.cacheManifest } } : {}),
        },
      } : {}),
      ...(request.analysis ? { analysis: { ...request.analysis } } : {}),
      ...(request.render ? { render: { ...request.render, plan: structuredClone(request.render.plan) } } : {}),
      ...(request.preview ? { preview: structuredClone(request.preview) } : {}),
    };
  }

  async create(request: JobRequest, fixedSnapshot?: ProjectSnapshot): Promise<JobRecord> {
    const prepared = this.prepareRequest(request);
    const snapshot = fixedSnapshot ?? (prepared.projectPath ? await this.captureSnapshot(prepared.projectPath) : undefined);
    return this.store.create(prepared, snapshot);
  }

  async enqueue(request: JobRequest, options: StartOptions = {}): Promise<JobRecord> {
    const job = await this.create(request);
    return this.start(job.id, options);
  }

  async submit(request: JobRequest, options: StartOptions = {}): Promise<JobRecord> {
    return this.enqueue(request, options);
  }

  async start(id: string, options: StartOptions = {}): Promise<JobRecord> {
    return options.detach ? this.detach(id) : this.runJob(id);
  }

  private workerArguments(id: string): string[] {
    const cliPath = fileURLToPath(new URL('./cli.js', import.meta.url));
    return [
      cliPath,
      'jobs', 'worker', id,
      '--project', this.store.projectDirectory,
      '--concurrency', String(this.maxConcurrency),
      '--heartbeat-ms', String(this.heartbeatMs),
      '--stale-ms', String(this.staleAfterMs),
      '--grace-ms', String(this.gracePeriodMs),
      '--tail-bytes', String(this.tailBytes),
    ];
  }

  private async detach(id: string): Promise<JobRecord> {
    const job = await this.store.get(id);
    if (isTerminalJob(job) || job.status === 'running' || job.status === 'stopping') return job;
    const child = spawn(process.execPath, this.workerArguments(id), {
      detached: true,
      stdio: 'ignore',
      env: { ...process.env },
    });
    try {
      await new Promise<void>((resolveSpawn, rejectSpawn) => {
        child.once('spawn', () => resolveSpawn());
        child.once('error', rejectSpawn);
      });
      const workerPid = child.pid;
      if (workerPid !== undefined) {
        await this.store.update(id, (current) => {
          if (current.status === 'queued') {
            current.workerPid = workerPid;
            current.heartbeatAt = now();
          }
        });
      }
      child.unref();
      return this.store.get(id);
    } catch (error) {
      const failed = await this.store.update(id, (current) => {
        if (!isTerminalJob(current)) {
          current.status = 'failed';
          current.stage = 'process.spawn';
          current.finishedAt = now();
          current.error = jobErrorPayload(new CodeCutError('WORKER_START_FAILED', 'Could not start detached worker', ExitCode.Media, {
            stage: 'process.spawn', jobId: id, cause: error, retryable: true,
          }), id);
        }
      });
      return failed;
    }
  }

  private async recover(job: JobRecord): Promise<JobRecord> {
    if (isTerminalJob(job)) return job;
    if (job.status === 'queued' && job.workerPid !== undefined && !processExists(job.workerPid)) {
      return this.store.update(job.id, (current) => {
        if (current.status !== 'queued') return;
        current.status = 'failed';
        current.health = 'stale';
        current.stage = 'process.spawn';
        current.finishedAt = now();
        current.error = jobErrorPayload(new CodeCutError('WORKER_START_FAILED', 'Detached worker exited before starting the job', ExitCode.Media, {
          stage: 'process.spawn', jobId: job.id, retryable: true,
          diagnostics: { workerPid: job.workerPid },
        }), job.id);
      });
    }
    if (job.status !== 'running' && job.status !== 'stopping') return job;
    if (job.workerPid !== undefined && !processExists(job.workerPid)) {
      const interrupted = await this.store.update(job.id, (current) => {
        if (current.status !== 'running' && current.status !== 'stopping') return;
        current.status = 'interrupted';
        current.health = 'stale';
        current.stage = 'worker.interrupted';
        current.finishedAt = now();
        current.error = jobErrorPayload(new CodeCutError('WORKER_INTERRUPTED', 'Worker process disappeared without a terminal job state', ExitCode.Internal, {
          stage: 'worker.interrupted', jobId: job.id, retryable: true,
          diagnostics: { workerPid: job.workerPid, heartbeatAt: job.heartbeatAt },
        }), job.id);
      });
      if (interrupted.status === 'interrupted') {
        if (job.pid !== undefined && job.pid !== process.pid) {
          try {
            process.kill(job.pid, 'SIGKILL');
          } catch (error) {
            if ((error as NodeJS.ErrnoException).code !== 'ESRCH') throw error;
          }
        }
        await this.cleanupTemporary(interrupted).catch(() => undefined);
      }
      return interrupted;
    }
    const heartbeat = job.heartbeatAt ? Date.parse(job.heartbeatAt) : 0;
    if (Date.now() - heartbeat > this.staleAfterMs && job.health !== 'stale') {
      return this.store.update(job.id, (current) => {
        if ((current.status === 'running' || current.status === 'stopping') && current.health !== 'stale') current.health = 'stale';
      });
    }
    return job;
  }

  async get(id: string): Promise<JobRecord> {
    return this.recover(await this.store.get(id));
  }

  async show(id: string): Promise<JobRecord> {
    const job = await this.get(id);
    const [stdout, stderr] = await Promise.all([
      readBoundedLogTail(job.logs.stdout),
      readBoundedLogTail(job.logs.stderr),
    ]);
    return { ...job, logTail: { stdout, stderr } };
  }

  async list(status?: JobStatus): Promise<JobRecord[]> {
    const jobs = await this.store.list();
    const recovered: JobRecord[] = [];
    for (const job of jobs) {
      const current = await this.recover(job);
      if (!status || current.status === status) recovered.push(current);
    }
    return recovered;
  }

  async wait(id: string, options: WaitOptions = {}): Promise<JobRecord> {
    for (;;) {
      if (options.signal?.aborted) {
        throw new CodeCutError('JOB_WAIT_ABORTED', 'Waiting for the job was aborted; the job was not cancelled', ExitCode.Cancelled, {
          stage: 'jobs.wait', jobId: id, retryable: false,
        });
      }
      const job = await this.get(id);
      if (isTerminalJob(job)) return job;
      await sleep(this.pollMs);
    }
  }

  async cancel(id: string): Promise<JobRecord> {
    const job = await this.get(id);
    if (isTerminalJob(job)) return job;
    if (job.status === 'queued') {
      const cancelled = await this.store.update(id, (current) => {
        if (current.status !== 'queued') return;
        current.status = 'cancelled';
        current.cancelReason = 'cancelled';
        current.stage = 'cancelled';
        current.finishedAt = now();
        current.error = cancellationError('cancelled', id).toJSON();
      });
      if (cancelled.status === 'cancelled') await this.cleanupTemporary(cancelled);
      return cancelled;
    }

    const stopping = await this.store.update(id, (current) => {
      if (current.status === 'running' || current.status === 'stopping') {
        current.status = 'stopping';
        current.cancelReason ??= 'cancelled';
        current.stage = 'process.stopping';
      }
    });
    const controller = this.active.get(id);
    if (controller) controller.stop(stopping.cancelReason ?? 'cancelled');
    else if (stopping.workerPid && stopping.workerPid !== process.pid) {
      try {
        process.kill(stopping.workerPid, 'SIGTERM');
      } catch (error) {
        if ((error as NodeJS.ErrnoException).code !== 'ESRCH') throw error;
      }
    }
    return stopping;
  }

  async retry(id: string, options: RetryOptions = {}): Promise<JobRecord> {
    const original = await this.store.get(id);
    const { request, snapshot } = await this.store.load(id);
    const replacement = await this.store.create(request, snapshot, original.id);
    return this.start(replacement.id, options);
  }

  private async verifySnapshot(snapshot: ProjectSnapshot | undefined): Promise<void> {
    if (!snapshot) return;
    for (const asset of snapshot.assets) {
      const path = resolve(this.store.projectDirectory, asset.path);
      let information;
      try {
        information = await stat(path);
      } catch (error) {
        if ((error as NodeJS.ErrnoException).code === 'ENOENT') {
          throw new CodeCutError('ASSET_SNAPSHOT_MISSING', 'An asset from the fixed job snapshot is missing', ExitCode.Media, {
            stage: 'jobs.preflight', path, retryable: false,
            diagnostics: { assetId: asset.id, projectRevision: snapshot.projectRevision },
          });
        }
        throw error;
      }
      if (!asset.exists || information.size !== asset.size || Math.abs(information.mtimeMs - (asset.mtimeMs ?? 0)) > 1) {
        throw new CodeCutError('ASSET_SNAPSHOT_CHANGED', 'An asset changed after the job snapshot was fixed', ExitCode.Media, {
          stage: 'jobs.preflight', path, retryable: false,
          diagnostics: { assetId: asset.id, projectRevision: snapshot.projectRevision },
        });
      }
    }
  }

  private materializeSpec(request: JobRequest, job: JobRecord): ProcessSpec {
    const paths = this.store.paths(job.id);
    const temporary = request.output ? this.store.temporaryOutputPath(job.id, request.output) : '';
    const replacements: Record<string, string> = {
      '{jobId}': job.id,
      '{jobDirectory}': paths.directory,
      '{output}': temporary,
      '{projectSnapshot}': paths.projectSnapshot,
      '{snapshot}': paths.snapshot,
    };
    const substitute = (value: string) => Object.entries(replacements).reduce(
      (result, [token, replacement]) => result.replaceAll(token, replacement),
      value,
    );
    if (!request.process.command || request.process.args.some((argument) => typeof argument !== 'string')) {
      throw new CodeCutError('USAGE_ERROR', 'Job process command and arguments must be strings', ExitCode.Usage, {
        stage: 'jobs.preflight', jobId: job.id, retryable: false,
      });
    }
    return {
      ...request.process,
      command: substitute(request.process.command),
      args: request.process.args.map(substitute),
      cwd: resolve(this.store.projectDirectory, substitute(request.process.cwd ?? '.')),
      ...(request.process.env ? {
        env: Object.fromEntries(Object.entries(request.process.env).map(([key, value]) => [key, substitute(value)])),
      } : {}),
    };
  }

  private async acquireSlot(id: string): Promise<Lease | undefined> {
    const directory = join(this.store.rootDirectory, 'locks', 'slots');
    try {
      await mkdir(directory, { recursive: true });
    } catch (error) {
      throw new CodeCutError('DISK_WRITE_FAILED', 'Could not initialize job concurrency slots', ExitCode.Internal, {
        stage: 'jobs.concurrency', jobId: id, path: directory, cause: error, retryable: true,
      });
    }
    for (;;) {
      const current = await this.store.get(id);
      if (isTerminalJob(current) || current.status === 'stopping') return undefined;
      for (let slot = 0; slot < this.maxConcurrency; slot += 1) {
        const path = join(directory, `${slot}.lock`);
        const token = randomBytes(8).toString('hex');
        let created = false;
        try {
          await mkdir(path);
          created = true;
          await writeFile(join(path, 'owner.json'), JSON.stringify({ token, pid: process.pid, jobId: id }), 'utf8');
          return {
            release: async () => {
              try {
                const owner = JSON.parse(await readFile(join(path, 'owner.json'), 'utf8')) as { token?: string };
                if (owner.token === token) await rm(path, { recursive: true, force: true });
              } catch {
                // Stale slots are reaped by another worker.
              }
            },
          };
        } catch (error) {
          if ((error as NodeJS.ErrnoException).code !== 'EEXIST' || created) {
            if (created) await rm(path, { recursive: true, force: true }).catch(() => undefined);
            throw new CodeCutError('DISK_WRITE_FAILED', 'Could not acquire a job concurrency slot', ExitCode.Internal, {
              stage: 'jobs.concurrency', jobId: id, path, cause: error, retryable: true,
            });
          }
          let owner: { pid?: number } | undefined;
          try {
            owner = JSON.parse(await readFile(join(path, 'owner.json'), 'utf8')) as { pid?: number };
          } catch {
            // A newly-created slot may not have written its owner yet.
          }
          let stale = owner ? !processExists(owner.pid) : false;
          if (!owner) {
            try {
              const information = await stat(path);
              stale = Date.now() - information.mtimeMs > 1_000;
            } catch {
              stale = true;
            }
          }
          if (stale) {
            const quarantine = `${path}.reap-${process.pid}-${randomBytes(4).toString('hex')}`;
            try {
              await rename(path, quarantine);
              await rm(quarantine, { recursive: true, force: true });
            } catch {
              // Another worker won stale-slot recovery.
            }
          }
        }
      }
      await sleep(this.pollMs);
    }
  }

  private async cleanupTemporary(job: JobRecord): Promise<void> {
    if (!job.temporaryOutputPath || job.temporaryOutputPath === job.outputPath) return;
    try {
      await unlink(job.temporaryOutputPath);
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code === 'ENOENT') return;
      throw new CodeCutError('DISK_WRITE_FAILED', 'Could not clean the temporary job output', ExitCode.Internal, {
        stage: 'output.cleanup', jobId: job.id, path: job.temporaryOutputPath, cause: error, retryable: true,
      });
    }
  }

  private async validateOutput(job: JobRecord, request: JobRequest, hooks: JobRunHooks): Promise<void> {
    if (!request.output || !job.temporaryOutputPath) return;
    const paths = this.store.paths(job.id);
    let validation: unknown;
    if (request.render && request.preview) {
      validation = await validateTimelinePreviewOutput(job.temporaryOutputPath, request.render.plan, {
        jobId: job.id,
        ...(request.render.ffprobePath === undefined ? {} : { ffprobePath: request.render.ffprobePath }),
        ...(request.render.ffmpegPath === undefined ? {} : { ffmpegPath: request.render.ffmpegPath }),
      });
    } else if (request.render) {
      validation = await validateRenderOutput(job.temporaryOutputPath, request.render.plan, {
        jobId: job.id,
        ...(request.render.ffprobePath === undefined ? {} : { ffprobePath: request.render.ffprobePath }),
        ...(request.render.ffmpegPath === undefined ? {} : { ffmpegPath: request.render.ffmpegPath }),
      });
    } else if (hooks.validateOutput) {
      validation = await hooks.validateOutput(job.temporaryOutputPath, job);
    } else {
      let information;
      try {
        information = await stat(job.temporaryOutputPath);
      } catch (error) {
        throw new CodeCutError('OUTPUT_VALIDATION_FAILED', 'Job did not produce a readable output file', ExitCode.Media, {
          stage: 'output.validate', jobId: job.id, path: job.temporaryOutputPath, cause: error, retryable: false,
        });
      }
      if (!information.isFile() || information.size === 0) {
        throw new CodeCutError('OUTPUT_VALIDATION_FAILED', 'Job output is empty or is not a regular file', ExitCode.Media, {
          stage: 'output.validate', jobId: job.id, path: job.temporaryOutputPath, retryable: false,
        });
      }
      validation = { type: 'nonEmpty', size: information.size };
      if (request.output.validation === 'ffprobe') {
        const result = await execa(request.output.ffprobePath ?? 'ffprobe', [
          '-v', 'error', '-show_streams', '-show_format', '-of', 'json', job.temporaryOutputPath,
        ], { reject: false, timeout: 30_000, maxBuffer: 1024 * 1024 });
        if (result.failed) {
          throw new CodeCutError('OUTPUT_VALIDATION_FAILED', 'ffprobe could not validate the job output', ExitCode.Media, {
            stage: 'output.validate', jobId: job.id, path: job.temporaryOutputPath, retryable: false,
            diagnostics: { exitCode: result.exitCode, stderr: result.stderr },
          });
        }
        let probed: { streams?: unknown[] };
        try {
          probed = JSON.parse(result.stdout) as { streams?: unknown[] };
        } catch (error) {
          throw new CodeCutError('OUTPUT_VALIDATION_FAILED', 'ffprobe returned invalid JSON', ExitCode.Media, {
            stage: 'output.validate', jobId: job.id, path: job.temporaryOutputPath, cause: error, retryable: false,
            diagnostics: { stdoutTail: result.stdout.slice(-4096), stderr: result.stderr },
          });
        }
        if (!Array.isArray(probed.streams) || probed.streams.length === 0) {
          throw new CodeCutError('OUTPUT_VALIDATION_FAILED', 'Job output has no media streams', ExitCode.Media, {
            stage: 'output.validate', jobId: job.id, path: job.temporaryOutputPath, retryable: false,
          });
        }
        validation = { type: 'ffprobe', size: information.size, streams: probed.streams.length };
      }
    }
    const validationPath = join(paths.diagnostics, 'validation.json');
    try {
      await writeFile(validationPath, `${JSON.stringify(validation ?? { valid: true }, null, 2)}\n`, 'utf8');
    } catch (error) {
      throw new CodeCutError('DISK_WRITE_FAILED', 'Could not persist output validation diagnostics', ExitCode.Internal, {
        stage: 'output.validate', jobId: job.id, path: validationPath, cause: error, retryable: true,
      });
    }
    await this.store.update(job.id, (current) => {
      current.diagnostics.validation = validationPath;
      current.validation = validation;
    });
  }

  private async publishOutput(job: JobRecord, request: JobRequest): Promise<void> {
    if (!request.output || !job.temporaryOutputPath) return;
    const output = request.output;
    try {
      if (output.overwrite) {
        await rename(job.temporaryOutputPath, output.path);
      } else {
        try {
          await link(job.temporaryOutputPath, output.path);
          await unlink(job.temporaryOutputPath);
        } catch (error) {
          if ((error as NodeJS.ErrnoException).code === 'EEXIST') {
            throw new CodeCutError('OUTPUT_EXISTS', 'Output already exists; enable overwrite to replace it', ExitCode.Usage, {
              stage: 'output.publish', jobId: job.id, path: output.path, cause: error, retryable: false,
            });
          }
          throw error;
        }
      }
    } catch (error) {
      if (error instanceof CodeCutError) throw error;
      throw new CodeCutError('DISK_WRITE_FAILED', 'Could not atomically publish the job output', ExitCode.Internal, {
        stage: 'output.publish', jobId: job.id, path: output.path, cause: error, retryable: true,
      });
    }
  }

  private async writeResultJson(path: string, value: unknown): Promise<void> {
    const temporary = `${path}.${process.pid}.${randomBytes(5).toString('hex')}.tmp`;
    try {
      await mkdir(dirname(path), { recursive: true });
      await writeFile(temporary, `${JSON.stringify(value, null, 2)}\n`, { encoding: 'utf8', flag: 'wx' });
      await rename(temporary, path);
    } catch (error) {
      await unlink(temporary).catch(() => undefined);
      throw new CodeCutError('DISK_WRITE_FAILED', 'Could not persist the structured job result', ExitCode.Internal, {
        stage: 'jobs.result', path, cause: error, retryable: true,
      });
    }
  }

  private async persistResult(
    id: string,
    request: JobRequest,
  ): Promise<{ data?: unknown; resultPath?: string }> {
    if (!request.analysis && !request.result) return {};
    const paths = this.store.paths(id);
    let data: unknown;
    if (request.analysis) {
      const resultPath = join(paths.diagnostics, 'result.json');
      data = await parseAnalysisLog(request.analysis, join(paths.logs, 'stderr.log'), resultPath);
    } else data = request.result?.data;

    if (request.result?.cacheManifestPath && request.result.cacheManifest) {
      await this.writeResultJson(request.result.cacheManifestPath, request.result.cacheManifest);
    }
    if (data === undefined) return {};
    const resultPath = join(paths.diagnostics, 'result.json');
    await this.writeResultJson(resultPath, data);
    return { data, resultPath };
  }

  private async finalize(
    id: string,
    status: 'succeeded' | 'failed' | 'cancelled' | 'timedOut',
    request: JobRequest,
    execution?: ProcessExecutionResult,
    failure?: unknown,
  ): Promise<JobRecord> {
    let finalFailure = failure;
    const latest = await this.store.get(id);
    let persistedResult: { data?: unknown; resultPath?: string } = {};
    if (status === 'succeeded') {
      try {
        persistedResult = await this.persistResult(id, request);
      } catch (error) {
        finalFailure = error;
        status = 'failed';
      }
    }
    try {
      await this.cleanupTemporary(latest);
    } catch (error) {
      finalFailure = error;
      status = 'failed';
    }
    if ((status === 'cancelled' || status === 'timedOut') && finalFailure === undefined) {
      finalFailure = cancellationError(status, id);
    }
    const errorPayload = finalFailure === undefined
      ? undefined
      : jobErrorPayload(finalFailure, id, execution ? { logs: execution.logs } : undefined);
    const tails = execution?.tails ?? {
      stdout: await readBoundedLogTail(latest.logs.stdout),
      stderr: await readBoundedLogTail(latest.logs.stderr),
    };
    return this.store.update(id, (current) => {
      if (isTerminalJob(current)) return;
      current.status = status;
      current.stage = status === 'failed' && errorPayload ? errorPayload.stage : status;
      current.health = 'ok';
      current.finishedAt = now();
      current.heartbeatAt = now();
      current.logTail = tails;
      if (errorPayload) current.error = errorPayload;
      if (persistedResult.resultPath) current.diagnostics.result = persistedResult.resultPath;
      if (execution || status === 'succeeded') {
        current.result = {
          ...(execution?.exitCode === undefined ? {} : { exitCode: execution.exitCode }),
          ...(execution?.signal === undefined ? {} : { signal: execution.signal }),
          ...(execution?.durationMs === undefined ? {} : { durationMs: execution.durationMs }),
          ...(execution?.forcefullyTerminated ? { forcefullyTerminated: true } : {}),
          ...(status === 'succeeded' && request.output ? { outputPath: request.output.path } : {}),
          ...(status === 'succeeded' && persistedResult.data !== undefined ? { data: persistedResult.data } : {}),
        };
      }
      if (execution?.progress) current.progress = execution.progress;
    });
  }

  async runJob(id: string, hooks: JobRunHooks = {}): Promise<JobRecord> {
    const initial = await this.store.get(id);
    if (isTerminalJob(initial)) return initial;
    if ((initial.status === 'running' || initial.status === 'stopping') && initial.workerPid !== undefined && initial.workerPid !== process.pid) {
      throw new CodeCutError('JOB_ALREADY_RUNNING', 'Another worker is already running this job', ExitCode.Usage, {
        stage: 'jobs.worker', jobId: id, retryable: false,
      });
    }
    const { request, snapshot } = await this.store.load(id);
    const controller = new ProcessController();
    this.active.set(id, controller);
    let heartbeat: NodeJS.Timeout | undefined;
    let externalControl: NodeJS.Timeout | undefined;
    let slot: Lease | undefined;
    let outputLock: OutputLock | undefined;
    let execution: ProcessExecutionResult | undefined;
    let progressWrite = Promise.resolve();
    let stoppingWrite = Promise.resolve();
    let heartbeatWrite = Promise.resolve();
    let signalCancellation = Promise.resolve();
    let finishing = false;
    const signalHandler = () => {
      if (finishing) return;
      controller.stop('cancelled');
      signalCancellation = signalCancellation.then(async () => {
        await this.cancel(id).catch(() => undefined);
      });
    };
    process.once('SIGINT', signalHandler);
    process.once('SIGTERM', signalHandler);
    const finalizeJob = async (
      status: 'succeeded' | 'failed' | 'cancelled' | 'timedOut',
      failure?: unknown,
    ): Promise<JobRecord> => {
      finishing = true;
      if (heartbeat) clearInterval(heartbeat);
      if (externalControl) clearInterval(externalControl);
      await Promise.all([stoppingWrite, heartbeatWrite, signalCancellation]);
      return this.finalize(id, status, request, execution, failure);
    };

    try {
      await this.store.update(id, (current) => {
        if (!isTerminalJob(current)) {
          current.workerPid = process.pid;
          current.stage = 'jobs.preflight';
          current.heartbeatAt = now();
        }
      });
      slot = await this.acquireSlot(id);
      if (!slot) {
        const current = await this.store.get(id);
        return isTerminalJob(current) ? current : finalizeJob('cancelled');
      }
      await this.verifySnapshot(snapshot);
      if (request.output) {
        try {
          await mkdir(dirname(request.output.path), { recursive: true });
          await mkdir(dirname(this.store.temporaryOutputPath(id, request.output)), { recursive: true });
        } catch (error) {
          throw new CodeCutError('DISK_WRITE_FAILED', 'Could not create the job output directory', ExitCode.Internal, {
            stage: 'jobs.preflight', jobId: id, path: request.output.path, cause: error, retryable: true,
          });
        }
        if (!request.output.overwrite) {
          try {
            await stat(request.output.path);
            throw new CodeCutError('OUTPUT_EXISTS', 'Output already exists; enable overwrite to replace it', ExitCode.Usage, {
              stage: 'jobs.preflight', jobId: id, path: request.output.path, retryable: false,
            });
          } catch (error) {
            if (error instanceof CodeCutError) throw error;
            if ((error as NodeJS.ErrnoException).code !== 'ENOENT') throw error;
          }
        }
        outputLock = await acquireOutputLock(request.output.path);
      }
      if (controller.reason) return await finalizeJob(controller.reason);

      const spec = this.materializeSpec(request, initial);
      heartbeat = setInterval(() => {
        if (finishing) return;
        heartbeatWrite = heartbeatWrite.then(async () => {
          if (finishing) return;
          await this.store.update(id, (current) => {
            if ((current.status === 'running' || current.status === 'stopping') && current.workerPid === process.pid) {
              current.heartbeatAt = now();
              current.health = 'ok';
            }
          }).catch(() => undefined);
        });
      }, this.heartbeatMs);
      externalControl = setInterval(() => {
        void this.store.get(id).then((current) => {
          if (current.status === 'stopping') controller.stop(current.cancelReason ?? 'cancelled');
        }).catch(() => undefined);
      }, this.pollMs);
      let lastProgressWrite = 0;
      execution = await executeControlledProcess({
        spec,
        logDirectory: this.store.paths(id).logs,
        controller,
        ...(request.timeoutMs === undefined ? {} : { timeoutMs: request.timeoutMs }),
        gracePeriodMs: request.gracePeriodMs ?? this.gracePeriodMs,
        tailBytes: this.tailBytes,
        onSpawn: async (pid) => {
          await this.store.update(id, (current) => {
            if (isTerminalJob(current)) return;
            if (current.status !== 'stopping') current.status = 'running';
            current.stage = 'process.execute';
            current.pid = pid;
            current.startedAt = now();
            current.heartbeatAt = now();
            current.progress ??= { percent: 0 };
          });
        },
        onProgress: (progress: ProgressState) => {
          const timestamp = Date.now();
          if (!progress.end && timestamp - lastProgressWrite < 200) return;
          lastProgressWrite = timestamp;
          progressWrite = progressWrite.then(() => this.store.update(id, (current) => {
            if (current.status === 'running') current.progress = progress;
          })).then(() => undefined);
          void progressWrite.catch(() => undefined);
        },
        onStopping: (reason) => {
          if (finishing) return;
          stoppingWrite = stoppingWrite.then(async () => {
            if (finishing) return;
            await this.store.update(id, (current) => {
              if (!isTerminalJob(current)) {
                current.status = 'stopping';
                current.cancelReason = reason;
                current.stage = 'process.stopping';
              }
            }).catch(() => undefined);
          });
        },
      });
      await progressWrite;
      const current = await this.store.get(id);
      const stopReason = execution.stopReason ?? (current.status === 'stopping' ? current.cancelReason ?? 'cancelled' : undefined);
      if (stopReason) return await finalizeJob(stopReason);
      if (request.render) await this.verifySnapshot(snapshot);

      await this.store.update(id, (job) => {
        if (!isTerminalJob(job)) job.stage = 'output.validate';
      });
      await this.validateOutput(await this.store.get(id), request, hooks);
      const beforePublish = await this.store.get(id);
      if (beforePublish.status === 'stopping') {
        return await finalizeJob(beforePublish.cancelReason ?? 'cancelled');
      }
      await this.store.update(id, (job) => {
        if (!isTerminalJob(job)) job.stage = 'output.publish';
      });
      await this.publishOutput(beforePublish, request);
      return await finalizeJob('succeeded');
    } catch (error) {
      await progressWrite.catch(() => undefined);
      const current = await this.store.get(id);
      const reason = controller.reason ?? (current.status === 'stopping' ? current.cancelReason ?? 'cancelled' : undefined);
      return finalizeJob(reason ?? 'failed', reason ? cancellationError(reason, id) : error);
    } finally {
      finishing = true;
      if (heartbeat) clearInterval(heartbeat);
      if (externalControl) clearInterval(externalControl);
      await Promise.all([stoppingWrite, heartbeatWrite, signalCancellation]);
      process.removeListener('SIGINT', signalHandler);
      process.removeListener('SIGTERM', signalHandler);
      this.active.delete(id);
      if (outputLock) await outputLock.release().catch(() => undefined);
      if (slot) await slot.release().catch(() => undefined);
    }
  }
}

export async function waitForJob(
  projectDirectory: string,
  id: string,
  options: WaitOptions = {},
): Promise<JobRecord> {
  return new JobService(projectDirectory).wait(id, options);
}

export type {
  JobRecord,
  JobRequest,
  JobStatus,
  ProjectSnapshot,
} from './jobs-store.js';
export { JobStore } from './jobs-store.js';
