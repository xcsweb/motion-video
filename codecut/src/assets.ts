import { execa } from 'execa';
import { access, mkdir, stat } from 'node:fs/promises';
import { constants } from 'node:fs';
import { dirname, relative, resolve, sep } from 'node:path';
import { CodeCutError, ExitCode } from './errors.js';
import {
  commitProjectTransaction,
  type ProjectTransactionResult,
} from './history.js';
import { loadProject } from './project.js';
import type {
  Asset,
  AssetFingerprint,
  AssetKind,
  AssetMetadata,
  AssetStream,
  Project,
} from './schema.js';

export interface AssetIdentity extends AssetFingerprint {
  path: string;
  absolutePath: string;
}

export interface AssetFileStatus {
  id: string;
  path: string;
  absolutePath: string;
  state: 'ok' | 'changed' | 'missing' | 'unreadable' | 'notFile';
  readable: boolean;
  size?: number;
  mtimeMs?: number;
  metadataStale: boolean;
  error?: { code: string; message: string };
}

export interface AssetReference {
  trackId: string;
  clipId: string;
}

export interface AssetWriteResult extends ProjectTransactionResult {
  asset: Asset;
  normalization?: { target: string; applied: boolean };
}

export interface AssetAddOptions {
  id: string;
  path: string;
  kind?: AssetKind;
  dryRun?: boolean;
  ffprobePath?: string;
}

export interface AssetProbeOptions {
  dryRun?: boolean;
  ffprobePath?: string;
}

interface FfprobeStream {
  index?: unknown;
  codec_type?: unknown;
  codec_name?: unknown;
  width?: unknown;
  height?: unknown;
  avg_frame_rate?: unknown;
  r_frame_rate?: unknown;
  sample_rate?: unknown;
  channels?: unknown;
  channel_layout?: unknown;
  duration?: unknown;
  bit_rate?: unknown;
  tags?: { rotate?: unknown } | unknown;
  side_data_list?: unknown;
}

interface FfprobeDocument {
  streams?: unknown;
  format?: {
    duration?: unknown;
    size?: unknown;
    format_name?: unknown;
    bit_rate?: unknown;
  };
}

const IDENTIFIER = /^[A-Za-z0-9][A-Za-z0-9._-]*$/;
const IMAGE_CODECS = new Set(['png', 'mjpeg', 'webp', 'bmp', 'gif', 'tiff', 'jpeg2000']);
const IMAGE_FORMATS = new Set(['image2', 'png_pipe', 'jpeg_pipe', 'webp_pipe', 'gif', 'bmp', 'tiff']);

function assetError(
  code: string,
  message: string,
  exitCode: ExitCode,
  stage: string,
  path?: string,
  options: { cause?: unknown; retryable?: boolean; diagnostics?: unknown } = {},
): CodeCutError {
  return new CodeCutError(code, message, exitCode, {
    stage,
    ...(path === undefined ? {} : { path }),
    ...(options.cause === undefined ? {} : { cause: options.cause }),
    ...(options.diagnostics === undefined ? {} : { diagnostics: options.diagnostics }),
    retryable: options.retryable ?? false,
  });
}

function optionalString(value: unknown): string | undefined {
  return typeof value === 'string' && value.length > 0 ? value : undefined;
}

function optionalNumber(value: unknown): number | undefined {
  if (value === undefined || value === null || value === '' || value === 'N/A') return undefined;
  const parsed = typeof value === 'number' ? value : Number(value);
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : undefined;
}

function optionalInteger(value: unknown): number | undefined {
  const parsed = optionalNumber(value);
  return parsed === undefined ? undefined : Math.round(parsed);
}

function frameRate(stream: FfprobeStream): number | undefined {
  for (const candidate of [stream.avg_frame_rate, stream.r_frame_rate]) {
    if (typeof candidate !== 'string') continue;
    const [numeratorText, denominatorText] = candidate.split('/');
    const numerator = Number(numeratorText);
    const denominator = Number(denominatorText);
    if (Number.isFinite(numerator) && Number.isFinite(denominator) && denominator > 0) {
      const value = numerator / denominator;
      if (Number.isFinite(value) && value > 0) return value;
    }
  }
  return undefined;
}

