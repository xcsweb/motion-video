import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { mkdtemp, readFile, readdir, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import test from 'node:test';

const root = dirname(dirname(fileURLToPath(import.meta.url)));
const cliPath = join(root, 'dist', 'cli.js');

function cli(args, input) {
  return new Promise((resolve, reject) => {
    const child = spawn(process.execPath, [cliPath, ...args], { cwd: root, stdio: ['pipe', 'pipe', 'pipe'] });
    let stdout = '';
    let stderr = '';
    child.stdout.setEncoding('utf8');
    child.stderr.setEncoding('utf8');
    child.stdout.on('data', (chunk) => { stdout += chunk; });
    child.stderr.on('data', (chunk) => { stderr += chunk; });
    child.once('error', reject);
    child.once('close', (status) => resolve({ status, stdout, stderr }));
    child.stdin.end(input);
  });
}

function success(result, command) {
  assert.equal(result.status, 0, result.stderr);
  assert.equal(result.stderr, '');
  const value = JSON.parse(result.stdout);
  assert.equal(value.ok, true);
  assert.equal(value.command, command);
  return value;
}

async function temporaryDirectory(t) {
  const directory = await mkdtemp(join(tmpdir(), 'codecut-edit-cli-test-'));
  t.after(() => rm(directory, { recursive: true, force: true }));
  return directory;
}

const addBackground = {
  type: 'addClip',
  trackId: 'v1',
  clip: { id: 'background', type: 'color', color: '#123456', start: 0, duration: 2 },
};
const addTitle = {
  type: 'addText',
  trackId: 'v1',
  clip: { id: 'title', type: 'text', text: 'Title', start: 2, duration: 1 },
};

test('edit apply supports file, option, inline JSON and explicit stdin with zero-write dry-runs', async (t) => {
  const directory = await temporaryDirectory(t);
  const project = join(directory, 'project');
  const operationsPath = join(directory, 'operations.json');
  await writeFile(operationsPath, JSON.stringify([addBackground]), 'utf8');
  success(await cli(['project', 'init', project, '--json']), 'project.init');
  const projectPath = join(project, 'project.json');
  const initial = await readFile(projectPath, 'utf8');

  const preview = success(await cli([
    'edit', 'apply', operationsPath, '--project', project, '--dry-run', '--summary', 'Preview only', '--json',
  ]), 'edit.apply');
  assert.equal(preview.dryRun, true);
  assert.equal(preview.revision, undefined);
  assert.equal(preview.timeline.duration, 2);
  assert.ok(Array.isArray(preview.diff));
  assert.ok(preview.diff.some((entry) => entry.after?.id === 'background'));
  assert.equal(await readFile(projectPath, 'utf8'), initial);
  assert.deepEqual(await readdir(project), ['project.json'], 'initial dry-run creates no lock, history, cache, or revision');

  const committed = success(await cli([
    'edit', 'apply', '--operations', operationsPath, '--project', project, '--summary', 'CLI background', '--json',
  ]), 'edit.apply');
  assert.equal(committed.dryRun, false);
  assert.equal(committed.revision.summary, 'CLI background');
  assert.equal(committed.project.revision, 1);
  assert.equal(committed.timeline.tracks.find((track) => track.id === 'v1').clipCount, 1);
  const historyPath = join(project, '.codecut', 'history.json');
  const historyBeforePreviews = await readFile(historyPath, 'utf8');

  const inline = success(await cli([
    'edit', 'apply', '--operations-json', JSON.stringify([addTitle]), '--project', project, '--dry-run', '--json',
  ]), 'edit.apply');
  assert.equal(inline.project.tracks[0].clips.length, 2);
  assert.equal(inline.revision, undefined);

  const stdin = success(await cli([
    'edit', 'apply', '-', '--project', project, '--dry-run', '--json',
  ], JSON.stringify([addTitle])), 'edit.apply');
  assert.equal(stdin.dryRun, true);
  assert.equal(stdin.project.tracks[0].clips[1].id, 'title');
  assert.equal(await readFile(historyPath, 'utf8'), historyBeforePreviews, 'inline and stdin dry-runs create no revisions');
  assert.equal((JSON.parse(await readFile(projectPath, 'utf8'))).revision, 1);
});

test('edit input usage errors are explicit and failed operations preserve index, JSON purity, and disk rollback', async (t) => {
  const directory = await temporaryDirectory(t);
  const project = join(directory, 'project');
  const operationsPath = join(directory, 'operations.json');
  success(await cli(['project', 'init', project, '--json']), 'project.init');
  await writeFile(operationsPath, JSON.stringify([addBackground]), 'utf8');
  success(await cli(['edit', 'apply', operationsPath, '--project', project, '--json']), 'edit.apply');
  const projectPath = join(project, 'project.json');
  const historyPath = join(project, '.codecut', 'history.json');
  const beforeProject = await readFile(projectPath, 'utf8');
  const beforeHistory = await readFile(historyPath, 'utf8');

  const missing = await cli(['edit', 'apply', '--project', project, '--json']);
  assert.equal(missing.status, 2);
  assert.equal(missing.stdout, '');
  assert.match(JSON.parse(missing.stderr).error.message, /stdin is never read implicitly/);

  const ambiguous = await cli([
    'edit', 'apply', operationsPath, '--operations-json', '[]', '--project', project, '--json',
  ]);
  assert.equal(ambiguous.status, 2);
  assert.equal(ambiguous.stdout, '');
  assert.equal(JSON.parse(ambiguous.stderr).error.code, 'USAGE_ERROR');

  const invalidPath = join(directory, 'invalid.json');
  await writeFile(invalidPath, JSON.stringify([
    { type: 'addClip', trackId: 'v2', clip: { id: 'temporary', type: 'color', color: '#000000', start: 0, duration: 1 } },
    { type: 'removeClip', clipId: 'does-not-exist' },
  ]), 'utf8');
  const failed = await cli(['edit', 'apply', invalidPath, '--project', project, '--json']);
  assert.equal(failed.status, 3);
  assert.equal(failed.stdout, '');
  const error = JSON.parse(failed.stderr).error;
  assert.equal(error.code, 'CLIP_NOT_FOUND');
  assert.equal(error.operationIndex, 1);
  assert.equal(error.stage, 'edit.apply');
  assert.equal(await readFile(projectPath, 'utf8'), beforeProject);
  assert.equal(await readFile(historyPath, 'utf8'), beforeHistory);

  await writeFile(invalidPath, '{not-json', 'utf8');
  const malformed = await cli(['edit', 'apply', invalidPath, '--project', project, '--json']);
  assert.equal(malformed.status, 2);
  assert.equal(malformed.stdout, '');
  assert.equal(JSON.parse(malformed.stderr).error.code, 'OPERATIONS_PARSE_ERROR');

  const nonArray = await cli(['edit', 'apply', '--operations-json', '{}', '--project', project, '--json']);
  assert.equal(nonArray.status, 2);
  assert.equal(nonArray.stdout, '');
  assert.equal(JSON.parse(nonArray.stderr).error.code, 'OPERATIONS_INVALID');
});
