import { randomBytes } from 'node:crypto';
import { mkdir, readFile, rm } from 'node:fs/promises';
import { dirname, join, resolve } from 'node:path';
import { CodeCutError, ExitCode } from './errors.js';
import {
  calculateTimeline,
  loadProject,
  resolveProjectFile,
  validateProjectData,
  writeJsonAtomic,
  type Timeline,
} from './project.js';
import { withProjectLock } from './project-lock.js';
import type { HistoryOperation, Project, Revision } from './schema.js';

export type RevisionKind = 'edit' | 'undo' | 'redo';
export type RevisionReference = string | null;

export type RevisionRecord = Revision;

export interface ProjectDiffEntry {
  op: 'add' | 'remove' | 'replace';
  path: string;
  before?: unknown;
  after?: unknown;
}

export interface ProjectTransactionResult {
  path: string;
  dryRun: boolean;
  project: Project;
  timeline: Timeline;
  diff: ProjectDiffEntry[];
  revision?: RevisionRecord;
}

export interface HistoryListResult {
  currentId: string | null;
  canUndo: boolean;
  canRedo: boolean;
  revisions: RevisionRecord[];
}

export interface RevisionDiffResult {
  fromId: RevisionReference;
  toId: RevisionReference;
  diff: ProjectDiffEntry[];
}

export interface ProjectTransactionOptions {
  dryRun?: boolean;
  summary: string;
  operations: HistoryOperation[];
}

interface HistoryState {
  schemaVersion: 1;
  currentId: string | null;
  baseSnapshotPath: string;
  undoStack: RevisionReference[];
  redoStack: RevisionReference[];
  revisionIds: string[];
}

interface HistoryPaths {
  projectDirectory: string;
  root: string;
  revisions: string;
  state: string;
  baseSnapshot: string;
}

interface PreparedCommit {
  before: Project;
  project: Project;
  state: HistoryState | undefined;
  nextState: HistoryState;
  revision: RevisionRecord;
  revisionDirectory: string;
  snapshotPath: string;
  metadataPath: string;
  baseCreated: boolean;
}

const IDENTIFIER = /^[A-Za-z0-9][A-Za-z0-9._-]*$/;
const BASE_SNAPSHOT_PATH = '.codecut/revisions/base.json';

function historyPaths(projectFile: string): HistoryPaths {
  const projectDirectory = dirname(projectFile);
  const root = join(projectDirectory, '.codecut');
  const revisions = join(root, 'revisions');
  return {
    projectDirectory,
    root,
    revisions,
    state: join(root, 'history.json'),
    baseSnapshot: join(revisions, 'base.json'),
  };
}

function clone<T>(value: T): T {
  return structuredClone(value);
}

function immutable<T>(value: T): T {
  if (typeof value !== 'object' || value === null || Object.isFrozen(value)) return value;
  Object.freeze(value);
  for (const child of Object.values(value)) immutable(child);
  return value;
}

function pointerPart(value: string): string {
  return value.replaceAll('~', '~0').replaceAll('/', '~1');
}

function isContainer(value: unknown): value is Record<string, unknown> | unknown[] {
  return typeof value === 'object' && value !== null;
}

function diffValues(before: unknown, after: unknown, path: string, entries: ProjectDiffEntry[]): void {
  if (Object.is(before, after)) return;
  if (!isContainer(before) || !isContainer(after) || Array.isArray(before) !== Array.isArray(after)) {
    entries.push({ op: 'replace', path: path || '/', before: clone(before), after: clone(after) });
    return;
  }

  if (Array.isArray(before) && Array.isArray(after)) {
    const common = Math.min(before.length, after.length);
    for (let index = 0; index < common; index += 1) {
      diffValues(before[index], after[index], `${path}/${index}`, entries);
    }
    for (let index = common; index < before.length; index += 1) {
      entries.push({ op: 'remove', path: `${path}/${index}`, before: clone(before[index]) });
    }
    for (let index = common; index < after.length; index += 1) {
      entries.push({ op: 'add', path: `${path}/${index}`, after: clone(after[index]) });
    }
    return;
  }

  const left = before as Record<string, unknown>;
  const right = after as Record<string, unknown>;
  for (const key of Object.keys(left)) {
    const childPath = `${path}/${pointerPart(key)}`;
    if (!Object.hasOwn(right, key)) entries.push({ op: 'remove', path: childPath, before: clone(left[key]) });
    else diffValues(left[key], right[key], childPath, entries);
  }
  for (const key of Object.keys(right)) {
    if (!Object.hasOwn(left, key)) {
      entries.push({ op: 'add', path: `${path}/${pointerPart(key)}`, after: clone(right[key]) });
    }
  }
}

export function diffProjects(before: Project, after: Project): ProjectDiffEntry[] {
  const entries: ProjectDiffEntry[] = [];
  diffValues(before, after, '', entries);
  return immutable(entries);
}

