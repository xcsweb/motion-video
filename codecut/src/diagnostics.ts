import { execa } from 'execa';
import { createReadStream, createWriteStream } from 'node:fs';
import {
  access,
  mkdir,
  mkdtemp,
  open,
  readFile,
  readdir,
  stat,
  statfs,
  unlink,
  writeFile,
} from 'node:fs/promises';
import { constants } from 'node:fs';
import { hostname, release, tmpdir } from 'node:os';
import { basename, dirname, join, resolve } from 'node:path';
import { createInterface } from 'node:readline';
import { StringDecoder } from 'node:string_decoder';
import { Transform } from 'node:stream';
import { pipeline } from 'node:stream/promises';
import { asCodeCutError } from './errors.js';
import { getProjectLockPath } from './project-lock.js';
import { processExists } from './output-lock.js';
import { JobService } from './jobs.js';
import { isTerminalJob, type JobRecord } from './jobs-store.js';
import { listHistory } from './history.js';
import { loadProject, resolveProjectFile } from './project.js';

export type DiagnosticStatus = 'ok' | 'warning' | 'error';

export interface DoctorCheck {
  name: string;
  status: DiagnosticStatus;
  message: string;
  path?: string;
  details?: unknown;
}

export interface DoctorReport {
  ok: boolean;
  projectDirectory: string;
  checks: DoctorCheck[];
}

export type JobLogStream = 'stdout' | 'stderr' | 'progress';
export type JobLogLevel = 'debug' | 'info' | 'warn' | 'error';

export interface JobLogEntry {
  jobId: string;
  stage: string;
  level: JobLogLevel;
  stream: JobLogStream;
  line: string;
  at?: string;
}

export interface LogQuery {
  jobId: string;
  stage?: string;
  level?: JobLogLevel;
  stream?: JobLogStream;
  tail?: number;
}

export interface JobLogResult {
  job: JobRecord;
  logs: JobLogEntry[];
  truncated: boolean;
}

export interface FollowLogsOptions extends LogQuery {
  signal?: AbortSignal;
  pollMs?: number;
  stopOnTerminal?: boolean;
}

export interface DiagnoseOptions {
  projectDirectory: string;
  jobId: string;
  output?: string;
}

export interface DiagnoseResult {
  jobId: string;
  directory: string;
  files: string[];
  redacted: true;
  sourceMediaIncluded: false;
  environmentVariablesIncluded: false;
}

const REDACTED = '[REDACTED]';
const SENSITIVE_KEY = /(?:pass(?:word)?|secret|token|api[-_]?key|authorization|credential|cookie|session|private[-_]?key|access[-_]?key)/i;
const LOG_LEVELS = new Set<JobLogLevel>(['debug', 'info', 'warn', 'error']);

