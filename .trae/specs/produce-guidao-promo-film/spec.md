# 山城轨道宣传片 Spec

## Why / 为什么

`guidao` 用真实地形高程和 OpenStreetMap 线网数据，把重庆轨道交通做成了可在浏览器里运行的三维可视化。README 和静态截图无法传达三个核心体验：线网在真实地形上展开、列车按班次运行、地下线网可以透视。需要一支 75–90 秒的横屏宣传片，让开发者、招聘方和普通观众在一分钟内理解：这不是一张地图，而是一座可运行的城市数字孪生。

一句话创意：**从一张扁平的二维线网，到一座在真实地形上生长出来的三维城市；最后落到“打开浏览器，坐上这班车”。**

## What Changes / 变更内容

- 新增 `guidao-promo/` 视频工程：创意与分镜、3D 素材采集、真实 UI 采集、2D 动态图形、中文 TTS 旁白、BGM/音效、ffmpeg 合成与验收脚本。
- 交付 `1920×1080 / 30fps / 约 78 秒` 的 H.264 MP4，中文旁白 + 句级字幕 + 授权 BGM。
- 交付 SRT 字幕、封面图、contact sheet，以及可复现的构建脚本。
- **不修改 `guidao` 仓库源码**：采集使用本地克隆和 Playwright；只在本地克隆中为采集打开 `preserveDrawingBuffer`，不提交、不回写。
- 不修改 workspace 中已有的 `motion-video`、`travel`、`codecut` 行为；复用其 TTS、音频和 HTML 逐帧截取经验。

## Impact / 影响

- Affected specs：新增“视频交付”能力；不改变现有视频项目规格。
- Affected code：仅新增 `guidao-promo/` 目录；`guidao`、`codecut`、`travel`、`v4` 均不改动。
- 外部依赖：`ffmpeg`/`ffprobe`、Playwright Chromium、`sherpa-onnx`（Kokoro 中文 TTS）、Mixkit 音乐/音效、系统 Noto Sans CJK / Smiley Sans 字体。

## 调研结论与取舍

### 1. 别人的产品宣传片怎么拍

- **四段式结构最稳**：Hook（先给痛点/结果）→ Problem（具体问题）→ Solution（一个核心工作流）→ Proof + CTA（一个具体结果、一个下一步）。首页 hero 视频建议 60–90 秒；开头 15 秒不要放 logo 和功能清单。
- **GitHub 项目 demo 是“预告片”，不是“说明书”**：30–90 秒，先讲问题，再立刻展示结果；只展示一条完整工作流；必须配字幕（大量开发者静音观看）；结尾只留一个 CTA（仓库或在线 demo）。
- **节奏规则**：任何镜头不超过 5 秒没有变化；旁白与画面动作同步；用 J-cut/L-cut 保持声音连续；关键句后留 1 秒呼吸。
- **音频优先于画面**：观众能容忍不够精致的画面，但忍不了糟糕的声音；旁白必须清楚，BGM 只做垫底。
- **3D 地铁宣传片的常用语法**：城市鸟瞰/航拍建立空间 → 镜头下降或穿行 → 站厅/站台细节 → 多视角切换；科技风材质 + 简约线稿；镜头运动要连续，不要无意义旋转。

### 2. 你的飞书文档能直接用上的结论

- BGM 选曲：60–85 BPM、小调优先、亮度低于 1600Hz、鼓点极轻或无鼓；BGM 低于人声 14–18dB，全程不断、不卡点；结尾留白。
- 结构：开头 3 秒给钩子；句级字幕、底部居中；参考片 90.14 秒 / 41 个镜头 / 平均 2.2 秒一切；关键句可以留 4–6 秒。
- 制作：旁白逐句生成、按实测时长排入点；BGM 用 `volumePoints`/ducking；最终 `loudnorm` 到 -14 LUFS、真峰值 ≤ -1.5 dBFS；抽帧检查字幕安全区。
- 可复用工具链：`travel/build/voice_kokoro.py` 的 Kokoro 中文 TTS、`travel/build/audio.py` 的原创配乐/混音思路、`v4/build/capture_web.py` 的 `window.__seek(t)` 逐帧截取方法。

