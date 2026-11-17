import { Type, type Static, type TObject, type TSchema } from '@sinclair/typebox';

const JSON_SCHEMA_DIALECT = 'https://json-schema.org/draft/2020-12/schema';

const object = <T extends Record<string, TSchema>>(
  properties: T,
  description?: string,
): TObject<T> => Type.Object(properties, {
  additionalProperties: false,
  ...(description === undefined ? {} : { description }),
});

const IdentifierSchema = Type.String({
  pattern: '^[A-Za-z0-9][A-Za-z0-9._-]*$',
  description: 'Stable identifier containing letters, digits, dot, underscore, or dash.',
});

export const RelativePathSchema = Type.String({
  minLength: 1,
  pattern: '^(?![/\\\\])(?![A-Za-z]:[/\\\\])',
  description: 'Non-empty path relative to the project directory; .. segments are allowed.',
});

export const AssetKindSchema = Type.Union([
  Type.Literal('video'),
  Type.Literal('audio'),
  Type.Literal('image'),
]);

export const AssetFingerprintSchema = object({
  size: Type.Integer({ minimum: 0 }),
  mtimeMs: Type.Number({ minimum: 0 }),
}, 'Source identity used to detect file changes and invalidate generated caches.');

export const AssetStreamSchema = object({
  index: Type.Integer({ minimum: 0 }),
  codecType: Type.String({ minLength: 1 }),
  codecName: Type.Optional(Type.String({ minLength: 1 })),
  width: Type.Optional(Type.Integer({ minimum: 1 })),
  height: Type.Optional(Type.Integer({ minimum: 1 })),
  frameRate: Type.Optional(Type.Number({ minimum: 0 })),
  sampleRate: Type.Optional(Type.Integer({ minimum: 1 })),
  channels: Type.Optional(Type.Integer({ minimum: 1 })),
  channelLayout: Type.Optional(Type.String({ minLength: 1 })),
  duration: Type.Optional(Type.Number({ minimum: 0 })),
  bitRate: Type.Optional(Type.Integer({ minimum: 0 })),
});

export const AssetMetadataSchema = object({
  probedAt: Type.String({ format: 'date-time' }),
  fingerprint: AssetFingerprintSchema,
  duration: Type.Number({ minimum: 0 }),
  size: Type.Integer({ minimum: 0 }),
  formatName: Type.Optional(Type.String({ minLength: 1 })),
  bitRate: Type.Optional(Type.Integer({ minimum: 0 })),
  streams: Type.Array(AssetStreamSchema),
}, 'Selected ffprobe metadata; probedAt and fingerprint describe when it was captured.');

export const AssetSchema = object({
  id: IdentifierSchema,
  kind: AssetKindSchema,
  path: RelativePathSchema,
  metadata: Type.Optional(AssetMetadataSchema),
}, 'A reusable source asset with an optional transactional ffprobe metadata snapshot.');

export const CropSchema = object({
  x: Type.Number({ minimum: 0, default: 0 }),
  y: Type.Number({ minimum: 0, default: 0 }),
  width: Type.Number({ exclusiveMinimum: 0 }),
  height: Type.Number({ exclusiveMinimum: 0 }),
}, 'Source crop rectangle in source pixels.');

export const PositionSchema = object({
  x: Type.Number({ default: 0 }),
  y: Type.Number({ default: 0 }),
}, 'Top-left position in output pixels.');

export const TransitionSchema = Type.Union([
  object({ type: Type.Literal('cut') }),
  object({
    type: Type.Literal('xfade'),
    duration: Type.Number({ exclusiveMinimum: 0 }),
    name: Type.Optional(Type.String({ minLength: 1, description: 'FFmpeg xfade transition name.' })),
  }),
]);

const clipProperties = {
  id: IdentifierSchema,
  start: Type.Number({ minimum: 0, description: 'Timeline start in seconds.' }),
  duration: Type.Number({ exclusiveMinimum: 0, description: 'Timeline duration in seconds.' }),
  sourceStart: Type.Optional(Type.Number({ minimum: 0, default: 0, description: 'Source in-point in seconds.' })),
  speed: Type.Optional(Type.Number({ exclusiveMinimum: 0, default: 1 })),
  crop: Type.Optional(CropSchema),
  scale: Type.Optional(Type.Number({ exclusiveMinimum: 0, default: 1 })),
  position: Type.Optional(PositionSchema),
  opacity: Type.Optional(Type.Number({ minimum: 0, maximum: 1, default: 1 })),
  volume: Type.Optional(Type.Number({ minimum: 0, default: 1 })),
  fadeIn: Type.Optional(Type.Number({ minimum: 0, default: 0, description: 'Audio fade-in seconds.' })),
  fadeOut: Type.Optional(Type.Number({ minimum: 0, default: 0, description: 'Audio fade-out seconds.' })),
  transition: Type.Optional(TransitionSchema),
};

