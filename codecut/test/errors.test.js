import assert from 'node:assert/strict';
import test from 'node:test';
import { asCodeCutError, CodeCutError, ExitCode, formatTextError } from '../dist/errors.js';

test('exit codes distinguish all required automation outcomes', () => {
  assert.deepEqual(ExitCode, {
    Success: 0,
    Internal: 1,
    Usage: 2,
    ProjectValidation: 3,
    Media: 4,
    Timeout: 5,
    Cancelled: 6,
  });
  assert.equal(new Set(Object.values(ExitCode)).size, 7);
});

test('structured errors retain optional diagnostic coordinates', () => {
  const error = new CodeCutError('EDIT_OPERATION_FAILED', 'bad operation', ExitCode.ProjectValidation, {
    stage: 'edit.apply',
    jobId: 'job-1',
    path: '/tmp/project.json',
    operationIndex: 2,
    retryable: false,
    diagnostics: { issues: [{ path: '/tracks/0', message: 'invalid' }] },
  });
  assert.deepEqual(error.toJSON(), {
    code: 'EDIT_OPERATION_FAILED',
    message: 'bad operation',
    stage: 'edit.apply',
    jobId: 'job-1',
    path: '/tmp/project.json',
    operationIndex: 2,
    retryable: false,
    diagnostics: { issues: [{ path: '/tracks/0', message: 'invalid' }] },
  });
  assert.match(formatTextError(error), /operationIndex=2/);
  assert.ok(!JSON.stringify(error.toJSON()).includes('stack'));
});

test('unexpected exceptions map to internal errors without a stack payload', () => {
  const error = asCodeCutError(new Error('unexpected failure'), 'test.stage');
  assert.equal(error.code, 'INTERNAL_ERROR');
  assert.equal(error.exitCode, ExitCode.Internal);
  assert.equal(error.stage, 'test.stage');
  assert.equal(error.toJSON().message, 'unexpected failure');
  assert.ok(!('stack' in error.toJSON()));
});