### 3. 对 guidao 实际画面的审计（决定分镜）

在本地跑起 guidao 并逐帧截图后，得到三条硬约束：

- **最好看的是 8–15km 的宏观线网视角**：地形、江面、15 条线路和站点分布都能读清楚，适合做电影感缓慢运镜。
- **4–6km 的近景偏弱**：建筑是低多边形体块，车站细节在无头渲染下不稳定；李子坝站在数据里被标成 `underground`，站台/跟随视角在采集环境里会黑屏。因此**不拍近景车站、不拍第一视角跟车**，改用真实 UI 卡片和 2D 线网动画讲清楚这些能力。
- **UI 是强项**：线路面板、车站卡片、列车运行面板、加载页的视觉完成度高，适合 2× 截取后做特写；但只展示真实存在的数据和状态，不伪造界面。

### 4. 技术可行性验证

- 本地 guidao + Playwright Chromium（SwiftShader）可稳定加载；`window.__viewer` 在 DEV 下暴露，可暂停渲染、设定仿真时间、直接设置相机并逐帧调用 `loop(now)`。
- 1080p 全场景约 2.5–6 秒/帧，720p 约 1–2 秒/帧。因此：**3D 运动镜头用 1280×720 采集后放大，3D 英雄静帧用 1920×1080 采集后做 Ken Burns**；2D/UI 用 2× 像素截取，保证文字锐利。
- Kokoro 中文 TTS（`sherpa-onnx`）可离线生成旁白；Mixkit 的 `A New Life`（1:39）和 `Piano Reflections`（3:19）可下载完整轨，授权为免费商用。

### 参考来源

