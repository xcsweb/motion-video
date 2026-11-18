import { randomBytes } from 'node:crypto';
import { createRequire } from 'node:module';
import {
  link,
  mkdir,
  open,
  readFile,
  rename,
  unlink,
} from 'node:fs/promises';
import type { FileHandle } from 'node:fs/promises';
import { basename, dirname, isAbsolute, join, posix, resolve, win32 } from 'node:path';
import type { ErrorObject } from 'ajv/dist/2020.js';
import { CodeCutError, ExitCode } from './errors.js';
import {
  ProjectSchema,
  type Asset,
  type Clip,
  type Project,
  type Track,
} from './schema.js';

const require = createRequire(import.meta.url);
const Ajv2020 = require('ajv/dist/2020.js') as typeof import('ajv/dist/2020.js').default;
const addFormats = require('ajv-formats') as typeof import('ajv-formats').default;
const ajv = new Ajv2020({ allErrors: true, strict: true });
addFormats(ajv);
const validateProjectShape = ajv.compile(ProjectSchema);
const EPSILON = 1e-9;

export interface ValidationIssue {
  path: string;
  message: string;
  keyword?: string;
}

export interface ProjectContext {
  project: Project;
  path: string;
}

export interface TimelineClip {
  id: string;
  type: Clip['type'];
  start: number;
  end: number;
  sourceStart: number;
  sourceEnd: number;
}

export interface TimelineTrack {
  id: string;
  kind: Track['kind'];
  duration: number;
  clipCount: number;
  clips: TimelineClip[];
}

export interface Timeline {
  duration: number;
  tracks: TimelineTrack[];
}

interface ValidationOptions {
  stage?: string;
  path?: string;
}

function pointerPart(value: string): string {
  return value.replaceAll('~', '~0').replaceAll('/', '~1');
}

function appendPointer(path: string, part: string): string {
  return `${path === '/' ? '' : path}/${pointerPart(part)}`;
}

function issuePath(error: ErrorObject): string {
  const base = error.instancePath || '/';
  if (error.keyword === 'required' && typeof error.params.missingProperty === 'string') {
    return appendPointer(base, error.params.missingProperty);
  }
  if (error.keyword === 'additionalProperties' && typeof error.params.additionalProperty === 'string') {
    return appendPointer(base, error.params.additionalProperty);
  }
  return base;
}

function shapeIssues(errors: ErrorObject[] | null | undefined): ValidationIssue[] {
  return (errors ?? []).map((error) => ({
    path: issuePath(error),
    message: error.message ?? 'is invalid',
    keyword: error.keyword,
  }));
}

function validationError(
  issues: ValidationIssue[],
  options: ValidationOptions,
  code = 'PROJECT_VALIDATION_ERROR',
): CodeCutError {
  return new CodeCutError(
    code,
    issues.length === 1 ? `Project validation failed: ${issues[0]?.message}` : `Project validation failed with ${issues.length} errors`,
    ExitCode.ProjectValidation,
    {
      stage: options.stage ?? 'project.validate',
      ...(options.path === undefined ? {} : { path: options.path }),
      diagnostics: { issues },
      retryable: false,
    },
  );
}

function isRelativeProjectPath(value: string): boolean {
  return value.length > 0
    && !value.includes('\0')
    && !isAbsolute(value)
    && !posix.isAbsolute(value)
    && !win32.isAbsolute(value)
    && !/^[A-Za-z]:/.test(value);
}

function duplicateIssues(values: string[], path: string, label: string): ValidationIssue[] {
  const seen = new Set<string>();
  const issues: ValidationIssue[] = [];
  values.forEach((value, index) => {
    if (seen.has(value)) {
      issues.push({ path: `${path}/${index}/id`, message: `duplicate ${label} id "${value}"`, keyword: 'unique' });
    }
    seen.add(value);
  });
  return issues;
}

function validateTrackTiming(track: Track, trackIndex: number): ValidationIssue[] {
  const issues: ValidationIssue[] = [];
  const ordered = track.clips.map((clip, index) => ({
    clip,
    index,
    end: clip.start + clip.duration,
  })).sort((left, right) => left.clip.start - right.clip.start || left.index - right.index);

  let furthestEnd = 0;
  let furthestClip: (typeof ordered)[number] | undefined;
  for (const current of ordered) {
    if (furthestClip && current.clip.start + EPSILON < furthestEnd) {
      const overlap = furthestEnd - current.clip.start;
      const transition = current.clip.transition;
      const validXfade = transition?.type === 'xfade'
        && Math.abs(overlap - transition.duration) <= EPSILON
        && current.end > furthestEnd;
      if (!validXfade) {
        issues.push({
          path: `/tracks/${trackIndex}/clips/${current.index}/start`,
          message: `clip "${current.clip.id}" overlaps clip "${furthestClip.clip.id}" without a matching xfade`,
          keyword: 'timeline',
        });
      }
    }
    if (current.end > furthestEnd) {
      furthestEnd = current.end;
      furthestClip = current;
    }
  }
  return issues;
}