export const VideoClipSchema = object({
  ...clipProperties,
  type: Type.Literal('video'),
  assetId: IdentifierSchema,
});

export const AudioClipSchema = object({
  ...clipProperties,
  type: Type.Literal('audio'),
  assetId: IdentifierSchema,
});

export const ImageClipSchema = object({
  ...clipProperties,
  type: Type.Literal('image'),
  assetId: IdentifierSchema,
});

export const ColorClipSchema = object({
  ...clipProperties,
  type: Type.Literal('color'),
  color: Type.String({
    pattern: '^#[0-9A-Fa-f]{6}([0-9A-Fa-f]{2})?$',
    default: '#000000',
  }),
});

export const TextClipSchema = object({
  ...clipProperties,
  type: Type.Literal('text'),
  text: Type.String({ minLength: 1 }),
  fontFamily: Type.Optional(Type.String({ minLength: 1, default: 'sans' })),
  fontFile: Type.Optional(RelativePathSchema),
  fontSize: Type.Optional(Type.Number({ exclusiveMinimum: 0, default: 48 })),
  color: Type.Optional(Type.String({
    pattern: '^#[0-9A-Fa-f]{6}([0-9A-Fa-f]{2})?$',
    default: '#FFFFFF',
  })),
  align: Type.Optional(Type.Union([
    Type.Literal('left'),
    Type.Literal('center'),
    Type.Literal('right'),
  ], { default: 'center' })),
});

export const VisualClipSchema = Type.Union([
  VideoClipSchema,
  ImageClipSchema,
  ColorClipSchema,
  TextClipSchema,
]);

export const ClipSchema = Type.Union([VisualClipSchema, AudioClipSchema]);

export const VideoTrackSchema = object({
  id: IdentifierSchema,
  kind: Type.Literal('video'),
  name: Type.Optional(Type.String({ minLength: 1 })),
  hidden: Type.Optional(Type.Boolean({ default: false })),
  muted: Type.Optional(Type.Boolean({ default: false })),
  clips: Type.Array(VisualClipSchema),
});

export const AudioTrackSchema = object({
  id: IdentifierSchema,
  kind: Type.Literal('audio'),
  name: Type.Optional(Type.String({ minLength: 1 })),
  muted: Type.Optional(Type.Boolean({ default: false })),
  clips: Type.Array(AudioClipSchema),
});

export const TrackSchema = Type.Union([VideoTrackSchema, AudioTrackSchema]);

export const OutputSchema = object({
  path: RelativePathSchema,
  format: Type.Literal('mp4', { default: 'mp4' }),
  videoCodec: Type.Literal('h264', { default: 'h264' }),
  audioCodec: Type.Literal('aac', { default: 'aac' }),
  width: Type.Integer({ minimum: 2, multipleOf: 2, default: 1920 }),
  height: Type.Integer({ minimum: 2, multipleOf: 2, default: 1080 }),
  frameRate: Type.Number({ exclusiveMinimum: 0, default: 30 }),
  pixelFormat: Type.Literal('yuv420p', { default: 'yuv420p' }),
  audioSampleRate: Type.Literal(48000, { default: 48000 }),
  audioChannels: Type.Literal(2, { default: 2 }),
});

export const ProjectSchema = object({
  schemaVersion: Type.Literal(1),
  revision: Type.Integer({ minimum: 0, default: 0 }),
  name: Type.String({ minLength: 1 }),
  assets: Type.Array(AssetSchema),
  tracks: Type.Array(TrackSchema, { minItems: 1 }),
  output: OutputSchema,
});
Object.assign(ProjectSchema, {
  $schema: JSON_SCHEMA_DIALECT,
  $id: 'https://codecut.local/schemas/project-v1.json',
  description: 'CodeCut authoritative project JSON, schema version 1.',
});

