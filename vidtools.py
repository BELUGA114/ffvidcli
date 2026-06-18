#!/usr/bin/env python3
"""
vidtool — 视频处理工具箱（依赖 ffmpeg / ffprobe）

用法:
  python vidtool.py                       交互式菜单
  python vidtool.py <命令> [参数]          命令行模式
  python vidtool.py --help                查看完整命令说明

通用选项:
  --gpu             启用 GPU 硬件编码（convert / resize / compress 可用）

命令分类:

  基础操作
    info              查看视频信息
    trim              裁剪片段
    convert           格式转换
    resize            调整分辨率
    rotate            旋转画面
    speed             调整播放速度
    compress          压缩视频
    screenshot        截图
    gif               生成 GIF
    thumbnail         均匀缩略图集
    thumbnail-grid    九宫格缩略图

  水印 / 叠加
    watermark-text    文字水印（支持定位）
    watermark-image   图片水印
    watermark-tile    平铺文字水印（满屏防伪）
    overlay-video     画中画叠加

  音频
    extract-audio     提取音频
    mute              去除音频
    replace-audio     替换音频
    volume            音量调节 (dB)

  字幕
    subtitle-extract  提取字幕
    subtitle-burn     烧录硬字幕
    subtitle-add      添加软字幕

  其他
    crop              裁切画面
    fps               改变帧率
    filter            自定义 ffmpeg 滤镜
    concat            视频拼接
"""

import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


# 工具函数（增强：进度输出、更完善的出错处理）

def run(cmd: list[str], desc: str = "", verbose: bool = False,
        output: str | None = None, duration: float | None = None
        ) -> subprocess.CompletedProcess:
    """执行 ffmpeg 命令，支持覆盖确认、进度显示、ETA 估算。"""
    if desc:
        print(f"  {desc}")
    print(f"   $ {shlex.join(str(c) for c in cmd)}\n")

    # 自动检测输出文件（cmd 最后一个非 flag 参数），回退覆盖明确传入的 output
    if output is None and cmd:
        last = str(cmd[-1])
        if last != os.devnull and not last.startswith('-') and '%' not in last:
            output = last

    # 覆盖保护：检查输出文件是否已存在
    if output and Path(output).exists():
        ans = input(f"  文件已存在: {output}\n  覆盖？(y/N): ").strip().lower()
        if ans != 'y':
            sys.exit("已取消")

    if verbose:
        proc = subprocess.Popen(cmd, stderr=subprocess.PIPE, text=True, bufsize=1,
                                encoding="utf-8", errors="replace")
        assert proc.stderr is not None
        import re as _re
        _time_re = _re.compile(r"time=(\d+):(\d+):(\d+\.?\d*)")
        for line in proc.stderr:
            line = line.rstrip()
            if "frame=" in line or "time=" in line:
                if duration:
                    m = _time_re.search(line)
                    if m:
                        elapsed = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
                        pct = min(99.9, elapsed / duration * 100) if duration > 0 else 0
                        remain = max(0, duration - elapsed)
                        print(f"   {line}  [{pct:5.1f}%  ETA {remain:.0f}s]", end="\r")
                    else:
                        print(f"   {line}", end="\r")
                else:
                    print(f"   {line}", end="\r")
            else:
                print(f"   {line}")
        proc.wait()
        if proc.returncode != 0:
            sys.exit(f"[错误] ffmpeg 退出码 {proc.returncode}")
        return subprocess.CompletedProcess(cmd, proc.returncode, "", "")
    else:
        result = subprocess.run(cmd, capture_output=True, text=True,
                                encoding="utf-8", errors="replace")
        if result.returncode != 0:
            print(f"[错误] ffmpeg 退出码 {result.returncode}")
            print(result.stderr[-2000:])
            sys.exit(1)
        return result


def check_ffmpeg():
    for tool in ("ffmpeg", "ffprobe"):
        if shutil.which(tool) is None:
            sys.exit(f"[错误] 未找到 {tool}，请先安装 ffmpeg。")


def preview_file(path: str) -> None:
    """快速预览视频关键信息（分辨率、时长、编码、大小）。"""
    result = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json",
         "-show_format", "-show_streams", path],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if result.returncode != 0:
        return
    data = json.loads(result.stdout)
    fmt = data.get("format", {})
    streams = data.get("streams", [])

    size_mb = int(fmt.get("size", 0)) / 1_048_576
    dur_s = float(fmt.get("duration", 0))
    dur_str = f"{int(dur_s // 3600)}:{int(dur_s % 3600 // 60):02d}:{int(dur_s % 60):02d}"
    vinfo, ainfo = "", ""
    for s in streams:
        if s.get("codec_type") == "video":
            vinfo = f"{s.get('width','?')}x{s.get('height','?')}  {s.get('codec_name','?')}"
        elif s.get("codec_type") == "audio":
            ainfo = f"{s.get('codec_name','?')}  {s.get('channels','?')}ch"
    print(f"  ── {Path(path).name} ──")
    if vinfo:
        print(f"  视频: {vinfo}")
    if ainfo:
        print(f"  音频: {ainfo}")
    print(f"  时长: {dur_str} ({dur_s:.0f}s)   大小: {size_mb:.1f} MB")
    print()


def clean_path(raw: str) -> str:
    """清洗终端拖拽产生的 PowerShell & 'path' 等杂质"""
    s = raw.strip()
    if s.startswith("& ") or s.startswith("&"):
        s = s.removeprefix("&").strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in ('"', "'"):
        s = s[1:-1]
    return s


def assert_input(path: str):
    if not Path(path).is_file():
        sys.exit(f"[错误] 输入文件不存在: {path}")


def default_output(input_path: str, suffix: str, ext: str | None = None) -> str:
    p = Path(input_path)
    ext = ext or p.suffix
    return str(p.parent / f"{p.stem}{suffix}{ext}")


def hms_to_sec(t: str) -> float:
    """HH:MM:SS.ms 或纯秒数 → float 秒"""
    t = t.strip()
    if not t:
        return 0.0
    if ":" in t:
        parts = t.split(":")
        try:
            return sum(float(v) * 60 ** i for i, v in enumerate(reversed(parts)))
        except ValueError:
            sys.exit(f"[错误] 无法解析时间: {t}")
    try:
        return float(t)
    except ValueError:
        sys.exit(f"[错误] 无法解析时间: {t}")


# 可调默认值 — 改此处一处，全局生效
THUMB_CELL_WIDTH = 1440         # 九宫格每格宽度 px
THUMB_DEFAULT_COUNT = 6         # 均匀缩略图张数
THUMB_DEFAULT_COLS = 3          # 九宫格默认列数
THUMB_DEFAULT_ROWS = 3          # 九宫格默认行数
GIF_DEFAULT_FPS = 10            # GIF 默认帧率
GIF_DEFAULT_WIDTH = 480         # GIF 默认宽度 px
WM_DEFAULT_POSITION = "bottomright"  # 水印 / 画中画默认位置
WM_DEFAULT_COLOR = "white@0.7"  # 文字水印默认颜色
WM_DEFAULT_FONT_SIZE = 36       # 文字水印默认字号
WM_IMAGE_DEFAULT_SCALE = 100    # 图片水印默认宽度 px
PIP_DEFAULT_SCALE = 160         # 画中画默认宽度 px
AUDIO_BITRATE = "128k"          # 通用音频比特率（转换 / 压缩）
EXT_AUDIO_BITRATE = "192k"      # 提取音频比特率
ENCODE_CRF = "23"               # 编码默认 CRF（转换 / 缩放）
COMPRESS_CRF = 28               # 压缩默认 CRF
ENCODE_PRESET = "fast"          # 默认编码 preset
def _detect_default_font() -> str:
    """跨平台检测可用字体，供 drawtext 滤镜使用。"""
    candidates = [
        # Windows
        "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/msyh.ttc",
        # macOS
        "/System/Library/Fonts/Helvetica.ttc",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/Library/Fonts/Arial.ttf",
        # Linux
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/TTF/DejaVuSans.ttf",
    ]
    for path in candidates:
        if os.path.isfile(path):
            return path
    # 最后回退：假设系统有 Arial
    return "Arial"


