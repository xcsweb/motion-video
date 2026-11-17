import type { ErrorPayload } from './schema.js';

export const ExitCode = {
  Success: 0,
  Internal: 1,
  Usage: 2,
  ProjectValidation: 3,
  Media: 4,
  Timeout: 5,
  Cancelled: 6,
} as const;

export type ExitCode = (typeof ExitCode)[keyof typeof ExitCode];

export interface ErrorOptions {
  stage: string;
  jobId?: string;
  path?: string;
  operationIndex?: number;
  retryable?: boolean;
  diagnostics?: unknown;
  cause?: unknown;
}

/** An expected, stable CLI failure. Unexpected exceptions are mapped separately. */
export class CodeCutError extends Error {
  readonly code: string;
  readonly exitCode: ExitCode;
  readonly stage: string;
  readonly jobId?: string;
  readonly path?: string;
  readonly operationIndex?: number;
  readonly retryable?: boolean;
  readonly diagnostics?: unknown;

  constructor(code: string, message: string, exitCode: ExitCode, options: ErrorOptions) {
    super(message, { cause: options.cause });
    this.name = 'CodeCutError';
    this.code = code;
    this.exitCode = exitCode;
    this.stage = options.stage;
    if (options.jobId !== undefined) this.jobId = options.jobId;
    if (options.path !== undefined) this.path = options.path;
    if (options.operationIndex !== undefined) this.operationIndex = options.operationIndex;
    if (options.retryable !== undefined) this.retryable = options.retryable;
    if (options.diagnostics !== undefined) this.diagnostics = options.diagnostics;
  }

  toJSON(): ErrorPayload {
    const payload: ErrorPayload = {
      code: this.code,
      message: this.message,
      stage: this.stage,
    };
    if (this.jobId !== undefined) payload.jobId = this.jobId;
    if (this.path !== undefined) payload.path = this.path;
    if (this.operationIndex !== undefined) payload.operationIndex = this.operationIndex;
    if (this.retryable !== undefined) payload.retryable = this.retryable;
    if (this.diagnostics !== undefined) payload.diagnostics = this.diagnostics;
    return payload;
  }
}

export function asCodeCutError(error: unknown, stage = 'cli'): CodeCutError {
  if (error instanceof CodeCutError) return error;
  const message = error instanceof Error ? error.message : String(error);
  return new CodeCutError('INTERNAL_ERROR', message, ExitCode.Internal, {
    stage,
    cause: error,
    retryable: false,
  });
}

export function formatTextError(error: CodeCutError): string {
  const location = [
    error.path ? `path=${error.path}` : undefined,
    error.operationIndex !== undefined ? `operationIndex=${error.operationIndex}` : undefined,
    error.jobId ? `jobId=${error.jobId}` : undefined,
  ].filter(Boolean).join(' ');
  return `${error.code} [${error.stage}]: ${error.message}${location ? `\n${location}` : ''}\n`;
}