const ClipParamsSchema = object({
  start: Type.Optional(Type.Number({ minimum: 0 })),
  duration: Type.Optional(Type.Number({ exclusiveMinimum: 0 })),
  sourceStart: Type.Optional(Type.Number({ minimum: 0 })),
  speed: Type.Optional(Type.Number({ exclusiveMinimum: 0 })),
  crop: Type.Optional(CropSchema),
  scale: Type.Optional(Type.Number({ exclusiveMinimum: 0 })),
  position: Type.Optional(PositionSchema),
  opacity: Type.Optional(Type.Number({ minimum: 0, maximum: 1 })),
  volume: Type.Optional(Type.Number({ minimum: 0 })),
  fadeIn: Type.Optional(Type.Number({ minimum: 0 })),
  fadeOut: Type.Optional(Type.Number({ minimum: 0 })),
  transition: Type.Optional(TransitionSchema),
});

export const EditOperationSchema = Type.Union([
  object({ type: Type.Literal('addTrack'), track: TrackSchema }),
  object({ type: Type.Literal('removeTrack'), trackId: IdentifierSchema }),
  object({ type: Type.Literal('addClip'), trackId: IdentifierSchema, clip: ClipSchema }),
  object({
    type: Type.Literal('trimClip'),
    clipId: IdentifierSchema,
    sourceStart: Type.Optional(Type.Number({ minimum: 0 })),
    duration: Type.Optional(Type.Number({ exclusiveMinimum: 0 })),
  }),
  object({
    type: Type.Literal('moveClip'),
    clipId: IdentifierSchema,
    start: Type.Number({ minimum: 0 }),
    targetTrackId: Type.Optional(IdentifierSchema),
  }),
  object({
    type: Type.Literal('splitClip'),
    clipId: IdentifierSchema,
    at: Type.Number({ minimum: 0, description: 'Absolute timeline time at which to split.' }),
    leftClipId: Type.Optional(IdentifierSchema),
    rightClipId: Type.Optional(IdentifierSchema),
  }),
  object({ type: Type.Literal('removeClip'), clipId: IdentifierSchema }),
  object({ type: Type.Literal('setClipParams'), clipId: IdentifierSchema, params: ClipParamsSchema }),
  object({ type: Type.Literal('addText'), trackId: IdentifierSchema, clip: TextClipSchema }),
  object({ type: Type.Literal('importSrt'), trackId: IdentifierSchema, path: RelativePathSchema }),
], { $id: 'https://codecut.local/schemas/edit-operation-v1.json' });

export const AssetOperationSchema = Type.Union([
  object({ type: Type.Literal('addAsset'), asset: AssetSchema }),
  object({ type: Type.Literal('probeAsset'), assetId: IdentifierSchema, metadata: AssetMetadataSchema }),
  object({ type: Type.Literal('removeAsset'), assetId: IdentifierSchema }),
], { $id: 'https://codecut.local/schemas/asset-operation-v1.json' });

export const HistoryOperationSchema = Type.Union([EditOperationSchema, AssetOperationSchema]);

const PreviewOutputProperties = {
  output: Type.Optional(RelativePathSchema),
  force: Type.Optional(Type.Boolean({ default: false })),
};

export const AssetPreviewRequestSchema = Type.Union([
  object({
    type: Type.Literal('thumbnail'),
    assetId: IdentifierSchema,
    at: Type.Optional(Type.Number({ minimum: 0, default: 0 })),
    width: Type.Optional(Type.Integer({ minimum: 16, maximum: 4096 })),
    height: Type.Optional(Type.Integer({ minimum: 16, maximum: 4096 })),
    ...PreviewOutputProperties,
  }),
  object({
    type: Type.Literal('sheet'),
    assetId: IdentifierSchema,
    start: Type.Optional(Type.Number({ minimum: 0, default: 0 })),
    end: Type.Optional(Type.Number({ exclusiveMinimum: 0 })),
    interval: Type.Optional(Type.Number({ exclusiveMinimum: 0, maximum: 3600 })),
    columns: Type.Optional(Type.Integer({ minimum: 1, maximum: 20, default: 4 })),
    rows: Type.Optional(Type.Integer({ minimum: 1, maximum: 20, default: 3 })),
    width: Type.Optional(Type.Integer({ minimum: 16, maximum: 2048, default: 320 })),
    height: Type.Optional(Type.Integer({ minimum: 16, maximum: 2048 })),
    ...PreviewOutputProperties,
  }),
], { $id: 'https://codecut.local/schemas/asset-preview-request-v1.json' });