FONT_FILE = _detect_default_font()  # drawtext 字体文件（ffmpeg Windows 需显式指定路径）
TILE_DEFAULT_COLOR = "white@0.15"   # 平铺水印默认颜色
TILE_DEFAULT_FONT_SIZE = 24         # 平铺水印默认字号
TILE_DEFAULT_CELL_W = 200           # 平铺水印单元格宽度 px
TILE_DEFAULT_CELL_H = 60            # 平铺水印单元格高度 px

# GPU 硬件编码支持

GPU_BACKENDS: dict = {}  # 缓存检测结果

def _detect_gpu_backends() -> dict:
    """扫描 ffmpeg -encoders，返回可用 GPU 后端列表。"""
    result = subprocess.run(
        ["ffmpeg", "-hide_banner", "-encoders"],
        capture_output=True, text=True, encoding="utf-8"
    )
    enc = result.stdout
    backends: dict = {}
    if "h264_nvenc" in enc:
        backends["nvidia"] = ("h264_nvenc", "hevc_nvenc")
    if "h264_amf" in enc:
        backends["amd"] = ("h264_amf", "hevc_amf")
    if "h264_qsv" in enc:
        backends["intel"] = ("h264_qsv", "hevc_qsv")
    if "h264_videotoolbox" in enc:
        backends["apple"] = ("h264_videotoolbox", "hevc_videotoolbox")
    return backends


def get_gpu_backend(backend_hint: str | None = None) -> str | None:
    """返回可用 backend 名称 (nvidia/amd/intel/apple)，按 hint 或自动检测。"""
    global GPU_BACKENDS
    if not GPU_BACKENDS:
        GPU_BACKENDS = _detect_gpu_backends()
    if not GPU_BACKENDS:
        return None
    if backend_hint:
        return backend_hint if backend_hint in GPU_BACKENDS else None
    return next(iter(GPU_BACKENDS))


def gpu_encoder_args(backend: str, *, hevc: bool = False,
                     crf: int = 23, preset: str = "fast") -> list[str]:
    """返回替换软件编码器的 ffmpeg 参数列表。

    注意各后端的参数差异:
      - NVENC: -cq (非 -crf), preset p1-p7
      - AMD:   -quality, -rc
      - Intel: -global_quality
      - Apple:  -q:v (1-100)
    """
    codec_map = {
        "nvidia": ("h264_nvenc", "hevc_nvenc"),
        "amd":    ("h264_amf", "hevc_amf"),
        "intel":  ("h264_qsv", "hevc_qsv"),
        "apple":  ("h264_videotoolbox", "hevc_videotoolbox"),
    }
    h264_codec, hevc_codec = codec_map.get(backend, ("libx264", "libx265"))
    codec = hevc_codec if hevc else h264_codec
    args: list[str] = ["-c:v", codec]

    nvenc_presets = {
        "ultrafast": "p1", "superfast": "p2", "veryfast": "p3",
        "faster": "p4", "fast": "p4", "medium": "p5",
        "slow": "p6", "slower": "p7", "veryslow": "p7",
    }

    if backend == "nvidia":
        args += ["-cq", str(crf)]
        args += ["-preset", nvenc_presets.get(preset, "p4")]
        args += ["-rc", "vbr", "-b:v", "0"]
    elif backend == "amd":
        args += ["-quality", preset, "-rc", "cbr"]
    elif backend == "intel":
        args += ["-global_quality", str(crf)]
    elif backend == "apple":
        args += ["-quality", preset]
        args += ["-q:v", str(max(1, min(100, int(100 - crf * 2))))]
    else:
        args = ["-c:v", "libx264", "-crf", str(crf), "-preset", preset]

    return args


def _video_encoder_args(args, *, crf_override: int | None = None,
                        preset_override: str | None = None) -> list[str] | None:
    """根据 --gpu 标志返回 GPU 编码参数，无 GPU 返回 None。

    crf_override/preset_override 可覆盖命令默认值（例如 compress 用不同预设）。
    """
    if not args.gpu:
        return None
    hint = args.gpu if isinstance(args.gpu, str) else None
    backend = get_gpu_backend(hint)
    if not backend:
        print("[警告] 未检测到 GPU 编码器，使用软件编码")
        return None
    crf_val = crf_override if crf_override is not None else int(getattr(args, 'crf', None) or ENCODE_CRF)
    preset = preset_override if preset_override is not None else ENCODE_PRESET
    return gpu_encoder_args(backend, crf=crf_val, preset=preset)


# 1. 视频信息

