import { createRequire } from 'node:module';
import { readFile } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { CodeCutError, ExitCode } from './errors.js';
import {
  commitProjectTransaction,
  type ProjectTransactionResult,
} from './history.js';
import { resolveProjectFile, validateProjectData } from './project.js';
import {
  EditOperationSchema,
  type Clip,
  type EditOperation,
  type Project,
  type TextClip,
  type Track,
} from './schema.js';

const require = createRequire(import.meta.url);
const Ajv2020 = require('ajv/dist/2020.js') as typeof import('ajv/dist/2020.js').default;
const addFormats = require('ajv-formats') as typeof import('ajv-formats').default;
const ajv = new Ajv2020({ allErrors: true, strict: true });
addFormats(ajv);
const validateOperationShape = ajv.compile(EditOperationSchema);
const EPSILON = 1e-9;

export interface ApplyOperationsOptions {
  projectPath?: string;
}

export interface ApplyEditOptions {
  dryRun?: boolean;
  summary?: string;
}

export interface SrtCue {
  index: number;
  start: number;
  end: number;
  text: string;
}

export type EditResult = ProjectTransactionResult;

function editError(
  code: string,
  message: string,
  options: { path?: string; cause?: unknown; diagnostics?: unknown; retryable?: boolean } = {},
): CodeCutError {
  return new CodeCutError(code, message, ExitCode.ProjectValidation, {
    stage: 'edit.apply',
    ...(options.path === undefined ? {} : { path: options.path }),
    ...(options.cause === undefined ? {} : { cause: options.cause }),
    ...(options.diagnostics === undefined ? {} : { diagnostics: options.diagnostics }),
    retryable: options.retryable ?? false,
  });
}

function withOperationIndex(error: unknown, operationIndex: number): CodeCutError {
  if (error instanceof CodeCutError && error.operationIndex === operationIndex) return error;
  if (error instanceof CodeCutError) {
    return new CodeCutError(error.code, error.message, error.exitCode, {
      stage: error.stage,
      ...(error.path === undefined ? {} : { path: error.path }),
      operationIndex,
      ...(error.retryable === undefined ? {} : { retryable: error.retryable }),
      ...(error.diagnostics === undefined ? {} : { diagnostics: error.diagnostics }),
      cause: error,
    });
  }
  return new CodeCutError(
    'EDIT_OPERATION_FAILED',
    error instanceof Error ? error.message : String(error),
    ExitCode.ProjectValidation,
    { stage: 'edit.apply', operationIndex, cause: error, retryable: false },
  );
}

function assertOperationShape(operation: EditOperation): void {
  if (validateOperationShape(operation)) return;
  const issues = (validateOperationShape.errors ?? []).map((issue) => ({
    path: issue.instancePath || '/',
    message: issue.message ?? 'is invalid',
    keyword: issue.keyword,
  }));
  throw editError('EDIT_OPERATION_INVALID', 'Edit operation does not match the operation schema', {
    diagnostics: { issues },
  });
}

function findTrack(project: Project, trackId: string): Track {
  const track = project.tracks.find((candidate) => candidate.id === trackId);
  if (!track) throw editError('TRACK_NOT_FOUND', `Track "${trackId}" does not exist`);
  return track;
}

function findClip(project: Project, clipId: string): { track: Track; index: number; clip: Clip } {
  for (const track of project.tracks) {
    const index = track.clips.findIndex((candidate) => candidate.id === clipId);
    if (index >= 0) {
      const clip = track.clips[index];
      if (clip) return { track, index, clip };
    }
  }
  throw editError('CLIP_NOT_FOUND', `Clip "${clipId}" does not exist`);
}

function assertTrackCompatibility(track: Track, clip: Clip): void {
  const compatible = track.kind === 'audio' ? clip.type === 'audio' : clip.type !== 'audio';
  if (!compatible) {
    throw editError(
      'TRACK_TYPE_MISMATCH',
      `${clip.type} clip "${clip.id}" cannot be placed on ${track.kind} track "${track.id}"`,
    );
  }
}

function insertClip(track: Track, clip: Clip): void {
  assertTrackCompatibility(track, clip);
  const clips = track.clips as Clip[];
  const index = clips.findIndex((candidate) => candidate.start > clip.start);
  if (index < 0) clips.push(clip);
  else clips.splice(index, 0, clip);
}

function allClipIds(project: Project): Set<string> {
  return new Set(project.tracks.flatMap((track) => track.clips.map((clip) => clip.id)));
}

function uniqueId(ids: Set<string>, preferred: string): string {
  if (!ids.has(preferred)) return preferred;
  let suffix = 2;
  while (ids.has(`${preferred}-${suffix}`)) suffix += 1;
  return `${preferred}-${suffix}`;
}