function streamRotation(stream: FfprobeStream): number | undefined {
  if (Array.isArray(stream.side_data_list)) {
    for (const entry of stream.side_data_list) {
      if (typeof entry !== 'object' || entry === null) continue;
      const rotation = optionalNumber((entry as { rotation?: unknown }).rotation);
      if (rotation !== undefined) return rotation;
    }
  }
  if (typeof stream.tags === 'object' && stream.tags !== null) {
    const tagged = optionalNumber((stream.tags as { rotate?: unknown }).rotate);
    if (tagged !== undefined) return tagged;
  }
  return undefined;
}

function mapStream(value: unknown, fallbackIndex: number): AssetStream | undefined {
  if (typeof value !== 'object' || value === null) return undefined;
  const stream = value as FfprobeStream;
  const codecType = optionalString(stream.codec_type);
  if (!codecType) return undefined;
  const index = optionalInteger(stream.index) ?? fallbackIndex;
  const result: AssetStream = { index, codecType };
  const assignments = {
    codecName: optionalString(stream.codec_name),
    width: optionalInteger(stream.width),
    height: optionalInteger(stream.height),
    frameRate: frameRate(stream),
    sampleRate: optionalInteger(stream.sample_rate),
    channels: optionalInteger(stream.channels),
    channelLayout: optionalString(stream.channel_layout),
    duration: optionalNumber(stream.duration),
    bitRate: optionalInteger(stream.bit_rate),
    rotation: streamRotation(stream),
  };
  for (const [key, entry] of Object.entries(assignments)) {
    if (entry !== undefined) (result as unknown as Record<string, unknown>)[key] = entry;
  }
  return result;
}

function sameFingerprint(left: AssetFingerprint, right: AssetFingerprint): boolean {
  return left.size === right.size && Math.abs(left.mtimeMs - right.mtimeMs) <= 1;
}

export async function inspectAssetFile(
  absolutePath: string,
  stage: string,
): Promise<AssetIdentity> {
  let information;
  try {
    information = await stat(absolutePath);
  } catch (cause) {
    const code = (cause as NodeJS.ErrnoException).code;
    if (code === 'ENOENT' || code === 'ENOTDIR') {
      throw assetError('ASSET_FILE_MISSING', 'Asset file does not exist', ExitCode.Media, stage, absolutePath, { cause });
    }
    throw assetError('ASSET_FILE_UNREADABLE', 'Asset file cannot be accessed', ExitCode.Media, stage, absolutePath, {
      cause,
      retryable: code === 'EACCES' || code === 'EPERM',
    });
  }
  if (!information.isFile()) {
    throw assetError('ASSET_NOT_FILE', 'Asset path is not a regular file', ExitCode.Media, stage, absolutePath);
  }
  try {
    await access(absolutePath, constants.R_OK);
  } catch (cause) {
    throw assetError('ASSET_FILE_UNREADABLE', 'Asset file is not readable', ExitCode.Media, stage, absolutePath, {
      cause,
      retryable: true,
    });
  }
  return {
    path: absolutePath,
    absolutePath,
    size: information.size,
    mtimeMs: information.mtimeMs,
  };
}

function isImage(document: FfprobeDocument, streams: AssetStream[]): boolean {
  const formatNames = (optionalString(document.format?.format_name) ?? '').split(',');
  if (formatNames.some((name) => IMAGE_FORMATS.has(name))) return true;
  return streams.some((stream) => stream.codecType === 'video' && stream.codecName && IMAGE_CODECS.has(stream.codecName))
    && optionalNumber(document.format?.duration) === undefined;
}

function validateKind(kind: AssetKind, inferred: AssetKind, streams: AssetStream[], path: string, stage: string): void {
  const hasVideo = streams.some((stream) => stream.codecType === 'video');
  const hasAudio = streams.some((stream) => stream.codecType === 'audio');
  const compatible = kind === 'audio' ? hasAudio : kind === 'video' ? hasVideo : hasVideo && inferred === 'image';
  if (!compatible) {
    throw assetError('ASSET_KIND_MISMATCH', `Asset kind "${kind}" is incompatible with the detected ${inferred} media streams`, ExitCode.Media, stage, path, {
      diagnostics: { detectedKind: inferred, streams },
    });
  }
}

