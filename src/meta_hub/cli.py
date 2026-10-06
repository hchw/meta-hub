"""meta-hub CLI."""
from __future__ import annotations
import argparse
import sys
from .pipeline import say, animate, turn
from .stages.speech import SpeechError
from .config import settings


def _build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="meta-hub")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_say = sub.add_parser("say", help="text -> wav (CosyVoice)")
    p_say.add_argument("text")
    p_say.add_argument("--out", default=None)

    p_an = sub.add_parser("animate", help="wav -> VMC (Audio2Face-3D)")
    p_an.add_argument("wav")
    p_an.add_argument("--fps", type=float, default=None)
    p_an.add_argument("--no-vmc", action="store_true")
    p_an.add_argument("--no-reset", action="store_true", help="do not return face to neutral at end")

    p_t = sub.add_parser("turn", help="text -> wav -> VMC")
    p_t.add_argument("text")
    p_t.add_argument("--out", default=None)
    p_t.add_argument("--no-vmc", action="store_true")
    p_t.add_argument("--no-reset", action="store_true")
    p_t.add_argument("--no-audio", action="store_true", help="do not play audio on the Windows side")

    p_meas = sub.add_parser("measure", help="sample GPU load over a window (task 4.3)")
    p_meas.add_argument("--seconds", type=float, default=20.0)
    p_meas.add_argument("--out", default=None)
    return ap


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        if args.cmd == "say":
            out = say(args.text, args.out)
            print("wav:", out) if out else print("say: (no content)")
        elif args.cmd == "animate":
            r = animate(args.wav, args.fps, send_vmc=not args.no_vmc, reset_neutral=not args.no_reset)
            print(f"sent {r['frames']} frames | {r['duration']:.2f}s | max_lag {r['max_lag_ms']:.1f}ms "
                  f"-> {settings.vmc_host}:{settings.vmc_port}")
        elif args.cmd == "turn":
            r = turn(args.text, args.out, send_vmc=not args.no_vmc, reset_neutral=not args.no_reset,
                     play_audio=not args.no_audio)
            if r.get("no_content"):
                print("turn: (no content)")
            else:
                tail = " + audio" if r.get("audio_played") else ""
                print(f"turn done: {r['frames']} frames | {r['duration']:.2f}s | max_lag {r['max_lag_ms']:.1f}ms "
                      f"-> {settings.vmc_host}:{settings.vmc_port}{tail}")
        elif args.cmd == "measure":
            from .measure import report
            text = report(args.seconds)
            if args.out:
                with open(args.out, "w") as fh:
                    fh.write(text + "\n")
            print(text)
    except SpeechError as e:
        # Distinguishable error; the caller keeps running (failure isolation).
        print(f"speech error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
