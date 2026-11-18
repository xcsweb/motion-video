import { execa, type ResultPromise } from 'execa';
import { open, readFile, stat } from 'node:fs/promises';
import type { FileHandle } from 'node:fs/promises';
import { join } from 'node:path';
import { StringDecoder } from 'node:string_decoder';
import type { Readable } from 'node:stream';
import { CodeCutError, ExitCode } from './errors.js';

export type StopReason = 'cancelled' | 'timedOut';

export interface ProgressState {
  percent: number;
  frame?: number;
  timeSeconds?: number;
  speed?: number;
  end: boolean;
}

export interface ProcessSpec {
  command: string;
  args: string[];
  cwd?: string;
  env?: Record<string, string>;
  progress?: 'ffmpeg' | 'none';
  durationSeconds?: number;
}

export interface ProcessLogPaths {
  stdout: string;
  stderr: string;
  progress?: string;
  progressEvents?: string;
}

export interface ProcessExecutionResult {
  pid: number;
  exitCode?: number;
  signal?: string;
  durationMs: number;
  forcefullyTerminated?: boolean;
  stopReason?: StopReason;
  progress?: ProgressState;
  logs: ProcessLogPaths;
  tails: { stdout: string; stderr: string };
}

export class ProcessController {
  private handler: ((reason: StopReason) => void) | undefined;
  private stopReason: StopReason | undefined;

  get reason(): StopReason | undefined {
    return this.stopReason;
  }

  stop(reason: StopReason): void {
    if (this.stopReason) return;
    this.stopReason = reason;
    this.handler?.(reason);
  }

  attach(handler: (reason: StopReason) => void): void {
    this.handler = handler;
    if (this.stopReason) handler(this.stopReason);
  }
}

export class BoundedLogTail {
  private value = '';
  private truncated = false;

  constructor(private readonly limit: number) {}

  append(value: string): void {
    if (value.length === 0 || this.limit <= 0) return;
    this.value += value;
    if (this.value.length > this.limit) {
      this.value = this.value.slice(-this.limit);
      this.truncated = true;
    }
  }

  toString(): string {
    return this.truncated ? `[... earlier output truncated; full output is in the log file ...]\n${this.value}` : this.value;
  }
}

function progressError(line: string, reason: string): CodeCutError {
  return new CodeCutError('FFMPEG_PROGRESS_INVALID', `Invalid FFmpeg progress: ${reason}`, ExitCode.Media, {
    stage: 'ffmpeg.progress',
    retryable: false,
    diagnostics: { line, reason },
  });
}

function nonNegativeNumber(line: string, value: string, integer = false): number {
  if (!value || !/^(?:\d+(?:\.\d*)?|\.\d+)$/.test(value)) throw progressError(line, 'expected a non-negative number');
  const parsed = Number(value);
  if (!Number.isFinite(parsed) || (integer && !Number.isInteger(parsed))) {
    throw progressError(line, integer ? 'expected a non-negative integer' : 'expected a finite number');
  }
  return parsed;
}

function parseClock(line: string, value: string): number {
  const match = /^(\d+):([0-5]\d):([0-5]\d(?:\.\d+)?)$/.exec(value);
  if (!match) throw progressError(line, 'out_time must be HH:MM:SS.microseconds');
  return Number(match[1]) * 3600 + Number(match[2]) * 60 + Number(match[3]);
}

/** Parses one FFmpeg -progress key/value stream without mixing it with stderr. */
export class FfmpegProgressParser {
  private buffered = '';
  private current: ProgressState = { percent: 0, end: false };
  private sawEnd = false;

  constructor(private readonly durationSeconds?: number) {}

  get state(): ProgressState {
    return { ...this.current };
  }