def cmd_info(args):
    assert_input(args.input)
    result = subprocess.run(
        [
            "ffprobe", "-v", "quiet",
            "-print_format", "json",
            "-show_format", "-show_streams",
            args.input,
        ],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        sys.exit("[错误] ffprobe 读取失败:\n" + result.stderr)

    data = json.loads(result.stdout)
    fmt  = data.get("format", {})
    streams = data.get("streams", [])

    print("=" * 50)
    print(f"  文件  : {args.input}")
    print(f"  大小  : {int(fmt.get('size', 0)) / 1_048_576:.2f} MB")
    print(f"  时长  : {float(fmt.get('duration', 0)):.2f} 秒")
    print(f"  格式  : {fmt.get('format_long_name', '-')}")
    print(f"  比特率: {int(fmt.get('bit_rate', 0)) // 1000} kbps")
    print("=" * 50)

    for s in streams:
        idx   = s.get("index")
        ctype = s.get("codec_type", "?")
        cname = s.get("codec_name", "?")
        if ctype == "video":
            w, h  = s.get("width", "?"), s.get("height", "?")
            fps_r = s.get("r_frame_rate", "0/1")
            num, den = (int(x) for x in fps_r.split("/"))
            fps = num / den if den else 0
            pix = s.get("pix_fmt", "?")
            print(f"  [视频流 #{idx}] {cname}  {w}x{h}  {fps:.2f}fps  {pix}")
        elif ctype == "audio":
            sr    = s.get("sample_rate", "?")
            ch    = s.get("channels", "?")
            print(f"  [音频流 #{idx}] {cname}  {sr}Hz  {ch}ch")
        elif ctype == "subtitle":
            lang  = s.get("tags", {}).get("language", "?")
            print(f"  [字幕流 #{idx}] {cname}  lang:{lang}")
        else:
            print(f"  [流    #{idx}] {ctype} / {cname}")
    print("=" * 50)


# 2. 裁剪片段

def cmd_trim(args):
    assert_input(args.input)
    output = args.output or default_output(args.input, "_trimmed")

    # 输出扩展名与输入不同且未启用精确裁剪 → 自动重编码（-c copy 跨容器会失败）
    input_ext = Path(args.input).suffix.lower()
    output_ext = Path(output).suffix.lower()
    if not args.accurate and input_ext != output_ext:
        print(f"  检测到容器格式变化 ({input_ext} → {output_ext})，自动切换为重编码模式")
        args.accurate = True

    cmd = [
        "ffmpeg", "-y",
        "-ss", args.start,
    ]
    if args.end:
        dur = hms_to_sec(args.end) - hms_to_sec(args.start)
        cmd += ["-t", str(dur)]
    cmd += ["-i", args.input]
    if args.accurate:
        cmd += ["-c:v", "libx264", "-crf", ENCODE_CRF, "-preset", ENCODE_PRESET,
                "-c:a", "aac", "-b:a", AUDIO_BITRATE]
    else:
        cmd += ["-c", "copy"]
    cmd.append(output)
    dur_val = float(get_duration(args.input))
    run(cmd, f"裁剪 {args.start} -> {args.end or '结尾'}", verbose=args.verbose,
        output=output, duration=dur_val)
    print(f"已保存: {output}")


# 3. 格式转换

def cmd_convert(args):
    assert_input(args.input)
    output = args.output or default_output(args.input, "_converted", f".{args.format}")
    cmd = [
        "ffmpeg", "-y",
        "-i", args.input,
    ]
    if args.format == "mp4":
        gpu_args = _video_encoder_args(args)
        if gpu_args:
            cmd += gpu_args
        else:
            cmd += ["-c:v", "libx264", "-crf", ENCODE_CRF, "-preset", ENCODE_PRESET]
        cmd += ["-c:a", "aac", "-b:a", AUDIO_BITRATE]
    elif args.format == "webm":
        cmd += ["-c:v", "libvpx-vp9", "-crf", "30", "-b:v", "0",
                "-c:a", "libopus", "-b:a", AUDIO_BITRATE]
    elif args.format == "gif":
        _to_gif(args.input, output, fps=GIF_DEFAULT_FPS, width=GIF_DEFAULT_WIDTH)
        size = Path(output).stat().st_size / 1024
        print(f"已保存: {output}  ({size:.0f} KB)")
        return
    else:
        cmd += ["-c", "copy"]
    cmd.append(output)
    dur_val = float(get_duration(args.input))
    run(cmd, f"转换为 {args.format.upper()}", verbose=args.verbose,
        output=output, duration=dur_val)
    print(f"已保存: {output}")


# 4. 调整分辨率

def cmd_resize(args):
    assert_input(args.input)
    output = args.output or default_output(args.input, f"_{args.size}")

    preset = {
        "4k": "3840:-2", "2160p": "3840:-2",
        "2k": "2560:-2", "1440p": "2560:-2",
        "1080p": "1920:-2", "720p": "1280:-2",
        "480p": "854:-2",  "360p": "640:-2",
    }
    # 规范化用户输入: "720"→"720p", "1280 720"→"1280:720", "1280x720"→"1280:720"
    size = args.size.lower().strip().replace("x", ":").replace(" ", ":")
    # 纯数字且无冒号 → 补 p
    if size.isdigit():
        size = size + "p"
    if ":" in size:
        scale = size
    else:
        scale = preset.get(size) or "1280:-2"

    enc_args = _video_encoder_args(args) or [
        "-c:v", "libx264", "-crf", ENCODE_CRF, "-preset", ENCODE_PRESET,
    ]
    run([
        "ffmpeg", "-y", "-i", args.input,
        "-vf", f"scale={scale}",
        *enc_args,
        "-c:a", "copy",
        output,
    ], f"调整分辨率 -> {args.size}", verbose=args.verbose, output=output)
    print(f"已保存: {output}")


# 5. 旋转视频

def cmd_rotate(args):
    assert_input(args.input)
    if args.degrees not in (90, 180, 270):
        sys.exit(f"[错误] 旋转角度仅支持 90/180/270，收到: {args.degrees}")
    output = args.output or default_output(args.input, f"_rot{args.degrees}")
    transpose_map = {"90": "1", "180": "2,transpose=2", "270": "2"}
    vf = f"transpose={transpose_map[str(args.degrees)]}"
    run([
        "ffmpeg", "-y", "-i", args.input,
        "-vf", vf, "-c:a", "copy",
        output,
    ], f"旋转 {args.degrees}度", verbose=args.verbose)
    print(f"已保存: {output}")


# 6. 调整播放速度

def cmd_speed(args):
    assert_input(args.input)
    factor = args.factor
    if factor <= 0:
        sys.exit("[错误] 速度倍率必须大于 0")
    output = args.output or default_output(args.input, f"_x{factor}")

    video_filter = f"setpts={1/factor:.4f}*PTS"
    if 0.5 <= factor <= 2.0:
        audio_filter = f"atempo={factor}"
    elif factor > 2.0:
        audio_filter = f"atempo=2.0,atempo={factor/2:.4f}"
    else:
        audio_filter = f"atempo=0.5,atempo={factor/0.5:.4f}"

    run([
        "ffmpeg", "-y", "-i", args.input,
        "-filter_complex",
        f"[0:v]{video_filter}[v];[0:a]{audio_filter}[a]",
        "-map", "[v]", "-map", "[a]",
        "-c:v", "libx264", "-crf", ENCODE_CRF, "-preset", ENCODE_PRESET,
        "-c:a", "aac", "-b:a", AUDIO_BITRATE,
        output,
    ], f"速度调整 x {factor}", verbose=args.verbose)
    print(f"已保存: {output}")


# 7. 提取音频

def cmd_extract_audio(args):
    assert_input(args.input)
    ext = args.format or "mp3"
    output = args.output or default_output(args.input, "_audio", f".{ext}")
    codec_map = {"mp3": "libmp3lame", "aac": "aac", "flac": "flac",
                 "wav": "pcm_s16le", "opus": "libopus"}
    codec = codec_map.get(ext, "libmp3lame")
    run([
        "ffmpeg", "-y", "-i", args.input,
        "-vn", "-c:a", codec,
        "-b:a", EXT_AUDIO_BITRATE,
        output,
    ], f"提取音频 -> {ext.upper()}", verbose=args.verbose)
    print(f"已保存: {output}")


# 8. 去除音频

def cmd_mute(args):
    assert_input(args.input)
    output = args.output or default_output(args.input, "_muted")
    run([
        "ffmpeg", "-y", "-i", args.input,
        "-an", "-c:v", "copy",
        output,
    ], "去除音频", verbose=args.verbose)
    print(f"已保存: {output}")

# 9. 替换音频

def cmd_replace_audio(args):
    assert_input(args.input)
    assert_input(args.audio)
    output = args.output or default_output(args.input, "_newaudio")
    run([
        "ffmpeg", "-y",
        "-i", args.input,
        "-i", args.audio,
        "-map", "0:v:0", "-map", "1:a:0",
        "-c:v", "copy", "-c:a", "aac",
        "-shortest",
        output,
    ], "替换音频", verbose=args.verbose)
    print(f"已保存: {output}")


# 10. 压缩视频

def cmd_compress(args):
    assert_input(args.input)
    output = args.output or default_output(args.input, "_compressed")

    if args.target_mb:
        duration_str = get_duration(args.input)
        if not duration_str or float(duration_str) <= 0:
            sys.exit("[错误] 无法获取视频时长，无法按目标大小压缩")
        duration = float(duration_str)
        target_kbps = int((args.target_mb * 8 * 1024) / duration)
        audio_kbps  = 128
        video_kbps  = max(100, target_kbps - audio_kbps)
        print(f"   时长: {duration:.1f}s  目标比特率: 视频 {video_kbps} kbps + 音频 {audio_kbps} kbps")

        gpu_args = _video_encoder_args(args)
        if gpu_args:
            # GPU 1-pass VBR；非 NVIDIA 后端可能不支持 -b:v，此时退回到 CRF 模式
            filtered: list[str] = []
            skip = False
            has_bv = any(a == "-b:v" for a in gpu_args)
            for item in gpu_args:
                if skip:
                    skip = False
                    continue
                if item == "-b:v":
                    filtered += ["-b:v", f"{video_kbps}k"]
                    skip = True  # 跳过后面的 "0"
                else:
                    filtered.append(item)
            if not has_bv:
                print(f"   [警告] 当前 GPU 后端不支持按比特率编码，使用限制 CRF={ENCODE_CRF} 模式")
                filtered += ["-crf", ENCODE_CRF]
            run(["ffmpeg", "-y", "-i", args.input] + filtered +
                ["-c:a", "aac", "-b:a", f"{audio_kbps}k", output],
                "GPU 压缩 (1-pass)", verbose=args.verbose)
        else:
            run(["ffmpeg", "-y", "-i", args.input,
                 "-c:v", "libx264", "-b:v", f"{video_kbps}k",
                 "-pass", "1", "-an", "-f", "null", os.devnull],
                "两遍压缩 第1遍", verbose=args.verbose)
            run(["ffmpeg", "-y", "-i", args.input,
                 "-c:v", "libx264", "-b:v", f"{video_kbps}k",
                 "-pass", "2", "-c:a", "aac", "-b:a", f"{audio_kbps}k",
                 output],
                "两遍压缩 第2遍", verbose=args.verbose)
    else:
        crf_val = args.crf or COMPRESS_CRF
        gpu_args = _video_encoder_args(args, crf_override=crf_val, preset_override="slow")
        if gpu_args:
            run(["ffmpeg", "-y", "-i", args.input] + gpu_args +
                ["-c:a", "aac", "-b:a", AUDIO_BITRATE, output],
                f"GPU CRF={crf_val} 压缩", verbose=args.verbose)
        else:
            run(["ffmpeg", "-y", "-i", args.input,
                 "-c:v", "libx264", "-crf", str(crf_val), "-preset", "slow",
                 "-c:a", "aac", "-b:a", AUDIO_BITRATE,
                 output],
                f"CRF={crf_val} 压缩", verbose=args.verbose)

    orig = Path(args.input).stat().st_size / 1_048_576
    comp = Path(output).stat().st_size / 1_048_576
    print(f"已保存: {output}")
    print(f"   {orig:.2f} MB -> {comp:.2f} MB  (压缩率 {(1-comp/orig)*100:.1f}%)")


# 11. 截图

def get_duration(path: str) -> str:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", path],
        capture_output=True, text=True,
    )
    return result.stdout.strip() or "60"


