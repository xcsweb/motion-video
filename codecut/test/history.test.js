import assert from 'node:assert/strict';
import { mkdir, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { applyEdit } from '../dist/edit.js';
import {
  diffProjects,
  diffRevisions,
  getRevisionSnapshot,
  listHistory,
  redoProject,
  undoProject,
} from '../dist/history.js';
import { calculateTimeline, initProject, loadProject } from '../dist/project.js';

async function temporaryDirectory(t) {
  const directory = await mkdtemp(join(tmpdir(), 'codecut-history-test-'));
  t.after(() => rm(directory, { recursive: true, force: true }));
  return directory;
}

function clips(project, trackId = 'v1') {
  return project.tracks.find((track) => track.id === trackId).clips;
}

test('immutable snapshots, parent links, arbitrary diffs, undo/redo and redo truncation share history', async (t) => {
  const directory = await temporaryDirectory(t);
  const { path, project } = await initProject(directory);
  const mediaDirectory = join(directory, 'media');
  await mkdir(mediaDirectory);
  const sourcePath = join(mediaDirectory, 'source.mp4');
  await writeFile(sourcePath, 'original-media-bytes', 'utf8');
  project.assets = [{ id: 'source', kind: 'video', path: 'media/source.mp4' }];
  await writeFile(path, JSON.stringify(project, null, 2), 'utf8');

  const first = await applyEdit(directory, [{
    type: 'addClip',
    trackId: 'v1',
    clip: { id: 'main', type: 'video', assetId: 'source', start: 0, duration: 4, sourceStart: 1, speed: 2 },
  }], { summary: 'Add main video' });
  const firstSnapshotRaw = await readFile(join(directory, first.revision.snapshotPath), 'utf8');
  const second = await applyEdit(directory, [{
    type: 'addText',
    trackId: 'v1',
    clip: { id: 'title', type: 'text', text: 'Title', start: 4, duration: 2 },
  }]);

  assert.equal(first.revision.summary, 'Add main video');
  assert.equal(second.revision.parentId, first.revision.id);
  const firstSnapshot = await getRevisionSnapshot(directory, first.revision.id);
  assert.equal(Object.isFrozen(firstSnapshot), true);
  assert.equal(Object.isFrozen(firstSnapshot.tracks), true);
  assert.equal(clips(firstSnapshot).length, 1);
  assert.equal(clips(second.project).length, 2);
  assert.throws(() => { firstSnapshot.name = 'mutated'; }, TypeError);
  assert.equal((await getRevisionSnapshot(directory, first.revision.id)).name, project.name);

  const forwardDiff = await diffRevisions(directory, first.revision.id, second.revision.id);
  assert.ok(forwardDiff.diff.some((entry) => entry.op === 'add' && entry.after?.id === 'title'));
  const baseDiff = await diffRevisions(directory, null, first.revision.id);
  assert.ok(baseDiff.diff.some((entry) => entry.after?.id === 'main'));
  assert.deepEqual(diffProjects(firstSnapshot, firstSnapshot), []);

  const undone = await undoProject(directory);
  assert.match(undone.revision.summary, /^Undo /);
  assert.equal(undone.revision.parentId, second.revision.id);
  assert.deepEqual(clips(undone.project).map((clip) => clip.id), ['main']);
  assert.deepEqual(JSON.parse(await readFile(path, 'utf8')), undone.project);
  assert.equal((await listHistory(directory)).canRedo, true);

  const redone = await redoProject(directory);
  assert.match(redone.revision.summary, /^Redo /);
  assert.deepEqual(clips(redone.project).map((clip) => clip.id), ['main', 'title']);
  assert.equal(redone.project.revision, 4);

  const undoneAgain = await undoProject(directory);
  assert.deepEqual(clips(undoneAgain.project).map((clip) => clip.id), ['main']);
  const replacement = await applyEdit(directory, [{
    type: 'setClipParams',
    clipId: 'main',
    params: { opacity: 0.5 },
  }], { summary: 'Adjust opacity on a new branch' });
  assert.equal(replacement.revision.parentId, undoneAgain.revision.id);
  assert.equal(clips(replacement.project)[0].opacity, 0.5);
  await assert.rejects(redoProject(directory), (error) => error.code === 'HISTORY_REDO_UNAVAILABLE');

  const history = await listHistory(directory);
  assert.equal(history.revisions.length, 6, 'undo/redo are immutable transactional revisions too');
  assert.equal(history.currentId, replacement.revision.id);
  assert.equal(history.canRedo, false);
  assert.equal(history.revisions.filter((revision) => revision.summary.startsWith('Undo ')).length, 2);
  assert.equal(history.revisions.filter((revision) => revision.summary.startsWith('Redo ')).length, 1);
  assert.equal(await readFile(join(directory, first.revision.snapshotPath), 'utf8'), firstSnapshotRaw, 'later history never overwrites an old snapshot');
  assert.equal(await readFile(sourcePath, 'utf8'), 'original-media-bytes', 'history operations never modify original media');
});

test('history inspection and dry-run are read-only, and dry-run undo does not move pointers', async (t) => {
  const directory = await temporaryDirectory(t);
  const { path } = await initProject(directory);
  const committed = await applyEdit(directory, [{
    type: 'addClip',
    trackId: 'v1',
    clip: { id: 'background', type: 'color', color: '#010203', start: 0, duration: 2 },
  }]);
  const historyPath = join(directory, '.codecut', 'history.json');
  const stateBefore = await readFile(historyPath, 'utf8');
  const projectBefore = await readFile(path, 'utf8');

  const preview = await applyEdit(directory, [{
    type: 'setClipParams',
    clipId: 'background',
    params: { opacity: 0.2 },
  }], { dryRun: true });
  assert.equal(preview.project.tracks[0].clips[0].opacity, 0.2);
  assert.equal(preview.revision, undefined);
  const undoPreview = await undoProject(directory, { dryRun: true });
  assert.equal(undoPreview.project.tracks[0].clips.length, 0);
  assert.equal(undoPreview.revision, undefined);

  const loaded = await loadProject(directory);
  calculateTimeline(loaded.project);
  await getRevisionSnapshot(directory, committed.revision.id);
  await diffRevisions(directory, committed.revision.id, committed.revision.id);
  const history = await listHistory(directory);
  assert.equal(history.revisions.length, 1, 'read, inspection, analysis-style calculation and dry-run create no revisions');
  assert.equal(await readFile(historyPath, 'utf8'), stateBefore);
  assert.equal(await readFile(path, 'utf8'), projectBefore);

  await assert.rejects(redoProject(directory), (error) => error.code === 'HISTORY_REDO_UNAVAILABLE');
  assert.equal((await listHistory(directory)).revisions.length, 1, 'failed navigation creates no revision');
});
