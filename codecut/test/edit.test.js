import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { mkdtemp, readFile, readdir, rm, writeFile } from 'node:fs/promises';
import { hostname, tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { applyEdit, applyOperations, parseSrt } from '../dist/edit.js';
import { getProjectLockPath, withProjectLock } from '../dist/project-lock.js';
import { calculateTimeline, createDefaultProject, initProject, loadProject } from '../dist/project.js';

async function temporaryDirectory(t) {
  const directory = await mkdtemp(join(tmpdir(), 'codecut-edit-test-'));
  t.after(() => rm(directory, { recursive: true, force: true }));
  return directory;
}

function editableProject() {
  const project = createDefaultProject('/tmp/edit', 'edit');
  project.assets = [
    { id: 'video', kind: 'video', path: 'media/video.mp4' },
    { id: 'image', kind: 'image', path: 'media/image.png' },
    { id: 'audio', kind: 'audio', path: 'media/audio.wav' },
  ];
  return project;
}

function findClip(project, id) {
  return project.tracks.flatMap((track) => track.clips).find((clip) => clip.id === id);
}

async function directoryFiles(directory) {
  const names = await readdir(directory, { recursive: true });
  return Promise.all(names.sort().map(async (name) => ({ name, content: await readFile(join(directory, name), 'utf8') })));
}

test('all structured operations compose multi-track timelines with source-accurate splits', async () => {
  const original = editableProject();
  const result = await applyOperations(original, [
    { type: 'addTrack', track: { id: 'v3', kind: 'video', clips: [] } },
    { type: 'addTrack', track: { id: 'a3', kind: 'audio', clips: [] } },
    { type: 'addClip', trackId: 'v1', clip: { id: 'main', type: 'video', assetId: 'video', start: 0, duration: 6, sourceStart: 1, speed: 2 } },
    { type: 'addClip', trackId: 'v2', clip: { id: 'overlay', type: 'image', assetId: 'image', start: 1, duration: 2 } },
    { type: 'addClip', trackId: 'v3', clip: { id: 'background', type: 'color', color: '#112233', start: 0, duration: 2 } },
    { type: 'addClip', trackId: 'a1', clip: { id: 'music', type: 'audio', assetId: 'audio', start: 0, duration: 8, volume: 0.4 } },
    { type: 'addClip', trackId: 'a3', clip: { id: 'voice', type: 'audio', assetId: 'video', start: 1, duration: 3 } },
    { type: 'addText', trackId: 'v3', clip: { id: 'title', type: 'text', text: 'Hello', start: 2, duration: 2, fontSize: 64, align: 'left' } },
    { type: 'trimClip', clipId: 'main', sourceStart: 2, duration: 4 },
    { type: 'moveClip', clipId: 'overlay', targetTrackId: 'v3', start: 4 },
    { type: 'splitClip', clipId: 'main', at: 1, rightClipId: 'main-right' },
    {
      type: 'setClipParams',
      clipId: 'main-right',
      params: {
        crop: { x: 10, y: 20, width: 640, height: 360 },
        scale: 1.25,
        position: { x: 30, y: 40 },
        opacity: 0.75,
        volume: 0.8,
        fadeIn: 0.25,
        fadeOut: 0.5,
      },
    },
    { type: 'removeClip', clipId: 'background' },
    { type: 'removeTrack', trackId: 'v2' },
  ]);

  assert.deepEqual(original.tracks.map((track) => track.clips.length), [0, 0, 0, 0], 'pure editing does not mutate input');
  assert.deepEqual(result.tracks.map((track) => track.id), ['v1', 'a1', 'a2', 'v3', 'a3']);
  assert.equal(findClip(result, 'main').duration, 1);
  assert.equal(findClip(result, 'main-right').sourceStart, 4, 'split advances source in-point by timeline offset × speed');
  assert.equal(findClip(result, 'main-right').duration, 3);
  assert.equal(findClip(result, 'main-right').fadeIn, 0.25);
  assert.equal(findClip(result, 'main-right').opacity, 0.75);
  assert.equal(findClip(result, 'main').fadeOut, undefined);
  assert.equal(findClip(result, 'overlay').start, 4);
  assert.equal(result.tracks.find((track) => track.id === 'v3').kind, 'video');
  assert.equal(findClip(result, 'background'), undefined);

  const timeline = calculateTimeline(result);
  assert.equal(timeline.duration, 8);
  assert.equal(timeline.tracks.find((track) => track.id === 'v1').clips[1].sourceEnd, 10);
  assert.equal(timeline.tracks.find((track) => track.id === 'v3').clipCount, 2);
  assert.equal(timeline.tracks.filter((track) => track.kind === 'audio').length, 3);
});

test('SRT parsing handles timecodes, multiline text, tags and escaped entities', async (t) => {
  const directory = await temporaryDirectory(t);
  await initProject(directory);
  const source = `1\n00:00:01,000 --> 00:00:02.500\n<i>A &amp; B</i><br>next &#x1F600;\n\n2\n01:02:03.25 --> 01:02:04,750\n&lt;literal&gt; &quot;quoted&quot;\n`;
  const path = join(directory, 'captions.srt');
  await writeFile(path, source, 'utf8');

  const cues = parseSrt(source);
  assert.deepEqual(cues[0], { index: 1, start: 1, end: 2.5, text: 'A & B\nnext 😀' });
  assert.equal(cues[1].start, 3723.25);
  assert.equal(cues[1].end, 3724.75);
  assert.equal(cues[1].text, '<literal> "quoted"');
  assert.throws(() => parseSrt('1\n00:00:02,000 --> 00:00:01,000\nbad\n'), (error) => error.code === 'SRT_PARSE_ERROR');

  const result = await applyEdit(directory, [{ type: 'importSrt', trackId: 'v2', path: 'captions.srt' }]);
  const clips = result.project.tracks.find((track) => track.id === 'v2').clips;
  assert.equal(clips.length, 2);
  assert.deepEqual(clips.map((clip) => [clip.id, clip.start, clip.duration]), [['srt-1', 1, 1.5], ['srt-2', 3723.25, 1.5]]);
  assert.equal(clips[0].text, 'A & B\nnext 😀');
  assert.equal(await readFile(path, 'utf8'), source, 'SRT import never changes the source subtitle');
});

test('parameter, track compatibility, transition and operation index validation are atomic on disk', async (t) => {
  const directory = await temporaryDirectory(t);
  const { path } = await initProject(directory);
  const before = await readFile(path, 'utf8');

  await assert.rejects(applyEdit(directory, [
    { type: 'addClip', trackId: 'v1', clip: { id: 'valid', type: 'color', color: '#000000', start: 0, duration: 2 } },
    { type: 'removeClip', clipId: 'missing' },
  ]), (error) => {
    assert.equal(error.code, 'CLIP_NOT_FOUND');
    assert.equal(error.operationIndex, 1);
    return true;
  });
  assert.equal(await readFile(path, 'utf8'), before, 'a later operation failure restores the original byte-for-byte project');
  assert.deepEqual(await readdir(directory), ['project.json'], 'failed edits leave no history or lock files');

  const invalidOperations = [
    { type: 'setClipParams', clipId: 'valid', params: { speed: 0 } },
    { type: 'setClipParams', clipId: 'valid', params: { opacity: 2 } },
    { type: 'setClipParams', clipId: 'valid', params: { scale: -1 } },
    { type: 'setClipParams', clipId: 'valid', params: { volume: -0.1 } },
    { type: 'setClipParams', clipId: 'valid', params: { fadeIn: 3 } },
    { type: 'setClipParams', clipId: 'valid', params: { crop: { x: 0, y: 0, width: 0, height: 10 } } },
  ];
  for (const operation of invalidOperations) {
    await assert.rejects(applyEdit(directory, [{ type: 'addClip', trackId: 'v1', clip: { id: 'valid', type: 'color', color: '#000000', start: 0, duration: 2 } }, operation]), (error) => {
      assert.equal(error.operationIndex, 1);
      return true;
    });
  }

  await assert.rejects(applyOperations(editableProject(), [
    { type: 'addClip', trackId: 'a1', clip: { id: 'sound', type: 'audio', assetId: 'audio', start: 0, duration: 2 } },
    { type: 'moveClip', clipId: 'sound', targetTrackId: 'v1', start: 0 },
  ]), (error) => error.code === 'TRACK_TYPE_MISMATCH' && error.operationIndex === 1);

  await assert.rejects(applyOperations(editableProject(), [
    { type: 'addClip', trackId: 'v1', clip: { id: 'one', type: 'color', color: '#000000', start: 0, duration: 5 } },
    { type: 'addClip', trackId: 'v1', clip: { id: 'two', type: 'color', color: '#FFFFFF', start: 4, duration: 2 } },
  ]), (error) => error.operationIndex === 1);
  const transitioned = await applyOperations(editableProject(), [
    { type: 'addClip', trackId: 'v1', clip: { id: 'one', type: 'color', color: '#000000', start: 0, duration: 5 } },
    { type: 'addClip', trackId: 'v1', clip: { id: 'two', type: 'color', color: '#FFFFFF', start: 4, duration: 2, transition: { type: 'xfade', duration: 1, name: 'fade' } } },
  ]);
  assert.equal(calculateTimeline(transitioned).duration, 6);
});

test('dry-run returns structured diffs without any persistent write and real commit is atomic JSON', async (t) => {
  const directory = await temporaryDirectory(t);
  const { path } = await initProject(directory);
  const beforeFiles = await directoryFiles(directory);
  const before = await readFile(path, 'utf8');
  const operations = [{ type: 'addClip', trackId: 'v1', clip: { id: 'background', type: 'color', color: '#123456', start: 0, duration: 2 } }];

  const preview = await applyEdit(directory, operations, { dryRun: true });
  assert.equal(preview.dryRun, true);
  assert.equal(preview.revision, undefined);
  assert.equal(preview.project.revision, 1);
  assert.ok(preview.diff.some((entry) => entry.op === 'add' && entry.path.includes('/clips/0')));
  assert.ok(preview.diff.some((entry) => entry.path === '/revision'));
  assert.equal(await readFile(path, 'utf8'), before);
  assert.deepEqual(await directoryFiles(directory), beforeFiles, 'dry-run leaves no lock, revision, temp, or cache files');

  const committed = await applyEdit(directory, operations);
  assert.equal(committed.dryRun, false);
  assert.equal(committed.revision.projectRevision, 1);
  assert.equal(committed.revision.parentId, undefined);
  assert.match(committed.revision.summary, /addClip/);
  assert.deepEqual(JSON.parse(await readFile(path, 'utf8')), committed.project);
  assert.equal((await loadProject(directory)).project.tracks[0].clips[0].id, 'background');
});

test('project locks reject active and nested writers and recover a crashed owner lock', async (t) => {
  const directory = await temporaryDirectory(t);
  await initProject(directory);
  const lockPath = getProjectLockPath(directory);
  let release;
  let entered;
  const enteredLock = new Promise((resolve) => { entered = resolve; });
  const gate = new Promise((resolve) => { release = resolve; });
  const holder = withProjectLock(directory, () => { entered(); return gate; });
  await enteredLock;

  await assert.rejects(withProjectLock(directory, () => undefined), (error) => error.code === 'PROJECT_LOCKED');
  release();
  await holder;
  await assert.rejects(withProjectLock(directory, () => withProjectLock(directory, () => undefined)), (error) => error.code === 'PROJECT_LOCKED');
  assert.deepEqual(await readdir(directory), ['project.json']);

  const child = spawn(process.execPath, ['-e', 'process.exit(0)'], { stdio: 'ignore' });
  await new Promise((resolve, reject) => { child.once('exit', resolve); child.once('error', reject); });
  await writeFile(lockPath, JSON.stringify({ version: 1, pid: child.pid, hostname: hostname(), token: 'crashed', createdAt: new Date().toISOString() }), 'utf8');
  assert.equal(await withProjectLock(directory, () => 'recovered'), 'recovered');
  assert.deepEqual(await readdir(directory), ['project.json']);
});