function decodeEntity(entity: string): string {
  const named: Record<string, string> = {
    amp: '&',
    lt: '<',
    gt: '>',
    quot: '"',
    apos: "'",
    nbsp: ' ',
  };
  const lower = entity.toLowerCase();
  if (named[lower] !== undefined) return named[lower];
  const match = /^#(?:x([0-9a-f]+)|([0-9]+))$/i.exec(entity);
  if (!match) return `&${entity};`;
  const value = Number.parseInt(match[1] ?? match[2] ?? '', match[1] ? 16 : 10);
  if (!Number.isSafeInteger(value) || value < 0 || value > 0x10ffff || (value >= 0xd800 && value <= 0xdfff)) {
    return `&${entity};`;
  }
  return String.fromCodePoint(value);
}

export function decodeSrtText(value: string): string {
  return value
    .replace(/<br\s*\/?\s*>/gi, '\n')
    .replace(/<\/?(?:i|b|u|s|font)(?:\s+[^>]*)?>/gi, '')
    .replace(/\{\\[^}]*\}/g, '')
    .replace(/&(#(?:x[0-9a-f]+|[0-9]+)|[a-z]+);/gi, (match, entity: string) => {
      const decoded = decodeEntity(entity);
      return decoded === `&${entity};` ? match : decoded;
    });
}

function parseTimestamp(value: string): number | undefined {
  const match = /^(\d{2,}):([0-5]\d):([0-5]\d)[,.](\d{1,3})$/.exec(value);
  if (!match) return undefined;
  const hours = Number(match[1]);
  const minutes = Number(match[2]);
  const seconds = Number(match[3]);
  const milliseconds = Number((match[4] ?? '').padEnd(3, '0'));
  const result = hours * 3600 + minutes * 60 + seconds + milliseconds / 1000;
  return Number.isSafeInteger(hours) && Number.isFinite(result) ? result : undefined;
}

function srtParseError(message: string, block: number): CodeCutError {
  return editError('SRT_PARSE_ERROR', `${message} (subtitle block ${block + 1})`, {
    diagnostics: { block: block + 1 },
  });
}

export function parseSrt(source: string): SrtCue[] {
  const normalized = source.replace(/^\uFEFF/, '').replace(/\r\n?/g, '\n').trim();
  if (!normalized) return [];
  const blocks = normalized.split(/\n[\t ]*\n/);
  const cues: SrtCue[] = [];

  for (const [blockIndex, block] of blocks.entries()) {
    const lines = block.split('\n');
    if (/^\d+$/.test(lines[0]?.trim() ?? '')) lines.shift();
    const timing = lines.shift()?.trim();
    if (!timing) throw srtParseError('Missing subtitle timing line', blockIndex);
    const match = /^(\S+)\s+-->\s+(\S+)(?:\s+.*)?$/.exec(timing);
    const start = match?.[1] ? parseTimestamp(match[1]) : undefined;
    const end = match?.[2] ? parseTimestamp(match[2]) : undefined;
    if (start === undefined || end === undefined) {
      throw srtParseError(`Invalid SRT timecode "${timing}"`, blockIndex);
    }
    if (end <= start) throw srtParseError('Subtitle end time must be after its start time', blockIndex);
    const text = decodeSrtText(lines.join('\n')).trim();
    if (!text) throw srtParseError('Subtitle text must not be empty', blockIndex);
    cues.push({ index: blockIndex + 1, start, end, text });
  }
  return cues;
}

async function importSrt(project: Project, track: Track, operation: Extract<EditOperation, { type: 'importSrt' }>, projectFile: string): Promise<void> {
  if (track.kind !== 'video') {
    throw editError('TRACK_TYPE_MISMATCH', `SRT subtitles require a video track, not audio track "${track.id}"`);
  }
  const path = resolve(dirname(projectFile), operation.path);
  let source: string;
  try {
    source = await readFile(path, 'utf8');
  } catch (cause) {
    throw editError('SRT_READ_FAILED', 'Could not read SRT subtitle file', {
      path,
      cause,
      retryable: true,
    });
  }

  let cues: SrtCue[];
  try {
    cues = parseSrt(source);
  } catch (cause) {
    if (cause instanceof CodeCutError) {
      throw new CodeCutError(cause.code, cause.message, cause.exitCode, {
        stage: cause.stage,
        path,
        diagnostics: cause.diagnostics,
        retryable: false,
        cause,
      });
    }
    throw cause;
  }

  const ids = allClipIds(project);
  let sequence = 1;
  for (const cue of cues) {
    while (ids.has(`srt-${sequence}`)) sequence += 1;
    const id = `srt-${sequence}`;
    sequence += 1;
    ids.add(id);
    const clip: TextClip = {
      id,
      type: 'text',
      start: cue.start,
      duration: cue.end - cue.start,
      text: cue.text,
      align: 'center',
    };
    insertClip(track, clip);
  }
}

