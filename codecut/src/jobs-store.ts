import { randomBytes } from 'node:crypto';
import {
  mkdir,
  open,
  readFile,
  readdir,
  rename,
  rm,
  stat,
  unlink,
  writeFile,
} from 'node:fs/promises';
import { basename, dirname, join, resolve } from 'node:path';
import { CodeCutError, ExitCode } from './errors.js';
import { processExists } from './output-lock.js';
import type { ProcessLogPaths, ProcessSpec, StopReason } from './process.js';
import type { RenderPlan, RenderPostprocess } from './render-plan.js';
import type { ErrorPayload, Job, Project } from './schema.js';

export type JobStatus = Job['status'];
export type JobKind = Job['kind'];

export interface JobProgress {
  percent: number;
  frame?: number;
  timeSeconds?: number;
  speed?: number;
  end?: boolean;
}

export interface JobOutput {
  path: string;
  temporaryPath?: string;
  overwrite?: boolean;
  validation?: 'nonEmpty' | 'ffprobe';
  ffprobePath?: string;
}

export type JobAnalysisRequest =
  | { type: 'scenes'; assetId: string; start: number; end: number; threshold: number }
  | { type: 'silence'; assetId: string; start: number; end: number; noiseDb: number; minimumDuration: number };

export interface JobResultRequest {
  data?: Record<string, unknown>;
  cacheManifestPath?: string;
  cacheManifest?: Record<string, unknown>;
}

export interface JobRequest {
  kind: JobKind;
  process: ProcessSpec;
  projectPath?: string;
  projectRevision?: number;
  output?: JobOutput;
  analysis?: JobAnalysisRequest;
  result?: JobResultRequest;
  render?: {
    plan: RenderPlan;
    ffprobePath?: string;
    ffmpegPath?: string;
  };
  preview?: {
    type: 'frame' | 'sheet' | 'proxy';
    parameters: RenderPostprocess;
  };
  timeoutMs?: number;
  gracePeriodMs?: number;
}

export interface AssetSnapshot {
  id: string;
  path: string;
  exists: boolean;
  size?: number;
  mtimeMs?: number;
}

export interface ProjectSnapshot {
  version: 1;
  createdAt: string;
  projectRevision: number;
  project: Project;
  assets: AssetSnapshot[];
}

export interface JobRecord extends Omit<Job, 'progress' | 'preview' | 'validation'> {
  progress?: JobProgress;
  pid?: number;
  workerPid?: number;
  cancelReason?: StopReason;
  outputPath?: string;
  temporaryOutputPath?: string;
  preview?: JobRequest['preview'];
  validation?: unknown;
  logs: ProcessLogPaths;
  diagnostics: {
    directory: string;
    request: string;
    snapshot?: string;
    validation?: string;
    result?: string;
    arguments?: string;
    filterGraph?: string;
    plan?: string;
    textFiles?: string[];
  };
  logTail?: { stdout: string; stderr: string };
  result?: {
    exitCode?: number;
    signal?: string;
    durationMs?: number;
    forcefullyTerminated?: boolean;
    outputPath?: string;
    data?: unknown;
  };
}

export interface StoredJob {
  request: JobRequest;
  snapshot?: ProjectSnapshot;
}

export interface JobPaths {
  directory: string;
  record: string;
  request: string;
  snapshot: string;
  projectSnapshot: string;
  logs: string;
  diagnostics: string;
}

const terminalStatuses = new Set<JobStatus>(['succeeded', 'failed', 'cancelled', 'timedOut', 'interrupted']);

export function isTerminalJob(job: JobRecord): boolean {
  return terminalStatuses.has(job.status);
}

function diskError(error: unknown, stage: string, path: string): CodeCutError {
  if (error instanceof CodeCutError) return error;
  return new CodeCutError('DISK_WRITE_FAILED', 'Could not update the persistent job store', ExitCode.Internal, {
    stage,
    path,
    cause: error,
    retryable: true,
  });
}

async function atomicJson(path: string, value: unknown, stage: string): Promise<void> {
  const temporary = join(dirname(path), `.${basename(path)}.${process.pid}.${randomBytes(5).toString('hex')}.tmp`);
  try {
    const handle = await open(temporary, 'wx');
    try {
      await handle.writeFile(`${JSON.stringify(value, null, 2)}\n`, 'utf8');
      await handle.sync();
    } finally {
      await handle.close();
    }
    await rename(temporary, path);
  } catch (error) {
    await unlink(temporary).catch(() => undefined);
    throw diskError(error, stage, path);
  }
}

async function readJson<T>(path: string, stage: string): Promise<T> {
  try {
    return JSON.parse(await readFile(path, 'utf8')) as T;
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === 'ENOENT') {
      throw new CodeCutError('JOB_NOT_FOUND', 'Job does not exist', ExitCode.Usage, {
        stage,
        path,
        retryable: false,
      });
    }
    throw new CodeCutError('JOB_STORE_READ_FAILED', 'Could not read persistent job data', ExitCode.Internal, {
      stage,
      path,
      cause: error,
      retryable: true,
    });
  }
}