export function redactDiagnosticText(value: string): string {
  return value
    .replace(/(https?:\/\/)[^\s/:@]+:[^\s/@]+@/gi, `$1${REDACTED}@`)
    .replace(/\b(Bearer|Basic)\s+[A-Za-z0-9._~+/=-]+/gi, `$1 ${REDACTED}`)
    .replace(/((?:"?(?:pass(?:word)?|secret|token|api[-_]?key|authorization|credential|cookie|session|private[-_]?key|access[-_]?key)"?)\s*[=:]\s*)(?:"[^"]*"|'[^']*'|[^\s,;}]+)/gi, `$1${REDACTED}`);
}

export function redactDiagnosticValue<T>(value: T, key?: string): T {
  if (key !== undefined && SENSITIVE_KEY.test(key)) return REDACTED as T;
  if (typeof value === 'string') return redactDiagnosticText(value) as T;
  if (Array.isArray(value)) {
    let redactNext = false;
    return value.map((entry) => {
      if (redactNext) {
        redactNext = false;
        return REDACTED;
      }
      if (typeof entry === 'string' && /^-{1,2}[A-Za-z0-9_-]+$/.test(entry) && SENSITIVE_KEY.test(entry)) {
        redactNext = true;
      }
      return redactDiagnosticValue(entry);
    }) as T;
  }
  if (typeof value === 'object' && value !== null) {
    const result: Record<string, unknown> = {};
    for (const [childKey, childValue] of Object.entries(value)) {
      result[childKey] = redactDiagnosticValue(childValue, childKey);
    }
    return result as T;
  }
  return value;
}

function check(name: string, status: DiagnosticStatus, message: string, extra: Partial<DoctorCheck> = {}): DoctorCheck {
  return { name, status, message, ...extra };
}

async function toolVersion(command: string): Promise<string> {
  const result = await execa(command, ['-version'], { reject: false, timeout: 5_000 });
  if (result.exitCode !== 0) throw new Error(`${command} exited with code ${result.exitCode}`);
  return (result.stdout || result.stderr).split(/\r?\n/, 1)[0] || `${command} version unavailable`;
}

async function checkWritableDirectory(name: string, path: string): Promise<DoctorCheck> {
  try {
    await mkdir(path, { recursive: true });
    await access(path, constants.R_OK | constants.W_OK);
    const probe = join(path, `.codecut-doctor-${process.pid}-${Date.now()}`);
    const handle = await open(probe, 'wx');
    await handle.close();
    await unlink(probe);
    const space = await statfs(path);
    const freeBytes = Number(space.bavail) * Number(space.bsize);
    return check(name, freeBytes > 0 ? 'ok' : 'error', freeBytes > 0 ? 'Directory is readable and writable' : 'No free disk space remains', {
      path,
      details: { freeBytes },
    });
  } catch (error) {
    return check(name, 'error', `Directory is not writable: ${(error as Error).message}`, { path });
  }
}

async function readJsonFile(path: string): Promise<Record<string, unknown> | undefined> {
  try {
    const value = JSON.parse(await readFile(path, 'utf8')) as unknown;
    return typeof value === 'object' && value !== null && !Array.isArray(value) ? value as Record<string, unknown> : undefined;
  } catch {
    return undefined;
  }
}

async function inspectProjectLock(projectPath: string): Promise<DoctorCheck> {
  const path = getProjectLockPath(projectPath);
  try {
    await stat(path);
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === 'ENOENT') return check('lock.project', 'ok', 'No project write lock is present', { path });
    return check('lock.project', 'error', 'Could not inspect the project write lock', { path });
  }
  const owner = await readJsonFile(path);
  const pid = typeof owner?.pid === 'number' ? owner.pid : undefined;
  if (!owner || pid === undefined) return check('lock.project', 'error', 'Project write lock is corrupt; inspect it manually', { path });
  const sameHost = owner.hostname === hostname();
  const active = sameHost ? processExists(pid) : undefined;
  return check('lock.project', active === false ? 'warning' : 'ok', active === false
    ? `Project lock owner PID ${pid} is no longer running`
    : active
      ? `Project is locked by active PID ${pid}`
      : `Project lock belongs to PID ${pid} on another host`, {
    path,
    details: { pid, hostname: owner.hostname, createdAt: owner.createdAt, active },
  });
}

async function inspectJobLocks(rootDirectory: string): Promise<DoctorCheck[]> {
  const root = join(rootDirectory, 'locks');
  let paths: string[];
  try {
    paths = (await readdir(root, { recursive: true, withFileTypes: true }))
      .filter((entry) => entry.isDirectory() && entry.name.endsWith('.lock'))
      .map((entry) => join(entry.parentPath, entry.name));
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === 'ENOENT') return [check('lock.jobs', 'ok', 'No task locks are present', { path: root })];
    return [check('lock.jobs', 'error', 'Could not inspect task locks', { path: root })];
  }
  if (paths.length === 0) return [check('lock.jobs', 'ok', 'No task locks are present', { path: root })];
  const checks: DoctorCheck[] = [];
  for (const path of paths.sort()) {
    const owner = await readJsonFile(join(path, 'owner.json'));
    const pid = typeof owner?.pid === 'number' ? owner.pid : undefined;
    if (pid === undefined) {
      checks.push(check(`lock.job.${basename(path)}`, 'warning', 'Task lock has no readable owner; it may be newly created or stale', { path }));
      continue;
    }
    const active = processExists(pid);
    checks.push(check(`lock.job.${basename(path)}`, active ? 'ok' : 'warning', active
      ? `Task lock is held by active PID ${pid}`
      : `Task lock owner PID ${pid} is no longer running`, { path, details: { pid, active } }));
  }
  return checks;
}

