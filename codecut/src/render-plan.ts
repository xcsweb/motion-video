import { resolve } from 'node:path';
import { CodeCutError, ExitCode } from './errors.js';
import { calculateTimeline, validateProjectData } from './project.js';
import type {
  Asset,
  AssetFingerprint,
  Clip,
  Effect,
  FlashEffect,
  Project,
  ShakeEffect,
  TextClip,
  Track,
} from './schema.js';

export interface RenderSource {
  asset: Asset;
  absolutePath: string;
  fingerprint: AssetFingerprint;
  hasVideo: boolean;
  hasAudio: boolean;
}

export interface RenderInput {
  index: number;
  assetId: string;
  kind: Asset['kind'];
  path: string;
  fingerprint: AssetFingerprint;
  hasVideo: boolean;
  hasAudio: boolean;
  clips: string[];
}

export interface RenderTextFile {
  clipId: string;
  path: string;
  content: string;
}

export interface RenderMediaSettings {
  durationSeconds: number;
  width: number;
  height: number;
  frameRate: number;
  pixelFormat: 'yuv420p';
  videoCodec: 'h264';
  audioCodec: 'aac';
  audioSampleRate: 48000;
  audioChannels: 2;
}

export interface FramePostprocess {
  type: 'frame';
  at: number;
  width: number;
  height: number;
}

export interface SheetPostprocess {
  type: 'sheet';
  start: number;
  end: number;
  interval: number;
  columns: number;
  rows: number;
  width: number;
  height: number;
  sampleTimes: number[];
}

export interface ProxyPostprocess {
  type: 'proxy';
  width: number;
  height: number;
  crf?: number;
  videoBitrateKbps?: number;
  audioBitrateKbps: number;
}

export type RenderPostprocess = FramePostprocess | SheetPostprocess | ProxyPostprocess;

export interface RenderPlan {
  version: 1;
  revision: number;
  command: string;
  durationSeconds: number;
  inputs: RenderInput[];
  args: string[];
  filter_graph: string;
  output: {
    path: string;
    temporaryPath: string;
    format: 'mp4' | 'png';
    overwrite: boolean;
  };
  media: RenderMediaSettings;
  warnings: string[];
  textFiles: RenderTextFile[];
  preview?: RenderPostprocess;
}

export interface CompileRenderPlanOptions {
  projectDirectory: string;
  sources: ReadonlyMap<string, RenderSource>;
  outputPath?: string;
  overwrite?: boolean;
  ffmpegPath?: string;
  postprocess?: RenderPostprocess;
}

interface VisualContext {
  clip: Clip;
  inputLabel?: string;
  generator?: string;
}

const EPSILON = 1e-9;

function number(value: number): string {
  if (!Number.isFinite(value)) throw new TypeError(`Non-finite render number: ${value}`);
  return Number(value.toFixed(9)).toString();
}

function planError(
  code: string,
  message: string,
  options: { path?: string; diagnostics?: unknown; exitCode?: ExitCode } = {},
): CodeCutError {
  return new CodeCutError(code, message, options.exitCode ?? ExitCode.ProjectValidation, {
    stage: 'render.plan',
    ...(options.path === undefined ? {} : { path: options.path }),
    ...(options.diagnostics === undefined ? {} : { diagnostics: options.diagnostics }),
    retryable: false,
  });
}