export async function probeAssetFile(
  absolutePath: string,
  stage = 'asset.probe',
  ffprobePath = 'ffprobe',
  expectedKind?: AssetKind,
): Promise<{ metadata: AssetMetadata; detectedKind: AssetKind; identity: AssetIdentity }> {
  const before = await inspectAssetFile(absolutePath, stage);
  const result = await execa(ffprobePath, [
    '-v', 'error', '-show_streams', '-show_format', '-of', 'json', absolutePath,
  ], { reject: false, timeout: 30_000, maxBuffer: 8 * 1024 * 1024 });
  if (result.failed) {
    const invalidMedia = result.exitCode !== undefined && !result.timedOut;
    throw assetError(
      invalidMedia ? 'ASSET_NOT_MEDIA' : 'ASSET_PROBE_FAILED',
      invalidMedia ? 'ffprobe could not identify audio or video media' : 'ffprobe could not read the asset as media',
      ExitCode.Media,
      stage,
      absolutePath,
      {
        retryable: result.timedOut,
        diagnostics: { exitCode: result.exitCode, stderr: result.stderr, timedOut: result.timedOut },
      },
    );
  }
  let document: FfprobeDocument;
  try {
    document = JSON.parse(result.stdout) as FfprobeDocument;
  } catch (cause) {
    throw assetError('ASSET_PROBE_INVALID', 'ffprobe returned invalid JSON', ExitCode.Media, stage, absolutePath, {
      cause,
      diagnostics: { stdoutTail: result.stdout.slice(-4096) },
    });
  }
  if (!Array.isArray(document.streams)) {
    throw assetError('ASSET_PROBE_INVALID', 'ffprobe response has no stream array', ExitCode.Media, stage, absolutePath);
  }
  const streams = document.streams.map(mapStream).filter((stream): stream is AssetStream => stream !== undefined);
  if (!streams.some((stream) => stream.codecType === 'video' || stream.codecType === 'audio')) {
    throw assetError('ASSET_NOT_MEDIA', 'Asset has no audio or video media stream', ExitCode.Media, stage, absolutePath, {
      diagnostics: { streams },
    });
  }
  const detectedKind: AssetKind = streams.some((stream) => stream.codecType === 'video')
    ? isImage(document, streams) ? 'image' : 'video'
    : 'audio';
  if (expectedKind) validateKind(expectedKind, detectedKind, streams, absolutePath, stage);
  const after = await inspectAssetFile(absolutePath, stage);
  if (!sameFingerprint(before, after)) {
    throw assetError('ASSET_FILE_CHANGED', 'Asset changed while ffprobe metadata was being captured', ExitCode.Media, stage, absolutePath, {
      retryable: true,
    });
  }
  const streamDurations = streams.map((stream) => stream.duration ?? 0);
  const duration = optionalNumber(document.format?.duration) ?? Math.max(0, ...streamDurations);
  const metadata: AssetMetadata = {
    probedAt: new Date().toISOString(),
    fingerprint: { size: before.size, mtimeMs: before.mtimeMs },
    duration,
    size: before.size,
    ...(optionalString(document.format?.format_name) === undefined ? {} : { formatName: optionalString(document.format?.format_name)! }),
    ...(optionalInteger(document.format?.bit_rate) === undefined ? {} : { bitRate: optionalInteger(document.format?.bit_rate)! }),
    streams,
  };
  return { metadata, detectedKind, identity: before };
}

export function normalizeAssetPath(projectDirectory: string, input: string): string {
  if (input.length === 0 || input.includes('\0')) {
    throw assetError('ASSET_PATH_INVALID', 'Asset path must not be empty', ExitCode.Usage, 'asset.add');
  }
  const normalized = relative(projectDirectory, resolve(projectDirectory, input)).split(sep).join('/');
  if (!normalized) {
    throw assetError('ASSET_PATH_INVALID', 'Asset path must identify a file, not the project directory', ExitCode.Usage, 'asset.add', input);
  }
  return normalized;
}

