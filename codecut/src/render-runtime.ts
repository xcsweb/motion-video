import { execa } from 'execa';
import { stat } from 'node:fs/promises';
import { CodeCutError, ExitCode } from './errors.js';
import type { RenderPlan } from './render-plan.js';

interface ProbeStream {
  index?: number;
  codec_type?: string;
  codec_name?: string;
  width?: number;
  height?: number;
  pix_fmt?: string;
  avg_frame_rate?: string;
  r_frame_rate?: string;
  sample_rate?: string;
  channels?: number;
  duration?: string;
  nb_read_frames?: string;
}

interface ProbeDocument {
  streams?: ProbeStream[];
  format?: { duration?: string; format_name?: string; size?: string };
}

export interface RenderValidationOptions {
  jobId: string;
  ffprobePath?: string;
  ffmpegPath?: string;
}

function validationError(message: string, path: string, options: RenderValidationOptions, diagnostics?: unknown): CodeCutError {
  return new CodeCutError('OUTPUT_VALIDATION_FAILED', message, ExitCode.Media, {
    stage: 'output.validate', jobId: options.jobId, path, retryable: false,
    ...(diagnostics === undefined ? {} : { diagnostics }),
  });
}

function numeric(value: string | undefined): number | undefined {
  if (value === undefined || value === '' || value === 'N/A') return undefined;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : undefined;
}

function frameRate(stream: ProbeStream): number | undefined {
  for (const value of [stream.avg_frame_rate, stream.r_frame_rate]) {
    if (!value) continue;
    const [numerator, denominator] = value.split('/').map(Number);
    if (numerator !== undefined && denominator !== undefined && Number.isFinite(numerator) && Number.isFinite(denominator) && denominator > 0) {
      return numerator / denominator;
    }
    const parsed = Number(value);
    if (Number.isFinite(parsed)) return parsed;
  }
  return undefined;
}

function assertClose(actual: number | undefined, expected: number, tolerance: number, label: string, path: string, options: RenderValidationOptions): void {
  if (actual === undefined || Math.abs(actual - expected) > tolerance) {
    throw validationError(`Rendered ${label} does not match the render plan`, path, options, { actual, expected, tolerance });
  }
}

export async function validateRenderOutput(
  path: string,
  plan: RenderPlan,
  options: RenderValidationOptions,
): Promise<Record<string, unknown>> {
  const information = await stat(path).catch((cause: unknown) => {
    throw validationError('Render did not produce a readable output file', path, options, { cause: String(cause) });
  });
  if (!information.isFile() || information.size === 0) {
    throw validationError('Render output is empty or is not a regular file', path, options);
  }

  const probe = await execa(options.ffprobePath ?? 'ffprobe', [
    '-v', 'error', '-show_streams', '-show_format', '-of', 'json', path,
  ], { reject: false, timeout: 30_000, maxBuffer: 8 * 1024 * 1024 });
  if (probe.failed) {
    throw validationError('ffprobe could not validate the rendered MP4', path, options, {
      exitCode: probe.exitCode, stderr: probe.stderr, timedOut: probe.timedOut,
    });
  }
  let document: ProbeDocument;
  try {
    document = JSON.parse(probe.stdout) as ProbeDocument;
  } catch (cause) {
    throw validationError('ffprobe returned invalid JSON for the rendered MP4', path, options, {
      cause: String(cause), stdoutTail: probe.stdout.slice(-4096),
    });
  }
  const video = document.streams?.find((stream) => stream.codec_type === 'video');
  const audio = document.streams?.find((stream) => stream.codec_type === 'audio');
  if (!video || !audio) throw validationError('Rendered MP4 must contain video and audio streams', path, options, { streams: document.streams });
  const problems: string[] = [];
  if (video.codec_name !== plan.media.videoCodec) problems.push(`video codec ${video.codec_name ?? 'unknown'}`);
  if (audio.codec_name !== plan.media.audioCodec) problems.push(`audio codec ${audio.codec_name ?? 'unknown'}`);
  if (video.width !== plan.media.width || video.height !== plan.media.height) problems.push(`dimensions ${video.width ?? 0}x${video.height ?? 0}`);
  if (video.pix_fmt !== plan.media.pixelFormat) problems.push(`pixel format ${video.pix_fmt ?? 'unknown'}`);
  if (numeric(audio.sample_rate) !== plan.media.audioSampleRate) problems.push(`sample rate ${audio.sample_rate ?? 'unknown'}`);
  if (audio.channels !== plan.media.audioChannels) problems.push(`audio channels ${audio.channels ?? 'unknown'}`);
  if (!document.format?.format_name?.split(',').some((name) => ['mp4', 'mov'].includes(name))) problems.push(`container ${document.format?.format_name ?? 'unknown'}`);
  if (problems.length > 0) {
    throw validationError(`Rendered media settings are invalid: ${problems.join(', ')}`, path, options, {
      expected: plan.media, video, audio, format: document.format,
    });
  }
  assertClose(frameRate(video), plan.media.frameRate, 0.001, 'frame rate', path, options);
  const tolerance = 1 / plan.media.frameRate;
  assertClose(numeric(document.format?.duration), plan.durationSeconds, tolerance, 'container duration', path, options);
  if (video.duration !== undefined) assertClose(numeric(video.duration), plan.durationSeconds, tolerance, 'video duration', path, options);
  if (audio.duration !== undefined) assertClose(numeric(audio.duration), plan.durationSeconds, tolerance, 'audio duration', path, options);

  const decode = await execa(options.ffmpegPath ?? plan.command ?? 'ffmpeg', [
    '-hide_banner', '-nostdin', '-v', 'error', '-xerror', '-i', path,
    '-map', '0:v:0', '-map', '0:a:0', '-f', 'null', '-',
  ], { reject: false, timeout: 120_000, maxBuffer: 1024 * 1024 });
  if (decode.failed) {
    throw new CodeCutError('OUTPUT_VALIDATION_FAILED', 'Rendered MP4 did not pass a complete audio/video decode', ExitCode.Media, {
      stage: 'output.decode', jobId: options.jobId, path, retryable: false,
      diagnostics: { exitCode: decode.exitCode, stderr: decode.stderr, timedOut: decode.timedOut },
    });
  }
  return {
    type: 'render',
    size: information.size,
    durationSeconds: numeric(document.format?.duration),
    video,
    audio,
    format: document.format,
    completeDecode: true,
  };
}