function historyError(
  code: string,
  message: string,
  stage: string,
  path?: string,
  options: { cause?: unknown; retryable?: boolean } = {},
): CodeCutError {
  return new CodeCutError(code, message, ExitCode.ProjectValidation, {
    stage,
    ...(path === undefined ? {} : { path }),
    ...(options.cause === undefined ? {} : { cause: options.cause }),
    retryable: options.retryable ?? false,
  });
}

function assertReference(value: unknown, path: string): asserts value is RevisionReference {
  if (value !== null && (typeof value !== 'string' || !IDENTIFIER.test(value))) {
    throw new TypeError(`Invalid revision reference at ${path}`);
  }
}

function parseHistoryState(value: unknown): HistoryState {
  if (typeof value !== 'object' || value === null) throw new TypeError('History state must be an object');
  const state = value as Partial<HistoryState>;
  if (state.schemaVersion !== 1
    || typeof state.baseSnapshotPath !== 'string'
    || !Array.isArray(state.undoStack)
    || !Array.isArray(state.redoStack)
    || !Array.isArray(state.revisionIds)
    || !state.revisionIds.every((id) => typeof id === 'string' && IDENTIFIER.test(id))) {
    throw new TypeError('Invalid history state');
  }
  assertReference(state.currentId, '/currentId');
  state.undoStack.forEach((reference, index) => assertReference(reference, `/undoStack/${index}`));
  state.redoStack.forEach((reference, index) => assertReference(reference, `/redoStack/${index}`));
  if (state.currentId !== null && !state.revisionIds.includes(state.currentId)) {
    throw new TypeError('Current revision is absent from history');
  }
  return clone(state as HistoryState);
}

async function readHistoryState(projectFile: string, stage: string): Promise<HistoryState | undefined> {
  const path = historyPaths(projectFile).state;
  let source: string;
  try {
    source = await readFile(path, 'utf8');
  } catch (cause) {
    if ((cause as NodeJS.ErrnoException).code === 'ENOENT') return undefined;
    throw historyError('HISTORY_READ_FAILED', 'Could not read project history', stage, path, {
      cause,
      retryable: true,
    });
  }
  try {
    return parseHistoryState(JSON.parse(source));
  } catch (cause) {
    throw historyError('HISTORY_CORRUPT', 'Project history is corrupt', stage, path, { cause });
  }
}

function revisionDirectory(projectFile: string, id: string): string {
  if (!IDENTIFIER.test(id)) throw historyError('REVISION_NOT_FOUND', `Invalid revision id "${id}"`, 'history.read');
  return join(historyPaths(projectFile).revisions, id);
}

async function readJsonFile(path: string, code: string, stage: string): Promise<unknown> {
  let source: string;
  try {
    source = await readFile(path, 'utf8');
  } catch (cause) {
    const missing = (cause as NodeJS.ErrnoException).code === 'ENOENT';
    throw historyError(missing ? 'REVISION_NOT_FOUND' : code, missing ? 'Revision data does not exist' : 'Could not read revision data', stage, path, {
      cause,
      retryable: !missing,
    });
  }
  try {
    return JSON.parse(source);
  } catch (cause) {
    throw historyError('HISTORY_CORRUPT', 'Revision data is not valid JSON', stage, path, { cause });
  }
}

function parseRevisionRecord(value: unknown, projectFile: string): RevisionRecord {
  if (typeof value !== 'object' || value === null) throw new TypeError('Revision must be an object');
  const revision = value as Partial<RevisionRecord>;
  if (typeof revision.id !== 'string'
    || !IDENTIFIER.test(revision.id)
    || !Number.isSafeInteger(revision.projectRevision)
    || (revision.projectRevision ?? 0) < 1
    || typeof revision.createdAt !== 'string'
    || typeof revision.summary !== 'string'
    || revision.summary.length === 0
    || !Array.isArray(revision.operations)
    || typeof revision.snapshotPath !== 'string') {
    throw new TypeError('Invalid revision record');
  }
  assertReference(revision.parentId ?? null, '/parentId');
  const expectedDirectory = revisionDirectory(projectFile, revision.id);
  const expectedSnapshot = resolve(expectedDirectory, 'project.json');
  if (resolve(historyPaths(projectFile).projectDirectory, revision.snapshotPath) !== expectedSnapshot) {
    throw new TypeError('Revision snapshot path does not match its id');
  }
  return immutable(clone(revision as RevisionRecord));
}

