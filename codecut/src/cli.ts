#!/usr/bin/env node
import { once } from 'node:events';
import { readFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { analyzeAsset, generateAssetPreview } from './asset-jobs.js';
import {
  addAsset,
  getAssetStatus,
  listAssets,
  probeAsset,
  removeAsset,
} from './assets.js';
import { CAPABILITIES } from './capabilities.js';
import {
  diagnoseJob,
  followJobLogs,
  readJobLogs,
  runDoctor,
  type JobLogLevel,
  type JobLogStream,
} from './diagnostics.js';
import { applyEdit } from './edit.js';
import {
  diffRevisions,
  listHistory,
  redoProject,
  undoProject,
  type ProjectTransactionResult,
} from './history.js';
import {
  asCodeCutError,
  CodeCutError,
  ExitCode,
  formatTextError,
} from './errors.js';
import {
  calculateTimeline,
  initProject,
  loadProject,
} from './project.js';
import {
  exitCodeForJob,
  JobService,
} from './jobs.js';
import { isTerminalJob, type JobRecord, type JobStatus } from './jobs-store.js';
import { previewProject, type PreviewOptions, type TimelinePreviewRequest } from './preview.js';
import { renderProject, type RenderOptions } from './render.js';
import { autotuneVocal } from './vocal-autotune.js';
import {
  AssetAnalysisRequestSchema,
  AssetAnalysisResultSchema,
  AssetOperationSchema,
  AssetPreviewRequestSchema,
  AssetPreviewResultSchema,
  AssetSchema,
  EditOperationSchema,
  DiagnoseResultSchema,
  DoctorResultSchema,
  JobLogEntrySchema,
  LogQuerySchema,
  JobSchema,
  ProjectSchema,
  RenderPlanSchema,
  RenderRequestSchema,
  RevisionSchema,
  TimelinePreviewRequestSchema,
  TimelinePreviewResultSchema,
  VocalAutotuneReportSchema,
  VocalAutotuneRequestSchema,
  type AssetAnalysisRequest,
  type AssetKind,
  type AssetPreviewRequest,
  type EditOperation,
} from './schema.js';

const VERSION = '0.1.0';
const USAGE = `CodeCut ${VERSION}

Usage:
  codecut project init [directory] [--name name] [--force] [--json]
  codecut project show [directory|project.json] [--json]
  codecut project validate [directory|project.json] [--json]
  codecut asset add PATH --id ID [--kind video|audio|image] [--project PATH] [--dry-run] [--json]
  codecut asset list [--project PATH] [--json]
  codecut asset status [ASSET_ID] [--project PATH] [--json]
  codecut asset probe ASSET_ID [--project PATH] [--dry-run] [--json]
  codecut asset remove ASSET_ID [--project PATH] [--dry-run] [--json]
  codecut asset thumbnail ASSET_ID [--at SECONDS] [--width N] [--height N] [--output PATH] [--force] [--detach] [--json]
  codecut asset sheet ASSET_ID [--start SECONDS] [--end SECONDS] [--interval SECONDS] [--columns N] [--rows N] [--width N] [--height N] [--output PATH] [--force] [--detach] [--json]
  codecut asset analyze scenes|silence ASSET_ID [--start SECONDS] [--end SECONDS] [--threshold RATIO|--noise-db DB --minimum-duration SECONDS] [--detach] [--json]
  codecut vocal autotune REQUEST_JSON [--output PATH] [--report PATH] [--python PATH] [--force] [--json]
  codecut edit apply OPERATIONS_JSON|- [--project PATH] [--dry-run] [--summary TEXT] [--json]
  codecut edit apply --operations PATH [--project PATH] [--dry-run] [--summary TEXT] [--json]
  codecut edit apply --operations-json JSON [--project PATH] [--dry-run] [--summary TEXT] [--json]
  codecut history list [--project PATH] [--json]
  codecut history diff FROM_ID TO_ID [--project PATH] [--json]
  codecut history undo [--project PATH] [--dry-run] [--json]
  codecut history redo [--project PATH] [--dry-run] [--json]
  codecut render [--project PATH] [--revision N|ID] [--output PATH] [--force] [--detach] [--timeout-ms N] [--dry-run] [--json]
  codecut preview frame [--at SECONDS] [--width N] [--height N] [--project PATH] [--revision N|ID] [--output PATH] [--force] [--detach] [--timeout-ms N] [--dry-run] [--json]
  codecut preview sheet [--start SECONDS] [--end SECONDS] [--interval SECONDS] [--columns N] [--rows N] [--width N] [--height N] [--project PATH] [--revision N|ID] [--output PATH] [--force] [--detach] [--timeout-ms N] [--dry-run] [--json]
  codecut preview proxy [--width N] [--height N] [--crf N|--video-bitrate KBPS] [--audio-bitrate KBPS] [--project PATH] [--revision N|ID] [--output PATH] [--force] [--detach] [--timeout-ms N] [--dry-run] [--json]
  codecut jobs list [--project PATH] [--status STATUS] [--limit N] [--json]
  codecut jobs show JOB_ID [--project PATH] [--json]
  codecut jobs wait JOB_ID [--project PATH] [--json]
  codecut jobs cancel JOB_ID [--project PATH] [--json]
  codecut jobs retry JOB_ID [--project PATH] [--detach] [--json]
  codecut doctor [--project PATH] [--json]
  codecut logs [JOB_ID] [--job JOB_ID] [--stage STAGE] [--level debug|info|warn|error] [--stream stdout|stderr|progress] [--tail N] [--follow] [--project PATH] [--json]
  codecut diagnose JOB_ID [--project PATH] [--output DIRECTORY] [--json]
  codecut ui [--project PATH] [--job JOB_ID]
  codecut schema [--json]
  codecut capabilities [--json]

Options:
  --project PATH   Project directory (or project.json for project commands)
  --operations PATH
                   Read an edit operation array from a JSON file; '-' explicitly selects stdin
  --operations-json JSON
                   Read an edit operation array directly from this argument
  --dry-run       Return an edit diff, render plan, or timeline preview plan without starting a job
  --summary TEXT  Override the edit revision summary
  --detach        Run an asset preview/analysis, timeline preview, render, or retried job in a detached worker
  --json          Emit machine-readable JSON; logs --follow emits one JSON object per line
  --verbose       Write command/stage details to stderr without changing JSON stdout
  --debug         Include internal details and error stacks on stderr (implies --verbose)
  --force         Replace an existing project.json, preview, rendered output, or autotune output/report
  --python PATH   Python 3 executable for vocal autotune (or CODECUT_AUTOTUNE_PYTHON)
  --help          Show this help
  --version       Show the CLI version
`;

interface CommandResult {
  command: string;
  data: Record<string, unknown>;
  text?: string;
  alwaysJson?: boolean;
  exitCode?: ExitCode;
  emit?: (json: boolean) => Promise<void>;
}

interface ProjectOptions {
  path: string;
  force: boolean;
  name?: string;
}

function usageError(message: string, stage = 'cli'): CodeCutError {
  return new CodeCutError('USAGE_ERROR', message, ExitCode.Usage, { stage, retryable: false });
}

function optionValue(args: string[], index: number, option: string): string {
  const value = args[index + 1];
  if (value === undefined || value === '' || value.startsWith('--')) {
    throw usageError(`${option} requires a value`);
  }
  return value;
}

function parseProjectOptions(args: string[], action: string): ProjectOptions {
  let positionalPath: string | undefined;
  let optionPath: string | undefined;
  let name: string | undefined;
  let force = false;
  let positionalOnly = false;

  for (let index = 0; index < args.length; index += 1) {
    const argument = args[index];
    if (argument === undefined) continue;
    if (positionalOnly) {
      if (positionalPath !== undefined) throw usageError('Only one project path is allowed', `project.${action}`);
      positionalPath = argument;
    } else if (argument === '--') {
      positionalOnly = true;
    } else if (argument === '--project' || argument === '-p') {
      optionPath = optionValue(args, index, argument);
      index += 1;
    } else if (argument.startsWith('--project=')) {
      optionPath = argument.slice('--project='.length);
      if (!optionPath) throw usageError('--project requires a value', `project.${action}`);
    } else if (argument === '--force') {
      if (action !== 'init') throw usageError('--force is only valid for project init', `project.${action}`);
      force = true;
    } else if (argument === '--name') {
      if (action !== 'init') throw usageError('--name is only valid for project init', `project.${action}`);
      name = optionValue(args, index, argument);
      index += 1;
    } else if (argument.startsWith('--name=')) {
      if (action !== 'init') throw usageError('--name is only valid for project init', `project.${action}`);
      name = argument.slice('--name='.length);
      if (!name) throw usageError('--name requires a value', 'project.init');
    } else if (argument.startsWith('-')) {
      throw usageError(`Unknown option: ${argument}`, `project.${action}`);
    } else {
      if (positionalPath !== undefined) throw usageError('Only one project path is allowed', `project.${action}`);
      positionalPath = argument;
    }
  }
  if (positionalPath !== undefined && optionPath !== undefined) {
    throw usageError('Use either a positional project path or --project, not both', `project.${action}`);
  }
  return {
    path: positionalPath ?? optionPath ?? '.',
    force,
    ...(name === undefined ? {} : { name }),
  };
}

async function executeProject(args: string[]): Promise<CommandResult> {
  const action = args[0];
  if (!action) throw usageError('Missing project action: init, show, or validate', 'project');
  if (!['init', 'show', 'validate'].includes(action)) {
    throw usageError(`Unknown project action: ${action}`, 'project');
  }
  const options = parseProjectOptions(args.slice(1), action);

  if (action === 'init') {
    const { project, path } = await initProject(options.path, {
      force: options.force,
      ...(options.name === undefined ? {} : { name: options.name }),
    });
    return {
      command: 'project.init',
      data: { path, project, timeline: calculateTimeline(project) },
      text: `Initialized project: ${path}\n`,
    };
  }

  const stage = `project.${action}`;
  const { project, path } = await loadProject(options.path, stage);
  if (action === 'show') {
    const timeline = calculateTimeline(project);
    return {
      command: stage,
      data: { path, project, timeline },
      text: `Project: ${project.name}\nPath: ${path}\nTimeline duration: ${timeline.duration}s\n`,
    };
  }
  return {
    command: stage,
    data: { path, valid: true },
    text: `Valid project: ${path}\n`,
  };
}

type AssetAction = 'add' | 'list' | 'status' | 'probe' | 'remove' | 'thumbnail' | 'sheet' | 'analyze';

interface ParsedAssetOptions {
  project: string;
  positionals: string[];
  values: Map<string, string>;
  dryRun: boolean;
  force: boolean;
  detach: boolean;
}

const ASSET_VALUE_OPTIONS: Record<AssetAction, Set<string>> = {
  add: new Set(['--id', '--kind']),
  list: new Set(),
  status: new Set(),
  probe: new Set(),
  remove: new Set(),
  thumbnail: new Set(['--at', '--width', '--height', '--output', '--timeout-ms']),
  sheet: new Set(['--start', '--end', '--interval', '--columns', '--rows', '--width', '--height', '--output', '--timeout-ms']),
  analyze: new Set(['--type', '--start', '--end', '--threshold', '--noise-db', '--minimum-duration', '--min-duration', '--timeout-ms']),
};

function parseAssetOptions(args: string[], action: AssetAction): ParsedAssetOptions {
  let project = '.';
  let dryRun = false;
  let force = false;
  let detach = false;
  let positionalOnly = false;
  const positionals: string[] = [];
  const values = new Map<string, string>();
  for (let index = 0; index < args.length; index += 1) {
    const argument = args[index];
    if (argument === undefined) continue;
    if (positionalOnly) {
      positionals.push(argument);
    } else if (argument === '--') positionalOnly = true;
    else if (argument === '--project' || argument === '-p') {
      project = optionValue(args, index, argument);
      index += 1;
    } else if (argument.startsWith('--project=')) {
      project = argument.slice('--project='.length);
      if (!project) throw usageError('--project requires a value', `asset.${action}`);
    } else if (argument === '--dry-run') {
      if (!['add', 'probe', 'remove'].includes(action)) throw usageError('--dry-run is only valid for asset add, probe, and remove', `asset.${action}`);
      dryRun = true;
    } else if (argument === '--force') {
      if (action !== 'thumbnail' && action !== 'sheet') throw usageError('--force is only valid for asset thumbnail and sheet', `asset.${action}`);
      force = true;
    } else if (argument === '--detach') {
      if (!['thumbnail', 'sheet', 'analyze'].includes(action)) throw usageError('--detach is only valid for asset preview and analysis jobs', `asset.${action}`);
      detach = true;
    } else if (argument.startsWith('--')) {
      const separator = argument.indexOf('=');
      const option = separator < 0 ? argument : argument.slice(0, separator);
      if (!ASSET_VALUE_OPTIONS[action].has(option)) throw usageError(`Unknown option for asset ${action}: ${option}`, `asset.${action}`);
      const value = separator < 0 ? optionValue(args, index, option) : argument.slice(separator + 1);
      if (separator < 0) index += 1;
      if (!value) throw usageError(`${option} requires a value`, `asset.${action}`);
      if (values.has(option)) throw usageError(`${option} may only be provided once`, `asset.${action}`);
      values.set(option, value);
    } else if (argument.startsWith('-')) throw usageError(`Unknown option: ${argument}`, `asset.${action}`);
    else positionals.push(argument);
  }
  return { project, positionals, values, dryRun, force, detach };
}

function assetNumber(options: ParsedAssetOptions, option: string, action: AssetAction, integer = false): number | undefined {
  const source = options.values.get(option);
  if (source === undefined) return undefined;
  const value = Number(source);
  if (!Number.isFinite(value) || integer && !Number.isInteger(value)) {
    throw usageError(`${option} requires ${integer ? 'an integer' : 'a finite number'}`, `asset.${action}`);
  }
  return value;
}

function optionalTimeout(options: ParsedAssetOptions): { timeoutMs?: number } {
  const value = assetNumber(options, '--timeout-ms', 'analyze', true);
  if (value !== undefined && value < 1) throw usageError('--timeout-ms requires a positive integer', 'asset.job');
  return value === undefined ? {} : { timeoutMs: value };
}

function previewRequest(options: ParsedAssetOptions, type: 'thumbnail' | 'sheet'): AssetPreviewRequest {
  const assetId = options.positionals[0]!;
  const common = {
    assetId,
    ...(options.values.has('--output') ? { output: options.values.get('--output')! } : {}),
    ...(options.force ? { force: true } : {}),
  };
  if (type === 'thumbnail') {
    return {
      type,
      ...common,
      ...(assetNumber(options, '--at', type) === undefined ? {} : { at: assetNumber(options, '--at', type)! }),
      ...(assetNumber(options, '--width', type, true) === undefined ? {} : { width: assetNumber(options, '--width', type, true)! }),
      ...(assetNumber(options, '--height', type, true) === undefined ? {} : { height: assetNumber(options, '--height', type, true)! }),
    };
  }
  return {
    type,
    ...common,
    ...(assetNumber(options, '--start', type) === undefined ? {} : { start: assetNumber(options, '--start', type)! }),
    ...(assetNumber(options, '--end', type) === undefined ? {} : { end: assetNumber(options, '--end', type)! }),
    ...(assetNumber(options, '--interval', type) === undefined ? {} : { interval: assetNumber(options, '--interval', type)! }),
    ...(assetNumber(options, '--columns', type, true) === undefined ? {} : { columns: assetNumber(options, '--columns', type, true)! }),
    ...(assetNumber(options, '--rows', type, true) === undefined ? {} : { rows: assetNumber(options, '--rows', type, true)! }),
    ...(assetNumber(options, '--width', type, true) === undefined ? {} : { width: assetNumber(options, '--width', type, true)! }),
    ...(assetNumber(options, '--height', type, true) === undefined ? {} : { height: assetNumber(options, '--height', type, true)! }),
  };
}

function analysisRequest(options: ParsedAssetOptions): AssetAnalysisRequest {
  let type = options.values.get('--type');
  let assetId: string;
  if (options.positionals.length === 2 && !type) {
    type = options.positionals[0];
    assetId = options.positionals[1]!;
  } else if (options.positionals.length === 1 && type) assetId = options.positionals[0]!;
  else throw usageError('asset analyze requires scenes|silence and ASSET_ID (or ASSET_ID --type TYPE)', 'asset.analyze');
  if (type !== 'scenes' && type !== 'silence') throw usageError('Asset analysis type must be scenes or silence', 'asset.analyze');
  const start = assetNumber(options, '--start', 'analyze');
  const end = assetNumber(options, '--end', 'analyze');
  if (type === 'scenes') {
    if (options.values.has('--noise-db') || options.values.has('--minimum-duration') || options.values.has('--min-duration')) {
      throw usageError('Silence options are not valid for scene analysis', 'asset.analyze');
    }
    const threshold = assetNumber(options, '--threshold', 'analyze');
    return {
      type, assetId,
      ...(start === undefined ? {} : { start }),
      ...(end === undefined ? {} : { end }),
      ...(threshold === undefined ? {} : { threshold }),
    };
  }
  if (options.values.has('--threshold')) throw usageError('--threshold is only valid for scene analysis', 'asset.analyze');
  const noiseDb = assetNumber(options, '--noise-db', 'analyze');
  const minimumDuration = assetNumber(options, options.values.has('--min-duration') ? '--min-duration' : '--minimum-duration', 'analyze');
  return {
    type, assetId,
    ...(start === undefined ? {} : { start }),
    ...(end === undefined ? {} : { end }),
    ...(noiseDb === undefined ? {} : { noiseDb }),
    ...(minimumDuration === undefined ? {} : { minimumDuration }),
  };
}

function jobCommandResult(command: string, job: JobRecord): CommandResult {
  return {
    command,
    data: {
      job,
      ...(job.result?.data === undefined ? {} : { result: job.result.data }),
      ...(job.outputPath ?? job.result?.outputPath
        ? { outputPath: job.outputPath ?? job.result?.outputPath }
        : {}),
    },
    text: jobText(job),
    exitCode: isTerminalJob(job) ? exitCodeForJob(job) : ExitCode.Success,
  };
}

async function executeAsset(args: string[]): Promise<CommandResult> {
  const action = args[0] as AssetAction | undefined;
  if (!action || !['add', 'list', 'status', 'probe', 'remove', 'thumbnail', 'sheet', 'analyze'].includes(action)) {
    throw usageError('Missing or unknown asset action: add, list, status, probe, remove, thumbnail, sheet, or analyze', 'asset');
  }
  const options = parseAssetOptions(args.slice(1), action);
  const positionalCount = options.positionals.length;
  if (action === 'add') {
    if (positionalCount !== 1) throw usageError('asset add requires one source PATH', 'asset.add');
    const id = options.values.get('--id');
    if (!id) throw usageError('asset add requires --id ID', 'asset.add');
    const kind = options.values.get('--kind');
    if (kind && !['video', 'audio', 'image'].includes(kind)) throw usageError('--kind must be video, audio, or image', 'asset.add');
    const result = await addAsset(options.project, {
      id,
      path: options.positionals[0]!,
      ...(kind ? { kind: kind as AssetKind } : {}),
      dryRun: options.dryRun,
    });
    return {
      command: 'asset.add',
      data: { ...result },
      text: `${options.dryRun ? 'Asset add dry-run' : 'Registered asset'}: ${id}\n`,
    };
  }
  if (action === 'list') {
    if (positionalCount > 0) throw usageError('asset list received too many positional arguments', 'asset.list');
    const result = await listAssets(options.project);
    return {
      command: 'asset.list',
      data: { ...result },
      text: result.assets.length === 0
        ? 'No assets.\n'
        : `${result.assets.map((asset) => `${asset.id}  ${asset.kind}  ${asset.path}`).join('\n')}\n`,
    };
  }
  if (action === 'status') {
    if (positionalCount > 1) throw usageError('asset status received too many positional arguments', 'asset.status');
    const result = await getAssetStatus(options.project, options.positionals[0]);
    return {
      command: 'asset.status',
      data: { ...result },
      text: result.assets.length === 0
        ? 'No assets.\n'
        : `${result.assets.map((asset) => `${asset.id}  ${asset.state}  ${asset.path}`).join('\n')}\n`,
    };
  }
  if (action === 'probe' || action === 'remove') {
    if (positionalCount !== 1) throw usageError(`asset ${action} requires one ASSET_ID`, `asset.${action}`);
    const id = options.positionals[0]!;
    const result = action === 'probe'
      ? await probeAsset(options.project, id, { dryRun: options.dryRun })
      : await removeAsset(options.project, id, { dryRun: options.dryRun });
    return {
      command: `asset.${action}`,
      data: { ...result },
      text: `${options.dryRun ? `Asset ${action} dry-run` : action === 'probe' ? 'Probed asset' : 'Removed asset'}: ${id}\n`,
    };
  }

  if (action === 'analyze') {
    const request = analysisRequest(options);
    const job = await analyzeAsset(options.project, request, {
      detach: options.detach,
      ...optionalTimeout(options),
    });
    return jobCommandResult(`asset.analyze.${request.type}`, job);
  }
  if (positionalCount !== 1) throw usageError(`asset ${action} requires one ASSET_ID`, `asset.${action}`);
  const job = await generateAssetPreview(options.project, previewRequest(options, action), {
    detach: options.detach,
    ...optionalTimeout(options),
  });
  return jobCommandResult(`asset.${action}`, job);
}

const JOB_STATUSES: JobStatus[] = [
  'queued', 'running', 'stopping', 'succeeded', 'failed', 'cancelled', 'timedOut', 'interrupted',
];

interface JobsOptions {
  project: string;
  id?: string;
  detach: boolean;
  status?: JobStatus;
  limit?: number;
  concurrency?: number;
  heartbeatMs?: number;
  staleMs?: number;
  graceMs?: number;
  tailBytes?: number;
  pollMs?: number;
}

function positiveInteger(value: string, option: string, action: string): number {
  if (!/^\d+$/.test(value) || Number(value) < 1) throw usageError(`${option} requires a positive integer`, `jobs.${action}`);
  return Number(value);
}

function parseJobsOptions(args: string[], action: string): JobsOptions {
  let project = '.';
  let id: string | undefined;
  let detach = false;
  let status: JobStatus | undefined;
  let limit: number | undefined;
  let concurrency: number | undefined;
  let heartbeatMs: number | undefined;
  let staleMs: number | undefined;
  let graceMs: number | undefined;
  let tailBytes: number | undefined;
  let pollMs: number | undefined;

  for (let index = 0; index < args.length; index += 1) {
    const argument = args[index];
    if (argument === undefined) continue;
    if (argument === '--project' || argument === '-p') {
      project = optionValue(args, index, argument);
      index += 1;
    } else if (argument.startsWith('--project=')) {
      project = argument.slice('--project='.length);
      if (!project) throw usageError('--project requires a value', `jobs.${action}`);
    } else if (argument === '--detach') {
      if (action !== 'retry') throw usageError('--detach is only valid for jobs retry', `jobs.${action}`);
      detach = true;
    } else if (argument === '--status') {
      if (action !== 'list') throw usageError('--status is only valid for jobs list', `jobs.${action}`);
      const value = optionValue(args, index, argument);
      if (!JOB_STATUSES.includes(value as JobStatus)) throw usageError(`Unknown job status: ${value}`, 'jobs.list');
      status = value as JobStatus;
      index += 1;
    } else if (argument === '--limit' || argument === '--concurrency' || argument === '--heartbeat-ms'
      || argument === '--stale-ms' || argument === '--grace-ms' || argument === '--tail-bytes' || argument === '--poll-ms') {
      const value = positiveInteger(optionValue(args, index, argument), argument, action);
      index += 1;
      if (argument === '--limit') {
        if (action !== 'list') throw usageError('--limit is only valid for jobs list', 'jobs.list');
        limit = value;
      } else if (argument === '--concurrency') concurrency = value;
      else if (argument === '--heartbeat-ms') heartbeatMs = value;
      else if (argument === '--stale-ms') staleMs = value;
      else if (argument === '--grace-ms') graceMs = value;
      else if (argument === '--tail-bytes') tailBytes = value;
      else pollMs = value;
    } else if (argument.startsWith('-')) {
      throw usageError(`Unknown option: ${argument}`, `jobs.${action}`);
    } else if (id !== undefined || action === 'list') {
      throw usageError(action === 'list' ? 'jobs list does not accept a job ID' : 'Only one job ID is allowed', `jobs.${action}`);
    } else id = argument;
  }
  if (action !== 'list' && id === undefined) throw usageError(`jobs ${action} requires a job ID`, `jobs.${action}`);
  if (action !== 'worker' && [concurrency, heartbeatMs, staleMs, graceMs, tailBytes].some((value) => value !== undefined)) {
    throw usageError('Worker tuning options are internal to jobs worker', `jobs.${action}`);
  }
  return {
    project, ...(id === undefined ? {} : { id }), detach,
    ...(status === undefined ? {} : { status }),
    ...(limit === undefined ? {} : { limit }),
    ...(concurrency === undefined ? {} : { concurrency }),
    ...(heartbeatMs === undefined ? {} : { heartbeatMs }),
    ...(staleMs === undefined ? {} : { staleMs }),
    ...(graceMs === undefined ? {} : { graceMs }),
    ...(tailBytes === undefined ? {} : { tailBytes }),
    ...(pollMs === undefined ? {} : { pollMs }),
  };
}

function jobText(job: JobRecord): string {
  const lines = [
    `Job: ${job.id}`,
    `Kind: ${job.kind}`,
    `Status: ${job.status}`,
    `Health: ${job.health ?? 'ok'}`,
    `Stage: ${job.stage}`,
    `Progress: ${job.progress?.percent ?? 0}%`,
    `Project revision: ${job.projectRevision}`,
    `Created: ${job.createdAt}`,
  ];
  if (job.retryOf) lines.push(`Retry of: ${job.retryOf}`);
  if (job.workerPid !== undefined) lines.push(`Worker PID: ${job.workerPid}`);
  if (job.pid !== undefined) lines.push(`Process PID: ${job.pid}`);
  if (job.startedAt) lines.push(`Started: ${job.startedAt}`);
  if (job.finishedAt) lines.push(`Finished: ${job.finishedAt}`);
  if (job.error) lines.push(`Error: ${job.error.code}: ${job.error.message}`);
  lines.push(`stdout log: ${job.logs.stdout}`, `stderr log: ${job.logs.stderr}`);
  if (job.logs.progress) lines.push(`progress log: ${job.logs.progress}`);
  lines.push(`diagnostics: ${job.diagnostics.directory}`);
  const previewPath = job.result?.outputPath ?? job.outputPath;
  if (previewPath) lines.push(`preview/output: ${previewPath}`);
  return `${lines.join('\n')}\n`;
}

async function executeJobs(args: string[]): Promise<CommandResult> {
  const action = args[0];
  if (!action || !['list', 'show', 'wait', 'cancel', 'retry', 'worker'].includes(action)) {
    throw usageError('Missing or unknown jobs action: list, show, wait, cancel, or retry', 'jobs');
  }
  const options = parseJobsOptions(args.slice(1), action);
  const service = new JobService({
    projectDirectory: options.project,
    ...(options.concurrency === undefined ? {} : { maxConcurrency: options.concurrency }),
    ...(options.heartbeatMs === undefined ? {} : { heartbeatMs: options.heartbeatMs }),
    ...(options.staleMs === undefined ? {} : { staleAfterMs: options.staleMs }),
    ...(options.graceMs === undefined ? {} : { gracePeriodMs: options.graceMs }),
    ...(options.tailBytes === undefined ? {} : { tailBytes: options.tailBytes }),
    ...(options.pollMs === undefined ? {} : { pollMs: options.pollMs }),
  });
  if (action === 'list') {
    const jobs = await service.list(options.status);
    const limited = options.limit === undefined ? jobs : jobs.slice(0, options.limit);
    return {
      command: 'jobs.list',
      data: { jobs: limited },
      text: limited.length === 0 ? 'No jobs.\n' : `${limited.map((job) => `${job.id}  ${job.status}  ${job.stage}  ${job.progress?.percent ?? 0}%`).join('\n')}\n`,
    };
  }
  const id = options.id!;
  if (action === 'show') {
    const job = await service.show(id);
    return { command: 'jobs.show', data: { job }, text: jobText(job) };
  }
  if (action === 'wait') {
    const job = await service.wait(id);
    return {
      command: 'jobs.wait',
      data: { job },
      text: jobText(job),
      exitCode: exitCodeForJob(job),
    };
  }
  if (action === 'cancel') {
    const job = await service.cancel(id);
    return { command: 'jobs.cancel', data: { job }, text: jobText(job) };
  }
  if (action === 'retry') {
    const job = await service.retry(id, { detach: options.detach });
    return {
      command: 'jobs.retry',
      data: { job, retryOf: id },
      text: jobText(job),
      exitCode: isTerminalJob(job) ? exitCodeForJob(job) : ExitCode.Success,
    };
  }
  const job = await service.runJob(id);
  return { command: 'jobs.worker', data: { job }, text: '' };
}

type OperationInput =
  | { kind: 'file'; value: string }
  | { kind: 'stdin'; value: '-' }
  | { kind: 'inline'; value: string };

interface EditApplyOptions {
  project: string;
  input: OperationInput;
  dryRun: boolean;
  summary?: string;
}

function parseEditApplyOptions(args: string[]): EditApplyOptions {
  let project = '.';
  let input: OperationInput | undefined;
  let dryRun = false;
  let summary: string | undefined;
  let positionalOnly = false;

  const selectInput = (next: OperationInput): void => {
    if (input) {
      throw usageError('Provide exactly one operation source: a file, explicit "-" stdin, or --operations-json', 'edit.apply');
    }
    input = next;
  };
  const selectFile = (value: string): void => {
    selectInput(value === '-' ? { kind: 'stdin', value: '-' } : { kind: 'file', value });
  };

  for (let index = 0; index < args.length; index += 1) {
    const argument = args[index];
    if (argument === undefined) continue;
    if (positionalOnly) {
      selectFile(argument);
    } else if (argument === '--') {
      positionalOnly = true;
    } else if (argument === '--project' || argument === '-p') {
      project = optionValue(args, index, argument);
      index += 1;
    } else if (argument.startsWith('--project=')) {
      project = argument.slice('--project='.length);
      if (!project) throw usageError('--project requires a value', 'edit.apply');
    } else if (argument === '--operations') {
      selectFile(optionValue(args, index, argument));
      index += 1;
    } else if (argument.startsWith('--operations=')) {
      const value = argument.slice('--operations='.length);
      if (!value) throw usageError('--operations requires a value', 'edit.apply');
      selectFile(value);
    } else if (argument === '--operations-json') {
      selectInput({ kind: 'inline', value: optionValue(args, index, argument) });
      index += 1;
    } else if (argument.startsWith('--operations-json=')) {
      const value = argument.slice('--operations-json='.length);
      if (!value) throw usageError('--operations-json requires a value', 'edit.apply');
      selectInput({ kind: 'inline', value });
    } else if (argument === '--dry-run') {
      dryRun = true;
    } else if (argument === '--summary') {
      summary = optionValue(args, index, argument);
      index += 1;
    } else if (argument.startsWith('--summary=')) {
      summary = argument.slice('--summary='.length);
      if (!summary) throw usageError('--summary requires a value', 'edit.apply');
    } else if (argument === '-') {
      selectInput({ kind: 'stdin', value: '-' });
    } else if (argument.startsWith('-')) {
      throw usageError(`Unknown option: ${argument}`, 'edit.apply');
    } else {
      selectFile(argument);
    }
  }
  if (!input) {
    throw usageError(
      'edit apply requires an operation array from OPERATIONS_JSON, --operations PATH, --operations-json JSON, or explicit "-" stdin; stdin is never read implicitly',
      'edit.apply',
    );
  }
  return { project, input, dryRun, ...(summary === undefined ? {} : { summary }) };
}

function operationsInputError(code: string, message: string, path?: string, cause?: unknown): CodeCutError {
  return new CodeCutError(code, message, ExitCode.Usage, {
    stage: 'edit.apply',
    ...(path === undefined ? {} : { path }),
    ...(cause === undefined ? {} : { cause }),
    retryable: false,
  });
}

async function readStandardInput(): Promise<string> {
  if (process.stdin.isTTY) {
    throw usageError('Refusing to read operations interactively from a TTY; redirect stdin or provide a JSON file', 'edit.apply');
  }
  process.stdin.setEncoding('utf8');
  let source = '';
  for await (const chunk of process.stdin) source += String(chunk);
  return source;
}

async function readOperations(input: OperationInput): Promise<EditOperation[]> {
  let source: string;
  let path: string | undefined;
  if (input.kind === 'inline') {
    source = input.value;
  } else {
    path = input.kind === 'file' ? resolve(input.value) : undefined;
    try {
      source = input.kind === 'stdin' ? await readStandardInput() : await readFile(path!, 'utf8');
    } catch (cause) {
      if (cause instanceof CodeCutError) throw cause;
      throw operationsInputError(
        'OPERATIONS_READ_FAILED',
        input.kind === 'stdin' ? 'Could not read the edit operation array from stdin' : 'Could not read the edit operation JSON file',
        path,
        cause,
      );
    }
  }

  let value: unknown;
  try {
    value = JSON.parse(source);
  } catch (cause) {
    throw operationsInputError('OPERATIONS_PARSE_ERROR', 'Edit operation input must be a JSON array', path, cause);
  }
  if (!Array.isArray(value)) {
    throw operationsInputError('OPERATIONS_INVALID', 'Edit operation input must contain a top-level JSON array', path);
  }
  return value as EditOperation[];
}

async function executeEdit(args: string[]): Promise<CommandResult> {
  const action = args[0];
  if (action !== 'apply') throw usageError('Missing or unknown edit action: apply', 'edit');
  const options = parseEditApplyOptions(args.slice(1));
  const operations = await readOperations(options.input);
  const result = await applyEdit(options.project, operations, {
    dryRun: options.dryRun,
    ...(options.summary === undefined ? {} : { summary: options.summary }),
  });
  return {
    command: 'edit.apply',
    data: { ...result },
    text: result.dryRun
      ? `Edit dry-run: ${result.diff.length} change(s); no files written\n`
      : `Applied edit: ${result.revision?.id ?? 'unknown revision'}\n`,
  };
}

type HistoryAction = 'list' | 'diff' | 'undo' | 'redo';

interface HistoryOptions {
  project: string;
  dryRun: boolean;
  ids: string[];
}

function parseHistoryOptions(args: string[], action: HistoryAction): HistoryOptions {
  let project = '.';
  let dryRun = false;
  const ids: string[] = [];
  for (let index = 0; index < args.length; index += 1) {
    const argument = args[index];
    if (argument === undefined) continue;
    if (argument === '--project' || argument === '-p') {
      project = optionValue(args, index, argument);
      index += 1;
    } else if (argument.startsWith('--project=')) {
      project = argument.slice('--project='.length);
      if (!project) throw usageError('--project requires a value', `history.${action}`);
    } else if (argument === '--dry-run') {
      if (action !== 'undo' && action !== 'redo') {
        throw usageError(`--dry-run is only valid for history undo and redo`, `history.${action}`);
      }
      dryRun = true;
    } else if (argument.startsWith('-')) {
      throw usageError(`Unknown option: ${argument}`, `history.${action}`);
    } else {
      ids.push(argument);
    }
  }

  const expected = action === 'diff' ? 2 : 0;
  if (ids.length !== expected) {
    throw usageError(
      action === 'diff' ? 'history diff requires FROM_ID and TO_ID' : `history ${action} does not accept positional arguments`,
      `history.${action}`,
    );
  }
  return { project, dryRun, ids };
}

function historyTransactionText(action: 'undo' | 'redo', result: ProjectTransactionResult): string {
  if (result.dryRun) return `History ${action} dry-run: ${result.diff.length} change(s); no files written\n`;
  return `History ${action} committed: ${result.revision?.id ?? 'unknown revision'}\n`;
}

async function executeHistory(args: string[]): Promise<CommandResult> {
  const action = args[0];
  if (action !== 'list' && action !== 'diff' && action !== 'undo' && action !== 'redo') {
    throw usageError('Missing or unknown history action: list, diff, undo, or redo', 'history');
  }
  const options = parseHistoryOptions(args.slice(1), action);
  if (action === 'list') {
    const history = await listHistory(options.project);
    return {
      command: 'history.list',
      data: { ...history },
      text: history.revisions.length === 0
        ? 'No revisions.\n'
        : `${history.revisions.map((revision) => `${revision.id === history.currentId ? '*' : ' '} ${revision.id}  r${revision.projectRevision}  ${revision.summary}`).join('\n')}\n`,
    };
  }
  if (action === 'diff') {
    const result = await diffRevisions(options.project, options.ids[0]!, options.ids[1]!);
    return {
      command: 'history.diff',
      data: { ...result },
      text: `Revision diff: ${result.diff.length} change(s)\n`,
    };
  }
  const result = action === 'undo'
    ? await undoProject(options.project, { dryRun: options.dryRun })
    : await redoProject(options.project, { dryRun: options.dryRun });
  return {
    command: `history.${action}`,
    data: { ...result },
    text: historyTransactionText(action, result),
  };
}

function parseRenderOptions(args: string[]): RenderOptions & { project: string } {
  let project = '.';
  const options: RenderOptions = {};
  for (let index = 0; index < args.length; index += 1) {
    const argument = args[index];
    if (argument === undefined) continue;
    if (argument === '--project' || argument === '-p') {
      project = optionValue(args, index, argument);
      index += 1;
    } else if (argument.startsWith('--project=')) {
      project = argument.slice('--project='.length);
      if (!project) throw usageError('--project requires a value', 'render');
    } else if (argument === '--revision' || argument === '--output' || argument === '--timeout-ms') {
      const value = optionValue(args, index, argument);
      index += 1;
      if (argument === '--revision') options.revision = /^\d+$/.test(value) ? Number(value) : value;
      else if (argument === '--output') options.output = value;
      else options.timeoutMs = positiveInteger(value, argument, 'render');
    } else if (argument.startsWith('--revision=') || argument.startsWith('--output=') || argument.startsWith('--timeout-ms=')) {
      const separator = argument.indexOf('=');
      const option = argument.slice(0, separator);
      const value = argument.slice(separator + 1);
      if (!value) throw usageError(`${option} requires a value`, 'render');
      if (option === '--revision') options.revision = /^\d+$/.test(value) ? Number(value) : value;
      else if (option === '--output') options.output = value;
      else options.timeoutMs = positiveInteger(value, option, 'render');
    } else if (argument === '--force') options.force = true;
    else if (argument === '--detach') options.detach = true;
    else if (argument === '--dry-run') options.dryRun = true;
    else throw usageError(`Unknown option for render: ${argument}`, 'render');
  }
  if (options.dryRun && options.detach) throw usageError('--detach cannot be combined with --dry-run', 'render');
  return { ...options, project };
}

async function executeRender(args: string[]): Promise<CommandResult> {
  const { project, ...options } = parseRenderOptions(args);
  const result = await renderProject(project, options);
  return {
    command: 'render',
    data: {
      dryRun: result.dryRun,
      ...(result.revisionId === undefined ? {} : { revisionId: result.revisionId }),
      plan: result.plan,
      ...(result.job === undefined ? {} : { job: result.job }),
      ...(result.job?.result?.outputPath === undefined ? {} : { outputPath: result.job.result.outputPath }),
    },
    text: result.dryRun
      ? `Render dry-run: revision ${result.plan.revision}, ${result.plan.inputs.length} input(s), ${result.plan.durationSeconds}s; no job created\n`
      : jobText(result.job!),
    ...(result.job === undefined ? {} : { exitCode: isTerminalJob(result.job) ? exitCodeForJob(result.job) : ExitCode.Success }),
  };
}

type TimelinePreviewType = TimelinePreviewRequest['type'];

function parsePreviewOptions(args: string[], type: TimelinePreviewType): {
  project: string;
  request: TimelinePreviewRequest;
  options: PreviewOptions;
} {
  const common = new Set(['--revision', '--output', '--timeout-ms']);
  const typeOptions: Record<TimelinePreviewType, Set<string>> = {
    frame: new Set(['--at', '--width', '--height']),
    sheet: new Set(['--start', '--end', '--interval', '--columns', '--rows', '--width', '--height']),
    proxy: new Set(['--width', '--height', '--crf', '--video-bitrate', '--bitrate', '--audio-bitrate']),
  };
  const allowed = new Set([...common, ...typeOptions[type]]);
  const values = new Map<string, string>();
  let project = '.';
  let force = false;
  let detach = false;
  let dryRun = false;
  for (let index = 0; index < args.length; index += 1) {
    const argument = args[index];
    if (argument === undefined) continue;
    if (argument === '--force') force = true;
    else if (argument === '--detach') detach = true;
    else if (argument === '--dry-run') dryRun = true;
    else if (argument === '-p') {
      project = optionValue(args, index, argument);
      index += 1;
    } else if (argument.startsWith('--')) {
      const separator = argument.indexOf('=');
      let option = separator < 0 ? argument : argument.slice(0, separator);
      if (option === '--bitrate') option = '--video-bitrate';
      let value: string;
      if (option === '--project') {
        value = separator < 0 ? optionValue(args, index, option) : argument.slice(separator + 1);
        if (separator < 0) index += 1;
        if (!value) throw usageError('--project requires a value', `preview.${type}`);
        project = value;
        continue;
      }
      if (!allowed.has(option)) throw usageError(`Unknown option for preview ${type}: ${option}`, `preview.${type}`);
      value = separator < 0 ? optionValue(args, index, option) : argument.slice(separator + 1);
      if (separator < 0) index += 1;
      if (!value) throw usageError(`${option} requires a value`, `preview.${type}`);
      if (values.has(option)) throw usageError(`${option} may only be provided once`, `preview.${type}`);
      values.set(option, value);
    } else throw usageError(`preview ${type} does not accept positional arguments: ${argument}`, `preview.${type}`);
  }
  if (dryRun && detach) throw usageError('--detach cannot be combined with --dry-run', `preview.${type}`);
  const numeric = (option: string, integer = false): number | undefined => {
    const source = values.get(option);
    if (source === undefined) return undefined;
    const value = Number(source);
    if (!Number.isFinite(value) || integer && !Number.isSafeInteger(value)) {
      throw usageError(`${option} requires ${integer ? 'an integer' : 'a finite number'}`, `preview.${type}`);
    }
    return value;
  };
  const timeoutMs = numeric('--timeout-ms', true);
  if (timeoutMs !== undefined && timeoutMs < 1) throw usageError('--timeout-ms requires a positive integer', `preview.${type}`);
  const revisionValue = values.get('--revision');
  const options: PreviewOptions = {
    ...(revisionValue === undefined ? {} : { revision: /^\d+$/.test(revisionValue) ? Number(revisionValue) : revisionValue }),
    ...(detach ? { detach: true } : {}),
    ...(dryRun ? { dryRun: true } : {}),
    ...(timeoutMs === undefined ? {} : { timeoutMs }),
  };
  const commonRequest = {
    ...(values.has('--output') ? { output: values.get('--output')! } : {}),
    ...(force ? { force: true } : {}),
  };
  let request: TimelinePreviewRequest;
  if (type === 'frame') {
    request = {
      type, ...commonRequest,
      ...(numeric('--at') === undefined ? {} : { at: numeric('--at')! }),
      ...(numeric('--width', true) === undefined ? {} : { width: numeric('--width', true)! }),
      ...(numeric('--height', true) === undefined ? {} : { height: numeric('--height', true)! }),
    };
  } else if (type === 'sheet') {
    request = {
      type, ...commonRequest,
      ...(numeric('--start') === undefined ? {} : { start: numeric('--start')! }),
      ...(numeric('--end') === undefined ? {} : { end: numeric('--end')! }),
      ...(numeric('--interval') === undefined ? {} : { interval: numeric('--interval')! }),
      ...(numeric('--columns', true) === undefined ? {} : { columns: numeric('--columns', true)! }),
      ...(numeric('--rows', true) === undefined ? {} : { rows: numeric('--rows', true)! }),
      ...(numeric('--width', true) === undefined ? {} : { width: numeric('--width', true)! }),
      ...(numeric('--height', true) === undefined ? {} : { height: numeric('--height', true)! }),
    };
  } else {
    request = {
      type, ...commonRequest,
      ...(numeric('--width', true) === undefined ? {} : { width: numeric('--width', true)! }),
      ...(numeric('--height', true) === undefined ? {} : { height: numeric('--height', true)! }),
      ...(numeric('--crf', true) === undefined ? {} : { crf: numeric('--crf', true)! }),
      ...(numeric('--video-bitrate', true) === undefined ? {} : { videoBitrateKbps: numeric('--video-bitrate', true)! }),
      ...(numeric('--audio-bitrate', true) === undefined ? {} : { audioBitrateKbps: numeric('--audio-bitrate', true)! }),
    };
  }
  return { project, request, options };
}

async function executePreview(args: string[]): Promise<CommandResult> {
  const type = args[0];
  if (type !== 'frame' && type !== 'sheet' && type !== 'proxy') {
    throw usageError('Missing or unknown preview action: frame, sheet, or proxy', 'preview');
  }
  const { project, request, options } = parsePreviewOptions(args.slice(1), type);
  const result = await previewProject(project, request, options);
  return {
    command: `preview.${type}`,
    data: {
      dryRun: result.dryRun,
      ...(result.revisionId === undefined ? {} : { revisionId: result.revisionId }),
      preview: result.preview,
      plan: result.plan,
      ...(result.job === undefined ? {} : { job: result.job }),
      ...(result.job?.result?.data === undefined ? {} : { result: result.job.result.data }),
      ...(result.job?.result?.outputPath === undefined ? {} : { outputPath: result.job.result.outputPath }),
    },
    text: result.dryRun
      ? `Preview ${type} dry-run: revision ${result.plan.revision}, ${result.plan.inputs.length} input(s); no job created\n`
      : jobText(result.job!),
    ...(result.job === undefined ? {} : { exitCode: isTerminalJob(result.job) ? exitCodeForJob(result.job) : ExitCode.Success }),
  };
}

function parseProjectOnly(args: string[], stage: string): string {
  let project = '.';
  for (let index = 0; index < args.length; index += 1) {
    const argument = args[index];
    if (argument === undefined) continue;
    if (argument === '--project' || argument === '-p') {
      project = optionValue(args, index, argument);
      index += 1;
    } else if (argument.startsWith('--project=')) {
      project = argument.slice('--project='.length);
      if (!project) throw usageError('--project requires a value', stage);
    } else throw usageError(`Unknown option for ${stage}: ${argument}`, stage);
  }
  return project;
}

async function executeDoctor(args: string[]): Promise<CommandResult> {
  const project = parseProjectOnly(args, 'doctor');
  const report = await runDoctor(project);
  return {
    command: 'doctor',
    data: { ...report },
    text: `${report.checks.map((entry) => `[${entry.status}] ${entry.name}: ${entry.message}${entry.path ? `\n  ${entry.path}` : ''}`).join('\n')}\n`,
    exitCode: report.ok ? ExitCode.Success : ExitCode.Media,
  };
}

interface LogsOptions {
  project: string;
  jobId: string;
  stage?: string;
  level?: JobLogLevel;
  stream?: JobLogStream;
  tail: number;
  follow: boolean;
}

function parseLogsOptions(args: string[]): LogsOptions {
  let project = '.';
  let jobId: string | undefined;
  let stage: string | undefined;
  let level: JobLogLevel | undefined;
  let stream: JobLogStream | undefined;
  let tail = 100;
  let follow = false;
  const setJob = (value: string) => {
    if (jobId !== undefined) throw usageError('Provide exactly one job ID, either positional or with --job', 'logs');
    jobId = value;
  };
  for (let index = 0; index < args.length; index += 1) {
    const argument = args[index];
    if (argument === undefined) continue;
    if (argument === '--project' || argument === '-p') {
      project = optionValue(args, index, argument);
      index += 1;
      continue;
    }
    if (argument === '--follow') {
      follow = true;
      continue;
    }
    if (!argument.startsWith('-')) {
      setJob(argument);
      continue;
    }
    const separator = argument.indexOf('=');
    const option = separator < 0 ? argument : argument.slice(0, separator);
    const value = separator < 0 ? optionValue(args, index, option) : argument.slice(separator + 1);
    if (separator < 0) index += 1;
    if (!value) throw usageError(`${option} requires a value`, 'logs');
    if (option === '--project') project = value;
    else if (option === '--job') setJob(value);
    else if (option === '--stage') stage = value;
    else if (option === '--level') {
      if (!['debug', 'info', 'warn', 'error'].includes(value)) throw usageError(`Unknown log level: ${value}`, 'logs');
      level = value as JobLogLevel;
    } else if (option === '--stream') {
      if (!['stdout', 'stderr', 'progress'].includes(value)) throw usageError(`Unknown log stream: ${value}`, 'logs');
      stream = value as JobLogStream;
    } else if (option === '--tail') {
      if (!/^\d+$/.test(value) || !Number.isSafeInteger(Number(value))) throw usageError('--tail requires a non-negative integer', 'logs');
      tail = Number(value);
    } else throw usageError(`Unknown option for logs: ${option}`, 'logs');
  }
  if (!jobId) throw usageError('logs requires JOB_ID or --job JOB_ID', 'logs');
  return {
    project, jobId, tail, follow,
    ...(stage === undefined ? {} : { stage }),
    ...(level === undefined ? {} : { level }),
    ...(stream === undefined ? {} : { stream }),
  };
}

async function writeStandardOutput(value: string): Promise<void> {
  if (!process.stdout.write(value)) await once(process.stdout, 'drain');
}

async function executeLogs(args: string[]): Promise<CommandResult> {
  const options = parseLogsOptions(args);
  const query = {
    jobId: options.jobId,
    tail: options.tail,
    ...(options.stage === undefined ? {} : { stage: options.stage }),
    ...(options.level === undefined ? {} : { level: options.level }),
    ...(options.stream === undefined ? {} : { stream: options.stream }),
  };
  if (options.follow) {
    return {
      command: 'logs',
      data: {},
      emit: async (json) => {
        const controller = new AbortController();
        const stop = () => controller.abort();
        process.once('SIGINT', stop);
        try {
          for await (const entry of followJobLogs(options.project, { ...query, signal: controller.signal })) {
            if (json) await writeStandardOutput(`${JSON.stringify({ ok: true, command: 'logs', ...entry })}\n`);
            else await writeStandardOutput(`[${entry.stage}] [${entry.level}] ${entry.stream}: ${entry.line}\n`);
          }
        } finally {
          process.removeListener('SIGINT', stop);
        }
      },
    };
  }
  const result = await readJobLogs(options.project, query);
  return {
    command: 'logs',
    data: { job: result.job, logs: result.logs, truncated: result.truncated },
    text: `${result.truncated ? '[... earlier matching output truncated ...]\n' : ''}${result.logs.map((entry) => `[${entry.stage}] [${entry.level}] ${entry.stream}: ${entry.line}`).join('\n')}${result.logs.length > 0 ? '\n' : ''}`,
  };
}

async function executeDiagnose(args: string[]): Promise<CommandResult> {
  let project = '.';
  let output: string | undefined;
  let jobId: string | undefined;
  for (let index = 0; index < args.length; index += 1) {
    const argument = args[index];
    if (argument === undefined) continue;
    if (!argument.startsWith('-')) {
      if (jobId) throw usageError('Only one job ID is allowed', 'diagnose');
      jobId = argument;
      continue;
    }
    const separator = argument.indexOf('=');
    const option = separator < 0 ? argument : argument.slice(0, separator);
    const value = separator < 0 ? optionValue(args, index, option) : argument.slice(separator + 1);
    if (separator < 0) index += 1;
    if (!value) throw usageError(`${option} requires a value`, 'diagnose');
    if (option === '--project' || option === '-p') project = value;
    else if (option === '--output') output = value;
    else throw usageError(`Unknown option for diagnose: ${option}`, 'diagnose');
  }
  if (!jobId) throw usageError('diagnose requires JOB_ID', 'diagnose');
  const result = await diagnoseJob({ projectDirectory: project, jobId, ...(output === undefined ? {} : { output }) });
  return {
    command: 'diagnose',
    data: { ...result },
    text: `Diagnostic directory: ${result.directory}\n${result.files.map((file) => `  ${file}`).join('\n')}\nSource media and environment variables were not collected; copied values were redacted.\n`,
  };
}

async function executeVocal(args: string[]): Promise<CommandResult> {
  const action = args[0];
  if (action !== 'autotune') throw usageError('Missing or unknown vocal action: autotune', 'vocal');
  let requestPath: string | undefined;
  let output: string | undefined;
  let report: string | undefined;
  let python: string | undefined;
  let force = false;
  for (let index = 1; index < args.length; index += 1) {
    const argument = args[index];
    if (argument === undefined) continue;
    if (argument === '--force') {
      force = true;
      continue;
    }
    if (!argument.startsWith('-')) {
      if (requestPath !== undefined) throw usageError('Only one autotune request JSON path is allowed', 'vocal.autotune');
      requestPath = argument;
      continue;
    }
    const separator = argument.indexOf('=');
    const option = separator < 0 ? argument : argument.slice(0, separator);
    const value = separator < 0 ? optionValue(args, index, option) : argument.slice(separator + 1);
    if (separator < 0) index += 1;
    if (!value) throw usageError(`${option} requires a value`, 'vocal.autotune');
    if (option === '--output') output = value;
    else if (option === '--report') report = value;
    else if (option === '--python') python = value;
    else throw usageError(`Unknown option for vocal autotune: ${option}`, 'vocal.autotune');
  }
  if (!requestPath) throw usageError('vocal autotune requires REQUEST_JSON', 'vocal.autotune');
  const result = await autotuneVocal({
    requestPath, force,
    ...(output === undefined ? {} : { output }),
    ...(report === undefined ? {} : { report }),
    ...(python === undefined ? {} : { python }),
  });
  const summary = result.report.summary;
  const pitch = summary.medianAbsoluteCentsError === undefined ? 'n/a' : `${summary.medianAbsoluteCentsError.toFixed(1)} cents`;
  return {
    command: 'vocal.autotune',
    data: { ...result },
    text: `Autotuned vocals: ${result.outputPath}\nReport: ${result.reportPath}\nNotes: ${summary.noteCount}; reliable pitch: ${summary.reliablePitchNoteCount}; median pitch error: ${pitch}; warnings: ${summary.warningCount}\n`,
  };
}

async function executeUi(args: string[]): Promise<CommandResult> {
  if (!process.stdin.isTTY || !process.stdout.isTTY) {
    throw usageError('codecut ui requires an interactive TTY; use codecut jobs list --json and codecut logs --json instead', 'ui');
  }
  let project = '.';
  let jobId: string | undefined;
  for (let index = 0; index < args.length; index += 1) {
    const argument = args[index];
    if (argument === undefined) continue;
    const separator = argument.indexOf('=');
    const option = separator < 0 ? argument : argument.slice(0, separator);
    const value = separator < 0 ? optionValue(args, index, option) : argument.slice(separator + 1);
    if (separator < 0) index += 1;
    if (!value) throw usageError(`${option} requires a value`, 'ui');
    if (option === '--project' || option === '-p') project = value;
    else if (option === '--job') jobId = value;
    else throw usageError(`Unknown option for ui: ${option}`, 'ui');
  }
  const { runTerminalUi } = await import('./ui.js');
  await runTerminalUi({ projectDirectory: project, ...(jobId === undefined ? {} : { jobId }) });
  return { command: 'ui', data: { closed: true }, text: '' };
}

async function execute(args: string[]): Promise<CommandResult> {
  const [command, ...rest] = args;
  if (!command) throw usageError('Missing command; use --help for usage');
  if (command === 'project') return executeProject(rest);
  if (command === 'asset') return executeAsset(rest);
  if (command === 'vocal') return executeVocal(rest);
  if (command === 'edit') return executeEdit(rest);
  if (command === 'history') return executeHistory(rest);
  if (command === 'render') return executeRender(rest);
  if (command === 'preview') return executePreview(rest);
  if (command === 'jobs') return executeJobs(rest);
  if (command === 'doctor') return executeDoctor(rest);
  if (command === 'logs') return executeLogs(rest);
  if (command === 'diagnose') return executeDiagnose(rest);
  if (command === 'ui') return executeUi(rest);
  if (command === 'schema') {
    if (rest.length > 0) throw usageError('schema does not accept arguments', 'schema');
    return {
      command: 'schema',
      data: {
        project: ProjectSchema,
        asset: AssetSchema,
        assetOperation: AssetOperationSchema,
        assetPreviewRequest: AssetPreviewRequestSchema,
        assetPreviewResult: AssetPreviewResultSchema,
        assetAnalysisRequest: AssetAnalysisRequestSchema,
        assetAnalysisResult: AssetAnalysisResultSchema,
        vocalAutotuneRequest: VocalAutotuneRequestSchema,
        vocalAutotuneReport: VocalAutotuneReportSchema,
        editOperation: EditOperationSchema,
        doctorResult: DoctorResultSchema,
        jobLogEntry: JobLogEntrySchema,
        logQuery: LogQuerySchema,
        diagnoseResult: DiagnoseResultSchema,
        job: JobSchema,
        renderRequest: RenderRequestSchema,
        renderPlan: RenderPlanSchema,
        timelinePreviewRequest: TimelinePreviewRequestSchema,
        timelinePreviewResult: TimelinePreviewResultSchema,
        revision: RevisionSchema,
      },
      alwaysJson: true,
    };
  }
  if (command === 'capabilities') {
    if (rest.length > 0) throw usageError('capabilities does not accept arguments', 'capabilities');
    return { command: 'capabilities', data: { capabilities: CAPABILITIES }, alwaysJson: true };
  }
  throw usageError(`Unknown command: ${command}`);
}

function debugErrorDetails(error: CodeCutError): string {
  const stacks: string[] = [];
  let current: unknown = error;
  const seen = new Set<unknown>();
  while (current instanceof Error && !seen.has(current)) {
    seen.add(current);
    stacks.push(current.stack ?? `${current.name}: ${current.message}`);
    current = current.cause;
  }
  return `${stacks.join('\nCaused by: ')}\n`;
}

export async function run(argv: string[] = process.argv.slice(2)): Promise<number> {
  const json = argv.includes('--json');
  const verbose = argv.includes('--verbose') || argv.includes('--debug');
  const debug = argv.includes('--debug');
  const args = argv.filter((argument) => !['--json', '--verbose', '--debug'].includes(argument));
  try {
    if (args.includes('--help') || args.includes('-h')) {
      if (json) {
        process.stdout.write(`${JSON.stringify({ ok: true, command: 'help', usage: USAGE }, null, 2)}\n`);
      } else {
        process.stdout.write(USAGE);
      }
      return ExitCode.Success;
    }
    if (args.includes('--version') || args.includes('-V')) {
      if (args.length !== 1) throw usageError('--version cannot be combined with other arguments');
      if (json) process.stdout.write(`${JSON.stringify({ ok: true, command: 'version', version: VERSION })}\n`);
      else process.stdout.write(`${VERSION}\n`);
      return ExitCode.Success;
    }

    const result = await execute(args);
    if (result.emit) {
      await result.emit(json);
    } else if (json || result.alwaysJson) {
      process.stdout.write(`${JSON.stringify({ ok: true, command: result.command, ...result.data }, null, 2)}\n`);
    } else {
      process.stdout.write(result.text ?? '');
    }
    if (verbose) process.stderr.write(`[verbose] ${result.command} completed\n`);
    if (debug) process.stderr.write(`[debug] result fields: ${Object.keys(result.data).join(', ') || '(streaming or none)'}\n`);
    return result.exitCode ?? ExitCode.Success;
  } catch (error) {
    const normalized = asCodeCutError(error);
    if (json) process.stderr.write(`${JSON.stringify({ error: normalized.toJSON() }, null, 2)}\n`);
    else process.stderr.write(formatTextError(normalized));
    if (verbose) {
      process.stderr.write(`[verbose] stage=${normalized.stage} retryable=${normalized.retryable ?? false}\n`);
      if (normalized.diagnostics !== undefined) process.stderr.write(`[verbose] diagnostics=${JSON.stringify(normalized.diagnostics)}\n`);
    }
    if (debug) process.stderr.write(`[debug]\n${debugErrorDetails(normalized)}`);
    return normalized.exitCode;
  }
}

const entry = process.argv[1];
if (entry && import.meta.url === pathToFileURL(resolve(entry)).href) {
  process.exitCode = await run();
}
