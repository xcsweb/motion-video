import assert from 'node:assert/strict';
import test from 'node:test';
import { ExitCode } from '../dist/errors.js';
import { applyOperations } from '../dist/edit.js';
import { validateProjectData } from '../dist/project.js';
import { compileRenderPlan } from '../dist/render-plan.js';

function audioAsset(id) {
  return {
    asset: {
      id,
      kind: 'audio',
      path: `${id}.wav`,
      metadata: {
        probedAt: '2026-01-01T00:00:00.000Z',
        fingerprint: { size: 1, mtimeMs: 1 },
        duration: 100,
        size: 1,
        streams: [{ index: 0, codecType: 'audio', codecName: 'pcm_s16le', sampleRate: 48000, channels: 2 }],
      },
    },
    absolutePath: `/tmp/${id}.wav`,
    fingerprint: { size: 1, mtimeMs: 1 },
    hasVideo: false,
    hasAudio: true,
  };
}

function projectWithAudio({ video = true, bgmDucking, sfx } = {}) {
  const tracks = [
    {
      id: 'v1',
      kind: 'video',
      clips: video
        ? [{ id: 'main', type: 'video', assetId: 'video', start: 0, duration: 10 }]
        : [],
    },
    {
      id: 'a1',
      kind: 'audio',
      ...(bgmDucking === undefined ? {} : { ducking: bgmDucking }),
      clips: [{ id: 'bgm', type: 'audio', assetId: 'bgm', start: 0, duration: 10 }],
    },
    {
      id: 'a2',
      kind: 'audio',
      clips: [{ id: 'voice', type: 'audio', assetId: 'voice', start: 0, duration: 10 }],
    },
    {
      id: 'a3',
      kind: 'audio',
      clips: sfx === undefined ? [] : [{ id: 'sfx', type: 'audio', assetId: 'sfx', start: sfx, duration: 0.5 }],
    },
  ];
  return {
    schemaVersion: 1,
    revision: 0,
    name: 'audio-fixture',
    assets: [
      { id: 'video', kind: 'video', path: 'video.mp4' },
      { id: 'bgm', kind: 'audio', path: 'bgm.wav' },
      { id: 'voice', kind: 'audio', path: 'voice.wav' },
      { id: 'sfx', kind: 'audio', path: 'sfx.wav' },
    ],
    tracks,
    output: {
      path: 'out.mp4',
      format: 'mp4',
      videoCodec: 'h264',
      audioCodec: 'aac',
      width: 1920,
      height: 1080,
      frameRate: 30,
      pixelFormat: 'yuv420p',
      audioSampleRate: 48000,
      audioChannels: 2,
    },
  };
}

function sources() {
  return new Map([
    ['video', {
      asset: {
        id: 'video',
        kind: 'video',
        path: 'video.mp4',
        metadata: {
          probedAt: '2026-01-01T00:00:00.000Z',
          fingerprint: { size: 1, mtimeMs: 1 },
          duration: 100,
          size: 1,
          streams: [{ index: 0, codecType: 'video', codecName: 'h264', width: 1920, height: 1080, frameRate: 30 }],
        },
      },
      absolutePath: '/tmp/video.mp4',
      fingerprint: { size: 1, mtimeMs: 1 },
      hasVideo: true,
      hasAudio: false,
    }],
    ['bgm', audioAsset('bgm')],
    ['voice', audioAsset('voice')],
    ['sfx', audioAsset('sfx')],
  ]);
}

function planFor(project) {
  return compileRenderPlan(project, { projectDirectory: '/tmp', sources: sources() });
}

test('track ducking compiles to a sidechain compressor keyed by the source track', () => {
  const plan = planFor(projectWithAudio({ bgmDucking: { by: 'a2' } }));
  assert.match(plan.filter_graph, /asplit=2/);
  assert.match(
    plan.filter_graph,
    /sidechaincompress=threshold=0\.05:ratio=8:attack=20:release=400:makeup=1/,
  );
  const sidechain = plan.filter_graph.split('\n').find((line) => line.includes('sidechaincompress'));
  assert.match(sidechain, /^\[cc_track_mix_\d+\]\[cc_duck_key_\d+\]sidechaincompress/);
});

test('ducking honors custom compressor settings and warns when the key track is silent', () => {
  const tuned = planFor(projectWithAudio({
    bgmDucking: { by: 'a2', threshold: 0.02, ratio: 12, attack: 5, release: 250, makeup: 2 },
  }));
  assert.match(
    tuned.filter_graph,
    /sidechaincompress=threshold=0\.02:ratio=12:attack=5:release=250:makeup=2/,
  );

  const silent = projectWithAudio({ bgmDucking: { by: 'a2' } });
  silent.tracks[2].clips = [];
  const plan = planFor(silent);
  assert.doesNotMatch(plan.filter_graph, /sidechaincompress/);
  assert.ok(plan.warnings.some((warning) => warning.includes('"a1"') && warning.includes('"a2"')), JSON.stringify(plan.warnings));
});

test('ducking references are validated before rendering', () => {
  const self = projectWithAudio({ bgmDucking: { by: 'a1' } });
  assert.throws(
    () => validateProjectData(self),
    (error) => {
      assert.equal(error.code, 'PROJECT_VALIDATION_ERROR');
      assert.equal(error.exitCode, ExitCode.ProjectValidation);
      assert.ok(error.diagnostics.issues.some((issue) => issue.path === '/tracks/1/ducking/by'));
      return true;
    },
  );

  const unknown = projectWithAudio({ bgmDucking: { by: 'missing' } });
  assert.throws(() => validateProjectData(unknown), (error) => {
    assert.ok(error.diagnostics.issues.some((issue) => issue.keyword === 'duckingReference'));
    return true;
  });
});

test('setTrackParams configures and clears ducking; audio tracks cannot be hidden', async () => {
  const project = projectWithAudio();
  const configured = await applyOperations(project, [
    { type: 'setTrackParams', trackId: 'a1', params: { ducking: { by: 'a2', ratio: 6 } } },
  ]);
  assert.deepEqual(configured.tracks.find((track) => track.id === 'a1').ducking, { by: 'a2', ratio: 6 });

  const cleared = await applyOperations(configured, [
    { type: 'setTrackParams', trackId: 'a1', params: { ducking: null } },
  ]);
  assert.equal(cleared.tracks.find((track) => track.id === 'a1').ducking, undefined);

  await assert.rejects(
    applyOperations(project, [{ type: 'setTrackParams', trackId: 'a1', params: { hidden: true } }]),
    (error) => {
      assert.equal(error.code, 'EDIT_TRACK_PARAMS_UNSUPPORTED');
      return true;
    },
  );
});

test('short audio cues that miss a visual cut by a frame or two raise a warning', () => {
  const nearMiss = planFor(projectWithAudio({ sfx: 0.1 }));
  assert.ok(
    nearMiss.warnings.some((warning) => warning.includes('"sfx"') && warning.includes('100ms')),
    JSON.stringify(nearMiss.warnings),
  );

  const aligned = planFor(projectWithAudio({ sfx: 0 }));
  assert.ok(!aligned.warnings.some((warning) => warning.includes('"sfx"')), JSON.stringify(aligned.warnings));

  const farAway = planFor(projectWithAudio({ sfx: 4 }));
  assert.ok(!farAway.warnings.some((warning) => warning.includes('"sfx"')), JSON.stringify(farAway.warnings));
});