export async function runDoctor(projectDirectory = '.'): Promise<DoctorReport> {
  const resolvedProject = resolve(projectDirectory);
  const projectFile = resolveProjectFile(resolvedProject);
  const checks: DoctorCheck[] = [];
  const nodeMajor = Number(process.versions.node.split('.')[0]);
  checks.push(check('node', nodeMajor >= 22 ? 'ok' : 'error', nodeMajor >= 22
    ? `Node.js ${process.version} satisfies the >=22 requirement`
    : `Node.js ${process.version} is too old; install Node.js 22 or newer`, {
    details: { version: process.version, required: '>=22' },
  }));

  const versions: Record<string, string> = {};
  for (const command of ['ffmpeg', 'ffprobe']) {
    try {
      versions[command] = await toolVersion(command);
      checks.push(check(command, 'ok', versions[command]!, { details: { command } }));
    } catch (error) {
      checks.push(check(command, 'error', `${command} is unavailable: ${(error as Error).message}`, {
        details: { command, remediation: `Install ${command} and ensure it is on PATH` },
      }));
    }
  }

  if (versions.ffmpeg) {
    try {
      const result = await execa('ffmpeg', ['-hide_banner', '-filters'], { reject: false, timeout: 5_000 });
      if (result.exitCode !== 0) throw new Error(`ffmpeg -filters exited with code ${result.exitCode}`);
      const available = new Set<string>();
      for (const line of `${result.stdout}\n${result.stderr}`.split(/\r?\n/)) {
        const match = /^\s*[TSC.]*\s+([A-Za-z0-9_]+)\s+/.exec(line);
        if (match?.[1]) available.add(match[1]);
      }
      const required = ['amix', 'atempo', 'crop', 'drawtext', 'overlay', 'scale', 'xfade'];
      const missing = required.filter((name) => !available.has(name));
      checks.push(check('ffmpeg.filters', missing.length === 0 ? 'ok' : 'error', missing.length === 0
        ? `Required FFmpeg filters are available: ${required.join(', ')}`
        : `Required FFmpeg filters are missing: ${missing.join(', ')}`, {
        details: { required, missing },
      }));
    } catch (error) {
      checks.push(check('ffmpeg.filters', 'error', `Could not enumerate FFmpeg filters: ${(error as Error).message}`));
    }
  }

  let project;
  try {
    project = (await loadProject(projectFile, 'doctor.project')).project;
    checks.push(check('project', 'ok', 'Project JSON is readable and valid', { path: projectFile }));
  } catch (error) {
    const normalized = asCodeCutError(error, 'doctor.project');
    checks.push(check('project', normalized.code === 'PROJECT_NOT_FOUND' ? 'warning' : 'error', normalized.code === 'PROJECT_NOT_FOUND'
      ? 'No project.json was found; directory checks will still run'
      : `${normalized.code}: ${normalized.message}`, { path: projectFile }));
  }

  const explicitFonts: string[] = [];
  for (const track of project?.tracks ?? []) {
    for (const clip of track.clips) {
      if (clip.type === 'text' && clip.fontFile !== undefined) explicitFonts.push(clip.fontFile);
    }
  }
  const missingFonts: string[] = [];
  for (const font of explicitFonts) {
    try {
      await access(resolve(dirname(projectFile), font), constants.R_OK);
    } catch {
      missingFonts.push(font);
    }
  }
  if (explicitFonts.length > 0) {
    checks.push(check('fonts.files', missingFonts.length === 0 ? 'ok' : 'error', missingFonts.length === 0
      ? `All ${explicitFonts.length} configured font file(s) are readable`
      : `Configured font files are unreadable: ${missingFonts.join(', ')}`, {
      details: { configured: explicitFonts, missing: missingFonts },
    }));
  }
  try {
    const font = await execa('fc-match', ['sans'], { reject: false, timeout: 5_000 });
    if (font.exitCode !== 0 || !font.stdout.trim()) throw new Error('fc-match returned no font');
    checks.push(check('fonts.default', 'ok', `Default font resolved with fontconfig: ${font.stdout.trim().split(/\r?\n/, 1)[0]}`));
  } catch (error) {
    checks.push(check('fonts.default', explicitFonts.length > 0 && missingFonts.length === 0 ? 'warning' : 'error',
      `Could not resolve the default sans font with fc-match: ${(error as Error).message}`, {
      details: { remediation: 'Install fontconfig and a sans font, or configure a readable fontFile for every text clip' },
    }));
  }

  checks.push(await checkWritableDirectory('permissions.project', dirname(projectFile)));
  const temporaryDirectory = tmpdir();
  checks.push(await checkWritableDirectory('permissions.temporary', temporaryDirectory));
  checks.push(await inspectProjectLock(projectFile));
  checks.push(...await inspectJobLocks(join(dirname(projectFile), '.codecut')));

  return {
    ok: checks.every((entry) => entry.status !== 'error'),
    projectDirectory: dirname(projectFile),
    checks,
  };
}

