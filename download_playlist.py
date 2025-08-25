import os
import subprocess
import csv
from yt_dlp import YoutubeDL
import librosa

# ===== 0. 카테고리 입력 =====
category = input("카테고리를 입력하세요 (origin / lofi): ").strip().lower()

if category not in ["origin", "lofi"]:
    raise ValueError("카테고리는 'origin' 또는 'lofi'만 가능합니다.")

# ===== 1. 경로 설정 =====
BASE_DIR = f"./data/{category}"
DOWNLOAD_DIR = os.path.join(BASE_DIR, "downloads")
PROCESSED_DIR = os.path.join(BASE_DIR, "processed")
CSV_PATH = os.path.join(BASE_DIR, "metadata.csv")

os.makedirs(DOWNLOAD_DIR, exist_ok=True)
os.makedirs(PROCESSED_DIR, exist_ok=True)

# ===== 2. 유튜브 재생목록 URL =====
PLAYLIST_URL = input("유튜브 재생목록 URL을 입력하세요: ").strip()
MAX_DURATION = 600  # 초 단위 (10분)

# ===== 3. 메타데이터 가져오기 =====
ydl_info_opts = {
    'quiet': True,
    'extract_flat': False,
    'skip_download': True
}

with YoutubeDL(ydl_info_opts) as ydl:
    info = ydl.extract_info(PLAYLIST_URL, download=False)

# ===== 4. 다운로드 옵션 =====
ydl_download_opts = {
    'format': 'bestaudio/best',
    'outtmpl': f'{DOWNLOAD_DIR}/%(title)s.%(ext)s',
    'postprocessors': [{
        'key': 'FFmpegExtractAudio',
        'preferredcodec': 'wav',
        'preferredquality': '192',
    }],
    'ignoreerrors': True,
    'noplaylist': False
}

# ===== 5. 길이 필터링 후 다운로드 =====
with YoutubeDL(ydl_download_opts) as ydl:
    for entry in info.get('entries', []):
        if not entry:
            continue
        duration = entry.get('duration')
        title = entry.get('title', 'Unknown Title')

        if duration and duration > MAX_DURATION:
            print(f"⏩ 건너뜀: {title} ({duration/60:.1f}분)")
            continue

        print(f"⬇ 다운로드: {title} ({duration/60:.1f}분)")
        ydl.download([entry['webpage_url']])

# ===== 6. ffmpeg 전처리 =====
def process_audio(input_path, output_path):
    cmd = [
        'ffmpeg', '-i', input_path,
        '-ar', '32000',  # 샘플레이트
        '-ac', '1',      # 모노
        '-af', 'loudnorm=I=-16:TP=-1.5:LRA=11',
        output_path,
        '-y'
    ]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

# ===== 7. BPM & 키 분석 =====
def analyze_audio(file_path):
    y, sr = librosa.load(file_path, sr=None)
    tempo, _ = librosa.beat.beat_track(y=y, sr=sr)
    chroma = librosa.feature.chroma_stft(y=y, sr=sr)
    key_index = chroma.mean(axis=1).argmax()
    keys = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
    return round(tempo, 2), keys[key_index]

# ===== 8. 전처리 + 분석 + CSV 저장 =====
with open(CSV_PATH, mode='w', newline='', encoding='utf-8') as csvfile:
    writer = csv.writer(csvfile)
    writer.writerow(["파일명", "BPM", "키"])

    for file_name in os.listdir(DOWNLOAD_DIR):
        if file_name.lower().endswith(".wav"):
            input_path = os.path.join(DOWNLOAD_DIR, file_name)
            output_path = os.path.join(PROCESSED_DIR, file_name)

            process_audio(input_path, output_path)
            bpm, key = analyze_audio(output_path)
            writer.writerow([file_name, bpm, key])

print(f"✅ {category} 카테고리 작업 완료! 데이터는 {BASE_DIR} 안에 저장되었습니다.")
