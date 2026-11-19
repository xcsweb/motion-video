# 30 秒治愈系视频制作全流程（可复用技巧）

> 案例：抖音「野生了了」《有一种累，叫明明一天什么也没干…》的 30 秒重制
> 工具链：ffmpeg/ffprobe + codecut CLI + 豆包 TTS + Mixkit 素材
> 目标：把「看一条参考片」变成「拆出规格 → 找素材 → 配音 → 组装 → 验收」的可重复流水线

## 总览：五步流水线

| 步骤 | 产出 | 用什么 |
|---|---|---|
| 0. 拆解参考片 | 时长、镜头表、节奏、字幕、响度 | ffprobe 场景检测 / silencedetect / ebur128 |
| 1. 写成规格 | 镜头时长表、字幕规范、声音规则 | 人工归纳，落到数字 |
| 2. 找素材 | 覆盖镜头表的空镜 | Mixkit 免费商用库，抓直链 |
| 3. 做旁白 | 逐句音频 + 整轨 | 豆包复刻音色，语速放慢 |
| 4. 组装 | project.json + 成片 | codecut CLI |
| 5. 验收 | 抽帧、响度、字幕质检 | preview frame / ffprobe / transcript check |

## 第 0 步：用数据拆解参考片

不要凭感觉描述节奏，先量出来：

```bash
# 基础参数
ffprobe -v error -show_entries format=duration:stream=codec_type,width,height,r_frame_rate \
  -of json ref.mp4

# 镜头切点（阈值 0.25 比较适合口播/空镜混剪）
ffmpeg -i ref.mp4 -filter:v "select='gt(scene,0.25)',showinfo" -f null - 2>&1 \
  | grep showinfo | sed -E 's/.*pts_time:([0-9.]+).*/\1/' > cuts.txt

# 用切点算镜头时长分布（python）
python3 - <<'EOF'
pts=[0.0]+[float(x) for x in open('cuts.txt')]+[90.1]
d=[round(b-a,2) for a,b in zip(pts,pts[1:])]
print(len(d), sum(d)/len(d), sorted(d)[len(d)//2], max(d))
EOF

# 静音区间与整体响度
ffmpeg -i ref.mp4 -af silencedetect=noise=-35dB:d=0.4 -f null - 2>&1 | grep silence_
ffmpeg -i ref.mp4 -af ebur128=peak=true -f null - 2>&1 | tail -20
```

记下四个数：**时长、镜头数、平均/中位镜头时长、整体 LUFS**。参考片是 90.1s / 41 个镜头 / 平均 2.2s / 中位 1.67s / -8.7 LUFS。

## 第 1 步：把观感翻译成可执行规格

拆解结论必须变成数字，否则剪的时候没有依据：

- **开头 3 秒只给情绪**：第一句不介绍背景，直接写状态（「有一种累…」）。
- **镜头时长**：主体段 2 秒一切，关键句留 4–6 秒；30 秒版平均 3.3 秒，比原片慢，是为了让治愈语气有呼吸。
- **字幕**：白色、句级、底部居中、2px 黑描边，一条字幕一句话。
- **声音**：人声全程，BGM 压到 0.22，人声出现时再让 3–6 dB。

## 第 2 步：找素材（Mixkit）

- 按镜头表逐个关键词搜空镜，优先**细节/氛围**（窗、雨、脚步、落叶、热茶），不要大场面。
- 从播放页抓 `assets.mixkit.co` 直链，用 `curl -L` 下载并统一命名成 `25145.mp4` 这类 ID。
- **颜色统一**：只选暖色、低对比、暗部不死黑的片段；冷色素材直接淘汰，不要指望后期救。
- 多下 1.5 倍候选，渲染前先拼 contact sheet 选片：

```bash
ffmpeg -i a.mp4 -i b.mp4 -i c.mp4 -i d.mp4 -filter_complex \
  "[0:v]scale=480:-1[a];[1:v]scale=480:-1[b];[2:v]scale=480:-1[c];[3:v]scale=480:-1[d];[a][b][c][d]xstack=inputs=4:layout=0_0|w0_0|0_h0|w0_h0" \
  -frames:v 1 sheet.jpg
```

## 第 3 步：做旁白（豆包复刻音色）

治愈系的关键不是文案，是**语速**。第一次生成偏快，原因是默认语速；把 `speech-rate` 调到 -20 后节奏才松下来。

