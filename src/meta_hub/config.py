import os
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


@dataclass
class Settings:
    # CosyVoice lives in its own venv (heavy deps); meta-hub drives it out-of-process.
    cosy_repo: str = os.environ.get("META_HUB_COSY_REPO", "/home/hebl/project/dh-services/CosyVoice")
    cosy_python: str = os.environ.get("META_HUB_COSY_PYTHON",
                                      "/home/hebl/project/dh-services/CosyVoice/.venv/bin/python")
    cosy_model: str = os.environ.get("META_HUB_COSY_MODEL", "pretrained_models/CosyVoice2-0.5B")
    # Audio2Face-3D NIM
    a2f_target: str = os.environ.get("META_HUB_A2F_TARGET", "localhost:52000")
    a2f_sample_rate: int = 16000
    # VMC sink (VRM renderer, e.g. VSeeFace)
    vmc_host: str = os.environ.get("META_HUB_VMC_HOST", "127.0.0.1")
    vmc_port: int = int(os.environ.get("META_HUB_VMC_PORT", "39539"))
    vmc_fps: float = float(os.environ.get("META_HUB_VMC_FPS", "60"))
    vmc_mouth_gain: float = float(os.environ.get("META_HUB_VMC_MOUTH_GAIN", "1.0"))
    # outputs
    out_dir: str = os.environ.get("META_HUB_OUT_DIR", "/tmp/meta-hub-out")
    # cross-boundary audio: hand the wav to a Windows-side player (design D8)
    audio_win_dir: str = os.environ.get("META_HUB_AUDIO_WIN_DIR", "/mnt/c/Windows/Temp/meta-hub")
    audio_enabled: bool = os.environ.get("META_HUB_AUDIO", "1") not in ("0", "false", "")
    cosy_helper: Path = field(default_factory=lambda: REPO_ROOT / "tools" / "cosy_say.py")


settings = Settings()
