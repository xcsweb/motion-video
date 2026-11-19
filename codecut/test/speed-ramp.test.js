import assert from 'node:assert/strict';
import test from 'node:test';
import { applyOperations } from '../dist/edit.js';
import { createDefaultProject } from '../dist/project.js';

function editableProject() {
  const project = createDefaultProject('/tmp/ramp', 'ramp');
  project.assets = [
    { id: 'video', kind: 'video', path: 'media/video.mp4' },
    { id: 'image', kind: 'image', path: 'media/image.png' },
    { id: 'audio', kind: 'audio', path: 'media/audio.wav' },
  ];
  return project;
}

function clipsOf(project) {
  return project.tracks.flatMap((track) => track.clips);
}

function clipById(project, id) {
  return clipsOf(project).find((clip) => clip.id === id);
}

const baseClip = { id: 'ramp', type: 'video', assetId: 'video', start: 2, duration: 4, sourceStart: 1 };

test('speed ramp splits a clip into sequential constant-speed slices', async () => {
  const project = await applyOperations(editableProject(), [
    { type: 'addClip', trackId: 'v1', clip: baseClip },
    {
      type: 'setSpeedRamp',
      clipId: 'ramp',
      steps: 4,
      points: [{ at: 0, speed: 1 }, { at: 1, speed: 1 }],
    },
  ]);

  const clips = clipsOf(project);
  assert.equal(clips.length, 4);
  assert.deepEqual(clips.map((clip) => clip.id), ['ramp', 'ramp-r1', 'ramp-r2', 'ramp-r3']);
  for (const clip of clips) {
    assert.equal(clip.duration, 1);
    assert.equal(clip.speed, 1);
  }
  assert.deepEqual(clips.map((clip) => clip.sourceStart), [1, 2, 3, 4]);
  assert.deepEqual(clips.map((clip) => clip.start), [2, 3, 4, 5]);
});

test('speed ramp follows the linear curve and keeps total source span', async () => {
  const project = await applyOperations(editableProject(), [
    { type: 'addClip', trackId: 'v1', clip: baseClip },
    {
      type: 'setSpeedRamp',
      clipId: 'ramp',
      steps: 4,
      points: [{ at: 0, speed: 0.5 }, { at: 1, speed: 2 }],
    },
  ]);

  const clips = clipsOf(project);
  assert.equal(clips.length, 4);
  const speeds = clips.map((clip) => Number(clip.speed.toFixed(4)));
  assert.deepEqual(speeds, [0.6875, 1.0625, 1.4375, 1.8125]);
  const sourceTotal = clips.reduce((sum, clip) => sum + clip.duration * clip.speed, 0);
  assert.ok(Math.abs(sourceTotal - 4) < 1e-9, `source span drifted: ${sourceTotal}`);
  const timelineTotal = clips.reduce((sum, clip) => sum + clip.duration, 0);
  const expected = clips.reduce((sum, clip) => sum + 1 / clip.speed, 0);
  assert.ok(Math.abs(timelineTotal - expected) < 1e-9);
});

test('speed ramp keeps the transition only on the last slice', async () => {
  const project = await applyOperations(editableProject(), [
    { type: 'addClip', trackId: 'v1', clip: { ...baseClip, transition: { type: 'xfade', duration: 0.4 } } },
    { type: 'setSpeedRamp', clipId: 'ramp', steps: 3, points: [{ at: 0, speed: 1 }, { at: 1, speed: 1 }] },
  ]);

  const clips = clipsOf(project);
  assert.equal(clips.length, 3);
  assert.equal(clips[0].transition, undefined);
  assert.equal(clips[1].transition, undefined);
  assert.deepEqual(clips[2].transition, { type: 'xfade', duration: 0.4 });
});

test('speed ramp rejects still clips and duplicate positions', async () => {
  const project = await applyOperations(editableProject(), [
    { type: 'addClip', trackId: 'v1', clip: { id: 'still', type: 'image', assetId: 'image', start: 0, duration: 2 } },
    { type: 'addClip', trackId: 'v1', clip: baseClip },
  ]);

  await assert.rejects(
    applyOperations(project, [
      { type: 'setSpeedRamp', clipId: 'still', points: [{ at: 0, speed: 1 }, { at: 1, speed: 1 }] },
    ]),
    /has no running source/,
  );

  await assert.rejects(
    applyOperations(project, [
      { type: 'setSpeedRamp', clipId: 'ramp', points: [{ at: 0.5, speed: 1 }, { at: 0.5, speed: 2 }] },
    ]),
    /distinct positions/,
  );
});

test('setClipParams applies and clears effects on visual clips', async () => {
  const withEffects = await applyOperations(editableProject(), [
    { type: 'addClip', trackId: 'v1', clip: baseClip },
    {
      type: 'setClipParams',
      clipId: 'ramp',
      params: { effects: [{ type: 'shake', amplitude: 12 }, { type: 'flash', at: 0.8 }] },
    },
  ]);

  const clip = clipById(withEffects, 'ramp');
  assert.equal(clip.effects.length, 2);
  assert.equal(clip.effects[0].type, 'shake');
  assert.equal(clip.effects[0].amplitude, 12);

  const cleared = await applyOperations(withEffects, [
    { type: 'setClipParams', clipId: 'ramp', params: { effects: [] } },
  ]);
  assert.deepEqual(clipById(cleared, 'ramp').effects, []);
  assert.equal(withEffects.tracks[0].clips[0].effects.length, 2, 'applying does not mutate the input project');
});

test('setClipParams refuses effects on audio clips', async () => {
  const project = await applyOperations(editableProject(), [
    { type: 'addClip', trackId: 'a1', clip: { id: 'music', type: 'audio', assetId: 'audio', start: 0, duration: 5 } },
  ]);

  await assert.rejects(
    applyOperations(project, [
      { type: 'setClipParams', clipId: 'music', params: { effects: [{ type: 'shake' }] } },
    ]),
    /is audio/,
  );
});
