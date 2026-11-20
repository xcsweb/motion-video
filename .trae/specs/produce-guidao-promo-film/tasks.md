# Tasks

> **Gate：Task 0 未确认前，不执行 Task 1 及以后的任何采集、配音、合成工作。**

- [x] Task 0: 确认文案与画面规划（当前阶段）。
  - [x] SubTask 0.1: 确认 11 句“指挥使”版旁白全文、字幕断行、语气/停顿。
  - [x] SubTask 0.2: 确认 17 个镜头的画面、运镜、文字/UI、声音/旁白对应关系，以及前 3 秒“点击→城市站起来”的钩子。
  - [x] SubTask 0.3: 确认视觉基调（色彩、字体、质感、转场）与画面禁区。
  - [x] SubTask 0.4: 用户明确回复“文案和画面规划 OK”后，才把本项勾选并进入 Task 1。

- [x] Task 1: 搭建 `guidao-promo/` 视频工程与可复现的采集环境。
  - [x] SubTask 1.1: 建目录 `capture/ pages/ data/ audio/ edit/ out/`，加 `.gitignore`（忽略 `.work/`、`out/frames/`、`out/*.mp4` 等大文件）。
  - [x] SubTask 1.2: `capture/setup.sh` 克隆 guidao 到 `.work/guidao`、`npm install`、启动 dev server；脚本可重复执行。
  - [x] SubTask 1.3: Playwright 冒烟测试：打开 `localhost:5173`，等待 `window.__viewer`，手动渲染一帧并保存，确认不是黑帧。
  - [x] SubTask 1.4: 在本地克隆的 `Viewer.ts` 加 `preserveDrawingBuffer: true`（仅采集用），记录补丁位置；验证 `toDataURL` 可用。

- [x] Task 2: 采集 3D 宏观镜头素材（不拍近景车站/跟随视角）。
  - [x] SubTask 2.1: 在 `capture/capture_3d.mjs` 中定义机位：环绕、后拉、2 号线高亮、6 号线高亮、高程夸张 1.0→1.8、城市夜景。
  - [x] SubTask 2.2: 采集 10–12 张 1920×1080 英雄静帧（quality high），用于 Ken Burns。
  - [x] SubTask 2.3: 采集 3D 运动素材：1 段 3 秒 1280×720 环绕（30fps 逐帧）+ 其余机位用 1080p 静帧做数码变焦，保证每个 3D 镜头都有运动。
  - [x] SubTask 2.4: 生成 contact sheet 逐段检查；出现黑帧、近景低模、UI 残影的镜头直接重采或淘汰。

- [x] Task 3: 采集真实 UI 素材。
  - [x] SubTask 3.1: 延迟地形请求，截取加载页 20%/55%/85% 三个真实进度状态。
  - [x] SubTask 3.2: 2× DPR 截取线路面板、李子坝车站卡片、列车运行面板、图层/高程控件。
  - [x] SubTask 3.3: 隐藏 canvas/页面背景，裁出透明面板；确认无鼠标、toast、性能调试层。

- [x] Task 4: 制作 2D 动态图形与标题系统。
  - [x] SubTask 4.1: 从 `network.json`/`features.json` 生成 `data/` 快照和 `stats.json`（15/270/562km/32,736/614）。
  - [x] SubTask 4.2: 定设计系统：`#04070b` 底、`#5FD3C4` 强调、`#F6A800` 辅助、线路官方色；Smiley Sans 标题 + Noto Sans CJK 正文 + 等宽数字。
  - [x] SubTask 4.3: 实现 2D 动态图形（2D 线网、标题、数字、终端、架构），由 `edit/render.py` 逐帧合成；画面由 `data/` 与 `audio/lines.json` 驱动。
  - [x] SubTask 4.4: 2D 资产以 2× 尺寸绘制（3840×2160）后下采样到 1080p，检查线条、文字、标签无锯齿/溢出。

- [x] Task 5: 生成中文旁白与字幕。
  - [x] SubTask 5.1: 把已确认的 11 句文案写入 `audio/narration.txt` 与 `audio/tts.py`；检查多音字（“二维”“折返”“高程”）。
  - [x] SubTask 5.2: `audio/tts.py` 用 Kokoro 男声 `zm_yunjian` 逐句生成；女声 `zf_xiaoxiao` 保留为参数备选。
  - [x] SubTask 5.3: 实测每句时长，生成 `audio/lines.json` 与 `out/guidao_promo.srt`；误差 ≤ 100ms。

- [x] Task 6: 音乐与音效设计、混音。
  - [x] SubTask 6.1: 下载 Mixkit `A New Life` 并分析段落/响度，确定 80 秒剪辑点；`We'll Be Okay` / `Possible Dreams` 按需再下。
  - [x] SubTask 6.2: 准备列车轰鸣、轮轨、whoosh、boom、UI tick、高程 riser 等音效（Mixkit 或程序化合成）。
  - [x] SubTask 6.3: 混音：BGM 在旁白下压 14–16dB，音量曲线/轻 ducking；输出 48kHz `audio/mix.wav`。
  - [x] SubTask 6.4: 整片 `loudnorm=I=-14:TP=-1.5:LRA=11`，用 `ebur128` 复核。

- [x] Task 7: 合成、调色、字幕与输出。
  - [x] SubTask 7.1: 写 `edit/timeline.json`：17 个镜头、背景类型、入出点、叠加层、字幕、S01 内部的 2D→3D 转场。
  - [x] SubTask 7.2: `edit/build.py` 用 ffmpeg 完成裁切/缩放/调色/bloom/暗角/颗粒/字幕/混音。
  - [x] SubTask 7.3: 输出 `out/guidao_promo_1080p.mp4`、`poster.jpg`、`contact_sheet.jpg`。

- [x] Task 8: 验收、修复与交付。
  - [x] SubTask 8.1: `edit/validate.py` 检查 ffprobe 规格、ebur128 响度、字幕安全区、黑帧。
  - [x] SubTask 8.2: 在 0:02 / 0:10 / 0:16 / 0:25 / 0:31 / 0:39 / 0:43 / 0:51 / 0:57 / 1:10 / 1:15 抽帧人工检查。
  - [x] SubTask 8.3: 修复发现的问题（重采、重配、重剪），重新渲染并复验。
  - [x] SubTask 8.4: 交付 MP4、SRT、封面、contact sheet；确认片尾署名与“模拟班次”说明完整。

# Task Dependencies

- **Task 0 是硬门槛**：未确认文案与画面规划，不执行 Task 1–8。
- Task 2、Task 3、Task 4、Task 5、Task 6 都依赖 Task 1；其中 Task 2/3/4 可并行，Task 5/6 可并行。
- Task 7 依赖 Task 2–6 的全部产物。
- Task 8 依赖 Task 7。
- 若 Task 2 发现某个 3D 镜头不可用，先回到 Task 2 重采，不进入 Task 7。