const sleep = (milliseconds: number) => new Promise<void>((resolveSleep) => setTimeout(resolveSleep, milliseconds));

export class JobStore {
  readonly projectDirectory: string;
  readonly rootDirectory: string;
  readonly jobsDirectory: string;

  constructor(projectDirectory: string, storeDirectory?: string) {
    const resolved = resolve(projectDirectory);
    this.projectDirectory = basename(resolved) === 'project.json' ? dirname(resolved) : resolved;
    this.rootDirectory = storeDirectory ?? join(this.projectDirectory, '.codecut');
    this.jobsDirectory = join(this.rootDirectory, 'jobs');
  }

  paths(id: string): JobPaths {
    if (!/^[A-Za-z0-9][A-Za-z0-9._-]*$/.test(id)) {
      throw new CodeCutError('USAGE_ERROR', 'Invalid job ID', ExitCode.Usage, {
        stage: 'jobs', retryable: false,
      });
    }
    const directory = join(this.jobsDirectory, id);
    return {
      directory,
      record: join(directory, 'job.json'),
      request: join(directory, 'request.json'),
      snapshot: join(directory, 'snapshot.json'),
      projectSnapshot: join(directory, 'project.json'),
      logs: join(directory, 'logs'),
      diagnostics: join(directory, 'diagnostics'),
    };
  }

  async create(request: JobRequest, snapshot?: ProjectSnapshot, retryOf?: string): Promise<JobRecord> {
    await mkdir(this.jobsDirectory, { recursive: true });
    const id = `job-${Date.now().toString(36)}-${randomBytes(5).toString('hex')}`;
    const paths = this.paths(id);
    const now = new Date().toISOString();
    const logs: ProcessLogPaths = {
      stdout: join(paths.logs, 'stdout.log'),
      stderr: join(paths.logs, 'stderr.log'),
      ...(request.process.progress === 'ffmpeg' ? {
        progress: join(paths.logs, 'progress.log'),
        progressEvents: join(paths.logs, 'progress.jsonl'),
      } : {}),
    };
    const job: JobRecord = {
      id,
      kind: request.kind,
      status: 'queued',
      health: 'ok',
      stage: 'queued',
      projectRevision: snapshot?.projectRevision ?? request.projectRevision ?? 0,
      ...(retryOf === undefined ? {} : { retryOf }),
      createdAt: now,
      ...(request.output ? {
        outputPath: request.output.path,
        temporaryOutputPath: this.temporaryOutputPath(id, request.output),
      } : {}),
      ...(request.preview ? { preview: structuredClone(request.preview) } : {}),
      logs,
      diagnostics: {
        directory: paths.diagnostics,
        request: paths.request,
        ...(snapshot ? { snapshot: paths.snapshot } : {}),
        ...(request.render ? {
          arguments: join(paths.diagnostics, 'arguments.json'),
          filterGraph: join(paths.diagnostics, 'filter_complex.txt'),
          plan: join(paths.diagnostics, 'plan.json'),
          textFiles: request.render.plan.textFiles.map((_, index) => join(paths.diagnostics, `text-${index}.txt`)),
        } : {}),
      },
    };

    try {
      await mkdir(paths.logs, { recursive: true });
      await mkdir(paths.diagnostics, { recursive: true });
      await atomicJson(paths.request, request, 'jobs.create');
      if (snapshot) {
        await atomicJson(paths.snapshot, snapshot, 'jobs.create');
        await atomicJson(paths.projectSnapshot, snapshot.project, 'jobs.create');
      }
      if (request.render) {
        const temporary = request.output ? this.temporaryOutputPath(id, request.output) : '';
        const replacements: Record<string, string> = {
          '{jobId}': id,
          '{jobDirectory}': paths.directory,
          '{output}': temporary,
          '{projectSnapshot}': paths.projectSnapshot,
          '{snapshot}': paths.snapshot,
        };
        const substitute = (value: string) => Object.entries(replacements).reduce(
          (result, [token, replacement]) => result.replaceAll(token, replacement),
          value,
        );
        await atomicJson(job.diagnostics.arguments!, {
          command: substitute(request.process.command),
          args: request.process.args.map(substitute),
          cwd: resolve(this.projectDirectory, substitute(request.process.cwd ?? '.')),
        }, 'jobs.create');
        await writeFile(job.diagnostics.filterGraph!, substitute(request.render.plan.filter_graph), 'utf8');
        await atomicJson(job.diagnostics.plan!, request.render.plan, 'jobs.create');
        for (const [index, text] of request.render.plan.textFiles.entries()) {
          const target = job.diagnostics.textFiles![index]!;
          if (resolve(this.projectDirectory, substitute(text.path)) !== target) {
            throw new CodeCutError('USAGE_ERROR', 'Render text diagnostics must stay inside the job directory', ExitCode.Usage, {
              stage: 'jobs.create', jobId: id, path: text.path, retryable: false,
            });
          }
          await writeFile(target, text.content, 'utf8');
        }
      }
      await atomicJson(paths.record, job, 'jobs.create');
      return job;
    } catch (error) {
      await rm(paths.directory, { recursive: true, force: true }).catch(() => undefined);
      throw diskError(error, 'jobs.create', paths.directory);
    }
  }

