#!/usr/bin/env python3
"""
다운로드 → WAV 변환 → torchaudio 로드 → MusicGen-Melody 스타일 변환 → 결과 저장 파이프라인.

Debian/Ubuntu 사전 설치(필요 시):
  sudo apt-get update
  sudo apt-get install -y ffmpeg
  # pyenv로 Python 3.11 설치가 필요한 경우 setup_lofi_venv.sh 실행

필요 파이썬 패키지:
  uv pip install yt-dlp ffmpeg-python torchaudio git+https://github.com/facebookresearch/audiocraft.git

사용법 예시:
  python lofi_convert_from_url.py "https://www.youtube.com/watch?v=..." \
    --output-dir outputs --style "lofi hip hop with mellow piano and vinyl crackle"

출력:
  outputs/
    - downloaded.mp3 (원본 다운로드 결과, 확장자는 상황에 따라 다를 수 있음)
    - downloaded.wav (ffmpeg 변환 결과)
    - lofi_output.wav (MusicGen 변환 결과)
"""

import argparse
import os
import sys
import subprocess
import tempfile
from pathlib import Path

import yt_dlp

import torchaudio
import torch
from audiocraft.models import MusicGen
from audiocraft.data.audio import audio_write

__version__ = "0.2.0"

def download_audio(url: str, outdir: Path) -> Path:
    outdir.mkdir(parents=True, exist_ok=True)
    # 출력 템플릿에 확장을 포함하지 않거나 %(ext)s를 사용해 이중 확장 방지
    # 최종 결과는 postprocessor에 의해 mp3가 됩니다.
    outtmpl = str(outdir / "downloaded.%(ext)s")
    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": outtmpl,
        "noplaylist": True,
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
            }
        ],
        # ffmpeg 경로를 자동 탐색하도록 기본값 사용. 필요 시 "ffmpeg_location" 지정 가능
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        # extract_info를 사용하면 메타 정보도 획득 가능
        ydl.extract_info(url, download=True)

    # 예상 경로: downloaded.mp3
    candidate = outdir / "downloaded.mp3"
    if candidate.exists():
        return candidate

    # 일부 환경에서 이중 확장으로 생성될 수 있음: downloaded.mp3.mp3
    double = outdir / "downloaded.mp3.mp3"
    if double.exists():
        return double

    # 혹시 다른 확장자가 되었으면 가장 최근 파일을 선택
    matches = sorted(outdir.glob("downloaded.*"), key=lambda p: p.stat().st_mtime, reverse=True)
    if matches:
        return matches[0]

    raise FileNotFoundError("yt-dlp output not found under 'downloaded.*'")


def ffmpeg_to_wav(src_path: Path, dst_path: Path, sample_rate: int = 32000) -> Path:
    dst_path.parent.mkdir(parents=True, exist_ok=True)
    # -y: overwrite, -ac 1: mono, -ar: sample rate
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(src_path),
        "-ac",
        "1",
        "-ar",
        str(sample_rate),
        str(dst_path),
    ]
    subprocess.run(cmd, check=True)
    return dst_path


def load_audio_torchaudio(wav_path: Path):
    wav, sr = torchaudio.load(str(wav_path))
    return wav, sr

def run_musicgen_melody(style_text: str, melody_wav, melody_sr: int, duration: int = 30):
    """MusicGen-Melody로 스타일 변환. CUDA가 가능하면 자동 사용."""
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"[INFO] Using device: {device}")
    model = MusicGen.get_pretrained("facebook/musicgen-melody")
    try:
        model = model.to(device)
    except Exception:
        pass  # 일부 버전은 to() 미지원일 수 있음
    model.set_generation_params(duration=duration)
    descriptions = [f"{style_text}, keep original melody and chord progression"]
    # 배치 차원 확장 [B, C, T]
    melody_wav = melody_wav.to(device)
    wav_outputs = model.generate_with_chroma(
        descriptions,
        melody_wav[None].expand(len(descriptions), -1, -1),
        melody_sr,
    )
    return wav_outputs[0].cpu(), model.sample_rate