export function findAsset(project: Project, id: string, stage = 'asset'): Asset {
  const asset = project.assets.find((candidate) => candidate.id === id);
  if (!asset) {
    throw assetError('ASSET_NOT_FOUND', `Asset "${id}" is not registered`, ExitCode.ProjectValidation, stage, undefined, {
      diagnostics: { assetId: id },
    });
  }
  return asset;
}

function assertIdentifier(id: string): void {
  if (!IDENTIFIER.test(id)) {
    throw assetError('ASSET_ID_INVALID', `Invalid asset ID "${id}"`, ExitCode.Usage, 'asset.add', undefined, {
      diagnostics: { pattern: IDENTIFIER.source },
    });
  }
}

function duplicateChecks(project: Project, id: string, absolutePath: string, projectDirectory: string, stage: string): void {
  if (project.assets.some((asset) => asset.id === id)) {
    throw assetError('ASSET_ID_EXISTS', `Asset ID "${id}" is already registered`, ExitCode.ProjectValidation, stage, undefined, {
      diagnostics: { assetId: id },
    });
  }
  const duplicate = project.assets.find((asset) => resolve(projectDirectory, asset.path) === absolutePath);
  if (duplicate) {
    throw assetError('ASSET_PATH_EXISTS', 'The same source path is already registered', ExitCode.ProjectValidation, stage, duplicate.path, {
      diagnostics: { assetId: duplicate.id, path: duplicate.path },
    });
  }
}

export function assetReferences(project: Project, id: string): AssetReference[] {
  const references: AssetReference[] = [];
  for (const track of project.tracks) {
    for (const clip of track.clips) {
      if ((clip.type === 'video' || clip.type === 'audio' || clip.type === 'image') && clip.assetId === id) {
        references.push({ trackId: track.id, clipId: clip.id });
      }
    }
  }
  return references;
}

function needsNormalization(streams: AssetStream[]): boolean {
  const video = streams.find((stream) => stream.codecType === 'video');
  if (!video) return false;
  if ((video.codecName ?? '') !== 'h264') return true;
  return Math.abs((video.rotation ?? 0) % 360) > 0.01;
}

async function normalizeVideoSource(
  sourcePath: string,
  outputPath: string,
  stage: string,
  ffmpegPath = 'ffmpeg',
): Promise<void> {
  await mkdir(dirname(outputPath), { recursive: true });
  const result = await execa(ffmpegPath, [
    '-y', '-v', 'error',
    '-i', sourcePath,
    '-map', '0:v:0',
    '-map', '0:a?',
    '-c:v', 'libx264',
    '-preset', 'veryfast',
    '-crf', '18',
    '-pix_fmt', 'yuv420p',
    '-c:a', 'aac',
    '-b:a', '192k',
    '-movflags', '+faststart',
    outputPath,
  ], { reject: false, timeout: 15 * 60 * 1000, maxBuffer: 16 * 1024 * 1024 });
  if (result.failed) {
    throw assetError('ASSET_NORMALIZE_FAILED', 'ffmpeg could not transcode the asset to H.264', ExitCode.Media, stage, sourcePath, {
      diagnostics: { exitCode: result.exitCode, stderr: result.stderr?.slice(-4096), timedOut: result.timedOut },
      retryable: result.timedOut,
    });
  }
}