- 逐句生成 `line1.mp3 … line5.mp3`，方便单独重录某一句。
- 每句生成后用 `ffprobe` 量时长，用来排入点，不要凭感觉。
- 整轨拼接：按入点用 `adelay` + `amix`，最后统一 `loudnorm=I=-16:TP=-1.5`，输出 48kHz 立体声 wav。

```bash
ffmpeg -i line1.mp3 -i line2.mp3 ... -filter_complex \
"[0:a]adelay=800|800[a0];[1:a]adelay=5332|5332[a1];...;[a0][a1]...amix=inputs=5:normalize=0,loudnorm=I=-16:TP=-1.5" \
-ar 48000 -ac 2 narration.wav
```

## 第 4 步：用 codecut 组装

```bash
codecut project init proj --name healing-30s          # 默认 1920x1080 / 30fps
codecut asset add media/25145.mp4 --id shot-window --project proj
# … 9 个镜头 + narration.wav + bgm.mp3
codecut edit apply ops.json --project proj --dry-run   # 先预演
codecut edit apply ops.json --project proj
codecut render --project proj --force                  # 注意是 --force，不是 --overwrite
```

`ops.json` 的关键写法：

- 镜头：同轨顺序拼接，`start` 是时间线绝对位置，`sourceStart` 是素材入点。
- 字幕：`type: text`，`fontFile: fonts/NotoSansCJK-Medium.ttc`、`fontSize: 44`、`color: #FFFFFF`、`borderWidth: 2`、`borderColor: #000000`、`position: {x:0, y:880}`（1080p 底部）。
- BGM：`volume: 0.22`、`fadeIn: 1`、`fadeOut: 3`。
- 人声压 BGM 用轨道级 ducking，不要手写关键帧：

```json
{ "type": "setTrackParams", "trackId": "a2",
  "params": { "ducking": { "by": "a1", "threshold": 0.03, "ratio": 6, "attack": 20, "release": 400 } } }
```

## 第 5 步：验收（三步）

1. **抽帧看字幕**：`codecut preview frame --project proj --at 2`（子命令是 `preview frame`，输出写在 `proj/preview.png`），再在 2s / 12s / 24s 各抽一帧拼图检查。
2. **量响度与时长**：`ffprobe` 确认 30.0s；`ebur128` 确认约 -16 LUFS、真峰值低于 -1 dBTP。
3. **字幕质检**：`codecut transcript check --srt talk.srt` 查重叠、长停顿、重复句、语气词、超长句。

## 踩过的坑

| 现象 | 原因 | 做法 |
|---|---|---|
| 字幕完全不显示 | 文本片段 `position` 被 drawtext 和轨道 overlay 各应用一次 | 文本只在画布内定位，overlay 固定 (0,0)（已修复） |
| `asset add` 报 `ASSET_FILE_MISSING` | 路径少了 `.mp4` 扩展名 | 用完整带扩展名的路径 |
| `render --overwrite` 报错 | 参数名不对 | 用 `--force` |
| `preview` 报 unknown action | 少了子命令 | `codecut preview frame --at 2` |
| 逐句 TTS 拼接后节奏发赶 | 默认语速偏快 | `speech-rate -20`，并按实测时长排入点 |
| 1080p 多轨渲染 OOM | 沙箱内存有限 | 先转 H.264、`-threads 1`，减少同时激活的特效 |

## 可复用配方（30 秒治愈系）

| 项 | 取值 |
|---|---|
| 输出 | 1920×1080 / 30fps / H.264 + AAC / 30.0s |
| 镜头 | 9 个，3–4 秒一个，结尾镜头留 4 秒 |
| 旁白 | 5 句，每句 4–6 秒，句间留 0.5 秒换气 |
| 字幕 | 44px 白色 + 2px 黑描边，底部 y=880，句级 |
| BGM | 0.22 音量，淡入 1s / 淡出 3s，ducking 让 6dB |
| 响度 | -16 LUFS，真峰值 ≤ -1.5 dBFS |

## 下一步可以自动化的部分

- 用 transcript check 的输出自动校验字幕时间码是否压到旁白。
- 把 `ops.json` 模板化：给定旁白音频和素材目录，按句时长自动生成切点。
- 拆解阶段接 ASR，直接拿到参考片台词，而不是靠画面字幕推断。
