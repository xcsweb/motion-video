import assert from 'node:assert/strict';
import { mkdtemp, readFile, readdir, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { ExitCode } from '../dist/errors.js';
import {
  calculateTimeline,
  createDefaultProject,
  initProject,
  loadProject,
  validateProjectData,
  writeJsonAtomic,
} from '../dist/project.js';

async function temporaryDirectory(t) {
  const directory = await mkdtemp(join(tmpdir(), 'codecut-project-test-'));
  t.after(() => rm(directory, { recursive: true, force: true }));
  return directory;
}

function baseProject() {
  return createDefaultProject('/tmp/example', 'example');
}

test('init creates a versioned multi-track project and protects overwrites', async (t) => {
  const directory = await temporaryDirectory(t);
  const { project, path } = await initProject(directory, { name: 'first' });

  assert.equal(project.schemaVersion, 1);
  assert.equal(project.tracks.filter((track) => track.kind === 'video').length, 2);
  assert.equal(project.tracks.filter((track) => track.kind === 'audio').length, 2);
  assert.equal(project.output.audioSampleRate, 48000);
  assert.equal(project.output.audioChannels, 2);
  assert.equal(project.output.path, 'output.mp4');
  assert.deepEqual(JSON.parse(await readFile(path, 'utf8')), project);
  assert.deepEqual(validateProjectData(project), project);

  const before = await readFile(path, 'utf8');
  await assert.rejects(initProject(directory, { name: 'should-not-win' }), (error) => {
    assert.equal(error.code, 'PROJECT_EXISTS');
    assert.equal(error.exitCode, ExitCode.Usage);
    assert.equal(error.path, path);
    return true;
  });
  assert.equal(await readFile(path, 'utf8'), before);

  const replacement = await initProject(directory, { force: true, name: 'replacement' });
  assert.equal(replacement.project.name, 'replacement');
  assert.equal(JSON.parse(await readFile(path, 'utf8')).name, 'replacement');
  assert.equal((await readdir(directory)).filter((name) => name.endsWith('.tmp')).length, 0);
});

test('load reports missing, malformed, and unsupported projects distinctly', async (t) => {
  const directory = await temporaryDirectory(t);
  const path = join(directory, 'project.json');

  await assert.rejects(loadProject(directory), (error) => {
    assert.equal(error.code, 'PROJECT_NOT_FOUND');
    assert.equal(error.exitCode, ExitCode.ProjectValidation);
    assert.equal(error.path, path);
    return true;
  });

  await writeFile(path, '{broken', 'utf8');
  await assert.rejects(loadProject(directory), (error) => {
    assert.equal(error.code, 'PROJECT_PARSE_ERROR');
    assert.equal(error.path, path);
    return true;
  });

  const unsupported = { ...baseProject(), schemaVersion: 99 };
  await writeFile(path, JSON.stringify(unsupported), 'utf8');
  await assert.rejects(loadProject(directory, 'project.validate'), (error) => {
    assert.equal(error.code, 'PROJECT_VERSION_UNSUPPORTED');
    assert.equal(error.stage, 'project.validate');
    assert.equal(error.diagnostics.issues[0].path, '/schemaVersion');
    return true;
  });
});

test('all clip kinds, track kinds, parameters, and timeline calculations share the model', () => {
  const project = baseProject();
  project.assets = [
    { id: 'video', kind: 'video', path: '../media/source.mp4' },
    { id: 'audio', kind: 'audio', path: 'audio/music.wav' },
    { id: 'image', kind: 'image', path: 'images/overlay.png' },
  ];
  project.tracks[0].clips = [
    {
      id: 'main', type: 'video', assetId: 'video', start: 0, duration: 4,
      sourceStart: 1, speed: 2, crop: { x: 0, y: 0, width: 1280, height: 720 },
      scale: 1.2, position: { x: 10, y: 20 }, opacity: 0.9, volume: 0.8,
      fadeIn: 0.2, fadeOut: 0.3,
    },
    { id: 'color', type: 'color', color: '#112233', start: 4, duration: 2 },
    {
      id: 'title', type: 'text', text: 'Hello', start: 6, duration: 2,
      fontFamily: 'sans', fontSize: 52, color: '#FFFFFF', align: 'center',
    },
  ];
  project.tracks[1].clips = [
    { id: 'overlay', type: 'image', assetId: 'image', start: 0, duration: 8 },
  ];
  project.tracks[2].clips = [
    { id: 'music', type: 'audio', assetId: 'audio', start: 0, duration: 8, volume: 0.4 },
    { id: 'source-audio', type: 'audio', assetId: 'video', start: 8, duration: 2 },
  ];

  const validated = validateProjectData(project);
  const timeline = calculateTimeline(validated);
  assert.equal(timeline.duration, 10);
  assert.equal(timeline.tracks[0].clips[0].sourceEnd, 9);
  assert.equal(timeline.tracks[0].duration, 8);
  assert.equal(timeline.tracks[2].duration, 10);
  assert.deepEqual(timeline.tracks.map((track) => track.clipCount), [3, 1, 2, 0]);
});

test('validation identifies field paths for bad paths and asset references', () => {
  const project = baseProject();
  project.assets = [{ id: 'asset', kind: 'video', path: '/absolute/source.mp4' }];
  assert.throws(() => validateProjectData(project), (error) => {
    assert.equal(error.code, 'PROJECT_VALIDATION_ERROR');
    assert.ok(error.diagnostics.issues.some((issue) => issue.path === '/assets/0/path'));
    return true;
  });

  project.assets[0].path = '../media/source.mp4';
  project.tracks[0].clips = [
    { id: 'broken', type: 'video', assetId: 'missing', start: 0, duration: 1 },
  ];
  assert.throws(() => validateProjectData(project), (error) => {
    assert.equal(error.code, 'PROJECT_VALIDATION_ERROR');
    assert.ok(error.diagnostics.issues.some((issue) => issue.path === '/tracks/0/clips/0/assetId'));
    return true;
  });
});

test('timeline overlap requires a matching xfade', () => {
  const project = baseProject();
  project.tracks[0].clips = [
    { id: 'one', type: 'color', color: '#000000', start: 0, duration: 5 },
    { id: 'two', type: 'color', color: '#FFFFFF', start: 4, duration: 2 },
  ];
  assert.throws(() => validateProjectData(project), /overlap|validation failed/i);

  project.tracks[0].clips[1].transition = { type: 'xfade', duration: 1 };
  assert.equal(calculateTimeline(validateProjectData(project)).duration, 6);
});

test('concurrent create-only writes publish exactly one complete project', async (t) => {
  const directory = await temporaryDirectory(t);
  const attempts = await Promise.allSettled(
    Array.from({ length: 8 }, (_, index) => initProject(directory, { name: `project-${index}` })),
  );
  assert.equal(attempts.filter((result) => result.status === 'fulfilled').length, 1);
  for (const result of attempts.filter((entry) => entry.status === 'rejected')) {
    assert.equal(result.reason.code, 'PROJECT_EXISTS');
  }
  const stored = JSON.parse(await readFile(join(directory, 'project.json'), 'utf8'));
  assert.match(stored.name, /^project-\d$/);
  assert.doesNotThrow(() => validateProjectData(stored));
  assert.equal((await readdir(directory)).filter((name) => name.endsWith('.tmp')).length, 0);
});

test('a failed forced write preserves the old project and leaves no temporary file', async (t) => {
  const directory = await temporaryDirectory(t);
  const { path } = await initProject(directory, { name: 'stable' });
  const before = await readFile(path, 'utf8');
  const circular = {};
  circular.self = circular;

  await assert.rejects(writeJsonAtomic(path, circular, { force: true }), (error) => {
    assert.equal(error.code, 'PROJECT_WRITE_FAILED');
    return true;
  });
  assert.equal(await readFile(path, 'utf8'), before);
  assert.equal((await readdir(directory)).filter((name) => name.endsWith('.tmp')).length, 0);
});
