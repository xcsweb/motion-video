# travel

竖屏旅行 / 情绪短片的成片仓库。核心是「文案 + 空镜 + 旁白 + 字幕 + 音乐」的固定结构，最终交给 codecut 渲染。

当前工程：

| 目录 | 内容 |
| --- | --- |
| `projects/xiancheng/` | 《没人推荐的县城》音频流水线：文案、TTS 旁白、混音、字幕时间轴 |
| `projects/shijie/` | 《世界》竖屏成片工程（codecut `project.json`） |

## 环境

```bash
python3 -m pip install -r requirements.txt   # Pillow / numpy / scipy / librosa / sherpa-onnx
```

外部依赖：

- `ffmpeg` / `ffprobe`
- 中文字体（Noto Sans CJK，脚本里用绝对路径或复制到工程 `fonts/`）
- TTS 模型首次运行会自动下载（Matcha / Kokoro），不入库

## 目录

```
travel/
├── bin/                  # 包装过的 ffmpeg（限制线程，规避小内存 OOM）
├── build/
│   ├── analyze_audio.py  # 音乐结构：BPM、小节线、逐段能量、静音起点
│   ├── make_motion.py    # 静图 → Ken Burns 运镜竖屏片段
│   ├── make_story_shots.py # 按小节线重切素材（叙事版）
│   ├── make_stock_shots.py # 按固定节奏重切素材（平铺版）
│   ├── voice.py          # Matcha-TTS 旁白
│   ├── voice_kokoro.py   # Kokoro 旁白（音色更自然）
│   ├── audio.py          # 原创钢琴/氛围垫/风声 + 混音 + ducking
│   ├── episode_audio.py  # 单集音频流水线
│   └── codecut_edit.py   # 调用 codecut 的封装
├── projects/<name>/      # 每个片子一个目录
│   ├── audio.json        # 配乐/音效编排
│   ├── audio/            # 旁白、混音、字幕时间轴
│   └── edit/project.json # codecut 工程
└── config/               # 时间线、文案
```

## 最短流程

```bash
# 0. 同级目录准备 codecut
git clone https://github.com/xcsweb/codecut
cd codecut && npm ci && npm run build && cd ..

# 1. 量音乐（决定切点）
python3 travel/build/analyze_audio.py projects/xiancheng/audio/bgm.wav
#    → bpm / bar_length / bars[] / silence_from

# 2. 写旁白（二选一）
python3 travel/build/voice.py
python3 travel/build/voice_kokoro.py

# 3. 生成运镜片段
python3 travel/build/make_motion.py

# 4. 混音（含 ducking）
python3 travel/build/audio.py

# 5. 渲染
node ../codecut/dist/cli.js render --project projects/<name>/edit
```

## 剪辑原则（这支片子验证过的）

1. **先测音频再排画面**：BPM、小节线、副歌点、音乐结束点，四个数决定所有切点
2. 铺垫段少切、慢切；副歌第一拍做一次画面质变（暗转亮、近转远）
3. 切点落在小节线上，不落在句中
4. 音乐停了就黑场，不要用画面填满空白
5. 大字落在换气处，一句话一个词，不要整句

`make_story_shots.py` 里的 `CUTS` 数组就是小节线，改数组即改结构。

## 已知限制

- 旁白是 TTS，不是真人；需要真人质感只能录真人或换云 TTS
- 素材库给不了「同一个人走完全程」的连续性，故事感受限于素材
- 4GB 内存下多轨 1080×1920 渲染容易 OOM，用 `travel/bin/ffmpeg` 包装（单线程）再渲染
- 第三方音乐与素材不入库，需要自行下载；BGM 授权见各工程 README