def cmd_screenshot(args):
    assert_input(args.input)
    output = args.output or default_output(args.input, f"_frame_{args.time.replace(':','')}", ".jpg")
    run([
        "ffmpeg", "-y",
        "-ss", args.time,
        "-i", args.input,
        "-frames:v", "1",
        "-q:v", "2",
        output,
    ], f"截图时间点 {args.time}", verbose=args.verbose)
    print(f"已保存: {output}")

# 12. 缩略图

def cmd_thumbnail(args):
    """均匀抽帧生成 N 张缩略图。"""
    assert_input(args.input)
    out_dir = Path(args.output or (Path(args.input).stem + "_thumbs"))
    out_dir.mkdir(parents=True, exist_ok=True)
    count = args.count or THUMB_DEFAULT_COUNT
    run([
        "ffmpeg", "-y", "-i", args.input,
        "-vf", f"fps=1/{int(float(get_duration(args.input))/count)},"
               f"scale=320:-2",
        "-frames:v", str(count),
        str(out_dir / "thumb_%03d.jpg"),
    ], f"生成 {count} 张缩略图", verbose=args.verbose)
    print(f"缩略图已保存至: {out_dir}/")

# 13. 九宫格拼图

def cmd_thumbnail_grid(args):
    """九宫格式缩略图拼图（例如 3x3）"""
    assert_input(args.input)
    output = args.output or default_output(args.input, "_grid", ".jpg")
    cols = args.columns or THUMB_DEFAULT_COLS
    rows = args.rows or THUMB_DEFAULT_ROWS
    cells = cols * rows
    duration = float(get_duration(args.input))
    # 用时长动态算帧率，保证短片也能填满网格
    fps = cells / max(duration, 0.1)
    run([
        "ffmpeg", "-y", "-i", args.input,
        "-vf", f"fps={fps:.4f},scale={args.scale or THUMB_CELL_WIDTH}:-2,tile={cols}x{rows}",
        "-frames:v", "1",
        output,
    ], f"生成 {cols}x{rows} 缩略图拼图", verbose=args.verbose)
    print(f"拼图已保存: {output}")


# 14. 转 GIF

def _to_gif(input_path, output, fps=GIF_DEFAULT_FPS, width=GIF_DEFAULT_WIDTH, start=None, duration=None):
    ss_args = (["-ss", start] if start else [])
    t_args  = (["-t", duration] if duration else [])
    scale   = f"scale={width}:-2:flags=lanczos"

    # 用 tempfile 创建调色板，确保异常退出时也能清理
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        palette = f.name
    try:
        run(
            ["ffmpeg", "-y"] + ss_args + t_args +
            ["-i", input_path,
             "-vf", f"{scale},palettegen",
             palette],
            "生成 GIF 调色板",
        )
        run(
            ["ffmpeg", "-y"] + ss_args + t_args +
            ["-i", input_path, "-i", palette,
             "-filter_complex",
             f"{scale}[x];[x][1:v]paletteuse",
             "-r", str(fps),
             output],
            "渲染 GIF",
        )
    finally:
        try:
            os.unlink(palette)
        except OSError:
            pass
    return output


def cmd_gif(args):
    assert_input(args.input)
    # 全视频转 GIF 可能耗时巨大且文件巨大，提醒用户
    if not args.start and not args.duration:
        dur = float(get_duration(args.input))
        if dur > 30:
            print(f"[警告] 视频时长 {dur:.0f}s，全量转 GIF 可能耗时较长且文件很大。")
            print("       建议用 -s 和 --duration 指定片段。")
            if input("继续转换？(y/N): ").strip().lower() != "y":
                print("已取消")
                return
    output = args.output or default_output(args.input, "_animated", ".gif")
    _to_gif(
        args.input, output,
        fps=args.fps or GIF_DEFAULT_FPS,
        width=args.width or GIF_DEFAULT_WIDTH,
        start=args.start,
        duration=args.duration,
    )
    size = Path(output).stat().st_size / 1024
    print(f"已保存: {output}  ({size:.0f} KB)")


# 15. 文字水印

POSITION_MAP = {
    "topleft":     "10:10",
    "topright":    "W-w-10:10",
    "bottomleft":  "10:H-h-10",
    "bottomright": "W-w-10:H-h-10",
    "center":      "(W-w)/2:(H-h)/2",
}

def cmd_watermark_text(args):
    assert_input(args.input)
    output = args.output or default_output(args.input, "_watermarked")
    pos    = POSITION_MAP.get(args.position or WM_DEFAULT_POSITION, "W-w-10:H-h-10")
    # drawtext 用 tw/th 表示文字宽高，overlay 用 w/h；这里做变量名转换
    pos    = pos.replace("w", "tw").replace("h", "th")
    color  = args.color or WM_DEFAULT_COLOR
    size   = args.size or WM_DEFAULT_FONT_SIZE
    font = getattr(args, "font", None) or FONT_FILE
    font = font.replace("\\", "/").replace(":", "\\:")
    vf = (
        f"drawtext=text='{args.text}'"
        f":fontfile='{font}'"
        f":fontcolor={color}:fontsize={size}"
        f":x={pos.split(':')[0]}:y={pos.split(':')[1]}"
        f":shadowcolor=black@0.5:shadowx=2:shadowy=2"
    )
    run(["ffmpeg", "-y", "-i", args.input, "-vf", vf, "-c:a", "copy", output],
        "添加文字水印", verbose=args.verbose)
    print(f"已保存: {output}")

# 16. 图片水印

def cmd_watermark_image(args):
    assert_input(args.input)
    assert_input(args.image)
    output = args.output or default_output(args.input, "_watermarked")
    pos    = POSITION_MAP.get(args.position or WM_DEFAULT_POSITION, "W-w-10:H-h-10")
    x, y   = pos.split(":")
    run([
        "ffmpeg", "-y",
        "-i", args.input,
        "-i", args.image,
        "-filter_complex",
        f"[1:v]scale={args.scale or WM_IMAGE_DEFAULT_SCALE}:-1[wm];[0:v][wm]overlay={x}:{y}",
        "-c:a", "copy",
        output,
    ], "添加图片水印", verbose=args.verbose)
    print(f"已保存: {output}")

# 17. 平铺水印

