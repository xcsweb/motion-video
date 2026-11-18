import { createHash } from 'node:crypto';
import { readFile, stat } from 'node:fs/promises';
import { dirname, join, resolve } from 'node:path';
import {
  assertAudioAsset,
  assertVisualAsset,
  findAsset,
  inspectAssetFile,
  probeAssetFile,
  validateAnalysisRange,
  type AssetIdentity,
} from './assets.js';
import { CodeCutError, ExitCode } from './errors.js';
import { JobService, type JobRecord, type JobRequest } from './jobs.js';
import { loadProject } from './project.js';
import type {
  Asset,
  AssetAnalysisRequest,
  AssetPreviewRequest,
  AssetPreviewResult,
} from './schema.js';

export interface AssetJobOptions {
  detach?: boolean;
  ffmpegPath?: string;
  ffprobePath?: string;
  timeoutMs?: number;
}

interface PreparedAsset {
  asset: Asset;
  projectFile: string;
  projectDirectory: string;
  identity: AssetIdentity;
}

interface CacheManifest {
  version: 1;
  cacheKey: string;
  outputPath: string;
  source: AssetPreviewResult['source'];
  parameters: Record<string, unknown>;
}

const CACHE_VERSION = 1;

function hash(value: unknown): string {
  return createHash('sha256').update(JSON.stringify(value)).digest('hex');
}

function sameIdentity(left: AssetIdentity, right: AssetIdentity): boolean {
  return left.size === right.size && Math.abs(left.mtimeMs - right.mtimeMs) <= 1;
}

async function prepareAsset(
  projectPath: string,
  id: string,
  stage: string,
  ffprobePath?: string,
): Promise<PreparedAsset> {
  const { project, path } = await loadProject(projectPath, stage);
  const registered = findAsset(project, id, stage);
  const projectDirectory = dirname(path);
  const absolutePath = resolve(projectDirectory, registered.path);
  const identity = await inspectAssetFile(absolutePath, stage);
  let asset = registered;
  if (!registered.metadata || !sameIdentity(identity, { ...registered.metadata.fingerprint, path: registered.path, absolutePath })) {
    const probed = await probeAssetFile(absolutePath, stage, ffprobePath, registered.kind);
    asset = { ...registered, metadata: probed.metadata };
  }
  return { asset: structuredClone(asset), projectFile: path, projectDirectory, identity };
}

function jobService(projectDirectory: string, service?: JobService): JobService {
  return service ?? new JobService({ projectDirectory });
}

function startOptions(options: AssetJobOptions): { detach?: boolean } {
  return options.detach === undefined ? {} : { detach: options.detach };
}

function outputExists(path: string): Promise<boolean> {
  return stat(path).then((information) => information.isFile() && information.size > 0).catch((error) => {
    if ((error as NodeJS.ErrnoException).code === 'ENOENT') return false;
    throw error;
  });
}

async function validCache(manifestPath: string, cacheKey: string, outputPath: string): Promise<boolean> {
  try {
    const manifest = JSON.parse(await readFile(manifestPath, 'utf8')) as Partial<CacheManifest>;
    return manifest.version === CACHE_VERSION
      && manifest.cacheKey === cacheKey
      && manifest.outputPath === outputPath
      && await outputExists(outputPath);
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === 'ENOENT' || error instanceof SyntaxError) return false;
    throw error;
  }
}

function cachedProcess(outputPath: string, manifestPath: string, cacheKey: string): JobRequest['process'] {
  return {
    command: process.execPath,
    args: [
      '-e',
      "const fs=require('fs');const [output,manifestPath,key]=process.argv.slice(1);const manifest=JSON.parse(fs.readFileSync(manifestPath,'utf8'));if(manifest.cacheKey!==key||manifest.outputPath!==output||fs.statSync(output).size===0)throw new Error('Cache entry changed before the job started')",
      outputPath,
      manifestPath,
      cacheKey,
    ],
  };
}

function previewRange(asset: Asset, start: number, end: number | undefined, stage: string): { start: number; end: number } {
  const duration = asset.metadata?.duration ?? 0;
  const resolvedEnd = end ?? duration;
  if (!Number.isFinite(start) || start < 0 || !Number.isFinite(resolvedEnd) || resolvedEnd <= start
    || duration <= 0 || start >= duration || resolvedEnd > duration + 0.001) {
    throw new CodeCutError('PREVIEW_RANGE_INVALID', 'Preview range must be within the asset duration and end after start', ExitCode.Usage, {
      stage,
      path: asset.path,
      retryable: false,
      diagnostics: { start, end: resolvedEnd, duration },
    });
  }
  return { start, end: resolvedEnd };
}

function scaleFilter(width: number | undefined, height: number | undefined, defaultWidth: number): string {
  const resolvedWidth = width ?? (height === undefined ? defaultWidth : -2);
  return `scale=${resolvedWidth}:${height ?? -2}`;
}

