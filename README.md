# motion-video

AI 音乐视频实验仓库：用「AI 插画 + 程序化合成 + 排版页面」做可复现的 MV。

## 项目

### 一笑江湖 · 天上白玉京（2026）

91 秒国风伤感 MV。视觉母题：天庭不是仙境，是一座华美的囚笼。仙人从云海坠向人间灯火，落到题眼“他日若得脱身法，生吃黄连苦也甜”。

- 工程与复现：[jianghu/README.md](jianghu/README.md)
- 制作复盘：[docs/production_notes.md](jianghu/docs/production_notes.md)
- 成片与文案：[飞书文档](https://my.feishu.cn/docx/Qi2QduAyooNQQJxWXWbcKnBBnuf)

### 我不甘心 · 为什么不是我（2026）

15 秒程序员焦虑短片。AI 8.2 秒写完他三天的代码，凌晨三点只剩一句“那我呢？”。人物一致性用黑卫衣剪影贯穿：开场只露一次脸，之后全部是过肩、背影和手部特写。

- 工程与文案：[ainight/](ainight/)、[交付说明](ainight/docs/delivery.md)
- 成片与文案：[飞书文档](https://my.feishu.cn/docx/CB8Od61CWofYkix8c0fcadt1nLf)

### 电磁炮 / railgun（2024）

早期程序化电磁炮 MV 实验，保留在 `railgun/`。

## 通用流水线

1. 定一首歌和情绪最完整的 60–90 秒。
2. 写一句视觉概念（必须能一句话说完）。
3. 按歌词切镜头，标素材 / 运镜 / 色调 / 天气 / 转场。
4. 生成统一画风的 16:9 素材。
5. 先渲关键帧抽检，再全量渲染。
6. ffmpeg 编码，抽检成片，归档时间轴与复盘。