async function applyOperationInPlace(
  project: Project,
  operation: EditOperation,
  projectFile: string,
): Promise<void> {
  switch (operation.type) {
    case 'addTrack': {
      if (project.tracks.some((track) => track.id === operation.track.id)) {
        throw editError('TRACK_EXISTS', `Track "${operation.track.id}" already exists`);
      }
      project.tracks.push(structuredClone(operation.track));
      return;
    }
    case 'removeTrack': {
      const index = project.tracks.findIndex((track) => track.id === operation.trackId);
      if (index < 0) throw editError('TRACK_NOT_FOUND', `Track "${operation.trackId}" does not exist`);
      project.tracks.splice(index, 1);
      return;
    }
    case 'addClip':
    case 'addText': {
      const track = findTrack(project, operation.trackId);
      insertClip(track, structuredClone(operation.clip));
      return;
    }
    case 'trimClip': {
      const { clip } = findClip(project, operation.clipId);
      if (operation.sourceStart !== undefined) clip.sourceStart = operation.sourceStart;
      if (operation.duration !== undefined) clip.duration = operation.duration;
      return;
    }
    case 'moveClip': {
      const source = findClip(project, operation.clipId);
      const target = operation.targetTrackId ? findTrack(project, operation.targetTrackId) : source.track;
      assertTrackCompatibility(target, source.clip);
      source.track.clips.splice(source.index, 1);
      const moved = structuredClone(source.clip);
      moved.start = operation.start;
      insertClip(target, moved);
      return;
    }
    case 'splitClip': {
      const { track, index, clip } = findClip(project, operation.clipId);
      const end = clip.start + clip.duration;
      if (operation.at <= clip.start + EPSILON || operation.at >= end - EPSILON) {
        throw editError('SPLIT_OUT_OF_RANGE', `Split time ${operation.at} must be strictly inside clip "${clip.id}"`);
      }
      const ids = allClipIds(project);
      const leftId = operation.leftClipId ?? clip.id;
      const rightId = operation.rightClipId ?? uniqueId(ids, `${clip.id}-right`);
      if (leftId === rightId) throw editError('CLIP_EXISTS', 'Split left and right clip ids must be different');
      if (leftId !== clip.id && ids.has(leftId)) throw editError('CLIP_EXISTS', `Clip "${leftId}" already exists`);
      if (ids.has(rightId)) throw editError('CLIP_EXISTS', `Clip "${rightId}" already exists`);

      const right = structuredClone(clip);
      const leftDuration = operation.at - clip.start;
      right.id = rightId;
      right.start = operation.at;
      right.duration = end - operation.at;
      right.sourceStart = (clip.sourceStart ?? 0) + leftDuration * (clip.speed ?? 1);
      delete right.transition;
      if (right.fadeIn !== undefined) right.fadeIn = 0;
      if (clip.fadeOut !== undefined) clip.fadeOut = 0;
      clip.id = leftId;
      clip.duration = leftDuration;
      (track.clips as Clip[]).splice(index + 1, 0, right);
      return;
    }
    case 'removeClip': {
      const { track, index } = findClip(project, operation.clipId);
      track.clips.splice(index, 1);
      return;
    }
    case 'setClipParams': {
      const { clip } = findClip(project, operation.clipId);
      const target = clip as unknown as Record<string, unknown>;
      for (const [key, value] of Object.entries(operation.params)) target[key] = structuredClone(value);
      return;
    }
    case 'importSrt': {
      const track = findTrack(project, operation.trackId);
      await importSrt(project, track, operation, projectFile);
      return;
    }
  }
}

async function applySequential(project: Project, operations: EditOperation[], projectFile: string): Promise<void> {
  for (const [operationIndex, operation] of operations.entries()) {
    try {
      assertOperationShape(operation);
      await applyOperationInPlace(project, operation, projectFile);
      validateProjectData(project, { stage: 'edit.apply', path: projectFile });
    } catch (error) {
      throw withOperationIndex(error, operationIndex);
    }
  }
}

export async function applyOperations(
  project: Project,
  operations: EditOperation[],
  options: ApplyOperationsOptions = {},
): Promise<Project> {
  if (!Array.isArray(operations)) throw editError('EDIT_OPERATIONS_INVALID', 'Edit operations must be an array');
  const draft = structuredClone(validateProjectData(project, { stage: 'edit.apply' }));
  await applySequential(draft, operations, resolveProjectFile(options.projectPath ?? '.'));
  return draft;
}

function operationSummary(operations: EditOperation[]): string {
  if (operations.length === 0) return 'No-op edit';
  const counts = new Map<string, number>();
  for (const operation of operations) counts.set(operation.type, (counts.get(operation.type) ?? 0) + 1);
  return [...counts].map(([type, count]) => `${type}${count === 1 ? '' : ` ×${count}`}`).join(', ');
}

export async function applyEdit(
  projectPath: string,
  operations: EditOperation[],
  options: ApplyEditOptions = {},
): Promise<EditResult> {
  if (!Array.isArray(operations)) throw editError('EDIT_OPERATIONS_INVALID', 'Edit operations must be an array');
  const projectFile = resolveProjectFile(projectPath);
  return commitProjectTransaction(projectFile, {
    dryRun: options.dryRun ?? false,
    summary: options.summary ?? operationSummary(operations),
    operations: structuredClone(operations),
  }, async (draft) => {
    await applySequential(draft, operations, projectFile);
  });
}