export async function generateAssetPreview(
  projectPath: string,
  request: AssetPreviewRequest,
  options: AssetJobOptions = {},
  service?: JobService,
): Promise<JobRecord> {
  const stage = `asset.${request.type}`;
  const prepared = await prepareAsset(projectPath, request.assetId, stage, options.ffprobePath);
  assertVisualAsset(prepared.asset, stage);
  let parameters: Record<string, unknown>;
  let filter: string;
  if (request.type === 'thumbnail') {
    const at = request.at ?? 0;
    const duration = prepared.asset.metadata?.duration ?? 0;
    if (!Number.isFinite(at) || at < 0 || (duration > 0 && at >= duration) || (prepared.asset.kind === 'image' && at !== 0)) {
      throw new CodeCutError('PREVIEW_TIME_INVALID', 'Thumbnail time must be within the asset duration', ExitCode.Usage, {
        stage,
        path: prepared.asset.path,
        retryable: false,
        diagnostics: { at, duration },
      });
    }
    if (request.width !== undefined && (!Number.isInteger(request.width) || request.width < 16 || request.width > 4096)
      || request.height !== undefined && (!Number.isInteger(request.height) || request.height < 16 || request.height > 4096)) {
      throw new CodeCutError('PREVIEW_SIZE_INVALID', 'Thumbnail dimensions must be integers from 16 to 4096 pixels', ExitCode.Usage, {
        stage, retryable: false,
      });
    }
    parameters = {
      at,
      width: request.width ?? (request.height === undefined ? 640 : null),
      height: request.height ?? null,
    };
    filter = scaleFilter(request.width, request.height, 640);
  } else {
    const start = request.start ?? 0;
    const columns = request.columns ?? 4;
    const rows = request.rows ?? 3;
    const width = request.width ?? 320;
    if (!Number.isInteger(columns) || columns < 1 || columns > 20
      || !Number.isInteger(rows) || rows < 1 || rows > 20 || columns * rows > 200
      || !Number.isInteger(width) || width < 16 || width > 2048
      || request.height !== undefined && (!Number.isInteger(request.height) || request.height < 16 || request.height > 2048)) {
      throw new CodeCutError('PREVIEW_SHEET_LAYOUT_INVALID', 'Sheet layout must use at most 200 cells and valid integer dimensions', ExitCode.Usage, {
        stage, retryable: false,
      });
    }
    const range = previewRange(prepared.asset, start, request.end, stage);
    const interval = request.interval ?? (range.end - range.start) / (columns * rows);
    if (!Number.isFinite(interval) || interval <= 0 || interval > 3600) {
      throw new CodeCutError('PREVIEW_INTERVAL_INVALID', 'Sheet interval must be greater than 0 and at most 3600 seconds', ExitCode.Usage, {
        stage, retryable: false, diagnostics: { interval },
      });
    }
    parameters = {
      start: range.start,
      end: range.end,
      interval,
      columns,
      rows,
      width,
      height: request.height ?? null,
    };
    const scale = scaleFilter(width, request.height, 320);
    const timestamp = "drawtext=text='%{pts\\:hms}':fontcolor=white:fontsize=18:box=1:boxcolor=black@0.65:boxborderw=4:x=6:y=6";
    filter = `fps=1/${interval},${scale},setpts=PTS+${range.start}/TB,${timestamp},tile=${columns}x${rows}:margin=8:padding=4:color=0x202020`;
  }

  const source: AssetPreviewResult['source'] = {
    path: prepared.asset.path,
    size: prepared.identity.size,
    mtimeMs: prepared.identity.mtimeMs,
  };
  const cacheKey = hash({ version: CACHE_VERSION, assetId: request.assetId, type: request.type, source, parameters });
  const defaultOutput = join(prepared.projectDirectory, '.codecut', 'cache', 'assets', request.assetId, `${cacheKey}.png`);
  const outputPath = request.output ? resolve(prepared.projectDirectory, request.output) : defaultOutput;
  const manifestPath = join(
    prepared.projectDirectory,
    '.codecut',
    'cache',
    'assets',
    request.assetId,
    `${hash({ cacheKey, outputPath })}.json`,
  );
  const force = request.force ?? false;
  const cacheHit = !force && await validCache(manifestPath, cacheKey, outputPath);
  const result: AssetPreviewResult = {
    type: request.type,
    assetId: request.assetId,
    outputPath,
    cacheKey,
    cacheHit,
    source,
    parameters,
  };
  const common = {
    projectPath: prepared.projectFile,
    result: {
      data: result as unknown as Record<string, unknown>,
      ...(cacheHit ? {} : {
        cacheManifestPath: manifestPath,
        cacheManifest: {
          version: CACHE_VERSION,
          cacheKey,
          outputPath,
          source,
          parameters,
        },
      }),
    },
    ...(options.timeoutMs === undefined ? {} : { timeoutMs: options.timeoutMs }),
  };
  let jobRequest: JobRequest;
  if (cacheHit) {
    jobRequest = {
      kind: request.type === 'thumbnail' ? 'asset.thumbnail' : 'asset.sheet',
      process: cachedProcess(outputPath, manifestPath, cacheKey),
      ...common,
    };
  } else {
    const args = [
      '-hide_banner', '-nostdin', '-progress', 'pipe:1', '-nostats',
    ];
    if (request.type === 'thumbnail') {
      args.push('-ss', String(parameters.at), '-i', resolve(prepared.projectDirectory, prepared.asset.path));
    } else {
      args.push(
        '-ss', String(parameters.start),
        '-t', String((parameters.end as number) - (parameters.start as number)),
        '-i', resolve(prepared.projectDirectory, prepared.asset.path),
      );
    }
    args.push('-an', '-vf', filter, '-frames:v', '1');
    if (request.type === 'sheet') args.push('-update', '1');
    args.push('-c:v', 'png', '-f', 'image2', '-n', '{output}');
    jobRequest = {
      kind: request.type === 'thumbnail' ? 'asset.thumbnail' : 'asset.sheet',
      process: {
        command: options.ffmpegPath ?? 'ffmpeg',
        args,
        progress: 'ffmpeg',
        ...(request.type === 'sheet'
          ? { durationSeconds: (parameters.end as number) - (parameters.start as number) }
          : prepared.asset.metadata?.duration === undefined ? {} : { durationSeconds: prepared.asset.metadata.duration }),
      },
      output: {
        path: outputPath,
        overwrite: force || outputPath === defaultOutput,
        validation: 'nonEmpty',
      },
      ...common,
    };
  }
  return jobService(prepared.projectDirectory, service).enqueue(jobRequest, startOptions(options));
}

