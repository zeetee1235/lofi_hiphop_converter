#!/bin/bash
set -euo pipefail

# Debian/Ubuntu 필수 패키지 설치 (Python 빌드 및 ffmpeg)
if command -v apt-get >/dev/null 2>&1; then
  echo "[INFO] Installing build deps and ffmpeg (requires sudo)..."
  sudo apt-get update -y
  sudo apt-get install -y make build-essential libssl-dev zlib1g-dev \
    libbz2-dev libreadline-dev libsqlite3-dev wget curl llvm \
    libncursesw5-dev xz-utils tk-dev libxml2-dev libxmlsec1-dev \
    libffi-dev liblzma-dev ffmpeg
fi

# Python 3.11 설치 (pyenv 사용)
if ! command -v pyenv &> /dev/null; then
  echo "[INFO] pyenv not found. Installing pyenv..."
  curl https://pyenv.run | bash
  export PATH="$HOME/.pyenv/bin:$PATH"
  eval "$(pyenv init --path)"
  eval "$(pyenv virtualenv-init -)"

  # 로그인/인터랙티브 쉘에서도 pyenv가 동작하도록 ~/.bashrc에 추가 (중복 방지)
  if ! grep -q 'PYENV_ROOT' "$HOME/.bashrc" 2>/dev/null; then
    {
      echo ''
      echo '# pyenv init (auto-added by setup_lofi_venv.sh)'
      echo 'export PYENV_ROOT="$HOME/.pyenv"'
      echo '[[ -d $PYENV_ROOT/bin ]] && export PATH="$PYENV_ROOT/bin:$PATH"'
      echo 'eval "$(pyenv init - bash)"'
      echo 'eval "$(pyenv virtualenv-init -)"'
    } >> "$HOME/.bashrc"
    echo "[INFO] Added pyenv init lines to ~/.bashrc (restart shell to take effect)."
  fi
fi

# pyenv 환경 적용
export PATH="$HOME/.pyenv/bin:$PATH"
eval "$(pyenv init --path)"
eval "$(pyenv virtualenv-init -)"

# Python 3.11 설치
if ! pyenv versions --bare | grep -qx 3.11.9; then
  echo "[INFO] Installing Python 3.11.9..."
  pyenv install 3.11.9
fi

cd "$(dirname "$0")"

# pyenv 가상환경 생성 및 활성화
if ! pyenv virtualenvs --bare | grep -qx lofi-3.11; then
  echo "[INFO] Creating virtualenv lofi-3.11..."
  pyenv virtualenv 3.11.9 lofi-3.11
fi
pyenv local lofi-3.11

# uv 설치
if ! command -v uv &> /dev/null; then
  echo "[INFO] Installing uv..."
  pip install uv
fi

# 패키지 설치
uv pip install --upgrade pip setuptools wheel

# 순서 중요: audiocraft(=torch 버전 고정) 먼저 설치
uv pip install git+https://github.com/facebookresearch/audiocraft.git
uv pip install yt-dlp ffmpeg-python pydub

# 설치된 torch 버전에 맞춰 torchaudio를 설치
TORCH_VER=$(python - <<'PY'
try:
    import torch
    print(torch.__version__.split('+')[0])
except Exception:
    raise SystemExit(1)
PY
)
if [ -n "${TORCH_VER:-}" ]; then
  echo "[INFO] Installing torchaudio==${TORCH_VER} to match torch version"
  uv pip install "torchaudio==${TORCH_VER}" || {
    echo "[WARN] torchaudio==${TORCH_VER} 설치 실패. 호환 가능한 버전을 자동 시도합니다."
    uv pip install torchaudio
  }
else
  echo "[WARN] torch 버전 확인 실패. torchaudio 최신 버전 설치를 시도합니다."
  uv pip install torchaudio
fi

echo "[SUCCESS] Python 3.11, audiocraft, yt-dlp 등 환경 자동 세팅 완료!"