export const AssetAnalysisRequestSchema = Type.Union([
  object({
    type: Type.Literal('scenes'),
    assetId: IdentifierSchema,
    start: Type.Optional(Type.Number({ minimum: 0, default: 0 })),
    end: Type.Optional(Type.Number({ exclusiveMinimum: 0 })),
    threshold: Type.Optional(Type.Number({ exclusiveMinimum: 0, maximum: 1, default: 0.3 })),
  }),
  object({
    type: Type.Literal('silence'),
    assetId: IdentifierSchema,
    start: Type.Optional(Type.Number({ minimum: 0, default: 0 })),
    end: Type.Optional(Type.Number({ exclusiveMinimum: 0 })),
    noiseDb: Type.Optional(Type.Number({ minimum: -120, exclusiveMaximum: 0, default: -35 })),
    minimumDuration: Type.Optional(Type.Number({ exclusiveMinimum: 0, maximum: 3600, default: 0.5 })),
  }),
], { $id: 'https://codecut.local/schemas/asset-analysis-request-v1.json' });

const AnalysisRangeProperties = {
  assetId: IdentifierSchema,
  start: Type.Number({ minimum: 0 }),
  end: Type.Number({ exclusiveMinimum: 0 }),
  resultPath: Type.String({ minLength: 1 }),
};

export const AssetAnalysisResultSchema = Type.Union([
  object({
    type: Type.Literal('scenes'),
    ...AnalysisRangeProperties,
    threshold: Type.Number({ exclusiveMinimum: 0, maximum: 1 }),
    points: Type.Array(object({
      time: Type.Number({ minimum: 0 }),
      score: Type.Number({ minimum: 0, maximum: 1 }),
    })),
  }),
  object({
    type: Type.Literal('silence'),
    ...AnalysisRangeProperties,
    noiseDb: Type.Number({ minimum: -120, exclusiveMaximum: 0 }),
    minimumDuration: Type.Number({ exclusiveMinimum: 0, maximum: 3600 }),
    intervals: Type.Array(object({
      start: Type.Number({ minimum: 0 }),
      end: Type.Number({ exclusiveMinimum: 0 }),
      duration: Type.Number({ exclusiveMinimum: 0 }),
    })),
  }),
], { $id: 'https://codecut.local/schemas/asset-analysis-result-v1.json' });

export const AssetPreviewResultSchema = object({
  type: Type.Union([Type.Literal('thumbnail'), Type.Literal('sheet')]),
  assetId: IdentifierSchema,
  outputPath: Type.String({ minLength: 1 }),
  cacheKey: Type.String({ minLength: 1 }),
  cacheHit: Type.Boolean(),
  source: object({ path: RelativePathSchema, ...AssetFingerprintSchema.properties }),
  parameters: Type.Record(Type.String(), Type.Unknown()),
});
Object.assign(AssetPreviewResultSchema, { $id: 'https://codecut.local/schemas/asset-preview-result-v1.json' });

export const RenderRequestSchema = object({
  revision: Type.Optional(Type.Union([
    Type.Integer({ minimum: 0 }),
    IdentifierSchema,
  ], { description: 'Immutable project revision number or revision ID; omitted selects the current project.' })),
  output: Type.Optional(RelativePathSchema),
  force: Type.Optional(Type.Boolean({ default: false })),
  detach: Type.Optional(Type.Boolean({ default: false })),
  dryRun: Type.Optional(Type.Boolean({ default: false })),
  timeoutMs: Type.Optional(Type.Integer({ minimum: 1 })),
}, 'Render the fixed project and asset snapshot as an H.264/AAC MP4. Dry-run returns a plan without creating a job.');
Object.assign(RenderRequestSchema, { $id: 'https://codecut.local/schemas/render-request-v1.json' });

const TimelinePreviewCommonProperties = {
  revision: Type.Optional(Type.Union([Type.Integer({ minimum: 0 }), IdentifierSchema])),
  output: Type.Optional(RelativePathSchema),
  force: Type.Optional(Type.Boolean({ default: false })),
  detach: Type.Optional(Type.Boolean({ default: false })),
  dryRun: Type.Optional(Type.Boolean({ default: false })),
  timeoutMs: Type.Optional(Type.Integer({ minimum: 1 })),
};

