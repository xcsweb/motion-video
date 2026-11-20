# Tasks

- [ ] Task 1: 搭建 `guidao-promo/` 视频工程与可复现的采集环境。
  - [ ] SubTask 1.1: 建目录 `capture/ pages/ data/ audio/ edit/ out/`，加 `.gitignore`（忽略 `.work/`、`out/frames/`、`out/*.mp4` 等大文件）。
  - [ ] SubTask 1.2: `capture/setup.sh` 克隆 guidao 到 `.work/guidao`、`npm install`、启动 dev server；脚本可重复执行。
  - [ ] SubTask 1.3: Playwright 冒烟测试：打开 `localhost:5173`，等待 `window.__viewer`，手动渲染一帧并保存，确认不是黑帧。
  - [ ] SubTask 1.4: 在本地克隆的 `Viewer.ts` 加 `preserveDrawingBuffer: true`（仅采集用），记录补丁位置；验证 `toDataURL` 可用。

- [ ] Task 2: 采集 3D 宏观镜头素材（不拍近景车站/跟随视角）。
  - [ ] SubTask 2.1: 写 `capture/camera_paths.json`：环绕、后拉、2 号线高亮、6 号线高亮、地下透视、高程夸张 1.0→1.8。
  - [ ] SubTask 2.2: 采集 10–12 张 1920×1080 英雄静帧（quality high），用于 Ken Burns。
  - [ ] SubTask 2.3: 采集 6–8 段 1280×720 运动片段（quality low/medium，30fps 逐帧），每段 3–5 秒。
  - [ ] SubTask 2.4: 生成 contact sheet 逐段检查；出现黑帧、近景低模、UI 残影的镜头直接重采或淘汰。

- [ ] Task 3: 采集真实 UI 素材。
  - [ ] SubTask 3.1: 延迟地形请求，截取加载页 20%/55%/85% 三个真实进度状态。
  - [ ] SubTask 3.2: 2× DPR 截取线路面板、李子坝车站卡片、列车运行面板、图层/高程控件。
  - [ ] SubTask 3.3: 隐藏 canvas/页面背景，裁出透明面板；确认无鼠标、toast、性能调试层。

- [ ] Task 4: 制作 2D 动态图形与标题系统。
  - [ ] SubTask 4.1: 从 `network.json`/`features.json` 生成 `data/` 快照和 `stats.json`（15/270/562km/32,736/614）。
  - [ ] SubTask 4.2: 定设计系统：`#04070b` 底、`#5FD3C4` 强调、`#F6A800` 辅助、线路官方色；Smiley Sans 标题 + Noto Sans CJK 正文 + 等宽数字。
  - [ ] SubTask 4.3: 实现 `pages/01_hook` 到 `09_cta`，每页暴露 `window.__seek(t)`，画面由数据驱动。
  - [ ] SubTask 4.4: 以 DPR 2 逐帧截取 PNG 序列（30fps），检查线条、文字、标签无锯齿/溢出。

- [ ] Task 5: 生成中文旁白与字幕。
  - [ ] SubTask 5.1: 锁定 `audio/narration.txt` 11 句文案；检查多音字（“二维”“折返”“高程”）。
  - [ ] SubTask 5.2: `audio/tts.py` 用 Kokoro 逐句生成；男声 `zm_yunjian` 与女声 `zf_xiaoxiao` 各出一版，按语速/停顿选一版。
  - [ ] SubTask 5.3: 实测每句时长，生成 `audio/lines.json` 与 `out/guidao_promo.srt`；误差 ≤ 100ms。

- [ ] Task 6: 音乐与音效设计、混音。
  - [ ] SubTask 6.1: 下载 Mixkit `A New Life`（首选）和 `Piano Reflections`（备选），分析段落/响度，确定 78 秒剪辑点。
  - [ ] SubTask 6.2: 准备列车轰鸣、轮轨、whoosh、boom、UI tick、地下低频等音效（Mixkit 或程序化合成）。
  - [ ] SubTask 6.3: 混音：BGM 在旁白下压 14–16dB，音量曲线/轻 ducking；输出 48kHz `audio/mix.wav`。
  - [ ] SubTask 6.4: 整片 `loudnorm=I=-14:TP=-1.5:LRA=11`，用 `ebur128` 复核。

- [ ] Task 7: 合成、调色、字幕与输出。
  - [ ] SubTask 7.1: 写 `edit/timeline.json`：18 个镜头、背景类型、入出点、叠加层、字幕、唯一 xfade。
  - [ ] SubTask 7.2: `edit/build.py` 用 ffmpeg 完成裁切/缩放/调色/bloom/暗角/颗粒/字幕/混音。
  - [ ] SubTask 7.3: 输出 `out/guidao_promo_1080p.mp4`、`poster.jpg`、`contact_sheet.jpg`。

- [ ] Task 8: 验收、修复与交付。
  - [ ] SubTask 8.1: `edit/validate.py` 检查 ffprobe 规格、ebur128 响度、字幕安全区、黑帧。
  - [ ] SubTask 8.2: 在 0:02 / 0:10 / 0:16 / 0:25 / 0:31 / 0:39 / 0:43 / 0:51 / 0:57 / 1:10 / 1:15 抽帧人工检查。
  - [ ] SubTask 8.3: 修复发现的问题（重采、重配、重剪），重新渲染并复验。
  - [ ] SubTask 8.4: 交付 MP4、SRT、封面、contact sheet；确认片尾署名与“模拟班次”说明完整。

# Task Dependencies

- Task 2、Task 3、Task 4、Task 5、Task 6 都依赖 Task 1；其中 Task 2/3/4 可并行，Task 5/6 可并行。
- Task 7 依赖 Task 2–6 的全部产物。
- Task 8 依赖 Task 7。
- 若 Task 2 发现某个 3D 镜头不可用，先回到 Task 2 重采，不进入 Task 7。