export async function analyzeAsset(
  projectPath: string,
  request: AssetAnalysisRequest,
  options: AssetJobOptions = {},
  service?: JobService,
): Promise<JobRecord> {
  const stage = `asset.analyze.${request.type}`;
  const prepared = await prepareAsset(projectPath, request.assetId, stage, options.ffprobePath);
  if (request.type === 'scenes') assertVisualAsset(prepared.asset, stage);
  else assertAudioAsset(prepared.asset, stage);
  const range = validateAnalysisRange(prepared.asset, request.start ?? 0, request.end, stage);
  const durationSeconds = range.end - range.start;
  const args = [
    '-hide_banner', '-nostdin', '-progress', 'pipe:1', '-nostats',
    '-ss', String(range.start), '-t', String(durationSeconds),
    '-i', resolve(prepared.projectDirectory, prepared.asset.path),
  ];
  let analysis: NonNullable<JobRequest['analysis']>;
  if (request.type === 'scenes') {
    const threshold = request.threshold ?? 0.3;
    if (!Number.isFinite(threshold) || threshold <= 0 || threshold > 1) {
      throw new CodeCutError('SCENE_THRESHOLD_INVALID', 'Scene threshold must be greater than 0 and at most 1', ExitCode.Usage, {
        stage, retryable: false,
      });
    }
    analysis = { type: 'scenes', assetId: request.assetId, ...range, threshold };
    args.push('-an', '-vf', `select='gt(scene,${threshold})',metadata=mode=print`);
  } else {
    const noiseDb = request.noiseDb ?? -35;
    const minimumDuration = request.minimumDuration ?? 0.5;
    if (!Number.isFinite(noiseDb) || noiseDb < -120 || noiseDb >= 0) {
      throw new CodeCutError('SILENCE_THRESHOLD_INVALID', 'Silence noise level must be in the range [-120, 0) dB', ExitCode.Usage, {
        stage, retryable: false,
      });
    }
    if (!Number.isFinite(minimumDuration) || minimumDuration <= 0 || minimumDuration > 3600) {
      throw new CodeCutError('SILENCE_DURATION_INVALID', 'Minimum silence duration must be greater than 0 and at most 3600 seconds', ExitCode.Usage, {
        stage, retryable: false,
      });
    }
    analysis = { type: 'silence', assetId: request.assetId, ...range, noiseDb, minimumDuration };
    args.push('-vn', '-af', `silencedetect=noise=${noiseDb}dB:d=${minimumDuration}`);
  }
  args.push('-f', 'null', '-');
  return jobService(prepared.projectDirectory, service).enqueue({
    kind: 'asset.analyze',
    projectPath: prepared.projectFile,
    process: { command: options.ffmpegPath ?? 'ffmpeg', args, progress: 'ffmpeg', durationSeconds },
    analysis,
    ...(options.timeoutMs === undefined ? {} : { timeoutMs: options.timeoutMs }),
  }, startOptions(options));
}