export async function addAsset(projectPath: string, options: AssetAddOptions): Promise<AssetWriteResult> {
  assertIdentifier(options.id);
  const { project, path } = await loadProject(projectPath, 'asset.add');
  const projectDirectory = dirname(path);
  const assetPath = normalizeAssetPath(projectDirectory, options.path);
  const absolutePath = resolve(projectDirectory, assetPath);
  duplicateChecks(project, options.id, absolutePath, projectDirectory, 'asset.add');
  const probed = await probeAssetFile(absolutePath, 'asset.add', options.ffprobePath, options.kind);
  const detectedKind = options.kind ?? probed.detectedKind;
  const normalizationTarget = `media/${options.id}.mp4`;
  const needsTranscode = detectedKind === 'video' && needsNormalization(probed.metadata.streams);
  const shouldNormalize = needsTranscode && options.dryRun !== true;

  let registeredPath = assetPath;
  let registeredAbsolute = absolutePath;
  let registeredMetadata = probed.metadata;
  let registeredIdentity = probed.identity;
  let normalizedFrom: AssetMetadata['normalizedFrom'];

  if (shouldNormalize) {
    const outputPath = resolve(projectDirectory, normalizationTarget);
    await normalizeVideoSource(absolutePath, outputPath, 'asset.add');
    const normalized = await probeAssetFile(outputPath, 'asset.add');
    const sourceVideo = probed.metadata.streams.find((stream) => stream.codecType === 'video');
    normalizedFrom = {
      path: assetPath,
      ...(sourceVideo?.codecName === undefined ? {} : { codecName: sourceVideo.codecName }),
      ...(sourceVideo?.rotation === undefined ? {} : { rotation: sourceVideo.rotation }),
    };
    registeredPath = normalizationTarget;
    registeredAbsolute = outputPath;
    registeredIdentity = normalized.identity;
    registeredMetadata = { ...normalized.metadata, normalizedFrom };
  }

  const asset: Asset = {
    id: options.id,
    kind: detectedKind,
    path: registeredPath,
    metadata: registeredMetadata,
  };
  const result = await commitProjectTransaction(path, {
    ...(options.dryRun === undefined ? {} : { dryRun: options.dryRun }),
    summary: `Add asset ${options.id}`,
    operations: [{ type: 'addAsset', asset }],
  }, async (draft) => {
    duplicateChecks(draft, options.id, absolutePath, projectDirectory, 'asset.add');
    const current = await inspectAssetFile(registeredAbsolute, 'asset.add');
    if (!sameFingerprint(current, registeredIdentity)) {
      throw assetError('ASSET_FILE_CHANGED', 'Asset changed before the registration transaction', ExitCode.Media, 'asset.add', registeredAbsolute, {
        retryable: true,
      });
    }
    draft.assets.push(asset);
  });
  const written = result.project.assets.find((candidate) => candidate.id === options.id)!;
  return {
    ...result,
    asset: written,
    ...(needsTranscode ? { normalization: { target: normalizationTarget, applied: shouldNormalize } } : {}),
  };
}

export async function probeAsset(projectPath: string, id: string, options: AssetProbeOptions = {}): Promise<AssetWriteResult> {
  const { project, path } = await loadProject(projectPath, 'asset.probe');
  const existing = findAsset(project, id, 'asset.probe');
  const projectDirectory = dirname(path);
  const absolutePath = resolve(projectDirectory, existing.path);
  const probed = await probeAssetFile(absolutePath, 'asset.probe', options.ffprobePath, existing.kind);
  const result = await commitProjectTransaction(path, {
    ...(options.dryRun === undefined ? {} : { dryRun: options.dryRun }),
    summary: `Probe asset ${id}`,
    operations: [{ type: 'probeAsset', assetId: id, metadata: probed.metadata }],
  }, async (draft) => {
    const asset = findAsset(draft, id, 'asset.probe');
    if (asset.path !== existing.path || asset.kind !== existing.kind) {
      throw assetError('ASSET_REGISTRATION_CHANGED', 'Asset registration changed before the probe transaction', ExitCode.ProjectValidation, 'asset.probe', asset.path, {
        retryable: true,
      });
    }
    const current = await inspectAssetFile(absolutePath, 'asset.probe');
    if (!sameFingerprint(current, probed.identity)) {
      throw assetError('ASSET_FILE_CHANGED', 'Asset changed before the metadata transaction', ExitCode.Media, 'asset.probe', absolutePath, {
        retryable: true,
      });
    }
    asset.metadata = probed.metadata;
  });
  return { ...result, asset: result.project.assets.find((candidate) => candidate.id === id)! };
}

