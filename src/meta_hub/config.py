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
    # Resident speech service (design D11). Autostart keeps ``meta-hub say`` working.
    tts_host: str = os.environ.get("META_HUB_TTS_HOST", "127.0.0.1")
    tts_port: int = int(os.environ.get("META_HUB_TTS_PORT", "7712"))
    tts_autostart: bool = os.environ.get("META_HUB_TTS_AUTOSTART", "1") not in ("0", "false", "")
    tts_startup_timeout: float = float(os.environ.get("META_HUB_TTS_STARTUP_TIMEOUT", "180"))
    # LLM (tool-calling, OpenAI-compatible endpoint)
    llm_base_url: str = os.environ.get("META_HUB_LLM_BASE_URL", "http://127.0.0.1:11434/v1")
    llm_api_key: str = os.environ.get("META_HUB_LLM_API_KEY", "")
    llm_model: str = os.environ.get("META_HUB_LLM_MODEL", "")
    # Character + ingress
    character: str = os.environ.get("META_HUB_CHARACTER", "")
    characters_dir: str = os.environ.get("META_HUB_CHARACTERS_DIR", str(REPO_ROOT / "characters"))
    ingress_host: str = os.environ.get("META_HUB_INGRESS_HOST", "127.0.0.1")
    ingress_port: int = int(os.environ.get("META_HUB_INGRESS_PORT", "7711"))
    # Audio2Face-3D NIM
    a2f_target: str = os.environ.get("META_HUB_A2F_TARGET", "localhost:52000")
    a2f_sample_rate: int = 16000
    # VMC sink (any VMC-compatible renderer: VSeeFace, VNyan, Warudo, ...)
    vmc_host: str = os.environ.get("META_HUB_VMC_HOST", "127.0.0.1")
    vmc_port: int = int(os.environ.get("META_HUB_VMC_PORT", "39539"))
    vmc_fps: float = float(os.environ.get("META_HUB_VMC_FPS", "60"))
    vmc_mouth_gain: float = float(os.environ.get("META_HUB_VMC_MOUTH_GAIN", "1.0"))
    # Renderer profile is documentation/debug only; the wire format is VMC.
    vmc_renderer: str = os.environ.get("META_HUB_VMC_RENDERER", "generic")
    # VNyan applies bone data through its VMC receiver; set to 0 if the
    # renderer only consumes blendshapes.
    vmc_bones: bool = os.environ.get("META_HUB_VMC_BONES", "1") not in ("0", "false", "")
    # /VMC/Ext/Bone/Apply is not in the VMC spec. Off by default for stricter
    # receivers such as VNyan; enable only if a renderer needs it.
    vmc_bone_apply: bool = os.environ.get("META_HUB_VMC_BONE_APPLY", "0") not in ("0", "false", "")
    # The current avatar is VRM 1.0, so send VRM1 preset names. Set to
    # "vrm0" for legacy VRM 0.x avatars / strict VMC receivers.
    vmc_blend_profile: str = os.environ.get("META_HUB_VMC_BLEND_PROFILE", "vrm1")
    # Exponential smoothing (seconds). 0 disables; ~0.1 keeps gestures natural.
    vmc_smoothing: float = float(os.environ.get("META_HUB_VMC_SMOOTHING", "0.08"))
    # Some receivers need a root pose before applying bone transforms.
    vmc_root: bool = os.environ.get("META_HUB_VMC_ROOT", "0") not in ("0", "false", "")
    # outputs
    out_dir: str = os.environ.get("META_HUB_OUT_DIR", "/tmp/meta-hub-out")
    # cross-boundary audio: hand the wav to a Windows-side player (design D8)
    audio_win_dir: str = os.environ.get("META_HUB_AUDIO_WIN_DIR", "/mnt/c/Windows/Temp/meta-hub")
    audio_enabled: bool = os.environ.get("META_HUB_AUDIO", "1") not in ("0", "false", "")
    cosy_helper: Path = field(default_factory=lambda: REPO_ROOT / "tools" / "cosy_say.py")


settings = Settings()