def cmd_watermark_tile(args):
    assert_input(args.input)
    output = args.output or default_output(args.input, "_tiled")
    text   = args.text
    color  = args.color or TILE_DEFAULT_COLOR
    size   = args.size or TILE_DEFAULT_FONT_SIZE
    font   = getattr(args, "font", None) or FONT_FILE
    font   = font.replace("\\", "/").replace(":", "\\:")
    cw     = args.cell_w or TILE_DEFAULT_CELL_W
    ch     = args.cell_h or TILE_DEFAULT_CELL_H
    # 获取视频分辨率
    w_str = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=p=0", args.input],
        capture_output=True, text=True,
    ).stdout.strip()
    vw, vh = map(int, w_str.split(",")) if "," in w_str else (1920, 1080)
    cols = max(1, vw // cw)
    rows = max(1, vh // ch)
    # 链式 drawtext：每个格子居中写文字
    filters = []
    for row in range(rows):
        for col in range(cols):
            x = int(col * cw + cw / 2)
            y = int(row * ch + ch / 2)
            filters.append(
                f"drawtext=text='{text}':fontfile='{font}':fontcolor={color}:fontsize={size}:x={x}-tw/2:y={y}-th/2"
            )
    vf = ",".join(filters)
    run([
        "ffmpeg", "-y", "-i", args.input,
        "-vf", vf,
        "-c:a", "copy", output,
    ], "平铺水印", verbose=args.verbose)
    print(f"已保存: {output}")

# 18. 音量调节
def cmd_volume(args):
    assert_input(args.input)
    output = args.output or default_output(args.input, f"_vol{args.db}dB")
    factor = 10 ** (args.db / 20.0)
    run([
        "ffmpeg", "-y", "-i", args.input,
        "-af", f"volume={factor:.4f}",
        "-c:v", "copy",
        output,
    ], f"音量调节 {args.db:+}dB", verbose=args.verbose)
    print(f"已保存: {output}")


# 19. 画面裁剪
def cmd_crop(args):
    assert_input(args.input)
    output = args.output or default_output(args.input, "_cropped")
    crop_filter = f"crop={args.geometry}"
    run([
        "ffmpeg", "-y", "-i", args.input,
        "-vf", crop_filter,
        "-c:a", "copy",
        output,
    ], f"裁剪画面 {args.geometry}", verbose=args.verbose)
    print(f"已保存: {output}")


# 20. 改变帧率（不改变速度）
def cmd_fps(args):
    assert_input(args.input)
    output = args.output or default_output(args.input, f"_fps{args.rate}")
    run([
        "ffmpeg", "-y", "-i", args.input,
        "-r", str(args.rate),
        "-c:v", "libx264", "-crf", ENCODE_CRF, "-preset", ENCODE_PRESET,
        "-c:a", "copy",
        output,
    ], f"帧率调整为 {args.rate} fps", verbose=args.verbose)
    print(f"已保存: {output}")


# 21. 通用视频滤镜（亮度、模糊、调色等）
def cmd_filter(args):
    assert_input(args.input)
    output = args.output or default_output(args.input, "_filtered")
    run([
        "ffmpeg", "-y", "-i", args.input,
        "-vf", args.filter_string,
        "-c:a", "copy",
        output,
    ], f"应用滤镜: {args.filter_string}", verbose=args.verbose)
    print(f"已保存: {output}")


# 22. 字幕提取
def cmd_subtitle_extract(args):
    assert_input(args.input)
    output = args.output or default_output(args.input, "_sub", f".{args.format or 'srt'}")
    run([
        "ffmpeg", "-y", "-i", args.input,
        "-map", f"0:s:{args.index or 0}",
        output,
    ], f"提取字幕流 #{args.index or 0}", verbose=args.verbose)
    print(f"已保存: {output}")


# 23. 烧录硬字幕
def cmd_subtitle_burn(args):
    assert_input(args.input)
    assert_input(args.sub_file)
    output = args.output or default_output(args.input, "_burnedsub")
    sub_path = args.sub_file.replace("\\", "/").replace(":", "\\:")
    vf = f"subtitles='{sub_path}'"
    run([
        "ffmpeg", "-y", "-i", args.input,
        "-vf", vf,
        "-c:a", "copy",
        output,
    ], f"烧录硬字幕: {args.sub_file}", verbose=args.verbose)
    print(f"已保存: {output}")


# 24. 添加外挂软字幕
def cmd_subtitle_add(args):
    assert_input(args.input)
    assert_input(args.sub_file)
    output = args.output or default_output(args.input, "_softsub")
    ext = Path(output).suffix.lower()
    sub_codec = "mov_text" if ext in [".mp4", ".m4v"] else "copy"
    run([
        "ffmpeg", "-y",
        "-i", args.input,
        "-i", args.sub_file,
        "-c", "copy",
        "-c:s", sub_codec,
        "-map", "0", "-map", "1",
        output,
    ], f"添加软字幕: {args.sub_file}", verbose=args.verbose)
    print(f"已保存: {output}")


# 25. 画中画（叠加另一个视频）
def cmd_overlay_video(args):
    assert_input(args.input)
    assert_input(args.overlay)
    output = args.output or default_output(args.input, "_pip")
    pos    = POSITION_MAP.get(args.position or WM_DEFAULT_POSITION, "W-w-10:H-h-10")
    run([
        "ffmpeg", "-y",
        "-i", args.input,
        "-i", args.overlay,
        "-filter_complex",
        f"[1:v]scale={args.scale or PIP_DEFAULT_SCALE}:-1[pip];[0:v][pip]overlay={pos}:shortest=1",
        "-c:a", "copy",
        output,
    ], "叠加画中画", verbose=args.verbose)
    print(f"已保存: {output}")


# 26. 视频拼接（多文件）
def cmd_concat(args):
    inputs = args.files
    for f in inputs:
        assert_input(f)
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8") as f:
        for file in inputs:
            f.write(f"file '{os.path.abspath(file)}'\n")
        list_file = f.name

    output = args.output or default_output(inputs[0], "_concat")

    # 输出容器格式与输入不同 → 不能 -c copy，需重编码
    input_ext = Path(inputs[0]).suffix.lower()
    output_ext = Path(output).suffix.lower()
    if input_ext != output_ext:
        print(f"  检测到容器格式变化 ({input_ext} → {output_ext})，切换为重编码模式")
        codec_args = ["-c:v", "libx264", "-crf", ENCODE_CRF, "-preset", ENCODE_PRESET,
                      "-c:a", "aac", "-b:a", AUDIO_BITRATE]
    else:
        codec_args = ["-c", "copy"]

    try:
        run([
            "ffmpeg", "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", list_file,
            *codec_args,
            output,
        ], f"拼接 {len(inputs)} 个文件", verbose=args.verbose)
    finally:
        try:
            os.unlink(list_file)
        except OSError:
            pass
    print(f"已保存: {output}")


# CLI 定义

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="vidtool",
        description="单视频处理工具（ffmpeg 驱动）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
命令示例:
  python vidtool.py info        input.mp4
  python vidtool.py trim        input.mp4 -s 00:01:00 -e 00:02:30
  python vidtool.py convert     input.mp4 -f webm
  python vidtool.py resize      input.mp4 --size 720p
  python vidtool.py rotate      input.mp4 --degrees 90
  python vidtool.py speed       input.mp4 --factor 2.0
  python vidtool.py extract-audio input.mp4 --format mp3
  python vidtool.py mute        input.mp4
  python vidtool.py replace-audio input.mp4 --audio bgm.mp3
  python vidtool.py compress    input.mp4 --target-mb 50
  python vidtool.py compress    input.mp4 --crf 26
  python vidtool.py screenshot  input.mp4 --time 00:01:23
  python vidtool.py thumbnail   input.mp4 --count 8
  python vidtool.py thumbnail-grid input.mp4 --columns 3 --rows 3
  python vidtool.py gif         input.mp4 -s 00:00:10 --duration 5
  python vidtool.py watermark-text  input.mp4 --text "(C) 2025" --position bottomright
  python vidtool.py watermark-image input.mp4 --image logo.png --position topright
  python vidtool.py volume      input.mp4 --db -10
  python vidtool.py crop        input.mp4 --geometry 640:480:0:0
  python vidtool.py fps         input.mp4 --rate 24
  python vidtool.py filter      input.mp4 --filter-string "eq=brightness=0.05:contrast=1.2"
  python vidtool.py subtitle-extract input.mkv --index 0 --format srt
  python vidtool.py subtitle-burn    input.mp4 --sub-file sub.srt
  python vidtool.py subtitle-add     input.mp4 --sub-file sub.srt
  python vidtool.py overlay-video input.mp4 --overlay pip.mp4 --position bottomright
  python vidtool.py concat 1.mp4 2.mp4 3.mp4 -o merged.mp4
""",
    )
    p.add_argument("-V", "--version", action="version", version="vidtool 1.0")
    p.add_argument("--verbose", action="store_true", default=False,
                   help="显示 ffmpeg 实时编码进度（需放在子命令前）")
    sub = p.add_subparsers(dest="command", metavar="<命令>")

    # info
    sp = sub.add_parser("info", help="查看视频元信息")
    sp.add_argument("input", help="输入视频文件")

    # trim
    sp = sub.add_parser("trim", help="按时间点裁剪片段")
    sp.add_argument("input");  sp.add_argument("-s", "--start", default="0", help="起始时间 (默认 0)")
    sp.add_argument("-e", "--end", default=None, help="结束时间 (默认到末尾)")
    sp.add_argument("--accurate", action="store_true", help="精确裁剪（重编码，避免黑屏）")
    sp.add_argument("-o", "--output")

    # convert
    sp = sub.add_parser("convert", help="格式转换")
    sp.add_argument("input");  sp.add_argument("-f", "--format", default="mp4",
        choices=["mp4", "mkv", "webm", "avi", "mov", "gif"], help="目标格式")
    sp.add_argument("--gpu", nargs="?", const=True, default=False,
        help="使用 GPU 硬件编码 (nvidia/amd/intel/apple，留空自动检测)")
    sp.add_argument("-o", "--output")

    # resize
    sp = sub.add_parser("resize", help="调整分辨率")
    sp.add_argument("input");  sp.add_argument("--size", default="720p",
        help="720p / 1080p / 4k / 宽:高，例: 1280:720")
    sp.add_argument("--gpu", nargs="?", const=True, default=False,
        help="使用 GPU 硬件编码 (nvidia/amd/intel/apple，留空自动检测)")
    sp.add_argument("-o", "--output")

    # rotate
    sp = sub.add_parser("rotate", help="旋转视频")
    sp.add_argument("input");  sp.add_argument("--degrees", type=int,
        choices=[90, 180, 270], default=90)
    sp.add_argument("-o", "--output")

    # speed
    sp = sub.add_parser("speed", help="调整播放速度")
    sp.add_argument("input");  sp.add_argument("--factor", type=float, default=2.0,
        help="速度倍数，如 0.5=半速 2.0=两倍速")
    sp.add_argument("-o", "--output")

    # extract-audio
    sp = sub.add_parser("extract-audio", help="提取音频")
    sp.add_argument("input");  sp.add_argument("--format", default="mp3",
        choices=["mp3", "aac", "flac", "wav", "opus"])
    sp.add_argument("-o", "--output")

    # mute
    sp = sub.add_parser("mute", help="去除音频")
    sp.add_argument("input");  sp.add_argument("-o", "--output")

    # replace-audio
    sp = sub.add_parser("replace-audio", help="替换音频")
    sp.add_argument("input");  sp.add_argument("--audio", required=True, help="替换用音频文件")
    sp.add_argument("-o", "--output")

    # compress
    sp = sub.add_parser("compress", help="压缩视频")
    sp.add_argument("input")
    g = sp.add_mutually_exclusive_group()
    g.add_argument("--target-mb", type=float, help="目标文件大小（MB），使用两遍编码")
    g.add_argument("--crf", type=int, help="CRF 值（18~35，越大越小）")
    sp.add_argument("--gpu", nargs="?", const=True, default=False,
        help="使用 GPU 硬件编码 (nvidia/amd/intel/apple，留空自动检测)")
    sp.add_argument("-o", "--output")

    # screenshot
    sp = sub.add_parser("screenshot", help="截取某帧为图片")
    sp.add_argument("input");  sp.add_argument("--time", default="00:00:01",
        help="时间点，如 00:01:23")
    sp.add_argument("-o", "--output")

    # thumbnail
    sp = sub.add_parser("thumbnail", help="均匀抽帧生成缩略图集")
    sp.add_argument("input");  sp.add_argument("--count", type=int, default=THUMB_DEFAULT_COUNT)
    sp.add_argument("-o", "--output", help="输出目录")

    # thumbnail-grid
    sp = sub.add_parser("thumbnail-grid", help="生成缩略图拼图（九宫格）")
    sp.add_argument("input")
    sp.add_argument("--columns", type=int, default=THUMB_DEFAULT_COLS)
    sp.add_argument("--rows", type=int, default=THUMB_DEFAULT_ROWS)
    sp.add_argument("--scale", type=int, default=THUMB_CELL_WIDTH, help=f"每格宽度（px，默认{THUMB_CELL_WIDTH}）")
    sp.add_argument("-o", "--output")

    # gif
    sp = sub.add_parser("gif", help="片段转 GIF（含调色板优化）")
    sp.add_argument("input")
    sp.add_argument("-s", "--start", help="起始时间")
    sp.add_argument("--duration", help="持续秒数")
    sp.add_argument("--fps", type=int, default=GIF_DEFAULT_FPS)
    sp.add_argument("--width", type=int, default=GIF_DEFAULT_WIDTH, help="GIF 宽度（px）")
    sp.add_argument("-o", "--output")

    # watermark-text
    sp = sub.add_parser("watermark-text", help="叠加文字水印")
    sp.add_argument("input");  sp.add_argument("--text", required=True)
    sp.add_argument("--position", default=WM_DEFAULT_POSITION,
        choices=list(POSITION_MAP.keys()))
    sp.add_argument("--color", default=WM_DEFAULT_COLOR, help="字体颜色（支持透明度）")
    sp.add_argument("--size", type=int, default=WM_DEFAULT_FONT_SIZE)
    sp.add_argument("--font", default=FONT_FILE, help="字体文件路径")
    sp.add_argument("-o", "--output")

    # watermark-image
    sp = sub.add_parser("watermark-image", help="叠加图片水印")
    sp.add_argument("input");  sp.add_argument("--image", required=True)
    sp.add_argument("--position", default=WM_DEFAULT_POSITION, choices=list(POSITION_MAP.keys()))
    sp.add_argument("--scale", type=int, default=WM_IMAGE_DEFAULT_SCALE, help="水印图片宽度（px）")
    sp.add_argument("-o", "--output")

    # watermark-tile
    sp = sub.add_parser("watermark-tile", help="平铺文字水印（满屏防伪）")
    sp.add_argument("input");  sp.add_argument("--text", required=True, help="水印文字")
    sp.add_argument("--color", default=TILE_DEFAULT_COLOR, help="字体颜色（支持透明度）")
    sp.add_argument("--size", type=int, default=TILE_DEFAULT_FONT_SIZE, help="字号")
    sp.add_argument("--font", default=FONT_FILE, help="字体文件路径")
    sp.add_argument("--cell-w", type=int, default=TILE_DEFAULT_CELL_W, help="单元格宽度（px）")
    sp.add_argument("--cell-h", type=int, default=TILE_DEFAULT_CELL_H, help="单元格高度（px）")
    sp.add_argument("-o", "--output")

    # volume
    sp = sub.add_parser("volume", help="调节音量（dB）")
    sp.add_argument("input");  sp.add_argument("--db", type=float, required=True,
        help="增减分贝值，例如 -6 为减半，+3 为增加")
    sp.add_argument("-o", "--output")

    # crop
    sp = sub.add_parser("crop", help="裁切画面")
    sp.add_argument("input");  sp.add_argument("--geometry", default="640:480:0:0",
        help="裁切参数: 宽:高:x:y，例如 640:480:10:20")
    sp.add_argument("-o", "--output")

    # fps
    sp = sub.add_parser("fps", help="改变视频帧率（不影响时长）")
    sp.add_argument("input");  sp.add_argument("--rate", type=float, default=24,
        help="目标帧率，例如 24")
    sp.add_argument("-o", "--output")

    # filter
    sp = sub.add_parser("filter", help="应用任意 ffmpeg 视频滤镜")
    sp.add_argument("input");  sp.add_argument("--filter-string", required=True,
        help="滤镜字符串，例如 eq=brightness=0.1,boxblur=2")
    sp.add_argument("-o", "--output")

    # subtitle-extract
    sp = sub.add_parser("subtitle-extract", help="提取字幕流")
    sp.add_argument("input")
    sp.add_argument("--index", type=int, default=0, help="字幕流索引")
    sp.add_argument("--format", default="srt", choices=["srt", "ass", "ssa"], help="输出格式")
    sp.add_argument("-o", "--output")

    # subtitle-burn
    sp = sub.add_parser("subtitle-burn", help="烧录硬字幕到视频")
    sp.add_argument("input");  sp.add_argument("--sub-file", required=True, help="字幕文件")
    sp.add_argument("-o", "--output")

    # subtitle-add
    sp = sub.add_parser("subtitle-add", help="添加外挂软字幕")
    sp.add_argument("input");  sp.add_argument("--sub-file", required=True, help="字幕文件")
    sp.add_argument("-o", "--output")

    # overlay-video
    sp = sub.add_parser("overlay-video", help="叠加画中画")
    sp.add_argument("input");  sp.add_argument("--overlay", required=True, help="画中画视频文件")
    sp.add_argument("--position", default=WM_DEFAULT_POSITION, choices=list(POSITION_MAP.keys()))
    sp.add_argument("--scale", type=int, default=PIP_DEFAULT_SCALE, help="画中画宽度（px）")
    sp.add_argument("-o", "--output")

    # concat
    sp = sub.add_parser("concat", help="拼接多个视频（同一编码格式）")
    sp.add_argument("files", nargs="+", help="要拼接的文件列表")
    sp.add_argument("-o", "--output")

    return p


COMMAND_MAP = {
    "info":           cmd_info,
    "trim":           cmd_trim,
    "convert":        cmd_convert,
    "resize":         cmd_resize,
    "rotate":         cmd_rotate,
    "speed":          cmd_speed,
    "extract-audio":  cmd_extract_audio,
    "mute":           cmd_mute,
    "replace-audio":  cmd_replace_audio,
    "compress":       cmd_compress,
    "screenshot":     cmd_screenshot,
    "thumbnail":      cmd_thumbnail,
    "thumbnail-grid": cmd_thumbnail_grid,
    "gif":            cmd_gif,
    "watermark-text": cmd_watermark_text,
    "watermark-image":cmd_watermark_image,
    "watermark-tile": cmd_watermark_tile,
    "volume":         cmd_volume,
    "crop":           cmd_crop,
    "fps":            cmd_fps,
    "filter":         cmd_filter,
    "subtitle-extract": cmd_subtitle_extract,
    "subtitle-burn":    cmd_subtitle_burn,
    "subtitle-add":     cmd_subtitle_add,
    "overlay-video":   cmd_overlay_video,
    "concat":          cmd_concat,
}


class _InteractiveArgs:
    """交互模式用的参数容器，使类型检查器能识别所有动态属性"""
    input: str = ""
    output: str | None = None
    start: str | None = "0"
    end: str | None = None
    accurate: bool = False
    format: str = ""
    size: str | int = ""
    degrees: int = 90
    factor: float = 1.0
    target_mb: float | None = None
    crf: int | None = None
    time: str = ""
    count: int = THUMB_DEFAULT_COUNT
    duration: str | None = None
    fps: int = GIF_DEFAULT_FPS
    width: int = GIF_DEFAULT_WIDTH
    text: str = ""
    position: str = ""
    color: str = ""
    image: str = ""
    scale: int = WM_IMAGE_DEFAULT_SCALE
    font: str = ""
    cell_w: int = TILE_DEFAULT_CELL_W
    cell_h: int = TILE_DEFAULT_CELL_H
    verbose: bool = False
    audio: str = ""
    db: float = 0.0
    geometry: str = ""
    rate: float = 24.0
    filter_string: str = ""
    index: int = 0
    sub_file: str = ""
    overlay: str = ""
    columns: int = THUMB_DEFAULT_COLS
    rows: int = THUMB_DEFAULT_ROWS
    files: list[str] | None = None
    gpu: bool | str = False


def main():
    check_ffmpeg()
    parser = build_parser()
    if len(sys.argv) == 1:
        interactive_mode()
    else:
        args = parser.parse_args()
        if not args.command:
            parser.print_help()
            sys.exit(1)
        handler = COMMAND_MAP.get(args.command)
        if not handler:
            parser.print_help()
            sys.exit(1)
        handler(args)


def interactive_mode():
    """简易交互式菜单，无需记忆命令"""
    print("vidtool 交互模式")
    while True:
        print("\n请选择操作:")
        options = [
            ("查看视频信息", "info"),
            ("裁剪片段", "trim"),
            ("格式转换", "convert"),
            ("调整分辨率", "resize"),
            ("旋转视频", "rotate"),
            ("调整播放速度", "speed"),
            ("提取音频", "extract-audio"),
            ("去除音频", "mute"),
            ("替换音频", "replace-audio"),
            ("压缩视频", "compress"),
            ("截图", "screenshot"),
            ("生成缩略图", "thumbnail"),
            ("九宫格缩略图", "thumbnail-grid"),
            ("生成GIF", "gif"),
            ("添加文字水印", "watermark-text"),
            ("添加图片水印", "watermark-image"),
            ("平铺文字水印", "watermark-tile"),
            ("音量调节", "volume"),
            ("裁切画面", "crop"),
            ("改变帧率", "fps"),
            ("视频滤镜", "filter"),
            ("字幕提取", "subtitle-extract"),
            ("烧录硬字幕", "subtitle-burn"),
            ("添加软字幕", "subtitle-add"),
            ("画中画", "overlay-video"),
            ("视频拼接", "concat"),
            ("退出", "exit"),
        ]
        for i, (desc, _) in enumerate(options, 1):
            print(f"  {i}. {desc}")
        choice = input("请输入数字: ").strip()
        if not choice.isdigit() or int(choice) > len(options):
            print("无效选择")
            continue
        idx = int(choice) - 1
        cmd = options[idx][1]
        if cmd == "exit":
            break

        args = _InteractiveArgs()
        args.verbose = True  # 交互模式默认显示编码进度
        val = clean_path(input("输入视频文件路径: "))
        args.input = val
        if not args.input or not Path(args.input).is_file():
            print("文件不存在，重新选择")
            continue

        # 快速预览文件信息，帮助用户做决策
        preview_file(args.input)
        out = input("输出文件 (直接回车使用默认): ").strip()
        if out:
            out = clean_path(out)
            # 纯文件名（无路径分隔符）→ 放到输入文件同目录下
            if os.sep not in out and os.altsep not in out:
                out = str(Path(args.input).parent / out)
        args.output = out if out else None

        if cmd == "info":
            cmd_info(args)
        elif cmd == "trim":
            args.start = input("起始时间 (如 00:01:20 或 0): ").strip() or "0"
            args.end = input("结束时间 (直接回车到结尾): ").strip() or None
            args.accurate = input("精确裁剪？(y/N): ").lower() == "y"
            cmd_trim(args)
        elif cmd == "convert":
            args.format = input("目标格式 (mp4/webm/mkv/mov/avi/gif): ").strip().lower()
            if input("使用 GPU 加速？(y/N): ").strip().lower() == "y":
                args.gpu = True
            cmd_convert(args)
        elif cmd == "resize":
            # 检测当前分辨率，智能建议缩放目标
            try:
                probe = json.loads(subprocess.run(
                    ["ffprobe", "-v", "quiet", "-print_format", "json",
                     "-show_streams", "-select_streams", "v:0", args.input],
                    capture_output=True, text=True,
                ).stdout)
                streams = probe.get("streams", [])
                if streams:
                    cw, ch = streams[0].get("width", 0), streams[0].get("height", 0)
                    print(f"  当前分辨率: {cw}x{ch}")
                    if ch >= 2160:
                        print(f"  建议: 1080p / 720p")
                    elif ch >= 1080:
                        print(f"  建议: 720p / 480p")
                    elif ch >= 720:
                        print(f"  建议: 480p / 360p")
            except Exception:
                pass
            args.size = input("分辨率 (720p/1080p/4k 或 1280:720): ").strip()
            if input("使用 GPU 加速？(y/N): ").strip().lower() == "y":
                args.gpu = True
            cmd_resize(args)
        elif cmd == "rotate":
            deg = input("旋转角度 (90/180/270): ").strip()
            args.degrees = int(deg) if deg.isdigit() else 90
            cmd_rotate(args)
        elif cmd == "speed":
            speed_str = input("速度倍数 (0.5=半速, 2.0=两倍): ").strip() or "1"
            try:
                args.factor = float(speed_str)
            except ValueError:
                print("请输入有效数字")
                continue
            if args.factor <= 0:
                print("速度倍率必须大于 0")
                continue
            cmd_speed(args)
        elif cmd == "extract-audio":
            args.format = input("音频格式 (mp3/aac/flac/wav/opus): ").strip().lower() or "mp3"
            cmd_extract_audio(args)
        elif cmd == "mute":
            cmd_mute(args)
        elif cmd == "compress":
            method = input("按目标大小(mb) 还是 画质(crf)？输入 mb/crf: ").strip().lower()
            if method == "mb":
                mb_str = input("目标大小(MB): ").strip()
                try:
                    args.target_mb = float(mb_str)
                except ValueError:
                    print("请输入有效数字")
                    continue
                args.crf = None
            else:
                crf_str = input(f"CRF值(18-35, 默认{COMPRESS_CRF}): ").strip() or str(COMPRESS_CRF)
                try:
                    args.crf = int(crf_str)
                except ValueError:
                    print("请输入有效整数")
                    continue
                args.target_mb = None
            if input("使用 GPU 加速？(y/N): ").strip().lower() == "y":
                args.gpu = True
            cmd_compress(args)
        elif cmd == "screenshot":
            args.time = input("截图时间点 (如 00:01:23): ").strip() or "00:00:01"
            cmd_screenshot(args)
        elif cmd == "thumbnail":
            count_str = input(f"缩略图数量 (默认{THUMB_DEFAULT_COUNT}): ").strip() or str(THUMB_DEFAULT_COUNT)
            try:
                args.count = int(count_str)
            except ValueError:
                print("请输入有效整数")
                continue
            cmd_thumbnail(args)
        elif cmd == "gif":
            args.start = input("起始时间 (可选): ").strip() or None
            args.duration = input("持续秒数 (可选): ").strip() or None
            fps_str = input(f"帧率 (默认{GIF_DEFAULT_FPS}): ").strip() or str(GIF_DEFAULT_FPS)
            width_str = input(f"宽度 (默认{GIF_DEFAULT_WIDTH}): ").strip() or str(GIF_DEFAULT_WIDTH)
            try:
                args.fps = int(fps_str)
                args.width = int(width_str)
            except ValueError:
                print("请输入有效整数")
                continue
            cmd_gif(args)
        elif cmd == "watermark-text":
            args.text = input("水印文字: ").strip()
            if not args.text:
                print("水印文字不能为空")
                continue
            args.position = input(f"位置 (topleft/topright/bottomleft/bottomright/center, 默认{WM_DEFAULT_POSITION}): ").strip() or WM_DEFAULT_POSITION
            args.color = input(f"颜色 (默认{WM_DEFAULT_COLOR}): ").strip() or WM_DEFAULT_COLOR
            args.size = int(input(f"字号 (默认{WM_DEFAULT_FONT_SIZE}): ").strip() or str(WM_DEFAULT_FONT_SIZE))
            args.font = input(f"字体路径 (默认{FONT_FILE}): ").strip() or FONT_FILE
            cmd_watermark_text(args)
        elif cmd == "watermark-image":
            args.image = clean_path(input("水印图片路径: "))
            args.position = input(f"位置 (默认{WM_DEFAULT_POSITION}): ").strip() or WM_DEFAULT_POSITION
            args.scale = int(input(f"水印宽度px (默认{WM_IMAGE_DEFAULT_SCALE}): ").strip() or str(WM_IMAGE_DEFAULT_SCALE))
            cmd_watermark_image(args)
        elif cmd == "watermark-tile":
            args.text = input("水印文字: ").strip()
            if not args.text:
                print("水印文字不能为空")
                continue
            args.color = input(f"颜色 (默认{TILE_DEFAULT_COLOR}): ").strip() or TILE_DEFAULT_COLOR
            args.size = int(input(f"字号 (默认{TILE_DEFAULT_FONT_SIZE}): ").strip() or str(TILE_DEFAULT_FONT_SIZE))
            args.font = input(f"字体路径 (默认{FONT_FILE}): ").strip() or FONT_FILE
            cw = input(f"单元格宽度px (默认{TILE_DEFAULT_CELL_W}): ").strip()
            ch = input(f"单元格高度px (默认{TILE_DEFAULT_CELL_H}): ").strip()
            args.cell_w = int(cw) if cw.isdigit() else TILE_DEFAULT_CELL_W
            args.cell_h = int(ch) if ch.isdigit() else TILE_DEFAULT_CELL_H
            cmd_watermark_tile(args)
        elif cmd == "replace-audio":
            args.audio = clean_path(input("替换音频文件路径: "))
            cmd_replace_audio(args)
        elif cmd == "thumbnail-grid":
            cols = input(f"列数 (默认{THUMB_DEFAULT_COLS}): ").strip()
            rows = input(f"行数 (默认{THUMB_DEFAULT_ROWS}): ").strip()
            sc = input(f"每格宽度px (默认{THUMB_CELL_WIDTH}): ").strip()
            args.columns = int(cols) if cols.isdigit() else THUMB_DEFAULT_COLS
            args.rows = int(rows) if rows.isdigit() else THUMB_DEFAULT_ROWS
            args.scale = int(sc) if sc.isdigit() else THUMB_CELL_WIDTH
            cmd_thumbnail_grid(args)
        elif cmd == "volume":
            db_str = input("分贝值 (如 -10 减半, +6 翻倍): ").strip()
            try:
                args.db = float(db_str) if db_str else 0.0
            except ValueError:
                print("请输入有效数字")
                continue
            cmd_volume(args)
        elif cmd == "crop":
            args.geometry = input("裁切参数 w:h:x:y (如 640:480:0:0): ").strip() or "640:480:0:0"
            cmd_crop(args)
        elif cmd == "fps":
            rate_str = input("目标帧率 (如 24): ").strip()
            try:
                args.rate = float(rate_str) if rate_str else 24.0
            except ValueError:
                print("请输入有效数字")
                continue
            if args.rate <= 0:
                print("帧率必须大于 0")
                continue
            cmd_fps(args)
        elif cmd == "filter":
            args.filter_string = input("滤镜字符串 (如 eq=brightness=0.05): ").strip()
            if not args.filter_string:
                print("滤镜不能为空")
                continue
            cmd_filter(args)
        elif cmd == "subtitle-extract":
            idx_str = input("字幕流索引 (默认0): ").strip()
            args.index = int(idx_str) if idx_str.isdigit() else 0
            args.format = input("输出格式 (srt/ass/ssa, 默认srt): ").strip().lower() or "srt"
            cmd_subtitle_extract(args)
        elif cmd == "subtitle-burn":
            args.sub_file = clean_path(input("字幕文件路径: "))
            if not args.sub_file or not Path(args.sub_file).is_file():
                print("字幕文件不存在")
                continue
            cmd_subtitle_burn(args)
        elif cmd == "subtitle-add":
            args.sub_file = clean_path(input("字幕文件路径: "))
            if not args.sub_file or not Path(args.sub_file).is_file():
                print("字幕文件不存在")
                continue
            cmd_subtitle_add(args)
        elif cmd == "overlay-video":
            args.overlay = clean_path(input("画中画视频路径: "))
            if not args.overlay or not Path(args.overlay).is_file():
                print("画中画文件不存在")
                continue
            args.position = input(f"位置 (topleft/topright/bottomleft/bottomright/center, 默认{WM_DEFAULT_POSITION}): ").strip() or WM_DEFAULT_POSITION
            sc = input(f"画中画宽度px (默认{PIP_DEFAULT_SCALE}): ").strip()
            args.scale = int(sc) if sc.isdigit() else PIP_DEFAULT_SCALE
            cmd_overlay_video(args)
        elif cmd == "concat":
            files_str = input("要拼接的文件 (用空格分隔): ").strip()
            args.files = files_str.split()
            if len(args.files) < 2:
                print("至少需要 2 个文件")
                continue
            cmd_concat(args)

        print("\n处理完成！")

if __name__ == "__main__":
    main()