function semanticIssues(project: Project): ValidationIssue[] {
  const issues: ValidationIssue[] = [];
  issues.push(...duplicateIssues(project.assets.map((asset) => asset.id), '/assets', 'asset'));
  issues.push(...duplicateIssues(project.tracks.map((track) => track.id), '/tracks', 'track'));
  const clipIds = new Set<string>();
  for (const [trackIndex, track] of project.tracks.entries()) {
    for (const [clipIndex, clip] of track.clips.entries()) {
      if (clipIds.has(clip.id)) {
        issues.push({
          path: `/tracks/${trackIndex}/clips/${clipIndex}/id`,
          message: `duplicate clip id "${clip.id}"`,
          keyword: 'unique',
        });
      }
      clipIds.add(clip.id);
    }
  }

  if (!project.tracks.some((track) => track.kind === 'video')) {
    issues.push({ path: '/tracks', message: 'at least one video track is required', keyword: 'trackKinds' });
  }
  if (!project.tracks.some((track) => track.kind === 'audio')) {
    issues.push({ path: '/tracks', message: 'at least one audio track is required', keyword: 'trackKinds' });
  }

  const assets = new Map<string, Asset>();
  for (const [index, asset] of project.assets.entries()) {
    if (!assets.has(asset.id)) assets.set(asset.id, asset);
    if (!isRelativeProjectPath(asset.path)) {
      issues.push({ path: `/assets/${index}/path`, message: 'asset path must be relative to the project directory', keyword: 'relativePath' });
    }
  }
  if (!isRelativeProjectPath(project.output.path)) {
    issues.push({ path: '/output/path', message: 'output path must be relative to the project directory', keyword: 'relativePath' });
  }

  for (const [trackIndex, track] of project.tracks.entries()) {
    for (const [clipIndex, clip] of track.clips.entries()) {
      const basePath = `/tracks/${trackIndex}/clips/${clipIndex}`;
      if ((clip.fadeIn ?? 0) > clip.duration || (clip.fadeOut ?? 0) > clip.duration) {
        issues.push({ path: basePath, message: 'fade duration cannot exceed clip duration', keyword: 'fadeDuration' });
      }
      if (clip.type === 'text' && clip.fontFile !== undefined && !isRelativeProjectPath(clip.fontFile)) {
        issues.push({ path: `${basePath}/fontFile`, message: 'font path must be relative to the project directory', keyword: 'relativePath' });
      }
      if (clip.type === 'color' || clip.type === 'text') continue;

      const asset = assets.get(clip.assetId);
      if (!asset) {
        issues.push({ path: `${basePath}/assetId`, message: `asset "${clip.assetId}" does not exist in the asset table`, keyword: 'assetReference' });
        continue;
      }
      const compatible = clip.type === 'image'
        ? asset.kind === 'image'
        : clip.type === 'video'
          ? asset.kind === 'video'
          : asset.kind === 'audio' || asset.kind === 'video';
      if (!compatible) {
        issues.push({
          path: `${basePath}/assetId`,
          message: `${clip.type} clip cannot use ${asset.kind} asset "${asset.id}"`,
          keyword: 'assetKind',
        });
      }
    }
    issues.push(...validateTrackTiming(track, trackIndex));
  }
  return issues;
}

export function validateProjectData(data: unknown, options: ValidationOptions = {}): Project {
  if (typeof data === 'object' && data !== null && 'schemaVersion' in data) {
    const version = (data as { schemaVersion?: unknown }).schemaVersion;
    if (version !== 1) {
      throw validationError([{
        path: '/schemaVersion',
        message: `unsupported project schema version ${JSON.stringify(version)}; supported version is 1`,
        keyword: 'const',
      }], options, 'PROJECT_VERSION_UNSUPPORTED');
    }
  }

  if (!validateProjectShape(data)) {
    throw validationError(shapeIssues(validateProjectShape.errors), options);
  }
  const project = data as Project;
  const issues = semanticIssues(project);
  if (issues.length > 0) throw validationError(issues, options);
  return project;
}

export function resolveProjectFile(input = '.'): string {
  const resolved = resolve(input);
  return basename(resolved) === 'project.json' ? resolved : join(resolved, 'project.json');
}

export function createDefaultProject(projectDirectory: string, name?: string): Project {
  return {
    schemaVersion: 1,
    revision: 0,
    name: name ?? (basename(projectDirectory) || 'codecut-project'),
    assets: [],
    tracks: [
      { id: 'v1', kind: 'video', name: 'Video 1', clips: [] },
      { id: 'v2', kind: 'video', name: 'Video 2', clips: [] },
      { id: 'a1', kind: 'audio', name: 'Audio 1', clips: [] },
      { id: 'a2', kind: 'audio', name: 'Audio 2', clips: [] },
    ],
    output: {
      path: 'output.mp4',
      format: 'mp4',
      videoCodec: 'h264',
      audioCodec: 'aac',
      width: 1920,
      height: 1080,
      frameRate: 30,
      pixelFormat: 'yuv420p',
      audioSampleRate: 48000,
      audioChannels: 2,
    },
  };
}

