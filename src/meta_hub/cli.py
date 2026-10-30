"""meta-hub CLI."""
from __future__ import annotations
import argparse
import sys
import time
from .agent.context import ContextAssembler
from .agent.gatekeeper import Gatekeeper
from .agent.llm import LLMClient, ToolCall
from .agent.metronome import Metronome
from .character import CharacterMemory, CharacterRuntime
from pathlib import Path

from .config import settings
from .events import Event
from .ingress.base import ReconnectingIngress, TcpJsonAdapter
from .live import LiveAgent
from .motion.player import VmcMotionPlayer
from .motion.choreography import default_program, parse_dance
from .motion.primitives import DEFAULT_DURATION, GESTURES
from .pipeline import say, animate, turn
from .speaker import PlayerSpeaker
from .stages.speech import SpeechError
from .timeline import TimelineCompiler, TimelineExecutor


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

    p_demo = sub.add_parser("demo", help="one utterance: TTS + A2F face + gesture + expression -> VMC")
    p_demo.add_argument("text")
    from .motion.primitives import GESTURES
    p_demo.add_argument("--gesture", default="nod", choices=sorted(GESTURES))
    p_demo.add_argument("--expression", default="joy")
    p_demo.add_argument("--no-audio", action="store_true")
    p_demo.add_argument("--no-vmc", action="store_true")
    p_live = sub.add_parser("live", help="real loop: ingress -> gatekeeper -> LLM -> timeline -> VMC")
    p_live.add_argument("--seconds", type=float, default=0.0, help="stop after N seconds (0 = forever)")
    p_live.add_argument("--ingress-port", type=int, default=settings.ingress_port)
    p_live.add_argument("--character", default=settings.character)
    p_live.add_argument("--model", default=settings.llm_model,
                        help="default: the model this Pi agent is using")
    p_live.add_argument("--base-url", default="")
    p_live.add_argument("--api-key", default="")
    p_live.add_argument("--llm-timeout", type=float, default=120.0)
    p_live.add_argument("--tick", type=float, default=0.5)
    p_live.add_argument("--no-vmc", action="store_true")
    p_dance = sub.add_parser("dance", help="play a multi-count choreography")
    p_dance.add_argument("--bpm", type=float, default=120.0)
    p_dance.add_argument("--seconds", type=float, default=12.0)
    p_dance.add_argument("--program", default="", help="JSON program file")
    p_dance.add_argument("--expression", default="joy")
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
        elif args.cmd == "demo":
            player = VmcMotionPlayer.from_settings()
            speaker = PlayerSpeaker(player, play_audio=not args.no_audio, verbose=True)
            executor = TimelineExecutor(speaker, player, player)
            calls = [
                ToolCall("set_expression", {"name": args.expression, "weight": 1.0}),
                ToolCall("gesture", {"name": args.gesture, "intensity": 0.8,
                                     "duration": DEFAULT_DURATION[args.gesture]}),
                ToolCall("speak", {"text": args.text}),
            ]
            try:
                if not args.no_vmc:
                    player.start()
                result = executor.play(TimelineCompiler().compile(calls))
                print(f"demo done: {result.played_seconds:.2f}s | "
                      f"completed={result.completed}")
            finally:
                player.close()
        elif args.cmd == "live":
            if args.model:
                model, base_url, api_key = args.model, args.base_url, args.api_key
            else:
                from .agent.pi import load_pi_llm
                pi = load_pi_llm()
                model, base_url, api_key = pi.model, pi.base_url, pi.api_key
            print(f"[live] model={model} base={base_url or '(default)'}", flush=True)
            runtime = None
            if args.character:
                runtime = CharacterRuntime.from_directory(args.character, settings.characters_dir)
                activation = runtime.activate_selected()
                persona = activation.persona
                greeting = activation.greeting
                topics = activation.topics
            else:
                persona = "你是一名抖音直播数字人主播，语气自然、简短、有互动感。"
                greeting, topics = "", []
            assembler = ContextAssembler(persona, greeting=greeting, topics=topics)
            memory = CharacterMemory() if runtime is not None else None
            llm = LLMClient(base_url, api_key, model, timeout=args.llm_timeout)
            player = VmcMotionPlayer.from_settings()
            speaker = PlayerSpeaker(player, play_audio=settings.audio_enabled, verbose=True)
            executor = TimelineExecutor(speaker, player, player)
            agent = LiveAgent(Gatekeeper(), Metronome(interval=1.0), assembler, llm,
                              executor, memory=memory)
            ingress = ReconnectingIngress(
                TcpJsonAdapter(settings.ingress_host, args.ingress_port))
            import threading
            stop = threading.Event()

            def loop() -> None:
                for event in ingress.stream():
                    if stop.is_set():
                        break
                    agent.submit(event)

            threading.Thread(target=loop, name="ingress", daemon=True).start()
            if not args.no_vmc:
                player.start()
            started = time.monotonic()
            try:
                while not stop.is_set():
                    if args.seconds and time.monotonic() - started >= args.seconds:
                        break
                    result = agent.step()
                    if result.action not in ("idle", "denied"):
                        extra = f" error={result.error}" if result.error else ""
                        print(f"[live] {result.action} | state={agent.metronome.state.value} "
                              f"| pending={len(agent.pending)}{extra}", flush=True)
                    time.sleep(args.tick)
            except KeyboardInterrupt:
                pass
            finally:
                stop.set()
                ingress.stop()
                player.close()
        elif args.cmd == "dance":
            if args.program:
                import json
                program = parse_dance(
                    json.loads(Path(args.program).read_text(encoding="utf-8")))
            else:
                program = default_program(args.bpm)
            player = VmcMotionPlayer.from_settings()
            player.set(args.expression, 1.0)
            player.play_dance(program)
            try:
                player.start()
                print(f"dancing {program.name or 'program'}: "
                      f"{program.total_beats:.0f} beats, {program.duration:.2f}s, "
                      f"loop={program.loop}", flush=True)
                time.sleep(max(0.1, args.seconds))
            except KeyboardInterrupt:
                pass
            finally:
                player.close()
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