export const TimelinePreviewRequestSchema = Type.Union([
  object({
    type: Type.Literal('frame'),
    at: Type.Optional(Type.Number({ minimum: 0, default: 0 })),
    width: Type.Optional(Type.Integer({ minimum: 16, maximum: 4096, multipleOf: 2 })),
    height: Type.Optional(Type.Integer({ minimum: 16, maximum: 4096, multipleOf: 2 })),
    ...TimelinePreviewCommonProperties,
  }),
  object({
    type: Type.Literal('sheet'),
    start: Type.Optional(Type.Number({ minimum: 0, default: 0 })),
    end: Type.Optional(Type.Number({ exclusiveMinimum: 0 })),
    interval: Type.Optional(Type.Number({ exclusiveMinimum: 0, maximum: 3600 })),
    columns: Type.Optional(Type.Integer({ minimum: 1, maximum: 20, default: 4 })),
    rows: Type.Optional(Type.Integer({ minimum: 1, maximum: 20, default: 3 })),
    width: Type.Optional(Type.Integer({ minimum: 16, maximum: 2048, multipleOf: 2 })),
    height: Type.Optional(Type.Integer({ minimum: 16, maximum: 2048, multipleOf: 2 })),
    ...TimelinePreviewCommonProperties,
  }),
  object({
    type: Type.Literal('proxy'),
    width: Type.Optional(Type.Integer({ minimum: 16, maximum: 1920, multipleOf: 2 })),
    height: Type.Optional(Type.Integer({ minimum: 16, maximum: 1920, multipleOf: 2 })),
    crf: Type.Optional(Type.Integer({ minimum: 0, maximum: 51 })),
    videoBitrateKbps: Type.Optional(Type.Integer({ minimum: 32, maximum: 10000 })),
    audioBitrateKbps: Type.Optional(Type.Integer({ minimum: 32, maximum: 320 })),
    ...TimelinePreviewCommonProperties,
  }),
], { $id: 'https://codecut.local/schemas/timeline-preview-request-v1.json' });

export const TimelinePreviewResultSchema = object({
  type: Type.Union([Type.Literal('frame'), Type.Literal('sheet'), Type.Literal('proxy')]),
  outputPath: Type.String({ minLength: 1 }),
  revision: Type.Integer({ minimum: 0 }),
  parameters: Type.Record(Type.String(), Type.Unknown()),
});
Object.assign(TimelinePreviewResultSchema, { $id: 'https://codecut.local/schemas/timeline-preview-result-v1.json' });

const RenderInputSchema = object({
  index: Type.Integer({ minimum: 0 }),
  assetId: IdentifierSchema,
  kind: AssetKindSchema,
  path: Type.String({ minLength: 1 }),
  fingerprint: AssetFingerprintSchema,
  hasVideo: Type.Boolean(),
  hasAudio: Type.Boolean(),
  clips: Type.Array(IdentifierSchema),
});

const RenderMediaSchema = object({
  durationSeconds: Type.Number({ exclusiveMinimum: 0 }),
  width: Type.Integer({ minimum: 2, multipleOf: 2 }),
  height: Type.Integer({ minimum: 2, multipleOf: 2 }),
  frameRate: Type.Number({ exclusiveMinimum: 0 }),
  pixelFormat: Type.Literal('yuv420p'),
  videoCodec: Type.Literal('h264'),
  audioCodec: Type.Literal('aac'),
  audioSampleRate: Type.Literal(48000),
  audioChannels: Type.Literal(2),
});

const RenderPostprocessSchema = Type.Union([
  object({
    type: Type.Literal('frame'),
    at: Type.Number({ minimum: 0 }),
    width: Type.Integer({ minimum: 16, maximum: 4096, multipleOf: 2 }),
    height: Type.Integer({ minimum: 16, maximum: 4096, multipleOf: 2 }),
  }),
  object({
    type: Type.Literal('sheet'),
    start: Type.Number({ minimum: 0 }),
    end: Type.Number({ exclusiveMinimum: 0 }),
    interval: Type.Number({ exclusiveMinimum: 0 }),
    columns: Type.Integer({ minimum: 1, maximum: 20 }),
    rows: Type.Integer({ minimum: 1, maximum: 20 }),
    width: Type.Integer({ minimum: 16, maximum: 2048, multipleOf: 2 }),
    height: Type.Integer({ minimum: 16, maximum: 2048, multipleOf: 2 }),
    sampleTimes: Type.Array(Type.Number({ minimum: 0 }), { minItems: 1, maxItems: 200 }),
  }),
  object({
    type: Type.Literal('proxy'),
    width: Type.Integer({ minimum: 16, maximum: 1920, multipleOf: 2 }),
    height: Type.Integer({ minimum: 16, maximum: 1920, multipleOf: 2 }),
    crf: Type.Optional(Type.Integer({ minimum: 0, maximum: 51 })),
    videoBitrateKbps: Type.Optional(Type.Integer({ minimum: 32, maximum: 10000 })),
    audioBitrateKbps: Type.Integer({ minimum: 32, maximum: 320 }),
  }),
]);