function escapeFilterValue(value: string): string {
  return value.replace(/\\/g, '\\\\')
    .replace(/'/g, "\\'")
    .replace(/:/g, '\\:')
    .replace(/,/g, '\\,')
    .replace(/\[/g, '\\[')
    .replace(/\]/g, '\\]')
    .replace(/;/g, '\\;');
}

function ffmpegColor(value: string): string {
  return `0x${value.slice(1)}`;
}

function atempoFilters(speed: number): string[] {
  if (Math.abs(speed - 1) <= EPSILON) return [];
  const filters: string[] = [];
  let remaining = speed;
  while (remaining > 2 + EPSILON) {
    filters.push('atempo=2');
    remaining /= 2;
  }
  while (remaining < 0.5 - EPSILON) {
    filters.push('atempo=0.5');
    remaining /= 0.5;
  }
  filters.push(`atempo=${number(remaining)}`);
  return filters;
}

function sourceRange(clip: Clip): { start: number; end: number; speed: number } {
  const start = clip.sourceStart ?? 0;
  const speed = clip.speed ?? 1;
  return { start, end: start + clip.duration * speed, speed };
}

function assertSourceRange(clip: Clip, source: RenderSource): void {
  if (clip.type !== 'video' && clip.type !== 'audio') return;
  const range = sourceRange(clip);
  const duration = source.asset.metadata?.duration ?? 0;
  if (duration > 0 && range.end > duration + Math.max(0.05, 1 / (source.asset.metadata?.streams.find((stream) => stream.codecType === 'video')?.frameRate ?? 30))) {
    throw planError('CLIP_SOURCE_RANGE_INVALID', `Clip "${clip.id}" reads past the end of asset "${source.asset.id}"`, {
      path: source.absolutePath,
      diagnostics: {
        clipId: clip.id,
        assetId: source.asset.id,
        sourceStart: range.start,
        sourceEnd: range.end,
        sourceDuration: duration,
        speed: range.speed,
      },
    });
  }
}

function assertCrop(clip: Clip, source: RenderSource | undefined): void {
  if (!clip.crop || !source) return;
  const video = source.asset.metadata?.streams.find((stream) => stream.codecType === 'video');
  if (!video?.width || !video.height) return;
  const { x, y, width, height } = clip.crop;
  if (x + width > video.width + EPSILON || y + height > video.height + EPSILON) {
    throw planError('CLIP_CROP_INVALID', `Crop for clip "${clip.id}" exceeds source dimensions`, {
      path: source.absolutePath,
      diagnostics: { clipId: clip.id, assetId: source.asset.id, crop: clip.crop, sourceWidth: video.width, sourceHeight: video.height },
    });
  }
}

class FilterGraph {
  readonly lines: string[] = [];
  private sequence = 0;

  label(prefix: string): string {
    const label = `[cc_${prefix}_${this.sequence}]`;
    this.sequence += 1;
    return label;
  }

  add(inputs: string[], filters: string[], output: string): string {
    if (filters.length === 0) throw new TypeError('A filter chain must contain at least one filter');
    this.lines.push(`${inputs.join('')}${filters.join(',')}${output}`);
    return output;
  }

  addSplit(inputs: string[], filters: string[], outputs: string[]): string[] {
    if (filters.length === 0) throw new TypeError('A filter chain must contain at least one filter');
    if (outputs.length === 0) throw new TypeError('A split filter chain must expose at least one output');
    this.lines.push(`${inputs.join('')}${filters.join(',')}${outputs.join('')}`);
    return outputs;
  }
}

function gradeFilters(clip: Clip): string[] {
  const grade = 'grade' in clip ? clip.grade : undefined;
  if (!grade) return [];
  const filters: string[] = [];
  const eq: string[] = [];
  if ((grade.contrast ?? 1) !== 1) eq.push(`contrast=${number(grade.contrast ?? 1)}`);
  if ((grade.saturation ?? 1) !== 1) eq.push(`saturation=${number(grade.saturation ?? 1)}`);
  if ((grade.brightness ?? 0) !== 0) eq.push(`brightness=${number(grade.brightness ?? 0)}`);
  if (eq.length > 0) filters.push(`eq=${eq.join(':')}`);
  const warmth = grade.warmth ?? 0;
  if (warmth !== 0) {
    filters.push(`colorbalance=rm=${number(warmth * 0.15)}:gm=${number(warmth * 0.05)}:bm=${number(-warmth * 0.15)}`);
  }
  return filters;
}

function transformFilters(clip: Clip, width: number, height: number): string[] {
  const filters: string[] = [];
  if (clip.crop) {
    const { x, y, width: cropWidth, height: cropHeight } = clip.crop;
    filters.push(`crop=w=${number(cropWidth)}:h=${number(cropHeight)}:x=${number(x)}:y=${number(y)}`);
  }
  filters.push(...gradeFilters(clip));
  filters.push('format=rgba');
  filters.push(`scale=w=${width}:h=${height}:force_original_aspect_ratio=decrease`);
  const scale = clip.scale ?? 1;
  if (Math.abs(scale - 1) > EPSILON) {
    filters.push(`scale=w=max(2\\,trunc(iw*${number(scale)}/2)*2):h=max(2\\,trunc(ih*${number(scale)}/2)*2):eval=frame`);
  }
  if ((clip.opacity ?? 1) < 1) filters.push(`colorchannelmixer=aa=${number(clip.opacity ?? 1)}`);
  return filters;
}

function clipEffects(clip: Clip): Effect[] {
  return 'effects' in clip && clip.effects ? clip.effects : [];
}

function shakeFilters(effect: ShakeEffect): string[] {
  const amplitude = effect.amplitude ?? 20;
  if (amplitude <= EPSILON) return [];
  const frequency = effect.frequency ?? 8;
  const base = number(amplitude);
  const span = number(amplitude * 2);
  const step = `floor(t*${number(frequency)})`;
  return [
    `crop=w=iw-${span}:h=ih-${span}:x='${base}+${base}*sin(${step}*12.9898)':y='${base}+${base}*sin(${step}*78.233+1.7)'`,
    `scale=w=iw+${span}:h=ih+${span}:flags=bicubic`,
  ];
}

function flashFilter(effect: FlashEffect): string {
  const start = effect.at;
  const end = start + (effect.duration ?? 0.12);
  return `eq=brightness='if(between(t,${number(start)},${number(end)}),${number(effect.strength ?? 0.55)},0)':eval=frame`;
}

function effectFilters(clip: Clip): string[] {
  const filters: string[] = [];
  for (const effect of clipEffects(clip)) {
    if (effect.type === 'shake') filters.push(...shakeFilters(effect));
    else filters.push(flashFilter(effect));
  }
  return filters;
}

function quotedFilterValue(value: string): string {
  return escapeFilterValue(value).replace(/ /g, '\\ ');
}

function textFilter(clip: TextClip, textPath: string, projectDirectory: string): string {
  const align = clip.align ?? 'center';
  const position = clip.position;
  const offsetX = position === undefined ? 0 : position.x;
  const baseX = align === 'left' ? '0' : align === 'right' ? 'w-text_w' : '(w-text_w)/2';
  const x = offsetX === 0 ? baseX : `${baseX}+${number(offsetX)}`;
  const y = position === undefined ? '(h-text_h)/2' : number(position.y);
  const options = [
    `textfile=${quotedFilterValue(textPath)}`,
    'expansion=none',
    `fontsize=${number(clip.fontSize ?? 48)}`,
    `fontcolor=${ffmpegColor(clip.color ?? '#FFFFFF')}`,
    `x=${x}`,
    `y=${y}`,
    'fix_bounds=1',
  ];
  const borderWidth = clip.borderWidth ?? 0;
  if (borderWidth > 0) {
    options.push(`borderw=${number(borderWidth)}`);
    options.push(`bordercolor=${ffmpegColor(clip.borderColor ?? '#000000')}`);
  }
  if (clip.fontFile) options.push(`fontfile=${quotedFilterValue(resolve(projectDirectory, clip.fontFile))}`);
  else options.push(`font=${quotedFilterValue(clip.fontFamily ?? 'sans')}`);
  return `drawtext=${options.join(':')}`;
}

function addTransparent(
  graph: FilterGraph,
  duration: number,
  width: number,
  height: number,
  frameRate: number,
): string {
  const output = graph.label('transparent');
  return graph.add([], [
    `color=c=black@0.0:s=${width}x${height}:r=${number(frameRate)}:d=${number(duration)}`,
    'format=rgba',
    'setpts=PTS-STARTPTS',
  ], output);
}

function addVisualClip(
  graph: FilterGraph,
  context: VisualContext,
  project: Project,
  projectDirectory: string,
  textPath: string | undefined,
): string {
  const { clip } = context;
  const { width, height, frameRate } = project.output;
  const filters: string[] = [];
  const inputs: string[] = [];
  if (context.inputLabel) {
    inputs.push(context.inputLabel);
    if (clip.type === 'video') {
      const range = sourceRange(clip);
      filters.push(`trim=start=${number(range.start)}:end=${number(range.end)}`);
      filters.push(`setpts=(PTS-STARTPTS)/${number(range.speed)}`);
    } else {
      filters.push(`trim=duration=${number(clip.duration)}`, 'setpts=PTS-STARTPTS');
    }
  } else if (context.generator) {
    filters.push(context.generator, 'setpts=PTS-STARTPTS');
    if (clip.type === 'text' && textPath) filters.push(textFilter(clip, textPath, projectDirectory));
  } else {
    throw new TypeError(`Visual clip ${clip.id} has no source`);
  }
  filters.push(`fps=${number(frameRate)}`);
  filters.push(...transformFilters(clip, width, height));
  filters.push(...effectFilters(clip));
  filters.push(`trim=duration=${number(clip.duration)}`, 'setpts=PTS-STARTPTS');
  const transformed = graph.label('clip');
  graph.add(inputs, filters, transformed);

  const canvas = addTransparent(graph, clip.duration, width, height, frameRate);
  const positioned = graph.label('positioned');
  // Text placement is already baked into drawtext, so overlay it at the canvas origin.
  const position = clip.type === 'text' ? { x: 0, y: 0 } : clip.position ?? { x: 0, y: 0 };
  graph.add([canvas, transformed], [
    `overlay=x=${number(position.x)}:y=${number(position.y)}:shortest=1:format=auto`,
    `trim=duration=${number(clip.duration)}`,
    'setpts=PTS-STARTPTS',
  ], positioned);
  return positioned;
}

function concatVisual(graph: FilterGraph, left: string, right: string): string {
  const output = graph.label('concat');
  return graph.add([left, right], ['concat=n=2:v=1:a=0', 'setpts=PTS-STARTPTS'], output);
}

function compileVideoTrack(
  graph: FilterGraph,
  track: Extract<Track, { kind: 'video' }>,
  project: Project,
  projectDirectory: string,
  inputForClip: (clip: Clip) => string,
  textPathForClip: (clip: TextClip) => string,
): string | undefined {
  const clips = track.hidden ? [] : [...track.clips].sort((left, right) => left.start - right.start);
  if (clips.length === 0) return undefined;
  let currentEnd = 0;
  let current: string | undefined;
  for (const clip of clips) {
    let context: VisualContext;
    if (clip.type === 'video') context = { clip, inputLabel: inputForClip(clip) };
    else if (clip.type === 'image') {
      context = { clip, inputLabel: inputForClip(clip) };
    } else if (clip.type === 'color') {
      context = {
        clip,
        generator: `color=c=${ffmpegColor(clip.color)}:s=${project.output.width}x${project.output.height}:r=${number(project.output.frameRate)}:d=${number(clip.duration)}`,
      };
    } else context = { clip, generator: `color=c=black@0.0:s=${project.output.width}x${project.output.height}:r=${number(project.output.frameRate)}:d=${number(clip.duration)}` };

    let next = addVisualClip(graph, context, project, projectDirectory, clip.type === 'text' ? textPathForClip(clip) : undefined);
    if (!current) {
      if (clip.start > EPSILON) {
        const gap = addTransparent(graph, clip.start, project.output.width, project.output.height, project.output.frameRate);
        next = concatVisual(graph, gap, next);
      }
      current = next;
      currentEnd = clip.start + clip.duration;
      continue;
    }

    if (clip.start > currentEnd + EPSILON) {
      const gap = addTransparent(graph, clip.start - currentEnd, project.output.width, project.output.height, project.output.frameRate);
      current = concatVisual(graph, current, gap);
      currentEnd = clip.start;
    }
    if (clip.transition?.type === 'xfade') {
      const output = graph.label('xfade');
      const overlap = currentEnd - clip.start;
      if (Math.abs(overlap - clip.transition.duration) > EPSILON) {
        throw planError('TRANSITION_OVERLAP_INVALID', `Transition on clip "${clip.id}" does not match its timeline overlap`, {
          diagnostics: { clipId: clip.id, overlap, transitionDuration: clip.transition.duration },
        });
      }
      const left = graph.add([current], ['settb=AVTB', 'setpts=PTS-STARTPTS'], graph.label('xfade_left'));
      const right = graph.add([next], ['settb=AVTB', 'setpts=PTS-STARTPTS'], graph.label('xfade_right'));
      current = graph.add([left, right], [
        `xfade=transition=${escapeFilterValue(clip.transition.name ?? 'fade')}:duration=${number(clip.transition.duration)}:offset=${number(clip.start)}`,
        `fps=${number(project.output.frameRate)}`,
        'setpts=PTS-STARTPTS',
      ], output);
    } else {
      current = concatVisual(graph, current, next);
    }
    currentEnd = clip.start + clip.duration;
  }
  return current;
}

function volumePointExpression(points: ReadonlyArray<{ at: number; volume: number }>): string {
  const sorted = [...points].sort((left, right) => left.at - right.at);
  const first = sorted[0]!;
  let expression = number(sorted[sorted.length - 1]!.volume);
  for (let index = sorted.length - 1; index > 0; index -= 1) {
    const previous = sorted[index - 1]!;
    const current = sorted[index]!;
    const span = current.at - previous.at;
    const ramp = span <= EPSILON
      ? number(current.volume)
      : `${number(previous.volume)}+${number(current.volume - previous.volume)}*(t-${number(previous.at)})/${number(span)}`;
    expression = `if(lt(t,${number(current.at)}),${ramp},${expression})`;
  }
  return `if(lt(t,${number(first.at)}),${number(first.volume)},${expression})`;
}

function loudnessFilters(loudness: Project['output']['loudness']): string[] {
  if (!loudness) return [];
  return [
    `loudnorm=I=${number(loudness.target)}:TP=${number(loudness.truePeak ?? -1.5)}:LRA=${number(loudness.range ?? 11)}`,
    'aresample=48000',
  ];
}

function audioClipFilters(clip: Clip): string[] {
  const range = sourceRange(clip);
  const filters = [
    `atrim=start=${number(range.start)}:end=${number(range.end)}`,
    'asetpts=PTS-STARTPTS',
    'aresample=48000',
    'aformat=sample_fmts=fltp:channel_layouts=stereo',
    ...atempoFilters(range.speed),
    'asetpts=PTS-STARTPTS',
  ];
  const volumePoints = 'volumePoints' in clip ? clip.volumePoints : undefined;
  if (volumePoints && volumePoints.length > 0) {
    filters.push(`volume=eval=frame:volume='${volumePointExpression(volumePoints)}'`);
  } else if ((clip.volume ?? 1) !== 1) {
    filters.push(`volume=${number(clip.volume ?? 1)}`);
  }
  if ((clip.fadeIn ?? 0) > 0) filters.push(`afade=t=in:st=0:d=${number(clip.fadeIn ?? 0)}`);
  if ((clip.fadeOut ?? 0) > 0) filters.push(`afade=t=out:st=${number(clip.duration - (clip.fadeOut ?? 0))}:d=${number(clip.fadeOut ?? 0)}`);
  filters.push(
    `apad=pad_dur=${number(clip.duration)}`,
    `atrim=duration=${number(clip.duration)}`,
    `adelay=delays=${number(clip.start * 1000)}:all=1`,
    'asetpts=PTS-STARTPTS',
  );
  return filters;
}

const SFX_MAX_DURATION = 3;
const SFX_NEAR_MISS_WINDOW = 0.25;
const SFX_TOLERANCE_FRAMES = 2;

function roundTime(value: number): number {
  return Number(value.toFixed(6));
}

function audioSyncWarnings(project: Project): string[] {
  const cuts: number[] = [];
  for (const track of project.tracks) {
    if (track.kind !== 'video' || track.hidden) continue;
    for (const clip of track.clips) {
      cuts.push(roundTime(clip.start), roundTime(clip.start + clip.duration));
    }
  }
  if (cuts.length === 0) return [];
  const tolerance = SFX_TOLERANCE_FRAMES / project.output.frameRate;
  const warnings: string[] = [];
  for (const track of project.tracks) {
    if (track.kind !== 'audio' || track.muted) continue;
    for (const clip of track.clips) {
      if (clip.type !== 'audio' || clip.duration > SFX_MAX_DURATION) continue;
      const start = roundTime(clip.start);
      const nearest = cuts.reduce((best, cut) => Math.min(best, Math.abs(cut - start)), Number.POSITIVE_INFINITY);
      if (nearest > tolerance && nearest <= SFX_NEAR_MISS_WINDOW) {
        warnings.push(
          `Audio clip "${clip.id}" starts ${(nearest * 1000).toFixed(0)}ms after the nearest visual cut; `
          + `short sound effects are usually placed within ${SFX_TOLERANCE_FRAMES} frames of a cut.`,
        );
      }
    }
  }
  return warnings;
}

function fitFilters(width: number, height: number, pixelFormat: string): string[] {
  return [
    `scale=w=${width}:h=${height}:force_original_aspect_ratio=decrease`,
    `pad=${width}:${height}:(ow-iw)/2:(oh-ih)/2:color=black`,
    `format=${pixelFormat}`,
  ];
}

function appendPostprocess(
  graph: FilterGraph,
  postprocess: RenderPostprocess,
  duration: number,
): void {
  if (postprocess.type !== 'proxy') graph.add(['[aout]'], ['anullsink'], '');
  if (postprocess.type === 'frame') {
    graph.add(['[vout]'], [
      `trim=start=${number(postprocess.at)}:end=${number(duration)}`,
      'setpts=PTS-STARTPTS',
      ...fitFilters(postprocess.width, postprocess.height, 'rgb24'),
    ], '[preview_vout]');
    return;
  }
  if (postprocess.type === 'sheet') {
    const sampleCount = postprocess.sampleTimes.length;
    const timecodeFontSize = Math.max(8, Math.min(18, Math.floor((postprocess.width - 4) / 7)));
    graph.add(['[vout]'], [
      `trim=start=${number(postprocess.start)}:end=${number(postprocess.end)}`,
      'setpts=PTS-STARTPTS',
      `fps=fps=${number(1 / postprocess.interval)}:start_time=0:round=near`,
      ...fitFilters(postprocess.width, postprocess.height, 'rgb24'),
      `setpts=PTS+${number(postprocess.start)}/TB`,
      `drawtext=text='%{pts\\:hms}':fontcolor=white:fontsize=${timecodeFontSize}:box=1:boxcolor=black@0.65:boxborderw=1:x=2:y=4`,
      `tile=${postprocess.columns}x${postprocess.rows}:nb_frames=${sampleCount}:margin=8:padding=4:color=0x202020`,
    ], '[preview_vout]');
    return;
  }
  graph.add(['[vout]'], [
    ...fitFilters(postprocess.width, postprocess.height, 'yuv420p'),
    `trim=duration=${number(duration)}`,
    'setpts=PTS-STARTPTS',
  ], '[preview_vout]');
}

function appendOutputArguments(
  args: string[],
  postprocess: RenderPostprocess | undefined,
  project: Project,
  duration: number,
): void {
  if (postprocess?.type === 'frame' || postprocess?.type === 'sheet') {
    args.push(
      '-filter_complex_script', '{jobDirectory}/diagnostics/filter_complex.txt',
      '-map', '[preview_vout]',
      '-an',
      '-frames:v', '1',
      '-c:v', 'png',
      '-update', '1',
      '-f', 'image2',
      '-y',
      '{output}',
    );
    return;
  }
  const proxy = postprocess?.type === 'proxy' ? postprocess : undefined;
  args.push(
    '-filter_complex_script', '{jobDirectory}/diagnostics/filter_complex.txt',
    '-map', proxy ? '[preview_vout]' : '[vout]',
    '-map', '[aout]',
    '-c:v', 'libx264',
    '-preset', 'veryfast',
  );
  if (proxy?.videoBitrateKbps !== undefined) args.push('-b:v', `${proxy.videoBitrateKbps}k`);
  else args.push('-crf', String(proxy?.crf ?? 18));
  args.push(
    '-pix_fmt', project.output.pixelFormat,
    '-r', number(project.output.frameRate),
    '-video_track_timescale', '90000',
    '-c:a', 'aac',
    '-b:a', `${proxy?.audioBitrateKbps ?? 192}k`,
    '-ar', '48000',
    '-ac', '2',
    '-movflags', '+faststart',
    '-t', number(duration),
    '-f', 'mp4',
    '-y',
    '{output}',
  );
}

export function compileRenderPlan(projectInput: Project, options: CompileRenderPlanOptions): RenderPlan {
  const project = validateProjectData(projectInput, { stage: 'render.plan' });
  const timeline = calculateTimeline(project);
  if (timeline.duration <= EPSILON) {
    throw planError('TIMELINE_EMPTY', 'Cannot render an empty timeline; add at least one clip with positive duration');
  }

  const references = new Map<string, string[]>();
  for (const track of project.tracks) {
    for (const clip of track.clips) {
      if (clip.type !== 'video' && clip.type !== 'audio' && clip.type !== 'image') continue;
      const ids = references.get(clip.assetId) ?? [];
      ids.push(clip.id);
      references.set(clip.assetId, ids);
    }
  }

  const inputIndex = new Map<string, number>();
  const inputs: RenderInput[] = [];
  const args = ['-hide_banner', '-nostdin', '-progress', 'pipe:1', '-nostats'];
  for (const [assetId, clips] of references) {
    const source = options.sources.get(assetId);
    if (!source) throw planError('RENDER_SOURCE_METADATA_REQUIRED', `No verified source metadata is available for asset "${assetId}"`, { diagnostics: { assetId, clips } });
    const index = inputs.length;
    inputIndex.set(assetId, index);
    inputs.push({
      index,
      assetId,
      kind: source.asset.kind,
      path: source.absolutePath,
      fingerprint: { ...source.fingerprint },
      hasVideo: source.hasVideo,
      hasAudio: source.hasAudio,
      clips,
    });
    if (source.asset.kind === 'image') args.push('-loop', '1', '-framerate', number(project.output.frameRate));
    args.push('-i', source.absolutePath);
  }

  const graph = new FilterGraph();
  const textFiles: RenderTextFile[] = [];
  const textPaths = new Map<string, string>();
  for (const track of project.tracks) {
    for (const clip of track.clips) {
      if (clip.type !== 'text') continue;
      const path = `{jobDirectory}/diagnostics/text-${textFiles.length}.txt`;
      textPaths.set(clip.id, path);
      textFiles.push({ clipId: clip.id, path, content: clip.text });
    }
  }

  const inputForClip = (clip: Clip, stream: 'v' | 'a'): string => {
    if (clip.type !== 'video' && clip.type !== 'audio' && clip.type !== 'image') throw new TypeError(`Clip ${clip.id} has no asset input`);
    const index = inputIndex.get(clip.assetId);
    if (index === undefined) throw new TypeError(`Clip ${clip.id} has no assigned input`);
    const source = options.sources.get(clip.assetId)!;
    if (stream === 'v' && !source.hasVideo) {
      throw planError('ASSET_HAS_NO_VIDEO', `Asset "${clip.assetId}" has no usable video stream`, { path: source.absolutePath, exitCode: ExitCode.Media });
    }
    if (stream === 'a' && !source.hasAudio) {
      throw planError('ASSET_HAS_NO_AUDIO', `Asset "${clip.assetId}" has no usable audio stream for clip "${clip.id}"`, {
        path: source.absolutePath,
        diagnostics: { assetId: clip.assetId, clipId: clip.id },
        exitCode: ExitCode.Media,
      });
    }
    if (clip.type !== 'image') assertSourceRange(clip, source);
    assertCrop(clip, source);
    return `[${index}:${stream}:0]`;
  };

  const videoTracks: string[] = [];
  for (const track of project.tracks) {
    if (track.kind !== 'video') continue;
    const compiled = compileVideoTrack(
      graph,
      track,
      project,
      options.projectDirectory,
      (clip) => inputForClip(clip, 'v'),
      (clip) => textPaths.get(clip.id)!,
    );
    if (compiled) videoTracks.push(compiled);
  }

  let video = graph.label('black');
  graph.add([], [
    `color=c=black:s=${project.output.width}x${project.output.height}:r=${number(project.output.frameRate)}:d=${number(timeline.duration)}`,
    'format=rgba',
    'setpts=PTS-STARTPTS',
  ], video);
  for (const track of videoTracks) {
    const output = graph.label('composite');
    video = graph.add([video, track], [
      'overlay=x=0:y=0:eof_action=pass:repeatlast=0:format=auto',
      'setpts=PTS-STARTPTS',
    ], output);
  }
  graph.add([video], [
    `fps=${number(project.output.frameRate)}`,
    `trim=duration=${number(timeline.duration)}`,
    'format=yuv420p',
    'setpts=PTS-STARTPTS',
  ], '[vout]');

  const warnings: string[] = [];
  const trackAudio = new Map<string, string>();
  for (const track of project.tracks) {
    if (track.muted) continue;
    const streams: string[] = [];
    for (const clip of track.clips) {
      if (track.kind === 'audio' && clip.type === 'audio') {
        const input = inputForClip(clip, 'a');
        const output = graph.label('audio');
        graph.add([input], audioClipFilters(clip), output);
        streams.push(output);
      } else if (track.kind === 'video' && clip.type === 'video') {
        const source = options.sources.get(clip.assetId)!;
        if (!source.hasAudio) continue;
        const input = inputForClip(clip, 'a');
        const output = graph.label('source_audio');
        graph.add([input], audioClipFilters(clip), output);
        streams.push(output);
      }
    }
    if (streams.length === 0) continue;
    const mixed = graph.label('track_mix');
    graph.add(streams, [
      ...(streams.length > 1 ? [`amix=inputs=${streams.length}:duration=longest:dropout_transition=0:normalize=0`] : []),
      'aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo',
      `apad=whole_dur=${number(timeline.duration)}`,
      `atrim=duration=${number(timeline.duration)}`,
      'asetpts=PTS-STARTPTS',
    ], mixed);
    trackAudio.set(track.id, mixed);
  }

  const duckingUsers = new Map<string, string[]>();
  for (const track of project.tracks) {
    if (!track.ducking || !trackAudio.has(track.id)) continue;
    const users = duckingUsers.get(track.ducking.by) ?? [];
    users.push(track.id);
    duckingUsers.set(track.ducking.by, users);
  }
  const keyStreams = new Map<string, string[]>();
  for (const [keyId, users] of duckingUsers) {
    const key = trackAudio.get(keyId);
    if (!key) {
      warnings.push(`Track(s) ${users.map((id) => `"${id}"`).join(', ')} duck under "${keyId}", but that track has no audible clips.`);
      continue;
    }
    const outputs = graph.addSplit(
      [key],
      [`asplit=${users.length + 1}`],
      Array.from({ length: users.length + 1 }, () => graph.label('duck_key')),
    );
    trackAudio.set(keyId, outputs[0]!);
    keyStreams.set(keyId, outputs.slice(1));
  }
  for (const track of project.tracks) {
    const ducking = track.ducking;
    if (!ducking) continue;
    const main = trackAudio.get(track.id);
    const key = keyStreams.get(ducking.by)?.shift();
    if (!main || !key) continue;
    const ducked = graph.label('ducked');
    graph.add([main, key], [
      `sidechaincompress=threshold=${number(ducking.threshold ?? 0.05)}:ratio=${number(ducking.ratio ?? 8)}:attack=${number(ducking.attack ?? 20)}:release=${number(ducking.release ?? 400)}:makeup=${number(ducking.makeup ?? 1)}`,
      'aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo',
      `atrim=duration=${number(timeline.duration)}`,
      'asetpts=PTS-STARTPTS',
    ], ducked);
    trackAudio.set(track.id, ducked);
  }

  const audioStreams = [...trackAudio.values()];
  const silence = graph.label('silence');
  graph.add([], [`anullsrc=r=48000:cl=stereo:d=${number(timeline.duration)}`], silence);
  if (audioStreams.length === 0) {
    graph.add([silence], [
      'aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo',
      `atrim=duration=${number(timeline.duration)}`,
      'asetpts=PTS-STARTPTS',
    ], '[aout]');
  } else {
    graph.add([silence, ...audioStreams], [
      `amix=inputs=${audioStreams.length + 1}:duration=longest:dropout_transition=0:normalize=0`,
      ...loudnessFilters(project.output.loudness),
      'aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo',
      `atrim=duration=${number(timeline.duration)}`,
      'asetpts=PTS-STARTPTS',
    ], '[aout]');
  }

  const outputPath = resolve(options.projectDirectory, options.outputPath ?? project.output.path);
  const overwrite = options.overwrite ?? false;
  if (options.postprocess) appendPostprocess(graph, options.postprocess, timeline.duration);
  appendOutputArguments(args, options.postprocess, project, timeline.duration);
  if (videoTracks.length === 0) warnings.push('No visible video clips; rendering a black video for the full timeline.');
  if (audioStreams.length === 0) warnings.push('No audible source clips; rendering stereo silence for the full timeline.');
  warnings.push(...audioSyncWarnings(project));
  for (const track of project.tracks) {
    for (const clip of track.clips) {
      if ((clip.type === 'image' || clip.type === 'color' || clip.type === 'text') && ((clip.sourceStart ?? 0) !== 0 || (clip.speed ?? 1) !== 1)) {
        warnings.push(`Clip "${clip.id}" is generated/static; sourceStart and speed have no visual effect.`);
      }
    }
  }
  return {
    version: 1,
    revision: project.revision,
    command: options.ffmpegPath ?? 'ffmpeg',
    durationSeconds: timeline.duration,
    inputs,
    args,
    filter_graph: `${graph.lines.join(';\n')}\n`,
    output: {
      path: outputPath,
      temporaryPath: '{output}',
      format: options.postprocess?.type === 'frame' || options.postprocess?.type === 'sheet' ? 'png' : 'mp4',
      overwrite,
    },
    media: {
      durationSeconds: timeline.duration,
      width: options.postprocess?.type === 'proxy' ? options.postprocess.width : project.output.width,
      height: options.postprocess?.type === 'proxy' ? options.postprocess.height : project.output.height,
      frameRate: project.output.frameRate,
      pixelFormat: 'yuv420p',
      videoCodec: 'h264',
      audioCodec: 'aac',
      audioSampleRate: 48000,
      audioChannels: 2,
    },
    warnings,
    textFiles,
    ...(options.postprocess === undefined ? {} : { preview: structuredClone(options.postprocess) }),
  };
}