export async function getRevision(projectPath: string, id: string): Promise<RevisionRecord> {
  const projectFile = resolveProjectFile(projectPath);
  const path = join(revisionDirectory(projectFile, id), 'revision.json');
  try {
    return parseRevisionRecord(await readJsonFile(path, 'HISTORY_READ_FAILED', 'history.read'), projectFile);
  } catch (cause) {
    if (cause instanceof CodeCutError) throw cause;
    throw historyError('HISTORY_CORRUPT', `Revision "${id}" is corrupt`, 'history.read', path, { cause });
  }
}

async function readSnapshotReference(
  projectFile: string,
  reference: RevisionReference,
  stage: string,
): Promise<Project> {
  const paths = historyPaths(projectFile);
  const path = reference === null
    ? paths.baseSnapshot
    : join(revisionDirectory(projectFile, reference), 'project.json');
  const data = await readJsonFile(path, 'HISTORY_READ_FAILED', stage);
  const snapshot = validateProjectData(data, { stage, path });
  return immutable(clone(snapshot));
}

export async function getRevisionSnapshot(projectPath: string, id: string): Promise<Project> {
  const projectFile = resolveProjectFile(projectPath);
  await getRevision(projectFile, id);
  return readSnapshotReference(projectFile, id, 'history.snapshot');
}

export async function listHistory(projectPath: string): Promise<HistoryListResult> {
  const projectFile = resolveProjectFile(projectPath);
  const state = await readHistoryState(projectFile, 'history.list');
  if (!state) return { currentId: null, canUndo: false, canRedo: false, revisions: [] };
  const revisions = await Promise.all(state.revisionIds.map((id) => getRevision(projectFile, id)));
  return immutable({
    currentId: state.currentId,
    canUndo: state.undoStack.length > 0,
    canRedo: state.redoStack.length > 0,
    revisions,
  });
}

export async function listRevisions(projectPath: string): Promise<RevisionRecord[]> {
  return (await listHistory(projectPath)).revisions;
}

export async function diffRevisions(
  projectPath: string,
  fromId: RevisionReference,
  toId: RevisionReference,
): Promise<RevisionDiffResult> {
  const projectFile = resolveProjectFile(projectPath);
  const [before, after] = await Promise.all([
    readSnapshotReference(projectFile, fromId, 'history.diff'),
    readSnapshotReference(projectFile, toId, 'history.diff'),
  ]);
  return immutable({ fromId, toId, diff: diffProjects(before, after) });
}

function validateRevisionConsistency(before: Project, state: HistoryState | undefined, revision?: RevisionRecord): void {
  if (!state) {
    if (before.revision !== 0) {
      throw historyError(
        'HISTORY_STATE_MISMATCH',
        'Project has a nonzero revision but no history state; refusing to create an incompatible history',
        'history.commit',
      );
    }
    return;
  }
  if (state.currentId === null || !revision || revision.projectRevision !== before.revision) {
    throw historyError(
      'HISTORY_STATE_MISMATCH',
      'Project revision and history head disagree; repair the project history before writing',
      'history.commit',
    );
  }
}

async function prepareCommit(
  projectFile: string,
  before: Project,
  project: Project,
  state: HistoryState | undefined,
  nextUndoStack: RevisionReference[],
  nextRedoStack: RevisionReference[],
  summary: string,
  operations: HistoryOperation[],
): Promise<PreparedCommit> {
  const paths = historyPaths(projectFile);
  const id = `r${project.revision}-${randomBytes(5).toString('hex')}`;
  const directory = join(paths.revisions, id);
  const snapshotPath = join(directory, 'project.json');
  const metadataPath = join(directory, 'revision.json');
  const revision: RevisionRecord = {
    id,
    ...(state?.currentId ? { parentId: state.currentId } : {}),
    projectRevision: project.revision,
    createdAt: new Date().toISOString(),
    summary,
    operations: clone(operations),
    snapshotPath: `.codecut/revisions/${id}/project.json`,
  };
  const nextState: HistoryState = {
    schemaVersion: 1,
    currentId: id,
    baseSnapshotPath: state?.baseSnapshotPath ?? BASE_SNAPSHOT_PATH,
    undoStack: nextUndoStack,
    redoStack: nextRedoStack,
    revisionIds: [...(state?.revisionIds ?? []), id],
  };
  return {
    before,
    project,
    state,
    nextState,
    revision,
    revisionDirectory: directory,
    snapshotPath,
    metadataPath,
    baseCreated: !state,
  };
}

