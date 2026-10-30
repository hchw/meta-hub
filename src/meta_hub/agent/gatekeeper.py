"""Gatekeeper: decide *whether* the model may be asked (design D3, task 3.1/3.5).

The LLM is only consulted when the rules allow it.  The rules are hard limits,
not prompt suggestions: cooldown, silence threshold, speaking budget and event
priority.  Everything is hot-reloadable so tuning during a live session takes
effect immediately.
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any, Callable, Iterable

from ..events import Event


class ConfigError(ValueError):
    pass


@dataclass
class GatekeeperConfig:
    # Proactive behaviour
    proactive_enabled: bool = True
    cooldown_seconds: float = 8.0            # min gap between proactive asks
    silence_threshold_seconds: float = 25.0  # idle time before proactive ask
    # Speaking budget (per rolling window)
    budget_window_seconds: float = 3600.0
    budget_max_speaks: int = 40
    # Event handling
    event_cooldown_seconds: float = 1.5
    min_event_priority: int = 25
    hard_interrupt_gift_value: int = 1000
    # Anti self-excitation (task 3.5)
    silence_multiplier_after_proactive: float = 1.5
    silence_relax_step_after_silence: float = 0.85
    min_silence_seconds: float = 10.0
    max_silence_seconds: float = 120.0

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "GatekeeperConfig":
        known = {f.name for f in fields(cls)}
        unknown = set(data) - known
        if unknown:
            raise ConfigError(f"unknown gatekeeper fields: {sorted(unknown)}")
        cfg = cls()
        for key, value in data.items():
            expected = type(getattr(cfg, key))
            if expected is bool and not isinstance(value, bool):
                raise ConfigError(f"{key} must be a bool")
            if expected is float and isinstance(value, bool):
                raise ConfigError(f"{key} must be a number")
            if expected is int and (isinstance(value, bool) or not isinstance(value, int)):
                raise ConfigError(f"{key} must be an integer")
            if expected is float and not isinstance(value, (int, float)):
                raise ConfigError(f"{key} must be a number")
            setattr(cfg, key, expected(value))
        cfg.validate()
        return cfg

    def validate(self) -> None:
        if self.cooldown_seconds < 0 or self.silence_threshold_seconds < 0:
            raise ConfigError("cooldowns must be >= 0")
        if self.budget_max_speaks < 0 or self.budget_window_seconds <= 0:
            raise ConfigError("budget must be positive")
        if not (0 < self.silence_relax_step_after_silence <= 1):
            raise ConfigError("silence_relax_step_after_silence must be in (0, 1]")
        if self.silence_multiplier_after_proactive < 1:
            raise ConfigError("silence_multiplier_after_proactive must be >= 1")


@dataclass
class Decision:
    allowed: bool
    reason: str
    proactive: bool = False
    hard_interrupt: bool = False
    trigger: list[Event] | None = None
    trigger_reason: str = ""

    def __bool__(self) -> bool:  # convenience: ``if decision:``
        return self.allowed


class Gatekeeper:
    """Rule gate in front of every model call."""

    def __init__(self, config: GatekeeperConfig | None = None,
                 *, clock: Callable[[], float] = time.monotonic) -> None:
        self.config = config or GatekeeperConfig()
        self._clock = clock
        self.last_spoke_at: float | None = None
        self.last_event_spoke_at: float | None = None
        self._window_start = clock()
        self._window_count = 0
        self._effective_silence = self.config.silence_threshold_seconds
        self._consecutive_silence = 0

    # -- configuration ----------------------------------------------------
    def update_config(self, config: GatekeeperConfig | dict[str, Any]) -> None:
        if isinstance(config, dict):
            config = GatekeeperConfig.from_dict(config)
        self.config = config
        self._effective_silence = min(
            self.config.max_silence_seconds,
            max(self.config.min_silence_seconds,
                self.config.silence_threshold_seconds),
        )

    def reload_if_changed(self, path: str | Path,
                          mtime: float | None = None) -> bool:
        """Reload JSON config when the file changed; return whether it did."""
        p = Path(path)
        try:
            changed = mtime if mtime is not None else p.stat().st_mtime
        except OSError:
            return False
        if changed == getattr(self, "_config_mtime", None):
            return False
        data = json.loads(p.read_text(encoding="utf-8"))
        self.update_config(data)
        self._config_mtime = changed
        return True

    # -- budget -----------------------------------------------------------
    def _roll_window(self, now: float) -> None:
        if now - self._window_start >= self.config.budget_window_seconds:
            self._window_start = now
            self._window_count = 0

    @property
    def speaks_in_window(self) -> int:
        self._roll_window(self._clock())
        return self._window_count

    @property
    def effective_silence_threshold(self) -> float:
        return self._effective_silence

    # -- evaluation -------------------------------------------------------
    def evaluate(self, events: Iterable[Event] = (),
                 now: float | None = None) -> Decision:
        now = self._clock() if now is None else now
        self._roll_window(now)
        events = sorted(events, key=lambda e: e.priority, reverse=True)
        hard = [e for e in events
                if e.is_high_value(self.config.hard_interrupt_gift_value)]
        if hard:
            return Decision(True, "hard_interrupt", hard_interrupt=True,
                            trigger=hard, trigger_reason="high_value_gift")

        if self._window_count >= self.config.budget_max_speaks:
            return Decision(False, "budget_exhausted", trigger=list(events))

        candidates = [e for e in events
                      if e.priority >= self.config.min_event_priority]
        if candidates:
            if (self.last_event_spoke_at is not None
                    and now - self.last_event_spoke_at
                    < self.config.event_cooldown_seconds):
                return Decision(False, "event_cooldown", trigger=candidates)
            return Decision(True, "event", proactive=False,
                            trigger=candidates,
                            trigger_reason=candidates[0].kind.value)

        # No actionable event -> maybe proactive, if the rules allow it.
        if not self.config.proactive_enabled:
            return Decision(False, "proactive_disabled")
        if self.last_spoke_at is not None:
            since = now - self.last_spoke_at
            if since < self.config.cooldown_seconds:
                return Decision(False, "cooldown", proactive=True)
            if since < self._effective_silence:
                return Decision(False, "silence_threshold", proactive=True)
        return Decision(True, "proactive", proactive=True,
                        trigger_reason="cold_room")

    # -- feedback ---------------------------------------------------------
    def record_spoken(self, *, proactive: bool,
                      now: float | None = None) -> None:
        now = self._clock() if now is None else now
        self._roll_window(now)
        self._window_count += 1
        self.last_spoke_at = now
        if proactive:
            self._effective_silence = min(
                self.config.max_silence_seconds,
                self._effective_silence
                * self.config.silence_multiplier_after_proactive,
            )
        else:
            self.last_event_spoke_at = now
        self._consecutive_silence = 0

    def record_do_nothing(self, now: float | None = None) -> None:
        """After consecutive silent decisions, become a little more willing."""
        _ = now
        self._consecutive_silence += 1
        self._effective_silence = max(
            self.config.min_silence_seconds,
            self._effective_silence
            * self.config.silence_relax_step_after_silence,
        )

    def snapshot(self) -> dict[str, Any]:
        return {
            "config": asdict(self.config),
            "last_spoke_at": self.last_spoke_at,
            "window_count": self._window_count,
            "effective_silence": self._effective_silence,
            "consecutive_silence": self._consecutive_silence,
        }