function normalizedLevel(value: unknown, fallback: JobLogLevel): JobLogLevel {
  if (value === 'warning') return 'warn';
  return typeof value === 'string' && LOG_LEVELS.has(value as JobLogLevel) ? value as JobLogLevel : fallback;
}

function parseLogLine(line: string, job: JobRecord, stream: JobLogStream): JobLogEntry {
  const fallbackLevel: JobLogLevel = stream === 'stderr' ? 'error' : 'info';
  if (line.startsWith('{')) {
    try {
      const value = JSON.parse(line) as Record<string, unknown>;
      if (typeof value === 'object' && value !== null) {
        const message = value.line ?? value.message ?? value.msg;
        if (typeof message === 'string') {
          return {
            jobId: job.id,
            stage: typeof value.stage === 'string' ? value.stage : job.stage,
            level: normalizedLevel(value.level, fallbackLevel),
            stream,
            line: message,
            ...(typeof value.at === 'string' ? { at: value.at } : {}),
          };
        }
      }
    } catch {
      // Raw process output is allowed to look like JSON without being structured CodeCut logs.
    }
  }
  const prefix = /^\[(debug|info|warn|warning|error)\]\s*/i.exec(line);
  return {
    jobId: job.id,
    stage: job.stage,
    level: prefix ? normalizedLevel(prefix[1]!.toLowerCase(), fallbackLevel) : fallbackLevel,
    stream,
    line: prefix ? line.slice(prefix[0].length) : line,
  };
}

function logPath(job: JobRecord, stream: JobLogStream): string | undefined {
  if (stream === 'stdout') return job.logs.stdout;
  if (stream === 'stderr') return job.logs.stderr;
  return job.logs.progress;
}

function selectedStreams(stream?: JobLogStream): JobLogStream[] {
  return stream ? [stream] : ['stdout', 'stderr'];
}

function matches(entry: JobLogEntry, query: LogQuery): boolean {
  return (!query.stage || entry.stage === query.stage)
    && (!query.level || entry.level === query.level)
    && (!query.stream || entry.stream === query.stream);
}

async function readStreamTail(
  job: JobRecord,
  stream: JobLogStream,
  query: LogQuery,
  limit: number,
): Promise<{ entries: JobLogEntry[]; truncated: boolean; offset: number }> {
  const path = logPath(job, stream);
  if (!path) return { entries: [], truncated: false, offset: 0 };
  const entries: JobLogEntry[] = [];
  let matched = 0;
  let offset = 0;
  try {
    const input = createReadStream(path, { encoding: 'utf8' });
    const reader = createInterface({ input, crlfDelay: Infinity });
    for await (const line of reader) {
      const entry = parseLogLine(line, job, stream);
      if (!matches(entry, query)) continue;
      matched += 1;
      if (limit > 0) {
        entries.push(entry);
        if (entries.length > limit) entries.shift();
      }
    }
    offset = input.bytesRead;
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== 'ENOENT') throw error;
  }
  return { entries, truncated: matched > entries.length, offset };
}

export async function readJobLogs(projectDirectory: string, query: LogQuery): Promise<JobLogResult> {
  const service = new JobService({ projectDirectory });
  const job = await service.get(query.jobId);
  const limit = query.tail ?? 100;
  const results = await Promise.all(selectedStreams(query.stream).map((stream) => readStreamTail(job, stream, query, limit)));
  return {
    job,
    logs: limit === 0 ? [] : results.flatMap((result) => result.entries).slice(-limit),
    truncated: results.some((result) => result.truncated),
  };
}

