import { execa } from 'execa';
import { mkdir, readFile, stat } from 'node:fs/promises';
import { createRequire } from 'node:module';
import { dirname, extname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import type { ErrorObject } from 'ajv/dist/2020.js';
import { CodeCutError, ExitCode } from './errors.js';
import {
  VocalAutotuneReportSchema,
  VocalAutotuneRequestSchema,
  type VocalAutotuneReport,
  type VocalAutotuneRequest,
} from './schema.js';

const require = createRequire(import.meta.url);
const Ajv2020 = require('ajv/dist/2020.js') as typeof import('ajv/dist/2020.js').default;
const addFormats = require('ajv-formats') as typeof import('ajv-formats').default;
const ajv = new Ajv2020({ allErrors: true, strict: true });
addFormats(ajv);
const validateRequestShape = ajv.compile(VocalAutotuneRequestSchema);
const validateReportShape = ajv.compile(VocalAutotuneReportSchema);
const EPSILON = 1e-9;

export interface VocalAutotuneOptions {
  requestPath: string;
  output?: string;
  report?: string;
  python?: string;
  force?: boolean;
}

export interface VocalAutotuneResult {
  outputPath: string;
  reportPath: string;
  report: VocalAutotuneReport;
}

interface ValidationIssue {
  path: string;
  message: string;
  keyword?: string;
}

interface WorkerError {
  code?: string;
  message?: string;
  diagnostics?: unknown;
  retryable?: boolean;
}

function error(
  code: string,
  message: string,
  exitCode: ExitCode,
  options: { path?: string; cause?: unknown; diagnostics?: unknown; retryable?: boolean } = {},
): CodeCutError {
  return new CodeCutError(code, message, exitCode, {
    stage: 'vocal.autotune',
    ...(options.path === undefined ? {} : { path: options.path }),
    ...(options.cause === undefined ? {} : { cause: options.cause }),
    ...(options.diagnostics === undefined ? {} : { diagnostics: options.diagnostics }),
    ...(options.retryable === undefined ? {} : { retryable: options.retryable }),
  });
}

function shapeIssues(errors: ErrorObject[] | null | undefined): ValidationIssue[] {
  return (errors ?? []).map((entry) => {
    let path = entry.instancePath || '/';
    if (entry.keyword === 'required' && typeof entry.params.missingProperty === 'string') {
      path = `${path === '/' ? '' : path}/${entry.params.missingProperty}`;
    }
    return {
      path,
      message: entry.message ?? 'is invalid',
      ...(entry.keyword === undefined ? {} : { keyword: entry.keyword }),
    };
  });
}

function invalidRequest(path: string, issues: ValidationIssue[]): CodeCutError {
  return error(
    'AUTOTUNE_REQUEST_INVALID',
    issues.length === 1 ? `Autotune request is invalid: ${issues[0]?.message}` : `Autotune request has ${issues.length} validation errors`,
    ExitCode.ProjectValidation,
    { path, diagnostics: { issues }, retryable: false },
  );
}

function validateSemantics(request: VocalAutotuneRequest, requestPath: string): void {
  const issues: ValidationIssue[] = [];
  const phraseIds = new Set<string>();
  const noteIds = new Set<string>();
  const framePeriod = (request.framePeriodMs ?? 5) / 1000;
  const timeline: { note: VocalAutotuneRequest['phrases'][number]['notes'][number]; phraseIndex: number; noteIndex: number }[] = [];
  let latestTargetEnd = 0;

  for (const [phraseIndex, phrase] of request.phrases.entries()) {
    if (phraseIds.has(phrase.id)) issues.push({ path: `/phrases/${phraseIndex}/id`, message: `duplicate phrase id "${phrase.id}"`, keyword: 'unique' });
    phraseIds.add(phrase.id);
    let previousEnd: number | undefined;
    for (const [noteIndex, note] of phrase.notes.entries()) {
      const base = `/phrases/${phraseIndex}/notes/${noteIndex}`;
      if (noteIds.has(note.id)) issues.push({ path: `${base}/id`, message: `duplicate note id "${note.id}"`, keyword: 'unique' });
      noteIds.add(note.id);
      if (note.source.end <= note.source.start + EPSILON) {
        issues.push({ path: `${base}/source/end`, message: 'must be greater than source.start', keyword: 'range' });
      } else if (note.source.end - note.source.start < framePeriod - EPSILON) {
        issues.push({ path: `${base}/source/end`, message: 'source range must contain at least one analysis frame', keyword: 'range' });
      }
      if (note.source.vowelStart !== undefined
        && (note.source.vowelStart < note.source.start - EPSILON || note.source.vowelStart >= note.source.end - EPSILON)) {
        issues.push({ path: `${base}/source/vowelStart`, message: 'must be inside [source.start, source.end)', keyword: 'range' });
      }
      if (note.target.duration < framePeriod - EPSILON) {
        issues.push({ path: `${base}/target/duration`, message: 'target duration must contain at least one analysis frame', keyword: 'range' });
      }
      if (note.target.vowelOffset !== undefined && note.target.vowelOffset >= note.target.duration - EPSILON) {
        issues.push({ path: `${base}/target/vowelOffset`, message: 'must be less than target.duration', keyword: 'range' });
      }
      const targetEnd = note.target.start + note.target.duration;
      latestTargetEnd = Math.max(latestTargetEnd, targetEnd);
      if (previousEnd !== undefined && Math.abs(note.target.start - previousEnd) > EPSILON) {
        issues.push({
          path: `${base}/target/start`,
          message: note.target.start < previousEnd
            ? 'must not overlap the previous note in this phrase'
            : 'must be contiguous with the previous note in this phrase; use separate phrases for silence',
          keyword: 'timeline',
        });
      }
      previousEnd = targetEnd;
      timeline.push({ note, phraseIndex, noteIndex });
    }
  }

  timeline.sort((left, right) => left.note.target.start - right.note.target.start);
  for (let index = 1; index < timeline.length; index += 1) {
    const previous = timeline[index - 1]!;
    const current = timeline[index]!;
    if (current.note.target.start < previous.note.target.start + previous.note.target.duration - EPSILON) {
      issues.push({
        path: `/phrases/${current.phraseIndex}/notes/${current.noteIndex}/target/start`,
        message: `overlaps note "${previous.note.id}" from another phrase`,
        keyword: 'timeline',
      });
    }
  }
  if (request.duration !== undefined && request.duration < latestTargetEnd - EPSILON) {
    issues.push({ path: '/duration', message: `must be at least the last target note end (${latestTargetEnd})`, keyword: 'range' });
  }
  if ((request.f0Ceil ?? 1000) <= (request.f0Floor ?? 50)) {
    issues.push({ path: '/f0Ceil', message: 'must be greater than f0Floor', keyword: 'range' });
  }
  if (issues.length > 0) throw invalidRequest(requestPath, issues);
}

async function readRequest(path: string): Promise<VocalAutotuneRequest> {
  let source: string;
  try {
    source = await readFile(path, 'utf8');
  } catch (cause) {
    throw error('AUTOTUNE_REQUEST_READ_FAILED', 'Could not read the autotune request JSON file', ExitCode.Usage, { path, cause });
  }
  let value: unknown;
  try {
    value = JSON.parse(source);
  } catch (cause) {
    throw error('AUTOTUNE_REQUEST_PARSE_ERROR', 'Autotune request must be a JSON object', ExitCode.Usage, { path, cause });
  }
  if (typeof value === 'object' && value !== null && 'schemaVersion' in value) {
    const version = (value as { schemaVersion?: unknown }).schemaVersion;
    if (version !== 1) {
      throw invalidRequest(path, [{ path: '/schemaVersion', message: `unsupported autotune schema version ${JSON.stringify(version)}; supported version is 1`, keyword: 'const' }]);
    }
  }
  if (!validateRequestShape(value)) throw invalidRequest(path, shapeIssues(validateRequestShape.errors));
  const request = value as VocalAutotuneRequest;
  validateSemantics(request, path);
  return request;
}

function requestRelative(base: string, path: string): string {
  return resolve(base, path);
}

function defaultReportPath(output: string): string {
  const extension = extname(output);
  return extension.toLowerCase() === '.wav'
    ? `${output.slice(0, -extension.length)}.report.json`
    : `${output}.report.json`;
}

async function assertSource(path: string): Promise<void> {
  let info;
  try {
    info = await stat(path);
  } catch (cause) {
    throw error('AUTOTUNE_SOURCE_NOT_FOUND', 'Autotune source media does not exist or is not readable', ExitCode.Media, { path, cause });
  }
  if (!info.isFile()) throw error('AUTOTUNE_SOURCE_NOT_FILE', 'Autotune source must be a media file', ExitCode.Media, { path });
}

async function assertOutput(path: string, force: boolean): Promise<void> {
  try {
    const info = await stat(path);
    if (!info.isFile()) throw error('AUTOTUNE_OUTPUT_NOT_FILE', 'Autotune output path is not a file', ExitCode.Usage, { path });
    if (!force) {
      throw error('AUTOTUNE_OUTPUT_EXISTS', 'Autotune output already exists; use --force to replace it', ExitCode.Usage, { path, retryable: false });
    }
  } catch (cause) {
    if (cause instanceof CodeCutError) throw cause;
    if ((cause as NodeJS.ErrnoException).code !== 'ENOENT') {
      throw error('AUTOTUNE_OUTPUT_NOT_WRITABLE', 'Could not inspect the autotune output path', ExitCode.Internal, { path, cause, retryable: true });
    }
  }
}

function parseWorkerResponse(stdout: string): { ok: boolean; report?: unknown; error?: WorkerError } {
  try {
    return JSON.parse(stdout) as { ok: boolean; report?: unknown; error?: WorkerError };
  } catch (cause) {
    throw error('AUTOTUNE_WORKER_INVALID', 'Autotune worker did not return valid JSON', ExitCode.Media, {
      cause,
      diagnostics: { stdoutTail: stdout.slice(-8192) },
    });
  }
}

export async function autotuneVocal(options: VocalAutotuneOptions): Promise<VocalAutotuneResult> {
  const requestPath = resolve(options.requestPath);
  const request = await readRequest(requestPath);
  const base = dirname(requestPath);
  const outputPath = options.output === undefined ? requestRelative(base, request.output) : resolve(options.output);
  const reportPath = options.report === undefined
    ? request.report === undefined ? defaultReportPath(outputPath) : requestRelative(base, request.report)
    : resolve(options.report);
  const sourcePath = requestRelative(base, request.source);
  const force = options.force ?? false;

  if (!outputPath.toLowerCase().endsWith('.wav')) {
    throw error('AUTOTUNE_OUTPUT_INVALID', 'Autotune output must be a WAV file', ExitCode.ProjectValidation, { path: outputPath });
  }
  if (!reportPath.toLowerCase().endsWith('.json')) {
    throw error('AUTOTUNE_REPORT_INVALID', 'Autotune report must be a JSON file', ExitCode.ProjectValidation, { path: reportPath });
  }
  const reserved = new Map([[sourcePath, 'source'], [requestPath, 'request']]);
  for (const [path, label] of [[outputPath, 'output'], [reportPath, 'report']] as const) {
    if (reserved.has(path)) throw error('AUTOTUNE_PATH_CONFLICT', `Autotune ${label} must not overwrite the ${reserved.get(path)}`, ExitCode.ProjectValidation, { path });
    reserved.set(path, label);
  }
  if (outputPath === reportPath) throw error('AUTOTUNE_PATH_CONFLICT', 'Autotune output and report must be different files', ExitCode.ProjectValidation, { path: outputPath });

  await assertSource(sourcePath);
  await Promise.all([assertOutput(outputPath, force), assertOutput(reportPath, force)]);
  try {
    await Promise.all([mkdir(dirname(outputPath), { recursive: true }), mkdir(dirname(reportPath), { recursive: true })]);
  } catch (cause) {
    throw error('AUTOTUNE_OUTPUT_NOT_WRITABLE', 'Could not create autotune output directories', ExitCode.Internal, { cause, retryable: true });
  }

  const workerPath = fileURLToPath(new URL('./workers/vocal_autotune.py', import.meta.url));
  const python = options.python ?? process.env.CODECUT_AUTOTUNE_PYTHON ?? 'python3';
  const normalized = { ...request, source: sourcePath, output: outputPath, report: reportPath };
  let processResult;
  try {
    processResult = await execa(python, [workerPath], {
      input: JSON.stringify(normalized),
      reject: false,
      timeout: 600_000,
      maxBuffer: 64 * 1024 * 1024,
    });
  } catch (cause) {
    const code = (cause as NodeJS.ErrnoException).code;
    throw error(
      code === 'ENOENT' ? 'AUTOTUNE_PYTHON_NOT_FOUND' : 'AUTOTUNE_WORKER_START_FAILED',
      code === 'ENOENT' ? `Python executable "${python}" was not found; install Python 3 or set --python` : 'Could not start the autotune Python worker',
      ExitCode.Media,
      { cause, retryable: code !== 'ENOENT', diagnostics: { python, workerPath } },
    );
  }

  if (processResult.code === 'ENOENT') {
    throw error('AUTOTUNE_PYTHON_NOT_FOUND', `Python executable "${python}" was not found; install Python 3 or set --python`, ExitCode.Media, {
      retryable: false,
      diagnostics: { python, workerPath },
    });
  }
  const response = parseWorkerResponse(processResult.stdout);
  if (processResult.failed || !response.ok) {
    const workerError = response.error ?? {};
    throw error(
      workerError.code ?? 'AUTOTUNE_WORKER_FAILED',
      workerError.message ?? 'Autotune Python worker failed',
      ExitCode.Media,
      {
        retryable: workerError.retryable ?? false,
        diagnostics: {
          ...(typeof workerError.diagnostics === 'object' && workerError.diagnostics !== null ? workerError.diagnostics : { details: workerError.diagnostics }),
          exitCode: processResult.exitCode,
          timedOut: processResult.timedOut,
          stderrTail: processResult.stderr.slice(-8192),
        },
      },
    );
  }
  if (!validateReportShape(response.report)) {
    throw error('AUTOTUNE_WORKER_INVALID', 'Autotune worker returned an invalid report', ExitCode.Media, {
      diagnostics: { issues: shapeIssues(validateReportShape.errors), stderrTail: processResult.stderr.slice(-4096) },
    });
  }
  return { outputPath, reportPath, report: response.report as VocalAutotuneReport };
}
