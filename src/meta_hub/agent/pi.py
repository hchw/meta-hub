"""Read the model configuration used by the local Pi coding agent.

The live loop must use the same model as the running agent in this workspace,
not a separate local Ollama model. This reads Pi's provider config, preferring
the login credential in ``auth.json`` over the seed key.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PiLLMConfig:
    base_url: str
    api_key: str
    model: str
    timeout: float = 120.0


def _read(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def load_pi_llm(agent_dir: str | Path | None = None) -> PiLLMConfig:
    root = Path(agent_dir or os.environ.get("PI_AGENT_DIR", Path.home() / ".pi" / "agent"))
    provider = _read(root / "commandcode.json")
    settings = _read(root / "settings.json")
    auth = _read(root / "auth.json")
    key = (auth.get("commandcode") or {}).get("key") or provider.get("apiKey", "")
    model = (os.environ.get("PI_MODEL") or settings.get("defaultModel")
             or "deepseek/deepseek-v4.1-flash")
    base = (os.environ.get("COMMANDCODE_BASE_URL") or provider.get("baseUrl")
            or "https://api.commandcode.ai/provider/v1")
    if not key:
        raise RuntimeError(f"no commandcode credential under {root}")
    return PiLLMConfig(base_url=base.rstrip("/"), api_key=key, model=model)
