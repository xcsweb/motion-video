import assert from 'node:assert/strict';
import test from 'node:test';
import { ExitCode } from '../dist/errors.js';
import { validateProjectData } from '../dist/project.js';
import { compileRenderPlan } from '../dist/render-plan.js';

function projectWithClip(clip, { width = 1080, height = 1920 } = {}) {
  return {
    schemaVersion: 1,
    revision: 0,
    name: 'effects-fixture',
    assets: [{ id: 'video', kind: 'video', path: 'video.mp4' }],
    tracks: [
      {
        id: 'v1',
        kind: 'video',
        clips: [{ id: 'main', type: 'video', assetId: 'video', start: 10, duration: 3, ...clip }],
      },
      { id: 'a1', kind: 'audio', clips: [] },
    ],
    output: {
      path: 'out.mp4',
      format: 'mp4',
      videoCodec: 'h264',
      audioCodec: 'aac',
      width,
      height,
      frameRate: 30,
      pixelFormat: 'yuv420p',
      audioSampleRate: 48000,
      audioChannels: 2,
    },
  };
}

function sources() {
  return new Map([['video', {
    asset: {
      id: 'video',
      kind: 'video',
      path: 'video.mp4',
      metadata: {
        probedAt: '2026-01-01T00:00:00.000Z',
        fingerprint: { size: 1, mtimeMs: 1 },
        duration: 100,
        size: 1,
        streams: [{ index: 0, codecType: 'video', codecName: 'h264', width: 1080, height: 1920, frameRate: 30 }],
      },
    },
    absolutePath: '/tmp/video.mp4',
    fingerprint: { size: 1, mtimeMs: 1 },
    hasVideo: true,
    hasAudio: true,
  }]]);
}

function planFor(clip, options) {
  return compileRenderPlan(projectWithClip(clip, options), { projectDirectory: '/tmp', sources: sources() });
}

function clipLine(plan) {
  return plan.filter_graph.split('\n').find((line) => line.includes('[cc_clip_0]'));
}

test('clips without effects keep the pre-effects filter chain', () => {
  const plan = planFor({});
  assert.equal(
    clipLine(plan),
    "[0:v:0]trim=start=0:end=3,setpts=(PTS-STARTPTS)/1,fps=30,format=rgba,scale=w=1080:h=1920:force_original_aspect_ratio=decrease,trim=duration=3,setpts=PTS-STARTPTS[cc_clip_0];",
  );
  assert.doesNotMatch(plan.filter_graph, /eq=brightness/);
  assert.doesNotMatch(plan.filter_graph, /crop=w=iw-/);
});

test('shake compiles to a per-frame crop that is scaled back to the clip size', () => {
  const line = clipLine(planFor({ effects: [{ type: 'shake', amplitude: 20, frequency: 8 }] }));
  const crop = "crop=w=iw-40:h=ih-40:x='20+20*sin(floor(t*8)*12.9898)':y='20+20*sin(floor(t*8)*78.233+1.7)'";
  const restore = 'scale=w=iw+40:h=ih+40:flags=bicubic';
  assert.ok(line.includes(crop), line);
  assert.ok(line.includes(restore), line);
  assert.ok(line.indexOf(crop) < line.indexOf(restore), 'crop must run before the scale restore');
  assert.ok(line.indexOf('force_original_aspect_ratio=decrease') < line.indexOf(crop), 'shake must run after the normal transform chain');
  assert.ok(line.indexOf(restore) < line.indexOf('trim=duration=3'), 'shake must run before the final clip trim');
});

test('shake defaults match the documented amplitude and frequency', () => {
  const line = clipLine(planFor({ effects: [{ type: 'shake' }] }));
  assert.ok(line.includes("crop=w=iw-40:h=ih-40:x='20+20*sin(floor(t*8)*12.9898)'"), line);
});