async function persistCommit(projectFile: string, commit: PreparedCommit): Promise<void> {
  const paths = historyPaths(projectFile);
  await mkdir(commit.revisionDirectory, { recursive: true });
  let baseWritten = false;
  try {
    if (commit.baseCreated) {
      await writeJsonAtomic(paths.baseSnapshot, commit.before, {
        force: false,
        stage: 'history.commit',
      });
      baseWritten = true;
    }
    await writeJsonAtomic(commit.snapshotPath, commit.project, { force: false, stage: 'history.commit' });
    await writeJsonAtomic(commit.metadataPath, commit.revision, { force: false, stage: 'history.commit' });
    await writeJsonAtomic(projectFile, commit.project, { force: true, stage: 'history.commit' });
    try {
      await writeJsonAtomic(paths.state, commit.nextState, { force: true, stage: 'history.commit' });
    } catch (cause) {
      await writeJsonAtomic(projectFile, commit.before, { force: true, stage: 'history.rollback' }).catch(() => undefined);
      throw cause;
    }
  } catch (cause) {
    await rm(commit.revisionDirectory, { recursive: true, force: true }).catch(() => undefined);
    if (baseWritten) await rm(paths.baseSnapshot, { force: true }).catch(() => undefined);
    if (cause instanceof CodeCutError) throw cause;
    throw historyError('HISTORY_COMMIT_FAILED', 'Could not commit project revision', 'history.commit', projectFile, {
      cause,
      retryable: true,
    });
  }
}

async function executeTransaction(
  projectPath: string,
  kind: RevisionKind,
  options: ProjectTransactionOptions,
  mutate?: (draft: Project) => void | Promise<void>,
): Promise<ProjectTransactionResult> {
  const projectFile = resolveProjectFile(projectPath);
  return withProjectLock(projectFile, async () => {
    if (options.summary.trim().length === 0) {
      throw historyError('REVISION_SUMMARY_INVALID', 'Revision summary must not be empty', `history.${kind}`);
    }
    const { project: before } = await loadProject(projectFile, 'history.commit');
    const state = await readHistoryState(projectFile, 'history.commit');
    const currentRevision = state?.currentId ? await getRevision(projectFile, state.currentId) : undefined;
    validateRevisionConsistency(before, state, currentRevision);

    let draft: Project;
    let nextUndoStack: RevisionReference[];
    let nextRedoStack: RevisionReference[];
    let summary = options.summary;

    if (kind === 'edit') {
      if (!mutate) throw new TypeError('An edit transaction requires a mutator');
      draft = clone(before);
      await mutate(draft);
      nextUndoStack = [...(state?.undoStack ?? []), state?.currentId ?? null];
      nextRedoStack = [];
    } else {
      if (!state) {
        throw historyError(`HISTORY_${kind.toUpperCase()}_UNAVAILABLE`, `Cannot ${kind} without project history`, `history.${kind}`);
      }
      const sourceStack = kind === 'undo' ? state.undoStack : state.redoStack;
      if (sourceStack.length === 0) {
        throw historyError(`HISTORY_${kind.toUpperCase()}_UNAVAILABLE`, `There is no revision to ${kind}`, `history.${kind}`);
      }
      const target = sourceStack[sourceStack.length - 1] ?? null;
      draft = clone(await readSnapshotReference(projectFile, target, `history.${kind}`));
      if (kind === 'undo') {
        nextUndoStack = state.undoStack.slice(0, -1);
        nextRedoStack = [...state.redoStack, state.currentId];
        summary = `Undo ${state.currentId ?? 'base revision'}`;
      } else {
        nextUndoStack = [...state.undoStack, state.currentId];
        nextRedoStack = state.redoStack.slice(0, -1);
        summary = `Redo ${target ?? 'base revision'}`;
      }
    }

    draft.revision = before.revision + 1;
    validateProjectData(draft, { stage: `history.${kind}`, path: projectFile });
    const diff = diffProjects(before, draft);
    if (options.dryRun) {
      return immutable({
        path: projectFile,
        dryRun: true,
        project: clone(draft),
        timeline: calculateTimeline(draft),
        diff,
      });
    }

    const commit = await prepareCommit(
      projectFile,
      before,
      draft,
      state,
      nextUndoStack,
      nextRedoStack,
      summary,
      kind === 'edit' ? options.operations : [],
    );
    await persistCommit(projectFile, commit);
    return immutable({
      path: projectFile,
      dryRun: false,
      project: clone(draft),
      timeline: calculateTimeline(draft),
      diff,
      revision: clone(commit.revision),
    });
  }, { stage: `history.${kind}` });
}

export async function commitProjectTransaction(
  projectPath: string,
  options: ProjectTransactionOptions,
  mutate: (draft: Project) => void | Promise<void>,
): Promise<ProjectTransactionResult> {
  return executeTransaction(projectPath, 'edit', options, mutate);
}

export async function undoProject(
  projectPath: string,
  options: { dryRun?: boolean } = {},
): Promise<ProjectTransactionResult> {
  return executeTransaction(projectPath, 'undo', { ...options, summary: 'Undo', operations: [] });
}

export async function redoProject(
  projectPath: string,
  options: { dryRun?: boolean } = {},
): Promise<ProjectTransactionResult> {
  return executeTransaction(projectPath, 'redo', { ...options, summary: 'Redo', operations: [] });
}
