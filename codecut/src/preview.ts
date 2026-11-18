import { join, resolve } from 'node:path';
import { CodeCutError, ExitCode } from './errors.js';
import { JobService, type JobRecord } from './jobs.js';
import { calculateTimeline } from './project.js';
import {
  fixedSnapshot,
  loadRenderProject,
  prepareSources,
} from './render.js';
import {
  compileRenderPlan,
  type RenderPlan,
  type RenderPostprocess,
  type SheetPostprocess,
} from './render-plan.js';

interface PreviewCommonRequest {
  output?: string;
  force?: boolean;
}

export type TimelinePreviewRequest = PreviewCommonRequest & (
  | { type: 'frame'; at?: number; width?: number; height?: number }
  | {
    type: 'sheet';
    start?: number;
    end?: number;
    interval?: number;
    columns?: number;
    rows?: number;
    width?: number;
    height?: number;
  }
  | {
    type: 'proxy';
    width?: number;
    height?: number;
    crf?: number;
    videoBitrateKbps?: number;
    audioBitrateKbps?: number;
  }
);

export interface PreviewOptions {
  revision?: number | string;
  detach?: boolean;
  dryRun?: boolean;
  timeoutMs?: number;
  ffmpegPath?: string;
  ffprobePath?: string;
}

export interface PreviewDescription {
  type: TimelinePreviewRequest['type'];
  outputPath: string;
  parameters: RenderPostprocess;
}

export interface PreviewResult {
  dryRun: boolean;
  revisionId?: string;
  plan: RenderPlan;
  preview: PreviewDescription;
  job?: JobRecord;
}

const EPSILON = 1e-9;
const MAX_CELLS = 200;

function previewError(
  code: string,
  message: string,
  type: TimelinePreviewRequest['type'],
  diagnostics?: unknown,
): CodeCutError {
  return new CodeCutError(code, message, ExitCode.Usage, {
    stage: `preview.${type}.plan`,
    retryable: false,
    ...(diagnostics === undefined ? {} : { diagnostics }),
  });
}

function assertDimension(value: number | undefined, label: string, type: TimelinePreviewRequest['type'], maximum: number): void {
  if (value !== undefined && (!Number.isSafeInteger(value) || value < 16 || value > maximum || value % 2 !== 0)) {
    throw previewError(
      'PREVIEW_SIZE_INVALID',
      `Preview ${label} must be an even integer from 16 to ${maximum} pixels`,
      type,
      { [label]: value, minimum: 16, maximum, multipleOf: 2 },
    );
  }
}

function even(value: number): number {
  return Math.max(2, Math.round(value / 2) * 2);
}

function dimensions(
  request: { width?: number; height?: number },
  sourceWidth: number,
  sourceHeight: number,
  defaultWidth: number,
  defaultHeight: number,
  type: TimelinePreviewRequest['type'],
  maximum: number,
): { width: number; height: number } {
  assertDimension(request.width, 'width', type, maximum);
  assertDimension(request.height, 'height', type, maximum);
  const width = request.width ?? (request.height === undefined
    ? defaultWidth
    : even(request.height * sourceWidth / sourceHeight));
  const height = request.height ?? (request.width === undefined
    ? defaultHeight
    : even(request.width * sourceHeight / sourceWidth));
  assertDimension(width, 'width', type, maximum);
  assertDimension(height, 'height', type, maximum);
  return { width, height };
}

function boundedDefaultSize(sourceWidth: number, sourceHeight: number, maximum: number): { width: number; height: number } {
  const scale = Math.min(1, maximum / sourceWidth, maximum / sourceHeight);
  return { width: even(sourceWidth * scale), height: even(sourceHeight * scale) };
}

function frameParameters(
  request: Extract<TimelinePreviewRequest, { type: 'frame' }>,
  duration: number,
  sourceWidth: number,
  sourceHeight: number,
): RenderPostprocess {
  const at = request.at ?? 0;
  if (!Number.isFinite(at) || at < 0 || at >= duration) {
    throw previewError('PREVIEW_TIME_INVALID', 'Frame time must be within [0, timeline duration)', 'frame', { at, duration });
  }
  const size = dimensions(request, sourceWidth, sourceHeight, sourceWidth, sourceHeight, 'frame', 4096);
  return { type: 'frame', at, ...size };
}

function validateGrid(columns: number, rows: number): void {
  if (!Number.isSafeInteger(columns) || columns < 1 || columns > 20
    || !Number.isSafeInteger(rows) || rows < 1 || rows > 20
    || columns * rows > MAX_CELLS) {
    throw previewError(
      'PREVIEW_SHEET_LAYOUT_INVALID',
      `Sheet layout must contain 1 to ${MAX_CELLS} cells with at most 20 rows and columns`,
      'sheet',
      { columns, rows, maximumCells: MAX_CELLS },
    );
  }
}