export const RenderPlanSchema = object({
  version: Type.Literal(1),
  revision: Type.Integer({ minimum: 0 }),
  command: Type.String({ minLength: 1 }),
  durationSeconds: Type.Number({ exclusiveMinimum: 0 }),
  inputs: Type.Array(RenderInputSchema),
  args: Type.Array(Type.String()),
  filter_graph: Type.String({ minLength: 1 }),
  output: object({
    path: Type.String({ minLength: 1 }),
    temporaryPath: Type.String({ minLength: 1 }),
    format: Type.Union([Type.Literal('mp4'), Type.Literal('png')]),
    overwrite: Type.Boolean(),
  }),
  media: RenderMediaSchema,
  warnings: Type.Array(Type.String()),
  textFiles: Type.Array(object({
    clipId: IdentifierSchema,
    path: Type.String({ minLength: 1 }),
    content: Type.String(),
  })),
  preview: Type.Optional(RenderPostprocessSchema),
}, 'Inspectable FFmpeg execution plan. Formal jobs materialize placeholders and persist arguments, filter graph, plan, and UTF-8 text files in job diagnostics.');
Object.assign(RenderPlanSchema, {
  $schema: JSON_SCHEMA_DIALECT,
  $id: 'https://codecut.local/schemas/render-plan-v1.json',
});

export const DoctorCheckSchema = object({
  name: Type.String({ minLength: 1 }),
  status: Type.Union([Type.Literal('ok'), Type.Literal('warning'), Type.Literal('error')]),
  message: Type.String({ minLength: 1 }),
  path: Type.Optional(Type.String({ minLength: 1 })),
  details: Type.Optional(Type.Unknown()),
});

export const DoctorResultSchema = object({
  ok: Type.Boolean(),
  projectDirectory: Type.String({ minLength: 1 }),
  checks: Type.Array(DoctorCheckSchema),
});

export const JobLogEntrySchema = object({
  jobId: IdentifierSchema,
  stage: Type.String({ minLength: 1 }),
  level: Type.Union([Type.Literal('debug'), Type.Literal('info'), Type.Literal('warn'), Type.Literal('error')]),
  stream: Type.Union([Type.Literal('stdout'), Type.Literal('stderr'), Type.Literal('progress')]),
  line: Type.String(),
  at: Type.Optional(Type.String({ format: 'date-time' })),
});

export const LogQuerySchema = object({
  jobId: IdentifierSchema,
  stage: Type.Optional(Type.String({ minLength: 1 })),
  level: Type.Optional(Type.Union([Type.Literal('debug'), Type.Literal('info'), Type.Literal('warn'), Type.Literal('error')])),
  stream: Type.Optional(Type.Union([Type.Literal('stdout'), Type.Literal('stderr'), Type.Literal('progress')])),
  tail: Type.Optional(Type.Integer({ minimum: 0, default: 100 })),
  follow: Type.Optional(Type.Boolean({ default: false })),
});

export const DiagnoseResultSchema = object({
  jobId: IdentifierSchema,
  directory: Type.String({ minLength: 1 }),
  files: Type.Array(Type.String({ minLength: 1 })),
  redacted: Type.Literal(true),
  sourceMediaIncluded: Type.Literal(false),
  environmentVariablesIncluded: Type.Literal(false),
});

export const ErrorPayloadSchema = object({
  code: Type.String({ minLength: 1 }),
  message: Type.String({ minLength: 1 }),
  stage: Type.String({ minLength: 1 }),
  jobId: Type.Optional(Type.String({ minLength: 1 })),
  path: Type.Optional(Type.String({ minLength: 1 })),
  operationIndex: Type.Optional(Type.Integer({ minimum: 0 })),
  retryable: Type.Optional(Type.Boolean()),
  diagnostics: Type.Optional(Type.Unknown()),
});

