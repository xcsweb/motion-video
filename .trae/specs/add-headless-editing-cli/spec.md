# 无界面 AI 剪辑 CLI Spec

## Why

当前项目已经能用代码生成固定 MV，也验证了普通视频素材可以通过 FFmpeg 剪辑，但渲染逻辑仍与单个示例绑死，无法让 AI 或用户直接裁切、重排任意本地素材。对本项目而言，GUI 不是最高优先级；可版本管理、可自动校验、可批量执行的 JSON 工程和 CLI 更适合 AI 操作。

技术选择采用**混合方案**：复用成熟的 FFmpeg / ffprobe 媒体内核，自建薄而清晰的工程格式与 CLI 编排层。不是全部自己重造，也不是为了剪辑功能引入一套庞大的第三方应用。MotionGit 继续适合 `.motion` 动画模板，人工精修则可继续使用成熟 GUI 剪辑软件；本工具专注代码驱动、可复现的普通 footage 剪辑。

## What Changes

- 新增独立的无界面 CLI，通过 `python3 -m codecut` 提供 `validate`、`render`、`preview` 三个命令。
- 新增 JSON 工程格式，声明素材、输出参数、有序镜头、转场和音频，不再把素材路径与时间线写死在 Python 示例中。
- 支持 FFmpeg 可解码的本地视频输入，完成裁切、重排、同源素材复用、画幅统一、硬切和常用叠化转场。
- 支持保留镜头原声、使用一条外部音频或静音；输出统一的 H.264 / AAC MP4。
- 支持无界面抽帧预览、机器可读的结果摘要、明确的退出码，以及非交互式错误处理。
- 提供可直接使用仓库现有素材运行的示例，以及无需联网的合成素材自动化测试。
- 保留现有 v1、v4 和 20 秒示例脚本的行为，不改变其时间线或渲染入口。

本期明确不做：GUI、多轨画面合成、素材库、拖拽裁切、撤销系统、插件系统、云端协作、自然语言编辑器、MotionGit 格式兼容，以及自研编解码器。需要人工精细操作时，不把 CLI 冒充成专业 GUI 的替代品。

## Impact

- Affected specs: 新增无界面普通视频剪辑、JSON 工程校验、无界面预览和 CLI 自动化能力。
- Affected code: 新增 `codecut/`（CLI、工程校验、FFmpeg 渲染）、`examples/headless_demo.json`、`tests/test_codecut.py`。
- Existing code: `scripts/`、`v4/`、现有 MV 配置及成片保持原行为；新能力不改写既有时间线。
- Runtime dependencies: Python 3 标准库、系统 FFmpeg / ffprobe；不新增 Python 媒体框架依赖。

## ADDED Requirements

### Requirement: JSON 剪辑工程

系统 SHALL 提供版本化 JSON 工程格式，包含素材表、输出宽度/高度/帧率、有序镜头列表和音频设置；镜头 SHALL 支持素材 ID、源入点、持续时长及可选转场。相对素材路径 SHALL 以工程文件所在目录解析，同一素材 SHALL 能在多个镜头中复用。

#### Scenario: 合法工程被接受

- **WHEN** 用户校验一个引用本地素材且镜头时间范围合法的工程
- **THEN** 系统解析全部路径和时间线，并返回计算后的总时长与镜头数量

#### Scenario: 非法引用被拒绝

- **WHEN** 工程引用不存在的素材 ID、文件，或包含负入点、非正时长、越界区间、非法帧率或尺寸
- **THEN** 系统指出具体字段和原因，以非零状态退出且不启动渲染

### Requirement: 工程预检

系统 SHALL 提供 `validate` 命令，在渲染前检查 JSON 结构、FFmpeg / ffprobe 可用性、素材可解码性、流类型、镜头区间和转场参数。转场时长 SHALL 大于零且不能超过相邻镜头可重叠的时长；不声明转场时 SHALL 视为硬切。

#### Scenario: 预检避免无效长任务

- **WHEN** 用户对缺少编解码工具或包含越界镜头的工程执行 `validate`
- **THEN** 系统快速返回可读错误，不产生输出文件

### Requirement: 普通视频裁切与重排

系统 SHALL 提供 `render` 命令，按 JSON 中镜头顺序裁切和重排普通视频，统一分辨率、帧率、像素格式和时间基。画幅不一致时 SHALL 等比缩放并居中裁切，避免拉伸变形。

