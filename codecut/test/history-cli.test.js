import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { mkdtemp, readFile, readdir, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import test from 'node:test';

const root = dirname(dirname(fileURLToPath(import.meta.url)));
const cliPath = join(root, 'dist', 'cli.js');

function cli(args) {
  return new Promise((resolve, reject) => {
    const child = spawn(process.execPath, [cliPath, ...args], { cwd: root, stdio: ['ignore', 'pipe', 'pipe'] });
    let stdout = '';
    let stderr = '';
    child.stdout.setEncoding('utf8');
    child.stderr.setEncoding('utf8');
    child.stdout.on('data', (chunk) => { stdout += chunk; });
    child.stderr.on('data', (chunk) => { stderr += chunk; });
    child.once('error', reject);
    child.once('close', (status) => resolve({ status, stdout, stderr }));
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

test('real bin edit/history flow supports diffs, dry-run navigation, undo/redo, and branch truncation', async (t) => {
  const directory = await mkdtemp(join(tmpdir(), 'codecut-history-cli-test-'));
  t.after(() => rm(directory, { recursive: true, force: true }));
  const project = join(directory, 'project');
  const projectPath = join(project, 'project.json');
  const historyPath = join(project, '.codecut', 'history.json');
  const operationsPath = join(directory, 'background.json');
  const background = [{
    type: 'addClip',
    trackId: 'v1',
    clip: { id: 'background', type: 'color', color: '#102030', start: 0, duration: 2 },
  }];
  const title = [{
    type: 'addText',
    trackId: 'v1',
    clip: { id: 'title', type: 'text', text: 'Title', start: 2, duration: 2 },
  }];
  await writeFile(operationsPath, JSON.stringify(background), 'utf8');
  success(await cli(['project', 'init', project, '--json']), 'project.init');

  const initialPreview = success(await cli([
    'edit', 'apply', operationsPath, '--project', project, '--dry-run', '--json',
  ]), 'edit.apply');
  assert.equal(initialPreview.revision, undefined);
  assert.deepEqual(await readdir(project), ['project.json']);
  const emptyHistory = success(await cli(['history', 'list', '--project', project, '--json']), 'history.list');
  assert.deepEqual(emptyHistory.revisions, []);
  assert.equal(emptyHistory.canUndo, false);
  assert.equal(emptyHistory.canRedo, false);

  const first = success(await cli([
    'edit', 'apply', operationsPath, '--project', project, '--summary', 'Add background', '--json',
  ]), 'edit.apply');
  const second = success(await cli([
    'edit', 'apply', '--operations-json', JSON.stringify(title), '--project', project, '--summary', 'Add title', '--json',
  ]), 'edit.apply');
  assert.equal(second.revision.parentId, first.revision.id);

  const history = success(await cli(['history', 'list', '--project', project, '--json']), 'history.list');
  assert.equal(history.revisions.length, 2);
  assert.equal(history.currentId, second.revision.id);
  assert.equal(history.revisions[0].summary, 'Add background');
  assert.equal(history.revisions[1].summary, 'Add title');

  const revisionDiff = success(await cli([
    'history', 'diff', first.revision.id, second.revision.id, '--project', project, '--json',
  ]), 'history.diff');
  assert.equal(revisionDiff.fromId, first.revision.id);
  assert.equal(revisionDiff.toId, second.revision.id);
  assert.ok(revisionDiff.diff.some((entry) => entry.after?.id === 'title'));

  const beforeUndoDryProject = await readFile(projectPath, 'utf8');
  const beforeUndoDryHistory = await readFile(historyPath, 'utf8');
  const undoPreview = success(await cli([
    'history', 'undo', '--project', project, '--dry-run', '--json',
  ]), 'history.undo');
  assert.equal(undoPreview.dryRun, true);
  assert.equal(undoPreview.revision, undefined);
  assert.deepEqual(undoPreview.project.tracks[0].clips.map((clip) => clip.id), ['background']);
  assert.equal(await readFile(projectPath, 'utf8'), beforeUndoDryProject);
  assert.equal(await readFile(historyPath, 'utf8'), beforeUndoDryHistory);

  const undone = success(await cli(['history', 'undo', '--project', project, '--json']), 'history.undo');
  assert.match(undone.revision.summary, /^Undo /);
  assert.deepEqual(undone.project.tracks[0].clips.map((clip) => clip.id), ['background']);

  const beforeRedoDryProject = await readFile(projectPath, 'utf8');
  const beforeRedoDryHistory = await readFile(historyPath, 'utf8');
  const redoPreview = success(await cli([
    'history', 'redo', '--project', project, '--dry-run', '--json',
  ]), 'history.redo');
  assert.equal(redoPreview.dryRun, true);
  assert.equal(redoPreview.revision, undefined);
  assert.deepEqual(redoPreview.project.tracks[0].clips.map((clip) => clip.id), ['background', 'title']);
  assert.equal(await readFile(projectPath, 'utf8'), beforeRedoDryProject);
  assert.equal(await readFile(historyPath, 'utf8'), beforeRedoDryHistory);

  const redone = success(await cli(['history', 'redo', '--project', project, '--json']), 'history.redo');
  assert.match(redone.revision.summary, /^Redo /);
  assert.deepEqual(redone.project.tracks[0].clips.map((clip) => clip.id), ['background', 'title']);
  const undoneAgain = success(await cli(['history', 'undo', '--project', project, '--json']), 'history.undo');
  assert.deepEqual(undoneAgain.project.tracks[0].clips.map((clip) => clip.id), ['background']);

  const replacement = success(await cli([
    'edit', 'apply', '--operations-json', JSON.stringify([{
      type: 'setClipParams', clipId: 'background', params: { opacity: 0.5 },
    }]), '--project', project, '--summary', 'Replace redo branch', '--json',
  ]), 'edit.apply');
  assert.equal(replacement.project.tracks[0].clips[0].opacity, 0.5);
  assert.equal(replacement.revision.parentId, undoneAgain.revision.id);

  const truncated = success(await cli(['history', 'list', '--project', project, '--json']), 'history.list');
  assert.equal(truncated.canRedo, false);
  assert.equal(truncated.currentId, replacement.revision.id);
  assert.equal(truncated.revisions.length, 6);
  const redoFailure = await cli(['history', 'redo', '--project', project, '--json']);
  assert.equal(redoFailure.status, 3);
  assert.equal(redoFailure.stdout, '');
  assert.equal(JSON.parse(redoFailure.stderr).error.code, 'HISTORY_REDO_UNAVAILABLE');

  const arbitraryDiff = success(await cli([
    'history', 'diff', first.revision.id, replacement.revision.id, '--project', project, '--json',
  ]), 'history.diff');
  assert.ok(arbitraryDiff.diff.some((entry) => entry.path.endsWith('/opacity') && entry.after === 0.5));
});
