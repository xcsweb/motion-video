# Tasks

- [x] Task 1: 锁定脚本与分镜，等用户确认后再开始制作。
  - [x] SubTask 1.1: 确认创意方向（nana = 摇篮曲 vs 奶奶）。
  - [x] SubTask 1.2: 确认旁白音色、语气和开场形式（是否保留“仿 AI 输入框”）。
  - [x] SubTask 1.3: 确认 BGM 走原创同类型，还是用户提供原音频。
  - [x] SubTask 1.4: 把确认后的台词、时间点、花字写入 `nana/config/script.json`。

- [x] Task 2: 制作原创 BGM 与 beat map。
  - [x] SubTask 2.1: 用 Python 合成 128 BPM、35.0s 的鼓组、808、pad、pluck、riser、impact。
  - [x] SubTask 2.2: 按 18 小节结构完成两段 drop、第 9 小节静音/心跳、结尾收束。
  - [x] SubTask 2.3: 输出 48kHz 立体声 WAV，响度 -14 LUFS、峰值 ≤ -1 dBTP。
  - [x] SubTask 2.4: 导出 `beatmap.json`（BPM、小节线、drop、音效点），并验证与分镜表一致。

- [x] Task 3: 生成视觉素材并统一风格。
  - [x] SubTask 3.1: 生成 A 段育婴房、摇篮、床铃/星尘关键帧。
  - [x] SubTask 3.2: 生成 B 段中式客厅、奶奶多表情、时钟/路由器/手机/拖鞋等道具。
  - [x] SubTask 3.3: 统一 Pixar 3D 质感、色调和光线；不合格的图重生成或降级为程序化图形。
  - [x] SubTask 3.4: （可选）用 GenerateVideo 生成 2–3 个 hero 镜头；失败则用静帧 + 动效降级。

- [x] Task 4: 制作中文旁白与音效。
  - [x] SubTask 4.1: 用中文女声 TTS 生成 6 句旁白，语速偏快、句尾上扬。
  - [x] SubTask 4.2: 对齐分镜时间，BGM 做侧链避让，保证人声清晰。
  - [x] SubTask 4.3: 补键盘、开关灯、拖鞋、电视噪声、心跳、whoosh 音效。

- [x] Task 5: 卡点剪辑与渲染。
  - [x] SubTask 5.1: 用 Python 渲染 1080×1920、30fps 帧序列，包含 2.5D 视差、粒子、文字动效、glitch。
  - [x] SubTask 5.2: 按 beat map 落切点，蒙太奇按 8 分音符快切。
  - [x] SubTask 5.3: 叠字幕/花字，做白闪、黑场、分屏和 end card。
  - [x] SubTask 5.4: 用 ffmpeg 合成 H.264/AAC MP4（`+faststart`），输出成片与封面。

- [x] Task 6: QA 与交付。
  - [x] SubTask 6.1: ffprobe 校验时长、分辨率、帧率、编码。
  - [x] SubTask 6.2: 抽帧对比 beat map，确认卡点误差 ≤ 1 帧。
  - [x] SubTask 6.3: 校对全部中文，检查缺字、错字、遮挡。
  - [x] SubTask 6.4: 测量响度和真峰值，确认 -14 LUFS / ≤ -1 dBTP。
  - [x] SubTask 6.5: 生成联系表，交付 `nana/out/nana_cn_35s.mp4`、封面、脚本和 beat map。

# Task Dependencies

- Task 1 是所有任务的前置；用户未确认脚本前，Task 2–6 不开始。
- Task 2 与 Task 3 可在 Task 1 后并行。
- Task 4 依赖 Task 2（BGM 时长和段落）和 Task 1（台词）。
- Task 5 依赖 Task 2、Task 3、Task 4。
- Task 6 依赖 Task 5；任何验收项失败，先修复再复验。