#### Scenario: 多段素材生成一个成片

- **WHEN** 用户使用多个本地视频或同一视频的多个区间执行 `render`
- **THEN** 系统生成一个按声明顺序排列的 MP4，镜头源入点和时长符合工程配置

#### Scenario: 混合硬切与转场

- **WHEN** 相邻镜头声明受支持的 `xfade` 转场及时长
- **THEN** 系统按重叠时长连接画面，输出总时长等于镜头时长之和减去全部转场重叠时长，误差不超过一帧

### Requirement: 音频处理

系统 SHALL 支持 `original`、`external`、`mute` 三种音频模式。默认 `original` 保留镜头原声并随画面硬切或交叉淡化；某镜头没有音频时 SHALL 补静音。`external` 使用工程指定的一条音频并按成片时长裁切或补静音；`mute` 输出静音 AAC 音轨。所有模式 SHALL 统一为 48kHz 双声道，避免改变成片时长。

#### Scenario: 配乐覆盖镜头原声

- **WHEN** 用户选择 `external` 并指定有效音频素材
- **THEN** 成片只使用该外部音频，音频长度与视频时间线一致

#### Scenario: 无原声素材仍可渲染

- **WHEN** 用户在默认 `original` 模式下剪辑不含音频流的视频
- **THEN** 渲染成功，对应区间使用静音而非报错或丢失同步

### Requirement: 无界面视觉校验

系统 SHALL 提供 `preview` 命令，复用与正式渲染相同的时间线和画面处理逻辑，在指定时间点输出 PNG，供 AI 或用户检查构图、顺序和转场，而不要求 GUI 或实时播放器。

#### Scenario: 抽取指定时间画面

- **WHEN** 用户对合法工程执行 `preview` 并给出成片时间点和图片输出路径
- **THEN** 系统生成对应该时间点的 PNG，其画面规则与正式成片一致

#### Scenario: 预览时间越界

- **WHEN** 指定时间点小于零或不早于成片总时长
- **THEN** 系统返回明确错误且不产生图片

### Requirement: AI 友好的非交互 CLI

CLI SHALL 在全部参数齐全时不询问交互式确认，并以稳定退出码区分成功和失败。`validate`、`render` SHALL 支持 `--json` 输出结构化摘要；错误 SHALL 写入标准错误。`render` 默认 SHALL 拒绝覆盖已有文件，只有显式传入 `--force` 才覆盖，并 SHALL 在成功后将临时输出原子替换为目标文件，避免留下被误认为成品的残缺文件。

#### Scenario: AI 批量调用

- **WHEN** AI 依次调用 `validate --json` 和 `render --json`
- **THEN** 无需人工界面即可获取校验结果、输出路径、时长和错误信息，并根据退出码决定后续操作

#### Scenario: 渲染中途失败

- **WHEN** FFmpeg 因不可解码素材或其他错误失败
- **THEN** CLI 返回非零状态、保留已有目标文件不变，并清理本次临时输出

### Requirement: 可运行示例与离线测试

项目 SHALL 提供一个引用仓库现有 `media/railgun_omr_v4_preview.mp4` 的示例工程，并提供使用临时合成音视频运行的自动化测试。测试 SHALL 覆盖裁切重排、转场、三种音频模式、预览、非法输入和覆盖保护，不依赖网络或大型开放电影素材。

#### Scenario: 本地复现

- **WHEN** 用户在仓库根目录按示例参数执行校验和渲染
- **THEN** 不修改既有 MV 工程即可得到新的 MP4，测试也能在隔离环境重复运行

## MODIFIED Requirements

### Requirement: 现有代码驱动视频工程

现有 v1、v4 和 20 秒 footage 示例 SHALL 保持各自入口、时间线和输出行为。新增 CLI SHALL 作为独立能力复用 FFmpeg 思路，不要求既有工程迁移，也不以兼容层改变旧命令。

#### Scenario: 新增工具不影响旧工程

- **WHEN** 用户只查看或运行原有脚本
- **THEN** 原有配置文件和渲染流程无需修改，新增 CLI 文件不会隐式改变其行为

## REMOVED Requirements

无。本次不删除现有功能，也不移除已生成的示例成片或脚本。
