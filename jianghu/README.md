# 一笑江湖 · 天上白玉京

91 秒国风伤感 MV。以“天上白玉京”为视觉母题：天庭越美、越冷，越显得长生是囚笼。结尾仙人从云海坠向人间灯火，落到题眼“他日若得脱身法，生吃黄连苦也甜”。

## 成片规格

- 1920×1080 / 30fps / 2730 帧 / 91.0 秒
- H.264 CRF22 + AAC 192k + faststart
- 音源：闻人听書_《一笑江湖》原版，截取 0:00–1:31

## 结构

```
jianghu/
├── assets/ai/            14 张 AI 古风插画（2560×1440）
├── assets/audio/         截取的 91 秒 WAV
├── assets/MaShanZheng-Regular.ttf  毛笔书法字体
├── config/timeline.json  21 个镜头、运镜、色调、天气
├── config/lyrics.json    20 句歌词时间轴
├── build/render.py       Pillow + numpy 逐帧合成器
├── build/encode.sh       ffmpeg 编码与 540p 预览
├── frames/               渲染帧（gitignore）
├── previews/             抽检帧（gitignore）
└── out/                  成片（gitignore）
```

## 视觉方法

- **色彩矩阵**：cold（青灰）/ memory（暖金过曝）/ red（战场残阳）/ warm（人间灯火）/ dawn（晨光）。整片按 tint 统一调色，而不是逐图凭感觉。
- **天气层**：程序化飘雪、雾、雨；用确定性随机数，保证每次渲染一致。
- **镜头**：Ken Burns 慢推 + 轻微 gate weave；转场用 dissolve / flash / fade-from-black。
- **歌词**：竖排毛笔字，右侧列；按演唱进度逐字“由淡到浓”，当前字暖金；底部保留一行小字幕保证可读性。
- **题字**：片头竖排“天上白玉京”＋朱砂印；片尾两列“他日若得脱身法 / 生吃黄连苦也甜”。

## 复现

```bash
cd jianghu
python3 build/render.py          # 全量 2730 帧
python3 build/render.py --step 15  # 快速预览
bash build/encode.sh             # 成片 + 540p
```

## 素材与版权

- 音乐：《一笑江湖》闻人听書_，仅作二创剪辑使用，版权归原作者/发行方。
- 插画：本项目 AI 生成，已裁掉生成水印。
- 字体：Ma Shan Zheng（Google Fonts，OFL）。
