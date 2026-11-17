import { randomBytes } from 'node:crypto';
import { mkdir, readFile, rename, rm, stat, writeFile } from 'node:fs/promises';
import { basename, dirname, join } from 'node:path';
import { CodeCutError, ExitCode } from './errors.js';

interface LockOwner {
  token: string;
  pid: number;
  outputPath: string;
  createdAt: string;
}

export interface OutputLock {
  readonly path: string;
  readonly outputPath: string;
  release(): Promise<void>;
}

export function processExists(pid: number | undefined): boolean {
  if (pid === undefined || !Number.isInteger(pid) || pid <= 0) return false;
  try {
    process.kill(pid, 0);
    return true;
  } catch (error) {
    return (error as NodeJS.ErrnoException).code === 'EPERM';
  }
}

export function outputLockPath(outputPath: string): string {
  return join(dirname(outputPath), `.${basename(outputPath)}.codecut.lock`);
}

async function readOwner(path: string): Promise<LockOwner | undefined> {
  try {
    const value = JSON.parse(await readFile(join(path, 'owner.json'), 'utf8')) as Partial<LockOwner>;
    if (typeof value.token !== 'string' || typeof value.pid !== 'number') return undefined;
    return value as LockOwner;
  } catch {
    return undefined;
  }
}

async function reapStaleLock(path: string): Promise<boolean> {
  const owner = await readOwner(path);
  if (owner && processExists(owner.pid)) return false;
  if (!owner) {
    try {
      const information = await stat(path);
      if (Date.now() - information.mtimeMs < 1_000) return false;
    } catch {
      return true;
    }
  }

  const quarantine = `${path}.reap-${process.pid}-${randomBytes(4).toString('hex')}`;
  try {
    await rename(path, quarantine);
    await rm(quarantine, { recursive: true, force: true });
    return true;
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === 'ENOENT') return true;
    return false;
  }
}

/** Acquires only the output lock. Callers must not hold a project write lock here. */
export async function acquireOutputLock(outputPath: string): Promise<OutputLock> {
  const path = outputLockPath(outputPath);
  const token = randomBytes(12).toString('hex');
  const owner: LockOwner = {
    token,
    pid: process.pid,
    outputPath,
    createdAt: new Date().toISOString(),
  };

  for (let attempt = 0; attempt < 2; attempt += 1) {
    try {
      await mkdir(path);
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== 'EEXIST') {
        throw new CodeCutError('DISK_WRITE_FAILED', 'Could not create the output path lock', ExitCode.Internal, {
          stage: 'output.lock',
          path,
          cause: error,
          retryable: true,
        });
      }
      if (attempt === 0 && await reapStaleLock(path)) continue;
      const current = await readOwner(path);
      throw new CodeCutError('OUTPUT_LOCKED', 'Another job is using this output path', ExitCode.Media, {
        stage: 'output.lock',
        path: outputPath,
        retryable: true,
        diagnostics: { lockPath: path, workerPid: current?.pid },
      });
    }

    try {
      await writeFile(join(path, 'owner.json'), `${JSON.stringify(owner, null, 2)}\n`, { encoding: 'utf8', flag: 'wx' });
    } catch (error) {
      await rm(path, { recursive: true, force: true }).catch(() => undefined);
      throw new CodeCutError('DISK_WRITE_FAILED', 'Could not initialize the output path lock', ExitCode.Internal, {
        stage: 'output.lock',
        path,
        cause: error,
        retryable: true,
      });
    }

    return {
      path,
      outputPath,
      async release() {
        const current = await readOwner(path);
        if (current?.token === token) await rm(path, { recursive: true, force: true });
      },
    };
  }

  throw new CodeCutError('OUTPUT_LOCKED', 'Another job is using this output path', ExitCode.Media, {
    stage: 'output.lock',
    path: outputPath,
    retryable: true,
  });
}
