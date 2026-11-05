# Motion Video — RAILGUN // OVERDRIVE

用代码做 MV 的实验档案：从纯程序化渲染，到 85 秒成片，再到 AI 插画 + 网页特效 + 程序化电磁炮的混剪版本。

## 成片

| 版本 | 时长 | 画面 | 下载 |
| --- | --- | --- | --- |
| v4（最终版） | 85 秒 | 39 个镜头：22 张 AI 插画 + 11 段网页特效（10 个页面）+ 6 发炮击 | [GitHub Release](https://github.com/xcsweb/motion-video/releases/tag/railgun-v1) |
| v3 | 85 秒 | 22 个镜头，12 发炮击，4 种转场 | [GitHub Release](https://github.com/xcsweb/motion-video/releases/tag/railgun-v1) |
| v4 540p 预览 | 85 秒 | 960×540 | [media/railgun_omr_v4_preview.mp4](media/railgun_omr_v4_preview.mp4) |

飞书归档：[MV 主文档](https://my.feishu.cn/docx/XUoLdqWzDoKvdOxCAkXcCg0rnHf)

## 目录

```
├── scripts/                    # v1 纯程序化版本的完整源码（可运行）
│   ├── audio.py                # 24 秒 120 BPM 原创电子配乐 + events.json
│   └── render.py               # 逐帧渲染电磁炮画面（Pillow / numpy / scipy）
├── docs/
│   ├── video_production_handbook.md   # 方法库、剪辑经验、流程优化
│   ├── railgun_overdrive.md           # 版本记录与 v4 制作说明
│   └── douyin_copy.md                 # 抖音发布文案（最终版）
├── media/
│   └── railgun_omr_v4_preview.mp4     # 540p 预览
├── events.json                 # audio.py 生成的事件表（镜头/发射/段落）
└── README.md
```

v3 / v4 的完整成片体积较大（129–207 MB），放在 GitHub Release，不进入 Git 历史。

## 快速开始（v1，24 秒版本）

依赖：Python 3、ffmpeg，以及三套字体（Lato Black、Fira Code Bold、Noto Sans CJK Black，路径写在脚本顶部）。

```bash
pip install -r scripts/requirements.txt

# 1. 生成配乐与事件表
python scripts/audio.py          # 输出 music.wav + events.json

# 2. 逐帧渲染（约 720 帧）
python scripts/render.py --mode all --workers 4

# 3. 合成
ffmpeg -y -framerate 30 -i frames/f_%04d.jpg -i music.wav \
  -c:v libx264 -preset slow -crf 22 -pix_fmt yuv420p \
  -c:a aac -b:a 192k -movflags +faststart out.mp4
```

`render.py` 也支持快速样帧：`python scripts/render.py --mode sample --times 6.0`。

## 三条技术路线

| 路线 | 实现 | 用在哪 |
| --- | --- | --- |
| 纯程序化 | Pillow + numpy + scipy 逐帧计算 | v1 全片、v4 的 6 发炮击 |
| AI 插画 + 运镜 | 文生图 + Ken Burns + 统一调色 | v4 的 22 个插画镜头 |
| HTML + 确定性截帧 | 每个页面实现 `window.__seek(t)`，Playwright 逐帧截图 | v4 的 10 个网页特效页 |

方法对比、剪辑规则、流程优化与可复用代码见 [docs/video_production_handbook.md](docs/video_production_handbook.md)。

## 版权说明

- 本项目仅作技术演示，音乐版权归 fripSide / NBC 环球日本所有，请勿用于商业发布。
- v4 未使用原作动画截图；插画为 AI 生成，网页界面为按剧情重绘。
- 公开发布请替换为已授权音乐，并遵守各平台关于 AI 生成内容的标注要求。