function sheetParameters(
  request: Extract<TimelinePreviewRequest, { type: 'sheet' }>,
  duration: number,
  sourceWidth: number,
  sourceHeight: number,
): SheetPostprocess {
  const start = request.start ?? 0;
  const end = request.end ?? duration;
  if (!Number.isFinite(start) || !Number.isFinite(end) || start < 0 || end <= start || start >= duration || end > duration + EPSILON) {
    throw previewError('PREVIEW_RANGE_INVALID', 'Sheet range must be non-empty and within the timeline duration', 'sheet', { start, end, duration });
  }
  const boundedEnd = Math.min(end, duration);
  const columns = request.columns ?? 4;
  if (!Number.isSafeInteger(columns) || columns < 1 || columns > 20) validateGrid(columns, request.rows ?? 1);
  if (request.rows !== undefined) validateGrid(columns, request.rows);
  const defaultSize = boundedDefaultSize(sourceWidth, sourceHeight, 320);
  const size = dimensions(request, sourceWidth, sourceHeight, defaultSize.width, defaultSize.height, 'sheet', 2048);
  let interval = request.interval;
  let rows = request.rows;
  let sampleTimes: number[];
  if (interval === undefined) {
    rows ??= 3;
    validateGrid(columns, rows);
    const count = columns * rows;
    interval = (boundedEnd - start) / count;
    sampleTimes = Array.from({ length: count }, (_, index) => start + index * interval!);
  } else {
    if (!Number.isFinite(interval) || interval <= 0 || interval > 3600) {
      throw previewError('PREVIEW_INTERVAL_INVALID', 'Sheet interval must be greater than 0 and at most 3600 seconds', 'sheet', { interval });
    }
    sampleTimes = [];
    for (let index = 0; ; index += 1) {
      const at = start + index * interval;
      if (at >= boundedEnd - EPSILON) break;
      if (index >= MAX_CELLS) {
        throw previewError('PREVIEW_SHEET_DENSITY_INVALID', `Sheet interval produces more than ${MAX_CELLS} samples`, 'sheet', { start, end: boundedEnd, interval, maximumCells: MAX_CELLS });
      }
      sampleTimes.push(at);
    }
    rows ??= Math.ceil(sampleTimes.length / columns);
    validateGrid(columns, rows);
    if (sampleTimes.length > columns * rows) {
      throw previewError('PREVIEW_SHEET_DENSITY_INVALID', 'Sheet interval produces more samples than the requested grid can contain', 'sheet', {
        start, end: boundedEnd, interval, columns, rows, sampleCount: sampleTimes.length,
      });
    }
  }
  if (sampleTimes.length === 0) {
    throw previewError('PREVIEW_SHEET_EMPTY', 'Sheet sampling configuration produces no frames', 'sheet', { start, end: boundedEnd, interval });
  }
  sampleTimes = sampleTimes.map((value) => Number(value.toFixed(9)));
  return {
    type: 'sheet', start, end: boundedEnd, interval, columns, rows, ...size, sampleTimes,
  };
}

function proxyParameters(
  request: Extract<TimelinePreviewRequest, { type: 'proxy' }>,
  sourceWidth: number,
  sourceHeight: number,
): RenderPostprocess {
  const defaultSize = boundedDefaultSize(sourceWidth, sourceHeight, 640);
  const size = dimensions(request, sourceWidth, sourceHeight, defaultSize.width, defaultSize.height, 'proxy', 1920);
  if (request.crf !== undefined && (!Number.isSafeInteger(request.crf) || request.crf < 0 || request.crf > 51)) {
    throw previewError('PREVIEW_PROXY_ENCODING_INVALID', 'Proxy CRF must be an integer from 0 to 51', 'proxy', { crf: request.crf });
  }
  if (request.videoBitrateKbps !== undefined && (!Number.isSafeInteger(request.videoBitrateKbps) || request.videoBitrateKbps < 32 || request.videoBitrateKbps > 10_000)) {
    throw previewError('PREVIEW_PROXY_ENCODING_INVALID', 'Proxy video bitrate must be an integer from 32 to 10000 kbit/s', 'proxy', { videoBitrateKbps: request.videoBitrateKbps });
  }
  if (request.audioBitrateKbps !== undefined && (!Number.isSafeInteger(request.audioBitrateKbps) || request.audioBitrateKbps < 32 || request.audioBitrateKbps > 320)) {
    throw previewError('PREVIEW_PROXY_ENCODING_INVALID', 'Proxy audio bitrate must be an integer from 32 to 320 kbit/s', 'proxy', { audioBitrateKbps: request.audioBitrateKbps });
  }
  if (request.crf !== undefined && request.videoBitrateKbps !== undefined) {
    throw previewError('PREVIEW_PROXY_ENCODING_INVALID', 'Proxy CRF and video bitrate are mutually exclusive', 'proxy', { crf: request.crf, videoBitrateKbps: request.videoBitrateKbps });
  }
  return {
    type: 'proxy',
    ...size,
    ...(request.videoBitrateKbps === undefined ? { crf: request.crf ?? 30 } : { videoBitrateKbps: request.videoBitrateKbps }),
    audioBitrateKbps: request.audioBitrateKbps ?? 96,
  };
}

