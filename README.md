# vidtool

基于 ffmpeg/ffprobe 的视频处理命令行工具，支持交互式菜单和直接命令两种模式。

## 依赖

- Python 3.10+
- ffmpeg + ffprobe（需在系统 PATH 中）

## 用法

```bash
# 交互式菜单
python vidtools.py

# 命令行模式
python vidtools.py <命令> [参数]

# 查看所有命令
python vidtools.py --help
```

## 命令列表

### 基础操作
| 命令 | 功能 |
|------|------|
| info | 查看视频信息 |
| trim | 裁剪片段 |
| convert | 格式转换（mp4/webm/mkv/avi/mov/gif） |
| resize | 调整分辨率 |
| rotate | 旋转画面（90/180/270） |
| speed | 调整播放速度 |
| compress | 压缩视频（CRF 或按目标大小） |
| screenshot | 截图 |
| gif | 生成 GIF（调色板优化） |
| thumbnail | 均匀缩略图集 |
| thumbnail-grid | 九宫格缩略图 |

### 水印 / 叠加
| 命令 | 功能 |
|------|------|
| watermark-text | 文字水印 |
| watermark-image | 图片水印 |
| watermark-tile | 平铺文字水印 |
| overlay-video | 画中画叠加 |

### 音频
| 命令 | 功能 |
|------|------|
| extract-audio | 提取音频（mp3/aac/flac/wav/opus） |
| mute | 去除音频 |
| replace-audio | 替换音频 |
| volume | 音量调节（dB） |

### 字幕
| 命令 | 功能 |
|------|------|
| subtitle-extract | 提取字幕流 |
| subtitle-burn | 烧录硬字幕 |
| subtitle-add | 添加软字幕 |

### 其他
| 命令 | 功能 |
|------|------|
| crop | 裁切画面 |
| fps | 改变帧率 |
| filter | 自定义 ffmpeg 滤镜 |
| concat | 视频拼接 |

## GPU 加速

convert / resize / compress 命令支持 `--gpu` 参数启用硬件编码：

```bash
python vidtools.py convert input.mp4 -f mp4 --gpu
python vidtools.py resize input.mp4 --size 1080p --gpu
python vidtools.py compress input.mp4 --crf 24 --gpu
```

不加 `--gpu` 时默认使用软件编码（libx264），兼容性最好。

## 示例

```bash
# 查看视频信息
python vidtools.py info input.mp4

# 裁剪片段
python vidtools.py trim input.mp4 -s 00:01:00 -e 00:02:30

# 格式转换
python vidtools.py convert input.mp4 -f webm

# 调整分辨率
python vidtools.py resize input.mp4 --size 720p

# 压缩
python vidtools.py compress input.mp4 --target-mb 50
python vidtools.py compress input.mp4 --crf 26

# 截图
python vidtools.py screenshot input.mp4 --time 00:01:23

# GIF
python vidtools.py gif input.mp4 -s 00:00:10 --duration 5

# 文字水印
python vidtools.py watermark-text input.mp4 --text "(C) 2025"

# 提取音频
python vidtools.py extract-audio input.mp4 --format mp3

# 视频拼接
python vidtools.py concat 1.mp4 2.mp4 3.mp4 -o merged.mp4
```

## 配置文件

代码开头的常量区（约第 110-130 行）可直接修改默认值，包括编码参数、水印位置、字体路径等。
