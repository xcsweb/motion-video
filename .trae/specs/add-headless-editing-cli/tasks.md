# Tasks

- [ ] Task 1: 建立 Node.js + TypeScript CLI、工程格式和 AI 自发现基础，统一后续模块的数据语义。
  - [ ] SubTask 1.1: 建立 Node.js 22+、TypeScript、CLI 入口和 Node 内置测试结构，不改变旧 Python 工程。
  - [ ] SubTask 1.2: 实现 `project init/show/validate`、版本化 `project.json`、相对路径和稳定错误模型。
  - [ ] SubTask 1.3: 定义多轨、镜头、文本、参数、输出、任务和修订的单一 Schema 来源。
  - [ ] SubTask 1.4: 实现 `schema`、`capabilities`、所有非交互命令 `--json`、退出码及 stdout/stderr 隔离。
  - [ ] SubTask 1.5: 为工程解析、Schema、CLI 输出和错误码添加基础测试。

- [ ] Task 2: 实现 Execa 异步子进程与持久化 job 运行时，先解决长任务、并发和异常生命周期。
  - [ ] SubTask 2.1: 实现有界并发、前台等待、`--detach`、`jobs list/show/wait/cancel/retry` 和持久化状态。
  - [ ] SubTask 2.2: 流式消费 stdout/stderr，解析 FFmpeg progress，保存有界内存尾部和完整诊断日志。
  - [ ] SubTask 2.3: 实现超时、SIGINT/SIGTERM 取消、终止宽限期、延迟强杀和临时文件清理。
  - [ ] SubTask 2.4: 实现 job 心跳、worker 崩溃后的 interrupted 判定、工程快照、项目写锁和输出路径锁。
  - [ ] SubTask 2.5: 使用可控假进程及 FFmpeg 测试并行、日志洪峰、取消、超时、崩溃和锁冲突。

- [ ] Task 3: 实现素材库和面向 AI 的内容定位，不让 AI 依赖文件名猜素材。
  - [ ] SubTask 3.1: 实现素材登记、列表、移除、文件状态检查和 ffprobe 元数据。
  - [ ] SubTask 3.2: 实现素材缩略图、带时间码联系表和缓存失效处理。
  - [ ] SubTask 3.3: 实现场景变化候选点与静音区间分析，统一接入 job 和 JSON 结果。
  - [ ] SubTask 3.4: 用合成素材验证元数据、场景/静音分析、并行分析和失效素材错误。

- [ ] Task 4: 实现多轨时间线与事务式结构化编辑，覆盖 AI 的日常剪辑操作。
  - [ ] SubTask 4.1: 实现多视频轨、多音频轨及视频/图片/颜色/文本镜头模型与时间线计算。
  - [ ] SubTask 4.2: 实现增删轨道、添加/裁切/移动/拆分/删除镜头和参数设置操作。
  - [ ] SubTask 4.3: 实现文本添加、SRT 导入、速度/变换/透明度/音量/淡化及转场校验。
  - [ ] SubTask 4.4: 实现 `edit apply --dry-run`、操作差异和全有或全无的写入回滚。
  - [ ] SubTask 4.5: 测试多轨计算、每种编辑操作、非法操作索引、并发写锁和事务回滚。

- [ ] Task 5: 实现工程修订历史、差异、撤销和重做，让 AI 可安全尝试不同剪法。
  - [ ] SubTask 5.1: 为所有成功写操作保存不可变修订、摘要和工程快照。
  - [ ] SubTask 5.2: 实现历史列表、任意修订差异、撤销、重做及重做分支截断。
  - [ ] SubTask 5.3: 验证只读/分析/渲染不产生修订，后台渲染固定修订且历史操作不修改原素材。