test('flash windows stay relative to the clip start regardless of timeline position', () => {
  const line = clipLine(planFor({ effects: [{ type: 'flash', at: 1.2, duration: 0.12, color: 'white', strength: 0.55 }] }));
  assert.ok(line.includes("eq=brightness='if(between(t,1.2,1.32),0.55,0)':eval=frame"), line);

  const shifted = projectWithClip({ effects: [{ type: 'flash', at: 1.2, duration: 0.12 }] });
  shifted.tracks[0].clips[0].start = 0;
  const shiftedLine = clipLine(compileRenderPlan(shifted, { projectDirectory: '/tmp', sources: sources() }));
  const window = (value) => value.match(/eq=brightness='[^']*':eval=frame/)?.[0];
  assert.equal(window(shiftedLine), window(line));
});

test('flash defaults to a 0.12s window at 0.55 strength', () => {
  const line = clipLine(planFor({ effects: [{ type: 'flash', at: 2 }] }));
  assert.ok(line.includes("eq=brightness='if(between(t,2,2.12),0.55,0)':eval=frame"), line);
});

test('effects on multiple kinds of visual clips and ordered chains compile together', () => {
  const line = clipLine(planFor({
    effects: [
      { type: 'shake', amplitude: 12, frequency: 4 },
      { type: 'flash', at: 0.5, duration: 0.25, strength: 0.4 },
    ],
  }));
  const shake = line.indexOf("crop=w=iw-24:h=ih-24:x='12+12*sin(floor(t*4)*12.9898)'");
  const flash = line.indexOf("eq=brightness='if(between(t,0.5,0.75),0.4,0)'");
  assert.ok(shake >= 0 && flash > shake, line);

  const color = projectWithClip({});
  color.assets = [];
  color.tracks[0].clips = [{
    id: 'main',
    type: 'color',
    color: '#FF0000',
    start: 0,
    duration: 3,
    effects: [{ type: 'flash', at: 0.5 }],
  }];
  const colorLine = clipLine(compileRenderPlan(color, { projectDirectory: '/tmp', sources: new Map() }));
  assert.ok(colorLine.includes('eq=brightness='), colorLine);
});

test('invalid effects are rejected with field paths', () => {
  const cases = [
    {
      clip: { effects: [{ type: 'flash', at: 3 }] },
      path: '/tracks/0/clips/0/effects/0/at',
    },
    {
      clip: { effects: [{ type: 'flash', at: 2.95, duration: 0.2 }] },
      path: '/tracks/0/clips/0/effects/0/duration',
    },
    {
      clip: { effects: [{ type: 'shake', amplitude: 600 }] },
      path: '/tracks/0/clips/0/effects/0/amplitude',
    },
  ];
  for (const { clip, path } of cases) {
    assert.throws(
      () => validateProjectData(projectWithClip(clip)),
      (error) => {
        assert.equal(error.code, 'PROJECT_VALIDATION_ERROR');
        assert.equal(error.exitCode, ExitCode.ProjectValidation);
        assert.ok(
          error.diagnostics.issues.some((issue) => issue.path === path),
          JSON.stringify(error.diagnostics.issues),
        );
        return true;
      },
    );
  }
});

test('malformed effects fail TypeBox validation and effects stay off audio clips', () => {
  for (const clip of [
    { effects: [{ type: 'blur' }] },
    { effects: [] },
    { effects: [{ type: 'shake', amplitude: -1 }] },
    { effects: [{ type: 'flash', strength: 2 }] },
    { effects: [{ type: 'flash', at: 0.5 }], type: 'audio', assetId: 'video' },
  ]) {
    assert.throws(
      () => validateProjectData(projectWithClip(clip)),
      (error) => {
        assert.equal(error.code, 'PROJECT_VALIDATION_ERROR');
        assert.ok(
          error.diagnostics.issues.some((issue) => issue.path.includes('/effects')),
          JSON.stringify(error.diagnostics.issues),
        );
        return true;
      },
    );
  }
});

test('valid effects survive project validation unchanged', () => {
  const project = projectWithClip({
    effects: [
      { type: 'shake', amplitude: 20, frequency: 8 },
      { type: 'flash', at: 1.2, duration: 0.12, color: 'white', strength: 0.55 },
    ],
  });
  assert.deepEqual(validateProjectData(project), project);
});