  pushLine(line: string): ProgressState | undefined {
    if (line.endsWith('\r')) line = line.slice(0, -1);
    if (!line) return undefined;
    const separator = line.indexOf('=');
    if (separator <= 0) throw progressError(line, 'expected key=value');
    const key = line.slice(0, separator);
    const value = line.slice(separator + 1);
    if (this.sawEnd) throw progressError(line, 'received data after progress=end');

    if (key === 'frame') {
      if (value !== 'N/A') this.current.frame = nonNegativeNumber(line, value, true);
    } else if (key === 'out_time_us' || key === 'out_time_ms') {
      if (value !== 'N/A') this.current.timeSeconds = nonNegativeNumber(line, value, true) / 1_000_000;
    } else if (key === 'out_time') {
      if (value !== 'N/A') this.current.timeSeconds = parseClock(line, value);
    } else if (key === 'speed') {
      if (value !== 'N/A') {
        const normalized = value.trim();
        if (!normalized.endsWith('x')) throw progressError(line, 'speed must end in x');
        this.current.speed = nonNegativeNumber(line, normalized.slice(0, -1));
      }
    } else if (key === 'progress') {
      if (value !== 'continue' && value !== 'end') throw progressError(line, 'progress must be continue or end');
      this.sawEnd = value === 'end';
      this.current.end = this.sawEnd;
      if (this.current.timeSeconds !== undefined && this.durationSeconds !== undefined && this.durationSeconds > 0) {
        this.current.percent = Math.min(100, this.current.timeSeconds / this.durationSeconds * 100);
      }
      if (this.sawEnd) this.current.percent = 100;
      return this.state;
    }
    return undefined;
  }

  pushChunk(chunk: string): ProgressState[] {
    this.buffered += chunk;
    const events: ProgressState[] = [];
    for (;;) {
      const newline = this.buffered.indexOf('\n');
      if (newline < 0) break;
      const line = this.buffered.slice(0, newline);
      this.buffered = this.buffered.slice(newline + 1);
      const event = this.pushLine(line);
      if (event) events.push(event);
    }
    return events;
  }

  finish(): ProgressState {
    if (this.buffered) {
      const line = this.buffered;
      this.buffered = '';
      this.pushLine(line);
    }
    if (!this.sawEnd) throw progressError('', 'stream ended without progress=end');
    return this.state;
  }
}

class LogFile {
  private constructor(private readonly handle: FileHandle, readonly path: string) {}

  static async open(path: string): Promise<LogFile> {
    return new LogFile(await open(path, 'w'), path);
  }

  async append(chunk: string | Uint8Array): Promise<void> {
    const data = typeof chunk === 'string' ? Buffer.from(chunk) : Buffer.from(chunk);
    let offset = 0;
    while (offset < data.length) {
      const { bytesWritten } = await this.handle.write(data, offset, data.length - offset);
      if (bytesWritten <= 0) throw new Error('Log write made no progress');
      offset += bytesWritten;
    }
  }

  async close(): Promise<void> {
    await this.handle.close();
  }
}

class ProcessLogs {
  private constructor(
    readonly stdout: LogFile,
    readonly stderr: LogFile,
    readonly progress?: LogFile,
    readonly events?: LogFile,
  ) {}

  static async create(directory: string, ffmpegProgress: boolean): Promise<ProcessLogs> {
    const files: LogFile[] = [];
    try {
      const stdout = await LogFile.open(join(directory, 'stdout.log'));
      files.push(stdout);
      const stderr = await LogFile.open(join(directory, 'stderr.log'));
      files.push(stderr);
      const progress = ffmpegProgress ? await LogFile.open(join(directory, 'progress.log')) : undefined;
      if (progress) files.push(progress);
      const events = ffmpegProgress ? await LogFile.open(join(directory, 'progress.jsonl')) : undefined;
      if (events) files.push(events);
      return new ProcessLogs(stdout, stderr, progress, events);
    } catch (error) {
      await Promise.all(files.map((file) => file.close().catch(() => undefined)));
      throw new CodeCutError('DISK_WRITE_FAILED', 'Could not open process log files', ExitCode.Internal, {
        stage: 'process.log',
        path: directory,
        cause: error,
        retryable: true,
      });
    }
  }

  paths(): ProcessLogPaths {
    return {
      stdout: this.stdout.path,
      stderr: this.stderr.path,
      ...(this.progress ? { progress: this.progress.path } : {}),
      ...(this.events ? { progressEvents: this.events.path } : {}),
    };
  }

  async close(): Promise<void> {
    const files = [this.stdout, this.stderr, this.progress, this.events].filter((file): file is LogFile => file !== undefined);
    const results = await Promise.allSettled(files.map((file) => file.close()));
    const failure = results.find((result) => result.status === 'rejected');
    if (failure) throw failure.reason;
  }
}