- [ ] Task 6: 实现完整 FFmpeg 多轨渲染器，确保工程语义真正转化为成片。
  - [ ] SubTask 6.1: 完成裁切重排、速度变化、画幅统一、同轨硬切和 `xfade` 转场。
  - [ ] SubTask 6.2: 完成跨轨视频合成、图片/颜色/文本镜头、裁切/缩放/位置/透明度。
  - [ ] SubTask 6.3: 完成多音频轨混合、原声补静音、变速音频、音量及淡入淡出。
  - [ ] SubTask 6.4: 输出 H.264 / AAC MP4，处理字幕字体、48kHz 双声道、时长同步和 FFmpeg 阶段错误。
  - [ ] SubTask 6.5: 实现 `render --dry-run` 执行计划、参数数组/滤镜图保存、原子输出和覆盖保护。

- [ ] Task 7: 实现与正式渲染同语义的 frame、sheet、proxy 三类预览。
  - [ ] SubTask 7.1: 实现任意合法时间点单帧 PNG 和越界错误。
  - [ ] SubTask 7.2: 实现带时间码时间线联系表及可配置采样区间/密度。
  - [ ] SubTask 7.3: 实现保留完整音频的低分辨率代理 MP4。
  - [ ] SubTask 7.4: 对同一工程比较预览与正式渲染代表帧，验证字幕和跨轨合成一致。

- [ ] Task 8: 实现排错命令和 Vue TUI 终端诊断仪表盘，使失败可定位而不是只返回“渲染失败”。
  - [ ] SubTask 8.1: 实现 `doctor`、`logs`、`diagnose`、`--verbose`、`--debug` 和脱敏诊断目录。
  - [ ] SubTask 8.2: 使用 Vue TUI 稳定 CLI runtime 和基础组件实现 jobs、进度、诊断文件位置、预览文件位置及修订差异视图，并处理 TTY、resize 和终端清理。
  - [ ] SubTask 8.3: 将实验性 `TLogView`/append-only log store 隔离在有界日志适配器中，保留普通 `logs --follow` 后备路径；取消/重试统一调用核心任务服务。
  - [ ] SubTask 8.4: 用 headless terminal 测试验证 TUI/CLI 状态一致、键盘操作和日志洪峰；验证非 TTY 明确报错、CI 无 TUI 全功能可用、退出观察界面不取消 detached job。

- [ ] Task 9: 提供从空工程到成品的完整示例和离线端到端测试。
  - [ ] SubTask 9.1: 新增使用 `media/railgun_omr_v4_preview.mp4` 的示例工程及可重放 CLI 操作序列。
  - [ ] SubTask 9.2: 串联素材登记/分析、结构化编辑、多轨字幕与音频、历史、异步任务、三类预览和渲染。
  - [ ] SubTask 9.3: 用 ffprobe、完整解码、代表帧、音频、job 记录和工程差异验证结果，不只检查退出码。
  - [ ] SubTask 9.4: 注入取消、超时、崩溃、日志洪峰和锁冲突，验证诊断、覆盖保护、撤销/重做及无网络运行。

- [ ] Task 10: 按清单系统验收并检查旧工程回归。
  - [ ] SubTask 10.1: 逐项验证 `checklist.md`；失败项新增修复任务并由子代理修复后复验。
  - [ ] SubTask 10.2: 检查 Git 差异，确认既有 `scripts/`、`v4/` 和用户文件未被改写、删除或回滚。

# Task Dependencies

- Task 1 是所有任务的前置；Task 2 依赖 Task 1。
- Task 3 依赖 Task 2；Task 4、Task 5 可在 Task 1 后并行，并通过同一项目写锁与修订接口集成。
- Task 6 依赖 Task 2、Task 3、Task 4；Task 7 依赖 Task 6。
- Task 8 的 doctor/logs/diagnose 可在 Task 2 后开始，完整 TUI 集成依赖 Task 3、Task 5、Task 6、Task 7。
- Task 9 依赖 Task 2 至 Task 8 的集成功能；各模块必须先完成自己的局部测试。
- Task 10 依赖 Task 9，任何失败检查项都必须先修复再复验。
