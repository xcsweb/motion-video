import { randomBytes } from 'node:crypto';
import {
  link,
  open,
  readFile,
  unlink,
  writeFile,
} from 'node:fs/promises';
import type { FileHandle } from 'node:fs/promises';
import { hostname } from 'node:os';
import { basename, dirname, join } from 'node:path';
import { CodeCutError, ExitCode } from './errors.js';
import { resolveProjectFile } from './project.js';

interface LockMetadata {
  version: 1;
  pid: number;
  hostname: string;
  token: string;
  createdAt: string;
}

export interface ProjectLockOptions {
  stage?: string;
}

const heldLocks = new Set<string>();

export function getProjectLockPath(projectPath = '.'): string {
  const projectFile = resolveProjectFile(projectPath);
  return join(dirname(projectFile), `.${basename(projectFile)}.lock`);
}

function lockError(
  code: string,
  message: string,
  path: string,
  stage: string,
  options: { cause?: unknown; retryable?: boolean } = {},
): CodeCutError {
  return new CodeCutError(code, message, ExitCode.ProjectValidation, {
    stage,
    path,
    ...(options.cause === undefined ? {} : { cause: options.cause }),
    retryable: options.retryable ?? false,
  });
}

async function createLockFile(
  lockPath: string,
  metadata: LockMetadata,
  stage: string,
): Promise<boolean> {
  const temporaryPath = join(
    dirname(lockPath),
    `.${basename(lockPath)}.${process.pid}.${randomBytes(6).toString('hex')}.tmp`,
  );
  let handle: FileHandle | undefined;
  try {
    handle = await open(temporaryPath, 'wx');
    await handle.writeFile(`${JSON.stringify(metadata)}\n`, 'utf8');
    await handle.sync();
    await handle.close();
    handle = undefined;
    try {
      await link(temporaryPath, lockPath);
      return true;
    } catch (cause) {
      if ((cause as NodeJS.ErrnoException).code === 'EEXIST') return false;
      throw cause;
    }
  } catch (cause) {
    throw lockError('PROJECT_LOCK_FAILED', 'Could not create the project write lock', lockPath, stage, {
      cause,
      retryable: true,
    });
  } finally {
    if (handle) await handle.close().catch(() => undefined);
    await unlink(temporaryPath).catch(() => undefined);
  }
}

async function readLockMetadata(lockPath: string, stage: string): Promise<LockMetadata | undefined> {
  let source: string;
  try {
    source = await readFile(lockPath, 'utf8');
  } catch (cause) {
    if ((cause as NodeJS.ErrnoException).code === 'ENOENT') return undefined;
    throw lockError('PROJECT_LOCK_FAILED', 'Could not read the project write lock', lockPath, stage, {
      cause,
      retryable: true,
    });
  }

  try {
    const value = JSON.parse(source) as Partial<LockMetadata>;
    if (value.version !== 1
      || !Number.isSafeInteger(value.pid)
      || (value.pid ?? 0) <= 0
      || typeof value.hostname !== 'string'
      || typeof value.token !== 'string'
      || value.token.length === 0
      || typeof value.createdAt !== 'string') {
      throw new TypeError('Invalid lock metadata');
    }
    return value as LockMetadata;
  } catch (cause) {
    throw lockError(
      'PROJECT_LOCK_INVALID',
      'Project write lock is corrupt; inspect it manually rather than ignoring a potentially active writer',
      lockPath,
      stage,
      { cause },
    );
  }
}

function processIsAlive(pid: number): boolean {
  try {
    process.kill(pid, 0);
    return true;
  } catch (cause) {
    const code = (cause as NodeJS.ErrnoException).code;
    if (code === 'ESRCH') return false;
    if (code === 'EPERM') return true;
    throw cause;
  }
}

function assertLockIsInactive(metadata: LockMetadata, lockPath: string, stage: string): void {
  if (metadata.hostname !== hostname()) {
    throw lockError(
      'PROJECT_LOCKED',
      `Project is locked by PID ${metadata.pid} on host ${metadata.hostname}; its liveness cannot be verified locally`,
      lockPath,
      stage,
      { retryable: true },
    );
  }

  let alive: boolean;
  try {
    alive = processIsAlive(metadata.pid);
  } catch (cause) {
    throw lockError('PROJECT_LOCK_FAILED', 'Could not determine whether the project lock owner is alive', lockPath, stage, {
      cause,
      retryable: true,
    });
  }
  if (alive) {
    throw lockError(
      'PROJECT_LOCKED',
      `Project is locked by active PID ${metadata.pid}`,
      lockPath,
      stage,
      { retryable: true },
    );
  }
}

async function recoverStaleLock(
  lockPath: string,
  expected: LockMetadata,
  metadata: LockMetadata,
  stage: string,
): Promise<boolean> {
  const recoveryPath = `${lockPath}.recover`;
  try {
    await writeFile(recoveryPath, `${process.pid}\n`, { encoding: 'utf8', flag: 'wx' });
  } catch (cause) {
    if ((cause as NodeJS.ErrnoException).code === 'EEXIST') {
      throw lockError('PROJECT_LOCKED', 'Another process is recovering the project write lock', lockPath, stage, {
        cause,
        retryable: true,
      });
    }
    throw lockError('PROJECT_LOCK_FAILED', 'Could not create the project lock recovery guard', recoveryPath, stage, {
      cause,
      retryable: true,
    });
  }

  try {
    const current = await readLockMetadata(lockPath, stage);
    if (!current || current.token !== expected.token) {
      throw lockError('PROJECT_LOCKED', 'Project lock changed while stale recovery was being attempted', lockPath, stage, {
        retryable: true,
      });
    }
    assertLockIsInactive(current, lockPath, stage);
    await unlink(lockPath);
    return await createLockFile(lockPath, metadata, stage);
  } finally {
    await unlink(recoveryPath).catch(() => undefined);
  }
}

export async function withProjectLock<T>(
  projectPath: string,
  fn: () => T | Promise<T>,
  options: ProjectLockOptions = {},
): Promise<T> {
  const stage = options.stage ?? 'project.lock';
  const lockPath = getProjectLockPath(projectPath);
  if (heldLocks.has(lockPath)) {
    throw lockError('PROJECT_LOCKED', 'Project write lock is already held by this process; nested locking is not allowed', lockPath, stage);
  }

  const metadata: LockMetadata = {
    version: 1,
    pid: process.pid,
    hostname: hostname(),
    token: randomBytes(16).toString('hex'),
    createdAt: new Date().toISOString(),
  };

  let acquired = await createLockFile(lockPath, metadata, stage);
  for (let attempt = 0; !acquired && attempt < 3; attempt += 1) {
    const existing = await readLockMetadata(lockPath, stage);
    if (!existing) {
      acquired = await createLockFile(lockPath, metadata, stage);
      continue;
    }
    assertLockIsInactive(existing, lockPath, stage);
    acquired = await recoverStaleLock(lockPath, existing, metadata, stage);
  }
  if (!acquired) {
    throw lockError('PROJECT_LOCKED', 'Could not acquire the project write lock', lockPath, stage, {
      retryable: true,
    });
  }

  heldLocks.add(lockPath);
  try {
    return await fn();
  } finally {
    heldLocks.delete(lockPath);
    const current = await readLockMetadata(lockPath, stage);
    if (current?.token === metadata.token) await unlink(lockPath);
  }
}