export async function writeJsonAtomic(
  filePath: string,
  value: unknown,
  options: { force?: boolean; stage?: string } = {},
): Promise<void> {
  const stage = options.stage ?? 'project.write';
  let serialized: string;
  try {
    const json = JSON.stringify(value, null, 2);
    if (json === undefined) throw new TypeError('Value is not JSON-serializable');
    serialized = `${json}\n`;
  } catch (cause) {
    throw new CodeCutError('PROJECT_WRITE_FAILED', 'Could not serialize project JSON', ExitCode.ProjectValidation, {
      stage,
      path: filePath,
      cause,
      retryable: false,
    });
  }

  const temporaryPath = join(
    dirname(filePath),
    `.${basename(filePath)}.${process.pid}.${randomBytes(6).toString('hex')}.tmp`,
  );
  let handle: FileHandle | undefined;
  try {
    handle = await open(temporaryPath, 'wx');
    await handle.writeFile(serialized, 'utf8');
    await handle.sync();
    await handle.close();
    handle = undefined;

    if (options.force) {
      await rename(temporaryPath, filePath);
    } else {
      try {
        await link(temporaryPath, filePath);
      } catch (cause) {
        if ((cause as NodeJS.ErrnoException).code === 'EEXIST') {
          throw new CodeCutError('PROJECT_EXISTS', 'Project already exists; pass --force to replace it', ExitCode.Usage, {
            stage,
            path: filePath,
            cause,
            retryable: false,
          });
        }
        throw cause;
      }
    }
  } catch (cause) {
    if (cause instanceof CodeCutError) throw cause;
    throw new CodeCutError('PROJECT_WRITE_FAILED', 'Could not atomically write project JSON', ExitCode.ProjectValidation, {
      stage,
      path: filePath,
      cause,
      retryable: true,
    });
  } finally {
    if (handle) await handle.close().catch(() => undefined);
    await unlink(temporaryPath).catch(() => undefined);
  }
}

export async function initProject(
  input = '.',
  options: { force?: boolean; name?: string } = {},
): Promise<ProjectContext> {
  const path = resolveProjectFile(input);
  const projectDirectory = dirname(path);
  try {
    await mkdir(projectDirectory, { recursive: true });
  } catch (cause) {
    throw new CodeCutError('PROJECT_WRITE_FAILED', 'Could not create project directory', ExitCode.ProjectValidation, {
      stage: 'project.init',
      path: projectDirectory,
      cause,
      retryable: true,
    });
  }
  const project = createDefaultProject(projectDirectory, options.name);
  validateProjectData(project, { stage: 'project.init', path });
  await writeJsonAtomic(path, project, {
    ...(options.force === undefined ? {} : { force: options.force }),
    stage: 'project.init',
  });
  return { project, path };
}

export async function loadProject(input = '.', stage = 'project.show'): Promise<ProjectContext> {
  const path = resolveProjectFile(input);
  let source: string;
  try {
    source = await readFile(path, 'utf8');
  } catch (cause) {
    const missing = (cause as NodeJS.ErrnoException).code === 'ENOENT';
    throw new CodeCutError(
      missing ? 'PROJECT_NOT_FOUND' : 'PROJECT_READ_FAILED',
      missing ? 'Project file does not exist' : 'Could not read project file',
      ExitCode.ProjectValidation,
      { stage, path, cause, retryable: !missing },
    );
  }

  let data: unknown;
  try {
    data = JSON.parse(source);
  } catch (cause) {
    throw new CodeCutError('PROJECT_PARSE_ERROR', 'Project file is not valid JSON', ExitCode.ProjectValidation, {
      stage,
      path,
      cause,
      retryable: false,
    });
  }
  const project = validateProjectData(data, { stage, path });
  return { project, path };
}

export function calculateTimeline(project: Project): Timeline {
  let duration = 0;
  const tracks = project.tracks.map((track): TimelineTrack => {
    let trackDuration = 0;
    const clips = track.clips.map((clip): TimelineClip => {
      const end = clip.start + clip.duration;
      const sourceStart = clip.sourceStart ?? 0;
      const sourceEnd = sourceStart + clip.duration * (clip.speed ?? 1);
      trackDuration = Math.max(trackDuration, end);
      return {
        id: clip.id,
        type: clip.type,
        start: clip.start,
        end,
        sourceStart,
        sourceEnd,
      };
    });
    duration = Math.max(duration, trackDuration);
    return {
      id: track.id,
      kind: track.kind,
      duration: trackDuration,
      clipCount: clips.length,
      clips,
    };
  });
  return { duration, tracks };
}