export async function validateTimelinePreviewOutput(
  path: string,
  plan: RenderPlan,
  options: RenderValidationOptions,
): Promise<Record<string, unknown>> {
  const preview = plan.preview;
  if (!preview) throw new TypeError('Timeline preview validation requires preview parameters');
  if (preview.type === 'proxy') {
    const validation = await validateRenderOutput(path, plan, options);
    return {
      ...validation,
      type: 'preview.proxy',
      parameters: preview,
      completeAudio: true,
    };
  }

  const information = await stat(path).catch((cause: unknown) => {
    throw validationError('Preview did not produce a readable output file', path, options, { cause: String(cause) });
  });
  if (!information.isFile() || information.size === 0) {
    throw validationError('Preview output is empty or is not a regular file', path, options);
  }
  const probe = await execa(options.ffprobePath ?? 'ffprobe', [
    '-v', 'error', '-count_frames', '-show_streams', '-show_format', '-of', 'json', path,
  ], { reject: false, timeout: 30_000, maxBuffer: 8 * 1024 * 1024 });
  if (probe.failed) {
    throw validationError('ffprobe could not validate the preview PNG', path, options, {
      exitCode: probe.exitCode, stderr: probe.stderr, timedOut: probe.timedOut,
    });
  }
  let document: ProbeDocument;
  try {
    document = JSON.parse(probe.stdout) as ProbeDocument;
  } catch (cause) {
    throw validationError('ffprobe returned invalid JSON for the preview PNG', path, options, {
      cause: String(cause), stdoutTail: probe.stdout.slice(-4096),
    });
  }
  const video = document.streams?.find((stream) => stream.codec_type === 'video');
  if (!video || video.codec_name !== 'png') {
    throw validationError('Preview output must contain a PNG video stream', path, options, { streams: document.streams });
  }
  const expectedWidth = preview.type === 'sheet' ? preview.columns * preview.width + (preview.columns - 1) * 4 + 16 : preview.width;
  const expectedHeight = preview.type === 'sheet' ? preview.rows * preview.height + (preview.rows - 1) * 4 + 16 : preview.height;
  if (video.width !== expectedWidth || video.height !== expectedHeight) {
    throw validationError('Preview PNG dimensions do not match its sampling plan', path, options, {
      actual: { width: video.width, height: video.height }, expected: { width: expectedWidth, height: expectedHeight }, parameters: preview,
    });
  }
  if (video.nb_read_frames !== undefined && Number(video.nb_read_frames) !== 1) {
    throw validationError('Preview PNG must contain exactly one composited image', path, options, { frames: video.nb_read_frames });
  }
  const decode = await execa(options.ffmpegPath ?? plan.command ?? 'ffmpeg', [
    '-hide_banner', '-nostdin', '-v', 'error', '-xerror', '-i', path,
    '-map', '0:v:0', '-frames:v', '1', '-f', 'null', '-',
  ], { reject: false, timeout: 30_000, maxBuffer: 1024 * 1024 });
  if (decode.failed) {
    throw new CodeCutError('OUTPUT_VALIDATION_FAILED', 'Preview PNG did not pass decoding validation', ExitCode.Media, {
      stage: 'output.decode', jobId: options.jobId, path, retryable: false,
      diagnostics: { exitCode: decode.exitCode, stderr: decode.stderr, timedOut: decode.timedOut },
    });
  }
  return {
    type: `preview.${preview.type}`,
    size: information.size,
    width: video.width,
    height: video.height,
    video,
    format: document.format,
    completeDecode: true,
    parameters: preview,
    ...(preview.type === 'sheet' ? {
      sampleCount: preview.sampleTimes.length,
      sampleTimes: preview.sampleTimes,
      timecodeBase: 'timeline',
    } : { timelineTimeSeconds: preview.at }),
  };
}