export async function removeAsset(
  projectPath: string,
  id: string,
  options: { dryRun?: boolean } = {},
): Promise<AssetWriteResult> {
  const { project, path } = await loadProject(projectPath, 'asset.remove');
  const existing = structuredClone(findAsset(project, id, 'asset.remove'));
  const result = await commitProjectTransaction(path, {
    ...(options.dryRun === undefined ? {} : { dryRun: options.dryRun }),
    summary: `Remove asset ${id}`,
    operations: [{ type: 'removeAsset', assetId: id }],
  }, (draft) => {
    const index = draft.assets.findIndex((asset) => asset.id === id);
    if (index < 0) findAsset(draft, id, 'asset.remove');
    const references = assetReferences(draft, id);
    if (references.length > 0) {
      throw assetError('ASSET_IN_USE', `Asset "${id}" is still referenced by timeline clips`, ExitCode.ProjectValidation, 'asset.remove', draft.assets[index]?.path, {
        diagnostics: { assetId: id, references },
      });
    }
    draft.assets.splice(index, 1);
  });
  return { ...result, asset: existing };
}

export async function listAssets(projectPath: string): Promise<{ path: string; assets: Asset[] }> {
  const { project, path } = await loadProject(projectPath, 'asset.list');
  return { path, assets: project.assets };
}

export async function getAssetStatus(
  projectPath: string,
  id?: string,
): Promise<{ path: string; assets: AssetFileStatus[] }> {
  const { project, path } = await loadProject(projectPath, 'asset.status');
  const projectDirectory = dirname(path);
  const selected = id === undefined ? project.assets : [findAsset(project, id, 'asset.status')];
  const assets: AssetFileStatus[] = [];
  for (const asset of selected) {
    const absolutePath = resolve(projectDirectory, asset.path);
    try {
      const identity = await inspectAssetFile(absolutePath, 'asset.status');
      const changed = asset.metadata !== undefined && !sameFingerprint(identity, asset.metadata.fingerprint);
      assets.push({
        id: asset.id,
        path: asset.path,
        absolutePath,
        state: changed ? 'changed' : 'ok',
        readable: true,
        size: identity.size,
        mtimeMs: identity.mtimeMs,
        metadataStale: changed,
      });
    } catch (error) {
      const normalized = error instanceof CodeCutError ? error : undefined;
      const state = normalized?.code === 'ASSET_FILE_MISSING'
        ? 'missing'
        : normalized?.code === 'ASSET_NOT_FILE' ? 'notFile' : 'unreadable';
      assets.push({
        id: asset.id,
        path: asset.path,
        absolutePath,
        state,
        readable: false,
        metadataStale: true,
        error: {
          code: normalized?.code ?? 'ASSET_FILE_UNREADABLE',
          message: normalized?.message ?? 'Asset file cannot be accessed',
        },
      });
    }
  }
  return { path, assets };
}

export function assertVisualAsset(asset: Asset, stage: string): void {
  if (asset.kind === 'audio' || !asset.metadata?.streams.some((stream) => stream.codecType === 'video')) {
    throw assetError('ASSET_HAS_NO_VIDEO', `Asset "${asset.id}" has no usable video stream`, ExitCode.Media, stage, asset.path, {
      diagnostics: { assetId: asset.id },
    });
  }
}

export function assertAudioAsset(asset: Asset, stage: string): void {
  if (!asset.metadata?.streams.some((stream) => stream.codecType === 'audio')) {
    throw assetError('ASSET_HAS_NO_AUDIO', `Asset "${asset.id}" has no usable audio stream`, ExitCode.Media, stage, asset.path, {
      diagnostics: { assetId: asset.id },
    });
  }
}

export function validateAnalysisRange(asset: Asset, start: number, end: number | undefined, stage: string): { start: number; end: number } {
  const duration = asset.metadata?.duration ?? 0;
  const resolvedEnd = end ?? duration;
  if (!Number.isFinite(start) || start < 0 || !Number.isFinite(resolvedEnd) || resolvedEnd <= start) {
    throw assetError('ANALYSIS_RANGE_INVALID', 'Analysis range must have start >= 0 and end > start', ExitCode.Usage, stage, asset.path, {
      diagnostics: { start, end: resolvedEnd, duration },
    });
  }
  if (duration > 0 && (start >= duration || resolvedEnd > duration + 0.001)) {
    throw assetError('ANALYSIS_RANGE_INVALID', 'Analysis range exceeds the asset duration', ExitCode.Usage, stage, asset.path, {
      diagnostics: { start, end: resolvedEnd, duration },
    });
  }
  return { start, end: resolvedEnd };
}
