# Tasks

- [ ] Task 1: 实现版本化 JSON 工程加载与预检，为 CLI 和渲染建立单一、可靠的时间线模型。
  - [ ] SubTask 1.1: 定义素材、输出、镜头、转场和音频配置模型，解析相对路径并计算总时长。
  - [ ] SubTask 1.2: 使用 ffprobe 检查工具、文件、流类型和镜头边界，返回字段级错误。
  - [ ] SubTask 1.3: 为合法工程、缺失素材、越界区间和非法转场添加单元测试。

- [ ] Task 2: 实现 FFmpeg 无界面渲染器，把通过预检的工程转换为同步的 MP4。
  - [ ] SubTask 2.1: 完成输入裁切、顺序重排、画幅/帧率/时间基统一及硬切连接。
  - [ ] SubTask 2.2: 完成受支持的 `xfade` 转场和对应原声交叉淡化，保证时长计算一致。
  - [ ] SubTask 2.3: 实现 `original`、`external`、`mute` 音频模式及无原声补静音。
  - [ ] SubTask 2.4: 输出 H.264 / AAC、48kHz 双声道 MP4，处理 `--force`、临时文件和失败清理。

- [ ] Task 3: 实现独立 CLI 与无界面预览，形成 AI 可直接调用的完整工作流。
  - [ ] SubTask 3.1: 提供 `validate`、`render`、`preview` 命令及稳定退出码、标准错误输出。
  - [ ] SubTask 3.2: 为校验和渲染提供 `--json` 摘要，包含状态、输出路径、时长和错误。
  - [ ] SubTask 3.3: 使用同一时间线渲染指定时间点 PNG，并拒绝越界时间。

- [ ] Task 4: 添加可运行示例和离线端到端测试，验证真实用户流程而非只检查函数。
  - [ ] SubTask 4.1: 新增引用 `media/railgun_omr_v4_preview.mp4` 的 `examples/headless_demo.json`。
  - [ ] SubTask 4.2: 用 FFmpeg 临时合成小视频和音频，覆盖裁切重排、转场、三种音频、预览及覆盖保护。
  - [ ] SubTask 4.3: 运行示例，使用 ffprobe 和完整解码核对输出，并抽取代表帧检查画面。

- [ ] Task 5: 执行规格清单和回归检查，确认交付范围及旧工程未受影响。
  - [ ] SubTask 5.1: 逐项验证 `checklist.md`，修复失败项后重新验证。
  - [ ] SubTask 5.2: 检查 Git 差异，确认没有修改既有 v1/v4 时间线、删除用户文件或意外提交构建产物。

# Task Dependencies

- Task 1 是 Task 2 和 Task 3 的共同前置；Task 3 的命令骨架可在 Task 1 后与 Task 2 并行，接入真实渲染需等待 Task 2。
- Task 4 依赖 Task 2 和 Task 3 完成。
- Task 5 依赖 Task 4，所有失败项必须先新增修复任务再复验。