function defaultOutput(
  directory: string,
  revision: number,
  parameters: RenderPostprocess,
): string {
  if (parameters.type === 'frame') return join(directory, '.codecut', 'previews', `frame-r${revision}-t${parameters.at.toFixed(3)}.png`);
  if (parameters.type === 'sheet') return join(directory, '.codecut', 'previews', `sheet-r${revision}.png`);
  return join(directory, '.codecut', 'previews', `proxy-r${revision}.mp4`);
}

export async function previewProject(
  projectPath: string,
  request: TimelinePreviewRequest,
  options: PreviewOptions = {},
  service?: JobService,
): Promise<PreviewResult> {
  const prepared = await loadRenderProject(projectPath, options.revision);
  const sources = await prepareSources(prepared, options.ffprobePath);
  const timeline = calculateTimeline(prepared.project);
  if (timeline.duration <= EPSILON) {
    throw new CodeCutError('TIMELINE_EMPTY', 'Cannot preview an empty timeline; add at least one clip with positive duration', ExitCode.ProjectValidation, {
      stage: `preview.${request.type}.plan`, retryable: false,
    });
  }
  let parameters: RenderPostprocess;
  if (request.type === 'frame') parameters = frameParameters(request, timeline.duration, prepared.project.output.width, prepared.project.output.height);
  else if (request.type === 'sheet') parameters = sheetParameters(request, timeline.duration, prepared.project.output.width, prepared.project.output.height);
  else parameters = proxyParameters(request, prepared.project.output.width, prepared.project.output.height);
  const outputPath = resolve(prepared.projectDirectory, request.output ?? defaultOutput(prepared.projectDirectory, prepared.project.revision, parameters));
  const plan = compileRenderPlan(prepared.project, {
    projectDirectory: prepared.projectDirectory,
    sources,
    outputPath,
    overwrite: request.force ?? false,
    postprocess: parameters,
    ...(options.ffmpegPath === undefined ? {} : { ffmpegPath: options.ffmpegPath }),
  });
  const preview: PreviewDescription = { type: request.type, outputPath, parameters };
  const base = {
    ...(prepared.revisionId === undefined ? {} : { revisionId: prepared.revisionId }),
    plan,
    preview,
  };
  if (options.dryRun) return { ...base, dryRun: true };

  const snapshot = await fixedSnapshot(prepared, sources);
  const jobs = service ?? new JobService({ projectDirectory: prepared.projectDirectory });
  const job = await jobs.create({
    kind: `preview.${request.type}`,
    projectPath: prepared.projectFile,
    projectRevision: prepared.project.revision,
    process: {
      command: plan.command,
      args: plan.args,
      cwd: prepared.projectDirectory,
      progress: 'ffmpeg',
      durationSeconds: request.type === 'frame' ? (parameters as Extract<RenderPostprocess, { type: 'frame' }>).at : plan.durationSeconds,
    },
    output: {
      path: plan.output.path,
      overwrite: plan.output.overwrite,
      validation: 'ffprobe',
      ...(options.ffprobePath === undefined ? {} : { ffprobePath: options.ffprobePath }),
    },
    render: {
      plan,
      ...(options.ffprobePath === undefined ? {} : { ffprobePath: options.ffprobePath }),
      ...(options.ffmpegPath === undefined ? {} : { ffmpegPath: options.ffmpegPath }),
    },
    preview: { type: request.type, parameters },
    result: {
      data: {
        type: request.type,
        outputPath,
        revision: prepared.project.revision,
        parameters: parameters as unknown as Record<string, unknown>,
      },
    },
    ...(options.timeoutMs === undefined ? {} : { timeoutMs: options.timeoutMs }),
  }, snapshot);
  const started = await jobs.start(job.id, { detach: options.detach ?? false });
  return { ...base, dryRun: false, job: started };
}
