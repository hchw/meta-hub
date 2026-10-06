#!/usr/bin/env python3
"""Run inside the CosyVoice venv: text -> wav (zero-shot)."""
import argparse, os, sys


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--text", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--prompt-wav", required=True)
    ap.add_argument("--prompt-text", default="希望你以后能够做的比我还好呦。")
    ap.add_argument("--model", default="pretrained_models/CosyVoice2-0.5B")
    args = ap.parse_args()

    sys.path.append("third_party/Matcha-TTS")
    sys.path.append(os.getcwd())
    from cosyvoice.cli.cosyvoice import AutoModel
    import torchaudio

    cosy = AutoModel(model_dir=args.model)
    for _, j in enumerate(cosy.inference_zero_shot(args.text, args.prompt_text,
                                                   args.prompt_wav, stream=False)):
        torchaudio.save(args.out, j["tts_speech"], cosy.sample_rate)
        break
    print("ok", args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