interface AppendState {
  offset: number;
  buffered: string;
  decoder: StringDecoder;
}

async function appendedText(path: string | undefined, state: AppendState): Promise<string[]> {
  if (!path) return [];
  let handle;
  try {
    const information = await stat(path);
    if (information.size < state.offset) {
      state.offset = 0;
      state.buffered = '';
      state.decoder = new StringDecoder('utf8');
    }
    if (information.size === state.offset) return [];
    const length = Math.min(information.size - state.offset, 64 * 1024);
    handle = await open(path, 'r');
    const buffer = Buffer.alloc(length);
    const { bytesRead } = await handle.read(buffer, 0, length, state.offset);
    state.offset += bytesRead;
    state.buffered += state.decoder.write(buffer.subarray(0, bytesRead));
    if (state.buffered.length > 1024 * 1024) {
      const overflow = state.buffered.length - 64 * 1024;
      state.buffered = state.buffered.slice(overflow);
      return ['[... an overlong log line was truncated ...]'];
    }
    const lines = state.buffered.split(/\r?\n/);
    state.buffered = lines.pop() ?? '';
    return lines;
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === 'ENOENT') return [];
    throw error;
  } finally {
    await handle?.close();
  }
}

const sleep = (milliseconds: number, signal?: AbortSignal) => new Promise<void>((resolveSleep) => {
  if (signal?.aborted) return resolveSleep();
  const onAbort = () => {
    clearTimeout(timer);
    resolveSleep();
  };
  const timer = setTimeout(() => {
    signal?.removeEventListener('abort', onAbort);
    resolveSleep();
  }, milliseconds);
  signal?.addEventListener('abort', onAbort, { once: true });
});

export async function* followJobLogs(projectDirectory: string, options: FollowLogsOptions): AsyncGenerator<JobLogEntry> {
  const service = new JobService({ projectDirectory });
  let job = await service.get(options.jobId);
  const limit = options.tail ?? 100;
  const initialResults = await Promise.all(selectedStreams(options.stream).map((stream) => readStreamTail(job, stream, options, limit)));
  const initialLogs = limit === 0 ? [] : initialResults.flatMap((result) => result.entries).slice(-limit);
  for (const entry of initialLogs) yield entry;
  const states = new Map<JobLogStream, AppendState>();
  const streams = selectedStreams(options.stream);
  for (const [index, stream] of streams.entries()) {
    states.set(stream, {
      offset: initialResults[index]?.offset ?? 0,
      buffered: '',
      decoder: new StringDecoder('utf8'),
    });
  }
  for (;;) {
    if (options.signal?.aborted) return;
    for (const [stream, state] of states) {
      const lines = await appendedText(logPath(job, stream), state);
      for (const line of lines) {
        const entry = parseLogLine(line, job, stream);
        if (matches(entry, options)) yield entry;
      }
    }
    job = await service.get(options.jobId);
    if ((options.stopOnTerminal ?? true) && isTerminalJob(job)) {
      for (const [stream, state] of states) {
        for (;;) {
          const previousOffset = state.offset;
          const lines = await appendedText(logPath(job, stream), state);
          for (const line of lines) {
            const entry = parseLogLine(line, job, stream);
            if (matches(entry, options)) yield entry;
          }
          if (state.offset === previousOffset) break;
        }
        state.buffered += state.decoder.end();
        if (state.buffered) {
          const entry = parseLogLine(state.buffered, job, stream);
          if (matches(entry, options)) yield entry;
          state.buffered = '';
        }
      }
      return;
    }
    await sleep(options.pollMs ?? 100, options.signal);
  }
}

async function writeJson(path: string, value: unknown): Promise<void> {
  await writeFile(path, `${JSON.stringify(redactDiagnosticValue(value), null, 2)}\n`, 'utf8');
}

