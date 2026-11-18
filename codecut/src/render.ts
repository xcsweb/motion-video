import { stat } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import {
  findAsset,
  inspectAssetFile,
  probeAssetFile,
} from './assets.js';
import { CodeCutError, ExitCode } from './errors.js';
import { getRevisionSnapshot, listHistory } from './history.js';
import { JobService, type JobRecord } from './jobs.js';
import type { AssetSnapshot, ProjectSnapshot } from './jobs-store.js';
import { loadProject } from './project.js';
import {
  compileRenderPlan,
  type RenderPlan,
  type RenderSource,
} from './render-plan.js';
import type { Project } from './schema.js';

export interface RenderOptions {
  revision?: number | string;
  output?: string;
  force?: boolean;
  detach?: boolean;
  dryRun?: boolean;
  timeoutMs?: number;
  ffmpegPath?: string;
  ffprobePath?: string;
}

export interface RenderResult {
  dryRun: boolean;
  revisionId?: string;
  plan: RenderPlan;
  job?: JobRecord;
}

export interface PreparedProject {
  project: Project;
  projectFile: string;
  projectDirectory: string;
  revisionId?: string;
}

function sameFingerprint(left: { size: number; mtimeMs: number }, right: { size: number; mtimeMs: number }): boolean {
  return left.size === right.size && Math.abs(left.mtimeMs - right.mtimeMs) <= 1;
}

export async function loadRenderProject(projectPath: string, revision?: number | string): Promise<PreparedProject> {
  if (revision === undefined) {
    const { project, path } = await loadProject(projectPath, 'render.load');
    return { project, projectFile: path, projectDirectory: dirname(path) };
  }
  const loaded = await loadProject(projectPath, 'render.load');
  let id: string;
  if (typeof revision === 'string') {
    id = revision;
  } else {
    if (!Number.isSafeInteger(revision) || revision < 0) {
      throw new CodeCutError('REVISION_NOT_FOUND', 'Render revision must be a non-negative integer or revision ID', ExitCode.Usage, {
        stage: 'render.load', retryable: false, diagnostics: { revision },
      });
    }
    if (revision === 0 && loaded.project.revision === 0) {
      return { project: loaded.project, projectFile: loaded.path, projectDirectory: dirname(loaded.path) };
    }
    const history = await listHistory(loaded.path);
    const match = history.revisions.find((candidate) => candidate.projectRevision === revision);
    if (!match) {
      throw new CodeCutError('REVISION_NOT_FOUND', `Project revision ${revision} does not exist`, ExitCode.Usage, {
        stage: 'render.load', retryable: false, diagnostics: { revision },
      });
    }
    id = match.id;
  }
  const project = await getRevisionSnapshot(loaded.path, id);
  return { project, projectFile: loaded.path, projectDirectory: dirname(loaded.path), revisionId: id };
}

export async function prepareSources(prepared: PreparedProject, ffprobePath?: string): Promise<Map<string, RenderSource>> {
  const referenced = new Set<string>();
  for (const track of prepared.project.tracks) {
    for (const clip of track.clips) {
      if (clip.type === 'video' || clip.type === 'audio' || clip.type === 'image') referenced.add(clip.assetId);
    }
  }
  const sources = new Map<string, RenderSource>();
  for (const id of referenced) {
    const registered = findAsset(prepared.project, id, 'render.preflight');
    const absolutePath = resolve(prepared.projectDirectory, registered.path);
    const identity = await inspectAssetFile(absolutePath, 'render.preflight');
    let asset = registered;
    if (registered.metadata) {
      if (!sameFingerprint(identity, registered.metadata.fingerprint)) {
        throw new CodeCutError('ASSET_FILE_CHANGED', 'Asset changed after its project metadata was captured', ExitCode.Media, {
          stage: 'render.preflight', path: absolutePath, retryable: false,
          diagnostics: { assetId: id, expected: registered.metadata.fingerprint, actual: { size: identity.size, mtimeMs: identity.mtimeMs } },
        });
      }
    } else {
      const probed = await probeAssetFile(absolutePath, 'render.preflight', ffprobePath, registered.kind);
      asset = { ...registered, metadata: probed.metadata };
    }
    const streams = asset.metadata?.streams ?? [];
    sources.set(id, {
      asset: structuredClone(asset),
      absolutePath,
      fingerprint: { size: identity.size, mtimeMs: identity.mtimeMs },
      hasVideo: streams.some((stream) => stream.codecType === 'video'),
      hasAudio: streams.some((stream) => stream.codecType === 'audio'),
    });
  }
  return sources;
}

export async function fixedSnapshot(prepared: PreparedProject, sources: ReadonlyMap<string, RenderSource>): Promise<ProjectSnapshot> {
  const assets: AssetSnapshot[] = [];
  for (const asset of prepared.project.assets) {
    const path = resolve(prepared.projectDirectory, asset.path);
    try {
      const information = await stat(path);
      const source = sources.get(asset.id);
      if (source && (!information.isFile() || !sameFingerprint(information, source.fingerprint))) {
        throw new CodeCutError('ASSET_FILE_CHANGED', 'Asset changed while the render snapshot was being fixed', ExitCode.Media, {
          stage: 'render.preflight', path, retryable: true, diagnostics: { assetId: asset.id },
        });
      }
      assets.push({ id: asset.id, path: asset.path, exists: true, size: information.size, mtimeMs: information.mtimeMs });
    } catch (error) {
      if (error instanceof CodeCutError) throw error;
      if ((error as NodeJS.ErrnoException).code !== 'ENOENT') throw error;
      if (sources.has(asset.id)) throw error;
      assets.push({ id: asset.id, path: asset.path, exists: false });
    }
  }
  return {
    version: 1,
    createdAt: new Date().toISOString(),
    projectRevision: prepared.project.revision,
    project: structuredClone(prepared.project),
    assets,
  };
}

export async function renderProject(
  projectPath: string,
  options: RenderOptions = {},
  service?: JobService,
): Promise<RenderResult> {
  const prepared = await loadRenderProject(projectPath, options.revision);
  const sources = await prepareSources(prepared, options.ffprobePath);
  const plan = compileRenderPlan(prepared.project, {
    projectDirectory: prepared.projectDirectory,
    sources,
    ...(options.output === undefined ? {} : { outputPath: options.output }),
    overwrite: options.force ?? false,
    ...(options.ffmpegPath === undefined ? {} : { ffmpegPath: options.ffmpegPath }),
  });
  const base = {
    ...(prepared.revisionId === undefined ? {} : { revisionId: prepared.revisionId }),
    plan,
  };
  if (options.dryRun) return { ...base, dryRun: true };

  const snapshot = await fixedSnapshot(prepared, sources);
  const jobs = service ?? new JobService({ projectDirectory: prepared.projectDirectory });
  const job = await jobs.create({
    kind: 'render',
    projectPath: prepared.projectFile,
    projectRevision: prepared.project.revision,
    process: {
      command: plan.command,
      args: plan.args,
      cwd: prepared.projectDirectory,
      progress: 'ffmpeg',
      durationSeconds: plan.durationSeconds,
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
    ...(options.timeoutMs === undefined ? {} : { timeoutMs: options.timeoutMs }),
  }, snapshot);
  const started = await jobs.start(job.id, { detach: options.detach ?? false });
  return { ...base, dryRun: false, job: started };
}