export const JobSchema = object({
  id: IdentifierSchema,
  kind: Type.Union([
    Type.Literal('asset.probe'),
    Type.Literal('asset.analyze'),
    Type.Literal('asset.thumbnail'),
    Type.Literal('asset.sheet'),
    Type.Literal('preview.frame'),
    Type.Literal('preview.sheet'),
    Type.Literal('preview.proxy'),
    Type.Literal('render'),
  ]),
  status: Type.Union([
    Type.Literal('queued'),
    Type.Literal('running'),
    Type.Literal('stopping'),
    Type.Literal('succeeded'),
    Type.Literal('failed'),
    Type.Literal('cancelled'),
    Type.Literal('timedOut'),
    Type.Literal('interrupted'),
  ]),
  health: Type.Optional(Type.Union([Type.Literal('ok'), Type.Literal('stale')], { default: 'ok' })),
  stage: Type.String({ minLength: 1 }),
  projectRevision: Type.Integer({ minimum: 0 }),
  retryOf: Type.Optional(IdentifierSchema),
  outputPath: Type.Optional(Type.String({ minLength: 1 })),
  preview: Type.Optional(object({
    type: Type.Union([Type.Literal('frame'), Type.Literal('sheet'), Type.Literal('proxy')]),
    parameters: RenderPostprocessSchema,
  })),
  validation: Type.Optional(Type.Unknown()),
  createdAt: Type.String({ format: 'date-time' }),
  startedAt: Type.Optional(Type.String({ format: 'date-time' })),
  finishedAt: Type.Optional(Type.String({ format: 'date-time' })),
  heartbeatAt: Type.Optional(Type.String({ format: 'date-time' })),
  progress: Type.Optional(object({
    percent: Type.Number({ minimum: 0, maximum: 100 }),
    frame: Type.Optional(Type.Integer({ minimum: 0 })),
    timeSeconds: Type.Optional(Type.Number({ minimum: 0 })),
    speed: Type.Optional(Type.Number({ minimum: 0 })),
  })),
  error: Type.Optional(ErrorPayloadSchema),
});

export const RevisionSchema = object({
  id: IdentifierSchema,
  parentId: Type.Optional(IdentifierSchema),
  projectRevision: Type.Integer({ minimum: 1 }),
  createdAt: Type.String({ format: 'date-time' }),
  summary: Type.String({ minLength: 1 }),
  operations: Type.Array(HistoryOperationSchema),
  snapshotPath: RelativePathSchema,
});

export type RelativePath = Static<typeof RelativePathSchema>;
export type AssetKind = Static<typeof AssetKindSchema>;
export type Asset = Static<typeof AssetSchema>;
export type AssetFingerprint = Static<typeof AssetFingerprintSchema>;
export type AssetStream = Static<typeof AssetStreamSchema>;
export type AssetMetadata = Static<typeof AssetMetadataSchema>;
export type Crop = Static<typeof CropSchema>;
export type Position = Static<typeof PositionSchema>;
export type Transition = Static<typeof TransitionSchema>;
export type VideoClip = Static<typeof VideoClipSchema>;
export type AudioClip = Static<typeof AudioClipSchema>;
export type ImageClip = Static<typeof ImageClipSchema>;
export type ColorClip = Static<typeof ColorClipSchema>;
export type TextClip = Static<typeof TextClipSchema>;
export type Clip = Static<typeof ClipSchema>;
export type Track = Static<typeof TrackSchema>;
export type Output = Static<typeof OutputSchema>;
export type Project = Static<typeof ProjectSchema>;
export type EditOperation = Static<typeof EditOperationSchema>;
export type AssetOperation = Static<typeof AssetOperationSchema>;
export type HistoryOperation = Static<typeof HistoryOperationSchema>;
export type AssetPreviewRequest = Static<typeof AssetPreviewRequestSchema>;
export type AssetAnalysisRequest = Static<typeof AssetAnalysisRequestSchema>;
export type AssetAnalysisResult = Static<typeof AssetAnalysisResultSchema>;
export type AssetPreviewResult = Static<typeof AssetPreviewResultSchema>;
export type RenderRequest = Static<typeof RenderRequestSchema>;
export type TimelinePreviewRequestDocument = Static<typeof TimelinePreviewRequestSchema>;
export type TimelinePreviewResultDocument = Static<typeof TimelinePreviewResultSchema>;
export type ErrorPayload = Static<typeof ErrorPayloadSchema>;
export type Job = Static<typeof JobSchema>;
export type Revision = Static<typeof RevisionSchema>;