def split_audio_segments(src_path: Path, segment_time: int, outdir: Path) -> list[Path]:
    """원본 WAV를 segment_time(초) 단위로 분할"""
    outdir.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y", "-i", str(src_path),
        "-f", "segment",
        "-segment_time", str(segment_time),
        "-c", "copy",
        str(outdir / "part_%03d.wav")
    ]
    subprocess.run(cmd, check=True)
    return sorted(outdir.glob("part_*.wav"))

def concat_segments(segment_paths: list[Path], output_path: Path):
    """분할된 WAV 파일들을 순서대로 합치기"""
    list_file = output_path.parent / "segments.txt"
    with open(list_file, "w") as f:
        for seg in segment_paths:
            f.write(f"file '{seg.resolve()}'\n")
    cmd = [
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", str(list_file),
        "-c", "copy", str(output_path)
    ]
    subprocess.run(cmd, check=True)

def process_segments_with_musicgen(style_text: str, segment_paths: list[Path], outdir: Path) -> list[Path]:
    """각 구간을 MusicGen으로 변환 (CUDA/GPU 지원)"""
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"[INFO] Using device: {device}")
    model = MusicGen.get_pretrained("facebook/musicgen-melody")
    try:
        model = model.to(device)
    except Exception:
        pass
    out_paths = []
    for seg in segment_paths:
        melody, sr = torchaudio.load(str(seg))
        melody = melody.to(device)
        model.set_generation_params(duration=int(melody.shape[1] / sr))
        descriptions = [f"{style_text}, keep original melody and chord progression"]
        wav_outputs = model.generate_with_chroma(
            descriptions,
            melody[None].expand(len(descriptions), -1, -1),
            sr,
        )
        out_path = outdir / f"lofi_{seg.name}"
        audio_write(out_path.with_suffix(""), wav_outputs[0].cpu(), model.sample_rate, strategy="loudness")
        out_paths.append(out_path)
    return out_paths

def main():
    parser = argparse.ArgumentParser(description="yt-dlp → ffmpeg → MusicGen-Melody (구간 변환) 파이프라인")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("url", help="YouTube URL")
    parser.add_argument("--output-dir", default="outputs", help="출력 디렉터리")
    parser.add_argument("--style", default="lofi hip hop with mellow piano and vinyl crackle", help="스타일 프롬프트")
    parser.add_argument("--segment", type=int, default=30, help="분할 길이(초)")
    parser.add_argument("--duration", type=int, default=8, help="(옵션) MusicGen 생성 길이(초). 세그먼트 모드에서는 자동 설정")
    parser.add_argument("--download-only", action="store_true", help="다운로드까지만 수행")
    args = parser.parse_args()

    outdir = Path(args.output_dir)
    seg_dir = outdir / "segments"
    lofi_seg_dir = outdir / "lofi_segments"

    print("[1/6] 오디오 다운로드...")
    mp3_path = download_audio(args.url, outdir)

    print("[2/6] WAV 변환...")
    wav_src = outdir / "downloaded.wav"
    ffmpeg_to_wav(mp3_path, wav_src, sample_rate=32000)

    if args.download_only:
        print("[INFO] 다운로드 및 변환까지만 완료")
        return

    print("[3/6] 원본 분할...")
    segments = split_audio_segments(wav_src, args.segment, seg_dir)

    print("[4/6] 각 구간 Lofi 변환...")
    lofi_segments = process_segments_with_musicgen(args.style, segments, lofi_seg_dir)

    print("[5/6] 변환 구간 합치기...")
    final_path = outdir / "lofi_full.wav"
    concat_segments(lofi_segments, final_path)

    print(f"[6/6] 완료! 결과: {final_path}")

if __name__ == "__main__":
    main()
