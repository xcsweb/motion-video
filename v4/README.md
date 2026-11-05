# v4 复刻版：三类素材混剪的 85 秒 MV

原始 v4 的工程文件在归档时没有保留下来。这里按同样的原理重写了一版可运行的实现：

- **image**：AI 插画 + Ken Burns 运镜 + 统一调色
- **web**：10 个 HTML 特效页，`window.__seek(t)` 确定性渲染，Playwright 逐帧截取
- **cannon**：复用 `scripts/render.py` 的电磁炮绘制函数，按 6 个机位重新取景
- **UI**：卡拉 OK 歌词、HUD、片头片尾，独立于镜头运动

> 这是重写版，不是原 v4 的逐行还原。素材为重新生成；歌词时间轴按 85 秒剪辑版重新对齐，可能与原片有差异。

## 目录

```
v4/
├── config/
│   ├── timeline.json      # 39 个镜头：类型、时间、机位、转场、色调
│   └── lyrics.json        # 22 句歌词与逐字高亮时间
├── pages/                 # 10 个网页特效页 + base.css + app.js
├── build/
│   ├── capture_web.py     # Playwright 逐帧截图 → assets/web/<page>/
│   ├── render.py          # 合成器：image / web / cannon + UI
│   └── encode.sh          # ffmpeg 合成
├── assets/
│   ├── ai/                # 16 张 AI 插画
│   ├── web/               # 网页帧（由脚本生成，不入库）
│   └── audio/             # 音轨（不入库）
├── frames/                # 中间帧（不入库）
└── previews/              # 样帧（不入库）
```

## 运行

```bash
# 0. 依赖
pip install numpy scipy Pillow playwright
python -m playwright install chromium
python -m playwright install-deps chromium

# 1. 准备音轨：85 秒，放到 assets/audio/source.wav
#    本项目不附带原曲，请使用自己拥有授权的音轨

# 2. 截取 10 个网页页（24fps）
python build/capture_web.py

# 3. 渲染（4 进程；先出几张样帧）
python build/render.py --mode sample --times 1.5 12.6 20 58

# 4. 全量渲染 2558 帧
python build/render.py --mode all --workers 4

# 5. 合成
bash build/encode.sh
```

## 设计约定

- 每个网页页只依赖传入的 `t`：`window.__seek(t)` 重绘整页，禁用 rAF，保证同一 t 永远同一帧。
- 页面统一 1920×1080，截图脚本用 `?t=` 首帧预热后逐帧调用 `__seek`。
- 歌词与 HUD 在合成阶段最后叠加，改文案或字号不需要重渲画面。
- 所有素材走同一套调色：青蓝暗部 + 洋红高光 + 低强度 bloom。
- 镜头表只有一个来源 `config/timeline.json`；改时间、机位、转场都只改这一处。

## 与原始 v4 的差异

| 项目 | 原始 v4 | 本复刻版 |
| --- | --- | --- |
| 源码 | 已丢失 | 重写，可运行 |
| 插画 | 16 张（原批） | 重新生成 16 张 |
| 歌词 | `lyrics_85.json`（原时间轴） | 按剪辑版重新对齐 |
| 网页页 | 10 个 | 重写 10 个，交互与信息结构一致 |
| 电磁炮 | 自定义 `cannon_plate` | 复用 v1 绘制函数 + 6 机位取景 |

## 版权

音乐与《某科学的超电磁炮》相关权利归 fripSide / NBC 环球日本。本项目仅作技术演示，不含原曲音频，请勿用于商业发布。
