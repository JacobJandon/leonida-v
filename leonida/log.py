"""The install log: every file Leonida V placed or saw change, per step."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

ADD = "add"                    # we placed a new file
REPLACE = "replace"            # we overwrote a file (original kept in backup)
MKDIR = "mkdir"                # we created an empty folder
EXT_ADD = "external-add"       # appeared during a run/guided step
EXT_CHANGE = "external-change" # changed during a run/guided step (backup if it was small enough)
EXT_REMOVE = "external-remove" # removed during a run/guided step (backup if it was small enough)


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class Action:
    op: str
    path: str  # relative to the game folder, POSIX style
    sha256: str | None = None
    backup: str | None = None  # relative to the state folder


@dataclass
class Step:
    id: int
    mod: str
    method: str
    started: str
    finished: str | None = None
    status: str = "running"  # running / done / failed / rolled-back
    actions: list[Action] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def active(self) -> bool:
        return self.status in ("done", "running", "failed")


class InstallLog:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.steps: list[Step] = []
        if self.path.exists():
            data = json.loads(self.path.read_text(encoding="utf-8"))
            for s in data.get("steps", []):
                acts = [Action(**a) for a in s.pop("actions", [])]
                self.steps.append(Step(**s, actions=acts))

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"steps": [asdict(s) for s in self.steps]}, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def new_step(self, mod: str, method: str) -> Step:
        step = Step(id=max((s.id for s in self.steps), default=0) + 1, mod=mod, method=method, started=now())
        self.steps.append(step)
        self.save()
        return step

    def get(self, step_id: int) -> Step:
        for s in self.steps:
            if s.id == step_id:
                return s
        raise KeyError(f"No step {step_id}")

    def active_steps(self) -> list[Step]:
        return [s for s in self.steps if s.active]

    def installed_mods(self) -> set[str]:
        return {s.mod for s in self.steps if s.status == "done"}

    def last_active(self) -> Step | None:
        act = self.active_steps()
        return act[-1] if act else None