  temporaryOutputPath(id: string, output: JobOutput): string {
    if (output.temporaryPath) return resolve(this.projectDirectory, output.temporaryPath);
    const extension = output.path.includes('.') ? `.${output.path.split('.').pop()}` : '';
    return join(this.paths(id).directory, `temporary-output${extension}`);
  }

  async get(id: string): Promise<JobRecord> {
    return readJson<JobRecord>(this.paths(id).record, 'jobs.show');
  }

  async getRequest(id: string): Promise<JobRequest> {
    return readJson<JobRequest>(this.paths(id).request, 'jobs.request');
  }

  async getSnapshot(id: string): Promise<ProjectSnapshot | undefined> {
    try {
      return await readJson<ProjectSnapshot>(this.paths(id).snapshot, 'jobs.snapshot');
    } catch (error) {
      if (error instanceof CodeCutError && error.code === 'JOB_NOT_FOUND') return undefined;
      throw error;
    }
  }

  async load(id: string): Promise<StoredJob> {
    const [request, snapshot] = await Promise.all([this.getRequest(id), this.getSnapshot(id)]);
    return { request, ...(snapshot ? { snapshot } : {}) };
  }

  async update(id: string, mutate: (job: JobRecord) => void): Promise<JobRecord> {
    const paths = this.paths(id);
    const lockPath = join(this.rootDirectory, 'locks', 'jobs', `${id}.lock`);
    await mkdir(dirname(lockPath), { recursive: true });
    const token = randomBytes(8).toString('hex');
    const deadline = Date.now() + 10_000;
    for (;;) {
      try {
        await mkdir(lockPath);
      } catch (error) {
        if ((error as NodeJS.ErrnoException).code !== 'EEXIST') {
          throw diskError(error, 'jobs.lock', lockPath);
        }
        let stale = false;
        let owner: { pid?: number } | undefined;
        try {
          owner = JSON.parse(await readFile(join(lockPath, 'owner.json'), 'utf8')) as { pid?: number };
        } catch {
          // A newly-created lock may not have written its owner yet.
        }
        if (owner) {
          stale = !processExists(owner.pid);
        } else {
          try {
            const information = await stat(lockPath);
            stale = Date.now() - information.mtimeMs > 1_000;
          } catch {
            stale = true;
          }
        }
        if (stale) {
          const quarantine = `${lockPath}.reap-${process.pid}-${randomBytes(4).toString('hex')}`;
          try {
            await rename(lockPath, quarantine);
            await rm(quarantine, { recursive: true, force: true });
            continue;
          } catch {
            // Another process is already reaping or replacing the lock.
          }
        }
        if (Date.now() >= deadline) {
          throw new CodeCutError('JOB_STORE_LOCKED', 'Timed out waiting for the job store lock', ExitCode.Internal, {
            stage: 'jobs.update', path: paths.record, retryable: true,
          });
        }
        await sleep(20);
        continue;
      }

      try {
        await atomicJson(join(lockPath, 'owner.json'), { token, pid: process.pid }, 'jobs.lock');
        break;
      } catch (error) {
        await rm(lockPath, { recursive: true, force: true }).catch(() => undefined);
        throw error;
      }
    }

    try {
      const job = await this.get(id);
      mutate(job);
      await atomicJson(paths.record, job, 'jobs.update');
      return job;
    } finally {
      try {
        const owner = JSON.parse(await readFile(join(lockPath, 'owner.json'), 'utf8')) as { token?: string };
        if (owner.token === token) await rm(lockPath, { recursive: true, force: true });
      } catch {
        // A stale lock is recoverable by the next writer.
      }
    }
  }

  async list(): Promise<JobRecord[]> {
    let entries;
    try {
      entries = await readdir(this.jobsDirectory, { withFileTypes: true });
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code === 'ENOENT') return [];
      throw diskError(error, 'jobs.list', this.jobsDirectory);
    }
    const jobs: JobRecord[] = [];
    for (const entry of entries) {
      if (entry.isDirectory() && entry.name.startsWith('job-')) jobs.push(await this.get(entry.name));
    }
    return jobs.sort((left, right) => right.createdAt.localeCompare(left.createdAt) || right.id.localeCompare(left.id));
  }
}