- [Product Demo Video Best Practices: 2026](https://videoeditingcompany.com/product-demo-video-best-practices/)
- [How to Create a Demo Video for Your GitHub Project (2026 Guide)](https://repoclip.io/blog/how-to-create-demo-video-github-project)
- [How to Make Product Demo Videos That Convert (2026)](https://www.storimaticstudio.com/blog/how-to-make-product-demo-video/)
- [Product Demo Video: Complete Guide](https://neverframe.com/blog/product-demo-video-complete-guide)
- [中铁建设集团地铁站三维动画](http://www.4ddh.com/gcsgdh/85.html)
- [广州地铁 12 号线三维动画宣传片](http://www.moview3d.cn/article/774.html)
- [北京地铁形象宣传片脚本](http://haidianqu.chuangzuoniu.cn/article/detail-238761.html)
- 飞书：[视频项目选型与工作流指南](https://my.feishu.cn/docx/KK4oducSaoTBHaxDLcOcmaCrnQe)、[口播视频：选题与 BGM 研究汇总](https://my.feishu.cn/docx/PwtDdcGLNoymekxFp0OcdYndnCe)、[20 首 BGM 候选歌单](https://my.feishu.cn/docx/BUyKdLTPio6n4mx4fEgcr7hunhb)、[参考片配乐拆解 + 3 版 BGM 试听](https://my.feishu.cn/docx/UJSOdhcMMoSvcwx9F5UczzS3nlc)、[30 秒治愈系视频制作全流程](https://my.feishu.cn/docx/MqS8dOAoyoGk0FxUgAEcAgLVnmg)

## 创意与叙事

### 基调

克制、电影感、科技但不炫技。暗色底、缓慢运镜、线路颜色是唯一的高饱和元素；字幕像产品发布会，不像短视频花字。没有“震惊体”，没有夸张音效，没有伪造的 UI。

### 叙事弧线

1. **钩子（0–14s）**：重庆没有一条路是平的；二维线网画不出这座城市的立体。
2. **揭晓（14–20s）**：把整座城市搬进浏览器；标题出现。
3. **证明（20–55s）**：15 条线 / 270 座车站 / 562km 在真实地形上展开；点开一条线，镜头飞过去；车站卡片、列车运行、地下透视、高程夸张。
4. **工程可信度（55–63s）**：从 OSM 到地形高程，从班次表到可接入的实时源；城市数据包即插即用。
5. **收束（63–78s）**：城市全景；品牌与一个 CTA；署名与“模拟班次”说明。

## 成片规格

| 项 | 规格 |
| --- | --- |
| 画幅 | 1920×1080，16:9，全画幅无遮幅 |
| 帧率 | 30fps |
| 时长 | 78 秒（可接受 75–90 秒） |
| 编码 | H.264 High，yuv420p，CRF 18–20；AAC 48kHz 立体声 192kbps；`+faststart` |
| 响度 | 整片 -14 LUFS ±0.5；真峰值 ≤ -1.5 dBFS |
| 旁白 | 中文，Kokoro TTS，男声优先（`zm_yunjian`），备选女声（`zf_xiaoxiao`） |
| 字幕 | 句级、底部居中、2 行以内；烧录 + 独立 SRT |
| 音乐 | Mixkit `A New Life`（首选）或 `Piano Reflections`（备选），免费商用 |
| 交付 | `guidao-promo/out/guidao_promo_1080p.mp4`、`.srt`、`poster.jpg`、`contact_sheet.jpg` |

## 旁白与字幕

旁白按句生成，按实测时长排入点；每句对应一个画面动作，不做“画面先剪好再配旁白”。

| # | 入点 | 旁白 | 画面任务 |
| --- | --- | --- | --- |
| 1 | 0:00 | 重庆，没有一条路是平的。 | 黑场、低频列车轰鸣、标题钩子 |
| 2 | 0:04 | 轻轨穿楼，地铁入地，一座城市被折叠成立体。 | 2D 线网开始生长；李子坝/朝天门标签 |
| 3 | 0:09 | 二维线网告诉你去哪，却画不出你要经过什么。 | 线网铺满、轻微倾斜；准备 match cut |
| 4 | 0:14 | 我们把整座城市，搬进了浏览器。 | 2D → 3D 揭晓；标题「山城轨道」 |
| 5 | 0:20 | 十五条线路，二百七十座车站，沿着真实高程生长。 | 3D 宏观轨道 + 数字滚动 |
| 6 | 0:27 | 点开一条线，镜头带你飞过去。 | 2 号线/6 号线高亮；线路面板 |
| 7 | 0:33 | 每一座车站，都有真实的位置和到发时刻。 | 李子坝车站卡片 + 3D 线网背景 |
| 8 | 0:40 | 列车按运行图发车、进站、折返。 | 列车运行面板；状态/ETA 特写 |
| 9 | 0:47 | 地下线网，可以透视；山城的高度，可以拉开。 | 地下透视开关；高程夸张 1.0→1.8 |
| 10 | 0:55 | 从开放地图数据，到可接入的实时列车。 | 数据管线/终端/文件树 |
| 11 | 1:03 | 山城轨道。打开浏览器，坐上这班车。 | 城市全景 → 品牌 → CTA |
| — | 1:12 | （音乐收尾，无旁白） | 片尾卡、URL、署名 |

字幕规范：

- 字号 42–46px（1080p），Noto Sans CJK SC Medium；关键词用 `#5FD3C4` 或线路色，单句最多强调 1 个词。
- 底部安全区：距底边 96px，左右各留 8%；字幕下面加 40% 黑色渐变 scrim，保证在亮地形上也可读。
- 不用逐字高亮、不用弹跳动画；整句淡入 120ms、淡出 120ms。

## 分镜表

| # | 时间 | 时长 | 画面 | 运镜/动效 | 声音 |
| --- | --- | --- | --- | --- | --- |
| S01 | 0:00–0:03 | 3s | 黑场；「重庆，没有一条路是平的。」 | 文字逐行淡入；极轻的噪点 | 低频轰鸣、远处轮轨声 |
| S02 | 0:03–0:07 | 4s | 2D 线网从中心向外生长；江河水系先出现 | 线条 stroke 生长；站点逐颗亮起 | BGM 进入；细碎 UI tick |
| S03 | 0:07–0:11 | 4s | 15 条线全部亮起；李子坝、朝天门、重庆北站标签 | 缓慢推近；标签错峰出现 | 轮轨声渐强 |
| S04 | 0:11–0:14 | 3s | 2D 线网整体倾斜/拉伸，画面被一道冷光扫过 | 2.5D 透视 + 白场过渡 | riser → 低频 boom |
| S05 | 0:14–0:20 | 6s | 3D 地形与线网从黑暗中浮现；标题「山城轨道」 | 相机后拉；标题字距收紧 | boom 收尾；BGM 打开 |
| S06 | 0:20–0:24 | 4s | 3D 线网宏观环绕；15 条线依次点亮 | 缓慢环绕 8–12km 高度 | 轻鼓点/弦乐推进 |
| S07 | 0:24–0:28 | 4s | 数字：15 条线 / 270 座车站 / 562km / 32,736 栋建筑 / 614 条水系 | 数字滚动；线路面板滑入 | UI tick 落在数字落定 |
| S08 | 0:28–0:33 | 5s | 2 号线高亮，镜头沿嘉陵江/李子坝方向移动 | 线路高亮；相机缓推 | BGM 持续；轻微 whoosh |
| S09 | 0:33–0:37 | 4s | 6 号线高亮，跨江段；江面反光 | 相机横移 | 水声/低频 |
| S10 | 0:37–0:41 | 4s | 真实「李子坝」车站卡片特写；背景是 3D 线网 | 卡片 2× 截图，缓慢上浮 | UI 轻响 |
| S11 | 0:41–0:45 | 4s | 列车运行面板：运行中/进站中/停站中/出站中 + ETA | 面板局部特写；列表轻微滚动 | 车站广播质感（很轻） |
| S12 | 0:45–0:49 | 4s | 打开「地下线路透视」；地下线网在 terrain 下发光 | 开关切换 + 亮度过渡 | 低频下潜 |
| S13 | 0:49–0:54 | 5s | 高程夸张 1.0→1.8；山城被拉高 | 参数滑块 + 地形抬升 | riser；弦乐抬升 |
| S14 | 0:54–0:58 | 4s | 终端/文件树：`npm run build:data`；OSM → terrain → network | 打字机 + 文件高亮 | 键盘声、数据流声 |
| S15 | 0:58–1:03 | 5s | 数据管线示意：城市注册表 + 标准数据包 + 实时 Provider | 节点连线动画 | BGM 推进 |
| S16 | 1:03–1:08 | 5s | 3D 城市夜景全景；列车光点沿线移动 | 大范围后拉/环绕 | BGM 打开；轮轨声 |
| S17 | 1:08–1:12 | 4s | 品牌标题「山城轨道」压在城市全景上 | 标题定版；轻微发光 | 音乐留白 1 拍 |
| S18 | 1:12–1:18 | 6s | 片尾卡：URL、GitHub、数据署名 | 元素依次淡入；最后 1s 黑场 | 音乐 tail；列车远去 |

> 约束：任何镜头不超过 5 秒没有变化；S05、S13、S17 可以例外，但必须有运镜或字效变化。

## 声音设计

- **BGM**：首选 Mixkit `A New Life`（Eugenio Mininni，1:39，约 64.6 BPM，A 小调，弦乐/合成器，Hope/Reflective）。结构上用它前 78 秒：0:00 滤波进入，0:14 打开，0:54 抬升，1:12 收束。备选 `Piano Reflections`（Ahjay Stelino，3:19，60.1 BPM，E 小调）。
- **旁白**：Kokoro `zm_yunjian`（男声，稳）优先；`zf_xiaoxiao`（女声，清晰）备选。逐句生成，speed 0.92–0.96；高通 80Hz、3–5kHz 轻微 presence、轻压缩；避免齿音。
- **音效**：列车低频轰鸣、轮轨 clack、map→3D 的 whoosh、标题 boom、UI tick、地下透视的低频下潜、数据管线的键盘/数据流。全部来自 Mixkit 免费音效或程序化合成；不用未授权素材。
- **混音**：BGM 在旁白下压低 14–16dB；旁白出现时用音量曲线/轻 ducking，不做明显 pumping；音效峰值不盖过旁白；整片 `loudnorm=I=-14:TP=-1.5:LRA=11`，48kHz 立体声。

## 技术方案

### 目录

```text
guidao-promo/
  capture/
    setup.sh               # 克隆 guidao、安装依赖、启动本地 dev server
    capture_3d.py          # 3D 英雄静帧 + 运动片段
    capture_ui.py          # 加载页/面板/卡片，2× 像素
    capture_pages.py       # HTML 动态图形逐帧截取
  pages/                   # 每个页面实现 window.__seek(t)
  data/                    # network.json / features.json 快照 + stats.json
  audio/
    tts.py                 # Kokoro 逐句旁白
    mix.py                 # BGM/SFX/VO 混音与响度
  edit/
    timeline.json          # 镜头、素材、字幕、转场
    build.py               # ffmpeg 合成、调色、字幕、输出
    validate.py            # ffprobe/响度/抽帧验收
  out/
```

### 3D 采集

- 本地克隆 guidao 到 `guidao-promo/.work/guidao`（gitignore），`npm install` 后 `npm run dev`。
- Playwright Chromium 打开 `http://localhost:5173/`，等待 `window.__viewer` 可用。
- 采集时：`clock.paused = true`，手动设定 `clock.timeSec`；直接设置 `camera.position` / `controls.target`；每帧 `lastFrame = now - 33.34` 后调用 `viewer.loop(now)`，再立即 `canvas.toDataURL('image/jpeg', 0.95)`。
- 在本地克隆的 `Viewer.ts` 中只加一行 `preserveDrawingBuffer: true`（采集用，不提交）。
- 3D 运动：1280×720，quality `low`/`medium`，隐藏 buildings/vegetation 以提速；按 30fps 逐帧步进（`t += 1/30`）直接采集，不做光流插帧。3D 静帧：1920×1080，quality `high`，用于 Ken Burns。
- 相机路线只用宏观高度（8–15km），避免 4–6km 的近景低模；不采集 follow/platform 视角。

### 2D 动态图形

- 用 `network.json` 的真实 `path`（`[x,z,...]` 扁平数组）和 `features.json` 的河流，绘制 2D 线网。
- 官方线路色；江河水系用低饱和深青；背景加细网格/噪点；站点用 2–3px 圆点，重点站标签用中文。
- 每个页面暴露 `window.__seek(t)`，保证同一 `t` 画面完全一致；Playwright 以 DPR 2 逐帧截取，输出 PNG。
- 页面清单：`01_hook`、`02_map2d`、`03_reveal`、`04_stats`、`05_lines`、`06_ui`、`07_xray`、`08_craft`、`09_cta`。

### UI 采集

- 加载页：拦截地形文件请求并延迟，截取 20%/55%/85% 三个真实进度状态；或按真实 DOM 结构重绘，文字必须与源码一致。
- 面板：线路面板、李子坝车站卡片、列车运行面板、图层/高程控件；在 2× DPR 下截取，隐藏 canvas 和页面背景以获得透明面板。
- 不伪造数据；数字与状态直接来自 `network.json` / 运行时 store。

### 合成

- `edit/timeline.json` 定义每个镜头的背景类型（3D 片段/静帧/2D 页面/纯色）、入出点、叠加层、字幕、转场。
- ffmpeg `filter_complex` 逐段处理：裁切→缩放→调色（青影/暖高光、对比、饱和）→ bloom（`gblur`+`blend=screen`）→ 暗角→细颗粒→字幕。
- 只在一个地方用 `xfade`（S04→S05 的 2D→3D），其余硬切；J/L cut 由音频先入/后出实现。
- 输出 `guidao_promo_1080p.mp4`，再生成 `poster.jpg`（1:08 或 1:12 的干净帧）和 `contact_sheet.jpg`（每 5 秒一帧）。

### 旁白与字幕

- Kokoro 模型放在 `guidao-promo/.work/models/kokoro-multi-lang-v1_0`（不入库）；`audio/tts.py` 逐句生成 48kHz WAV，输出 `vo/lines.json`（文本、入点、时长）。
- 按实测时长微调旁白入点；字幕由 `lines.json` 生成 SRT，再转 ASS 烧录。
- 字幕与旁白误差 ≤ 100ms；字幕不压到画面关键信息（站名、数字、URL）。

## 验收标准

### 技术

- `ffprobe`：1920×1080、30fps、78s（75–90 可接受）、H.264 + AAC、`faststart`。
- `ebur128`：-14 LUFS ±0.5；真峰值 ≤ -1.5 dBFS。
- 全片可完整解码，无丢帧、无黑帧（除 S01/S18 的意图黑场）、无音频爆音。
- 字幕安全区：左右 ≥ 8%，底部 ≥ 96px；最大 2 行；无截断。

### 内容

- 片头 3 秒内出现钩子；没有 logo 开场、没有功能清单旁白。
- 事实准确：15 条线路、270 座车站、562km、32,736 栋建筑、614 条水系；列车为“模拟班次”。
- 只展示真实存在的功能与 UI；不出现 follow/platform 黑屏、不伪造按钮/数据。
- 片尾有且只有一个主 CTA（在线 demo），GitHub 作为次级链接；数据署名完整。
- 旁白与字幕一致；关键数字与画面一致。

### 版权与合规

- BGM/音效均来自 Mixkit 免费商用库，保留授权说明；不使用参考片音乐。
- 地图/地形署名：`线网/建筑/水系 © OpenStreetMap 贡献者 (ODbL)`、`高程 Terrarium / AWS Open Data`。
- TTS 旁白在发布描述中注明“AI 配音”；若平台要求 AI 内容标注，按平台规则执行。

### 可复现

- `capture/setup.sh` 可从头拉起本地 guidao 和采集环境。
- `python3 edit/build.py` 可从 `out/frames` + `audio/mix.wav` 一键出片。
- `python3 edit/validate.py` 自动检查规格、响度、字幕和抽帧。

## ADDED Requirements

### Requirement: 宣传片成片

系统 SHALL 交付一支 1920×1080 / 30fps / 75–90 秒的中文旁白宣传片，MP4 可在浏览器和常见播放器中直接播放。

#### Scenario: 规格与播放

- **WHEN** 播放 `guidao_promo_1080p.mp4`
- **THEN** 画面为 1920×1080、30fps，时长 75–90 秒，H.264/AAC，音频无爆音，字幕完整可读

#### Scenario: 叙事与 CTA

- **WHEN** 观众观看前 5 秒
- **THEN** 出现明确钩子（重庆没有一条路是平的），而不是 logo 或功能列表
- **WHEN** 视频结束
- **THEN** 只出现一个主 CTA（在线 demo URL）和完整的 GitHub/数据署名

### Requirement: 真实素材与事实一致

系统 SHALL 只使用 guidao 真实渲染画面、真实 UI 和真实数据；不得伪造功能、按钮或运营数据。

#### Scenario: UI 与数据

- **WHEN** 画面出现线路数、车站数、里程、建筑/水系数量
- **THEN** 数字与 `network.json`/`manifest.json` 一致（15 / 270 / 562km / 32,736 / 614）
- **WHEN** 画面出现列车状态或到发时刻
- **THEN** 界面标注“模拟班次”，且不宣称是官方实时数据

### Requirement: 可复现制作管线

系统 SHALL 提供从素材采集、旁白、混音到成片输出的脚本，使同一工程可重新生成成片。

#### Scenario: 重新构建

- **WHEN** 在干净环境执行 `capture/setup.sh` 和 `python3 edit/build.py`
- **THEN** 生成与交付版规格一致的 MP4、SRT、封面和 contact sheet
- **WHEN** 执行 `python3 edit/validate.py`
- **THEN** 自动输出规格、响度、字幕安全区和抽帧检查结果

### Requirement: 版权与署名

系统 SHALL 使用可商用授权的音乐/音效，并在片尾保留地图、地形和模拟数据的署名。

#### Scenario: 片尾署名

- **WHEN** 视频进入片尾卡
- **THEN** 显示 OpenStreetMap ODbL、Terrarium/AWS Open Data、模拟班次说明

## MODIFIED Requirements

无。该变更只新增视频工程，不修改现有项目行为。

## REMOVED Requirements

无。
