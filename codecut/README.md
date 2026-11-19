# codecut

用 JSON 时间线驱动 FFmpeg 的命令行剪辑工具。不做画面生成，只负责把素材剪成片：多轨合成、字幕、转场、特效、变速、混音、渲染。

- 工程是可版本控制的 `project.json`，所有改动走事务，支持 `--dry-run`、undo/redo
- 预览与正式渲染共用同一套时间线语义，所见即所得
- 渲染计划可导出为纯 FFmpeg 参数，便于排查

## 环境

- Node.js 22+
- 系统安装 `ffmpeg` / `ffprobe`（字幕用 `drawtext`，依赖 fontconfig）
- 无需数据库，无需服务端

```bash
npm ci
npm run build
node dist/cli.js --help
```

## 最短流程

```bash
# 1. 建工程（生成 project.json）
node dist/cli.js project init my-video --name demo

# 2. 登记素材（会 ffprobe 探测；非 H.264 或带旋转的视频自动转码，见下）
node dist/cli.js asset add clip.mp4 --id clip --project my-video
node dist/cli.js asset add bgm.mp3  --id bgm  --project my-video

# 3. 写操作列表，先预演再落地
node dist/cli.js edit apply ops.json --project my-video --dry-run
node dist/cli.js edit apply ops.json --project my-video

# 4. 渲染
node dist/cli.js render --project my-video
```

`ops.json` 示例：

```json
[
  { "type": "addClip", "trackId": "v1",
    "clip": { "id": "c1", "type": "video", "assetId": "clip",
              "start": 0, "duration": 1.8, "sourceStart": 4.2,
              "effects": [{ "type": "shake", "amplitude": 14, "frequency": 6 },
                          { "type": "flash", "at": 0.9, "duration": 0.12, "strength": 0.55 }] } },
  { "type": "setSpeedRamp", "clipId": "c1", "steps": 4,
    "points": [{ "at": 0, "speed": 0.7 }, { "at": 1, "speed": 2.2 }] },
  { "type": "addText", "trackId": "v2",
    "clip": { "id": "t1", "type": "text", "text": "标题", "start": 0.2, "duration": 2,
              "fontFile": "fonts/NotoSansCJK-Black.ttc", "fontSize": 96,
              "color": "#FFD400", "position": { "x": 0, "y": 1240 } } },
  { "type": "addClip", "trackId": "a1",
    "clip": { "id": "bgm", "type": "audio", "assetId": "bgm", "start": 0, "duration": 6, "fadeOut": 0.5 } }
]
```

## 命令

| 命令 | 作用 |
| --- | --- |
| `project init <dir> --name <name>` | 建工程，默认 1920×1080 / 30fps，按需改 `output` |
| `asset add / list / probe / remove` | 素材登记与探测 |
| `asset preview / thumbnail / sheet` | 单帧、缩略图、contact sheet |
| `asset analyze scenes\|silence` | 场景切点、静音区间分析 |
| `edit apply <ops.json>` | 执行编辑操作，支持 `--dry-run`、`--summary` |
| `history list / diff / undo / redo` | 版本历史与回滚 |
| `render --project <dir>` | 渲染成片；`--detach` 走后台任务 |
| `jobs list / show / cancel` | 异步任务管理 |

## 编辑操作

`addTrack`、`removeTrack`、`setTrackParams`、`addClip`、`addText`、`trimClip`、`moveClip`、`splitClip`、`removeClip`、`setClipParams`、`setSpeedRamp`、`importSrt`。

关键字段：

- 时间单位统一为秒；`start` 是时间线绝对位置，`sourceStart` 是素材内的入点
- `speed` 恒定变速；曲线变速用 `setSpeedRamp`，把分段线性的 `points` 物化成等速子片段（`steps` 越大越平滑，但滤镜分支也越多）
- `effects` 只挂在视觉片段上：`shake`（`amplitude` 像素、`frequency` 次/秒）、`flash`（`at` 相对片段起点）
- 同轨片段必须顺序拼接；重叠要么拆轨，要么用 `transition: { type: "xfade", duration }`
- 字幕可拆到多条轨道叠放，避免重叠校验；`importSrt` 会按时间码把每条字幕落成 `text` 片段，样式走 `fontSize` / `color` / `fontFile`
- 人声压 BGM 用轨道级 `ducking`，不用手动写音量曲线：

```json
{ "type": "setTrackParams", "trackId": "a1",
  "params": { "ducking": { "by": "a2", "threshold": 0.05, "ratio": 8, "attack": 20, "release": 400 } } }
```

  `a1`（BGM）在 `a2`（人声）出声时自动让位；`by` 取的是该轨道压之前的原始混音，所以两条轨道互相引用也不会成环。传 `ducking: null` 取消。

## 音效对位检查

渲染（含 `--dry-run`）会检查时长 ≤ 3 秒的音频片段：若起点距离最近的画面切点不到 250ms、但又超过 2 帧，就写一条 warning，提示音效可能没卡准。离切点很远的片段视为有意为之，不报警。

## 转录/字幕质检

导入字幕后先跑一遍离线检查，不用接 ASR：

```bash
codecut transcript check --srt talk.srt
codecut transcript check --srt talk.srt --max-gap 1.5 --max-chars 20 --max-duration 6 --json
```

会报告 5 类问题：`overlap`（字幕重叠，error）、`long-gap`（句间停顿过长）、`duplicate`（相邻句重复/说错重说，保留更完整的一句）、`filler`（嗯/呃/那个等语气词）、`too-long`（单条字幕超时或超字数）。阈值都可以用参数调，`--json` 输出结构化报告，方便 agent 或脚本继续处理。

## 素材自动转码

`asset add` 探测到**非 H.264** 或**带 rotation 元数据**的视频时，会自动转成 H.264 / yuv420p，把旋转烘进像素，登记 `media/<id>.mp4`，并在 metadata 里记录 `normalizedFrom`。

原因：带旋转的 HEVC 源会让渲染速度掉到 0.06x 并吃满内存被 OOM 杀掉。`--dry-run` 只报告将要转码，不写文件。

## 已知限制

- 沙箱 4GB 内存时，多轨 1080×1920 + 多特效容易 OOM。把 ffmpeg 包一层 `-threads 1 -filter_complex_threads 1` 可显著缓解，或先把素材转成 H.264
- `zoompan` 的 x/y 是整数截断，慢推会有轻微抖动；需要时可先 2× 超采样
- 字幕走 drawtext，逐词高亮这类效果目前做不到，需要 ASS
- 没有原生关键帧模型；缓动要靠表达式或物化成多段

## 测试

```bash
npm test          # 构建 + 全量测试
node --test test/effects.test.js test/speed-ramp.test.js   # 单跑某个套件
```

`test/e2e.test.js` 依赖仓库外的 `examples/headless_demo.js`，缺失时该套件会失败，与剪辑功能无关。