export interface ExecuteProcessOptions {
  spec: ProcessSpec;
  logDirectory: string;
  controller?: ProcessController;
  timeoutMs?: number;
  gracePeriodMs?: number;
  tailBytes?: number;
  onSpawn?: (pid: number) => void | Promise<void>;
  onProgress?: (progress: ProgressState) => void;
  onStopping?: (reason: StopReason) => void;
}

function asDiskError(error: unknown, directory: string): CodeCutError {
  if (error instanceof CodeCutError) return error;
  return new CodeCutError('DISK_WRITE_FAILED', 'Could not write process output logs', ExitCode.Internal, {
    stage: 'process.log',
    path: directory,
    cause: error,
    retryable: true,
  });
}

export async function executeControlledProcess(options: ExecuteProcessOptions): Promise<ProcessExecutionResult> {
  const controller = options.controller ?? new ProcessController();
  const tailBytes = options.tailBytes ?? 64 * 1024;
  const logs = await ProcessLogs.create(options.logDirectory, options.spec.progress === 'ffmpeg');
  const stdoutTail = new BoundedLogTail(tailBytes);
  const stderrTail = new BoundedLogTail(tailBytes);
  const parser = options.spec.progress === 'ffmpeg' ? new FfmpegProgressParser(options.spec.durationSeconds) : undefined;
  let child: ResultPromise<any> | undefined;
  let terminationStarted = false;
  let forcefullyTerminated = false;
  let forceTimer: NodeJS.Timeout | undefined;
  let timeoutTimer: NodeJS.Timeout | undefined;
  const failures: unknown[] = [];

  const terminate = (reason?: StopReason) => {
    if (terminationStarted || !child) return;
    terminationStarted = true;
    if (reason) options.onStopping?.(reason);
    child.kill('SIGTERM');
    forceTimer = setTimeout(() => {
      if (child?.kill('SIGKILL')) forcefullyTerminated = true;
    }, options.gracePeriodMs ?? 5_000);
    forceTimer.unref();
  };
  controller.attach(terminate);

  try {
    child = execa(options.spec.command, options.spec.args, {
      ...(options.spec.cwd === undefined ? {} : { cwd: options.spec.cwd }),
      ...(options.spec.env === undefined ? {} : { env: options.spec.env }),
      stdin: 'ignore',
      stdout: 'pipe',
      stderr: 'pipe',
      buffer: false,
      reject: false,
      cleanup: false,
      forceKillAfterDelay: false,
    }) as unknown as ResultPromise<any>;
  } catch (error) {
    await logs.close().catch(() => undefined);
    throw new CodeCutError('PROCESS_START_FAILED', 'Could not start the media process', ExitCode.Media, {
      stage: 'process.spawn',
      cause: error,
      retryable: true,
    });
  }

  const activeChild = child!;
  const resultPromise = activeChild.then((result) => result);
  void resultPromise.catch(() => undefined);
  let spawnResolve: (() => void) | undefined;
  let spawnReject: ((error: unknown) => void) | undefined;
  const spawned = new Promise<void>((resolve, reject) => {
    spawnResolve = resolve;
    spawnReject = reject;
  });
  const onSpawnEvent = () => spawnResolve?.();
  const onErrorEvent = (error: unknown) => spawnReject?.(error);
  activeChild.once('spawn', onSpawnEvent);
  activeChild.once('error', onErrorEvent);

  const consume = async (stream: Readable, kind: 'stdout' | 'stderr'): Promise<void> => {
    const decoder = new StringDecoder('utf8');
    try {
      for await (const chunk of stream) {
        const data = chunk as Uint8Array;
        const text = decoder.write(data);
        if (kind === 'stdout') {
          await logs.stdout.append(data);
          stdoutTail.append(text);
          if (parser && logs.progress && logs.events) {
            await logs.progress.append(data);
            for (const progress of parser.pushChunk(text)) {
              await logs.events.append(`${JSON.stringify({ at: new Date().toISOString(), ...progress })}\n`);
              options.onProgress?.(progress);
            }
          }
        } else {
          await logs.stderr.append(data);
          stderrTail.append(text);
        }
      }
      const remainder = decoder.end();
      if (kind === 'stdout') {
        stdoutTail.append(remainder);
        if (parser && logs.events) {
          for (const progress of parser.pushChunk(remainder)) {
            await logs.events.append(`${JSON.stringify({ at: new Date().toISOString(), ...progress })}\n`);
            options.onProgress?.(progress);
          }
          const final = parser.finish();
          await logs.events.append(`${JSON.stringify({ at: new Date().toISOString(), final: true, ...final })}\n`);
        }
      } else stderrTail.append(remainder);
    } catch (error) {
      failures.push(asDiskError(error, options.logDirectory));
      terminate();
    }
  };

  const stdout = activeChild.stdout as Readable | null;
  const stderr = activeChild.stderr as Readable | null;
  if (!stdout || !stderr) {
    activeChild.kill('SIGKILL');
    await logs.close().catch(() => undefined);
    throw new CodeCutError('PROCESS_START_FAILED', 'The media process did not expose output streams', ExitCode.Media, {
      stage: 'process.spawn',
      retryable: false,
    });
  }
  const consumers = [consume(stdout, 'stdout'), consume(stderr, 'stderr')];

  try {
    await spawned;
  } catch (error) {
    activeChild.off('spawn', onSpawnEvent);
    activeChild.off('error', onErrorEvent);
    await resultPromise.catch(() => undefined);
    await Promise.all(consumers);
    await logs.close().catch(() => undefined);
    throw new CodeCutError('PROCESS_START_FAILED', 'Could not start the media process', ExitCode.Media, {
      stage: 'process.spawn',
      cause: error,
      retryable: true,
      diagnostics: { command: options.spec.command },
    });
  }
  activeChild.off('spawn', onSpawnEvent);
  activeChild.off('error', onErrorEvent);

  const pid = activeChild.pid;
  if (pid === undefined) {
    failures.push(new CodeCutError('PROCESS_START_FAILED', 'The media process has no PID', ExitCode.Media, {
      stage: 'process.spawn', retryable: false,
    }));
    terminate();
  } else {
    try {
      await options.onSpawn?.(pid);
    } catch (error) {
      failures.push(error);
      terminate();
    }
  }
  if (controller.reason && !terminationStarted) terminate(controller.reason);
  if (options.timeoutMs !== undefined && options.timeoutMs > 0) {
    timeoutTimer = setTimeout(() => controller.stop('timedOut'), options.timeoutMs);
  }

  const result = await resultPromise;
  if (timeoutTimer) clearTimeout(timeoutTimer);
  if (forceTimer) clearTimeout(forceTimer);
  await Promise.all(consumers);
  try {
    await logs.close();
  } catch (error) {
    failures.push(asDiskError(error, options.logDirectory));
  }
  if (failures.length > 0) throw failures[0];

  const stopReason = controller.reason;
  if (!stopReason && result.failed) {
    throw new CodeCutError('MEDIA_PROCESS_FAILED', `Media process failed${result.exitCode === undefined ? '' : ` with exit code ${result.exitCode}`}`, ExitCode.Media, {
      stage: 'process.execute',
      retryable: false,
      diagnostics: {
        command: options.spec.command,
        args: options.spec.args,
        exitCode: result.exitCode,
        signal: result.signal,
        logs: logs.paths(),
        stderrTail: stderrTail.toString(),
      },
    });
  }

  return {
    pid: pid ?? 0,
    ...(result.exitCode === undefined ? {} : { exitCode: result.exitCode }),
    ...(result.signal === undefined ? {} : { signal: result.signal }),
    durationMs: result.durationMs,
    ...(forcefullyTerminated ? { forcefullyTerminated } : {}),
    ...(stopReason === undefined ? {} : { stopReason }),
    ...(parser ? { progress: parser.state } : {}),
    logs: logs.paths(),
    tails: { stdout: stdoutTail.toString(), stderr: stderrTail.toString() },
  };
}

export async function readBoundedLogTail(path: string, limit = 16 * 1024): Promise<string> {
  try {
    const information = await stat(path);
    const handle = await open(path, 'r');
    try {
      const length = Math.min(information.size, limit);
      const buffer = Buffer.alloc(length);
      await handle.read(buffer, 0, length, Math.max(0, information.size - length));
      const tail = buffer.toString('utf8');
      return information.size > length ? `[... earlier output truncated; full output is in the log file ...]\n${tail}` : tail;
    } finally {
      await handle.close();
    }
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === 'ENOENT') return '';
    throw error;
  }
}

export async function readCompleteLog(path: string): Promise<string> {
  try {
    return await readFile(path, 'utf8');
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === 'ENOENT') return '';
    throw error;
  }
}