async function copySanitizedText(source: string, target: string): Promise<boolean> {
  try {
    await stat(source);
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === 'ENOENT') return false;
    throw error;
  }
  let buffered = '';
  const decoder = new StringDecoder('utf8');
  const redactor = new Transform({
    transform(chunk: Buffer, _encoding, callback) {
      buffered += decoder.write(chunk);
      const lines = buffered.split(/\r?\n/);
      buffered = lines.pop() ?? '';
      callback(null, lines.length > 0 ? `${lines.map(redactDiagnosticText).join('\n')}\n` : undefined);
    },
    flush(callback) {
      buffered += decoder.end();
      callback(null, buffered ? `${redactDiagnosticText(buffered)}\n` : undefined);
    },
  });
  await pipeline(createReadStream(source), redactor, createWriteStream(target, { encoding: 'utf8' }));
  return true;
}

async function environmentSnapshot(): Promise<Record<string, unknown>> {
  const tools: Record<string, string> = {};
  for (const command of ['ffmpeg', 'ffprobe']) {
    try {
      tools[command] = await toolVersion(command);
    } catch (error) {
      tools[command] = `unavailable: ${(error as Error).message}`;
    }
  }
  return {
    capturedAt: new Date().toISOString(),
    node: process.version,
    platform: process.platform,
    architecture: process.arch,
    osRelease: release(),
    tools,
    note: 'Environment variables and credential values are intentionally not collected.',
  };
}

export async function diagnoseJob(options: DiagnoseOptions): Promise<DiagnoseResult> {
  const service = new JobService({ projectDirectory: options.projectDirectory });
  const job = await service.get(options.jobId);
  const paths = service.store.paths(job.id);
  const directory = options.output
    ? resolve(service.store.projectDirectory, options.output)
    : await mkdtemp(join(paths.diagnostics, 'report-'));
  if (options.output) await mkdir(directory, { recursive: false });
  const files: string[] = [];
  const addJson = async (name: string, value: unknown) => {
    await writeJson(join(directory, name), value);
    files.push(name);
  };
  const addText = async (name: string, source: string | undefined) => {
    if (source && await copySanitizedText(source, join(directory, name))) files.push(name);
  };

  await addJson('environment.json', await environmentSnapshot());
  await addJson('job.json', job);
  await addJson('error.json', job.error ?? null);
  const request = await service.store.getRequest(job.id);
  const { env: _environment, ...processWithoutEnvironment } = request.process;
  await addJson('request.json', { ...request, process: processWithoutEnvironment });
  const snapshot = await service.store.getSnapshot(job.id);
  if (snapshot) {
    await addJson('snapshot.json', snapshot);
    await addJson('assets.json', {
      registered: snapshot.project.assets,
      capturedFiles: snapshot.assets,
    });
  } else {
    await addJson('assets.json', []);
  }
  if (job.diagnostics.arguments) {
    try {
      await addJson('arguments.json', JSON.parse(await readFile(job.diagnostics.arguments, 'utf8')));
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== 'ENOENT') throw error;
    }
  }
  await addText('filter_complex.txt', job.diagnostics.filterGraph);
  if (job.diagnostics.plan) {
    try {
      await addJson('plan.json', JSON.parse(await readFile(job.diagnostics.plan, 'utf8')));
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== 'ENOENT') throw error;
    }
  }
  await addText('stderr.log', job.logs.stderr);
  await addText('stdout.log', job.logs.stdout);
  await addText('progress.log', job.logs.progress);
  await addText('progress.jsonl', job.logs.progressEvents);

  let revisions: unknown = { jobRevision: job.projectRevision, revisions: [], currentId: null };
  try {
    revisions = { jobRevision: job.projectRevision, ...await listHistory(service.store.projectDirectory) };
  } catch (error) {
    revisions = {
      ...revisions as Record<string, unknown>,
      warning: `Project history unavailable: ${(error as Error).message}`,
    };
  }
  await addJson('revisions.json', revisions);
  const manifestFiles = [...files].sort();
  await writeJson(join(directory, 'manifest.json'), {
    version: 1,
    jobId: job.id,
    createdAt: new Date().toISOString(),
    files: manifestFiles,
    redacted: true,
    sourceMediaIncluded: false,
    environmentVariablesIncluded: false,
  });
  return {
    jobId: job.id,
    directory,
    files: [...manifestFiles, 'manifest.json'].sort(),
    redacted: true,
    sourceMediaIncluded: false,
    environmentVariablesIncluded: false,
  };
}
