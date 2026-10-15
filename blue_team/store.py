"""
Blue run store — the host-side data layer that lets the atomic tools CHAIN BY REFERENCE.

Every tool that produces rows (sample / map_sample / grade / monitor) writes them here and returns a
short id; every tool that consumes rows (grade / analyze / fetch / monitor) takes that id. So a
100-item x 2-condition sweep never round-trips 200 completions through the agent's context: the agent
passes `set_0003`, not the payload. Two id kinds:

  conv_NNNN  an immutable conversation transcript (messages incl. the assistant reply). Each `sample`
             completion mints a NEW conv id, so branching a conversation is free and history is
             authentic (the agent continues from an id rather than re-typing turns).
  set_NNNN   a set of ROWS (one per completion): handle, condition, item, messages, completion,
             reasoning, answer/tests, grade, monitor verdict. `grade`/`monitor` annotate rows in place.
  act_NNNN / probe_NNNN / dir_NNNN   white-box artifacts (fp16 activations / fitted probes / steering
             directions) under store/acts/; the agent gets ids + summaries, never the tensors.

Layout (inside the run folder, deliberately AGENT-READABLE — its own Python may read the JSONL too):
  <run>/store/index.json        {id: {kind, tool, created, n_rows, parents, note}}
  <run>/store/<set_id>.jsonl    one JSON row per line
  <run>/store/<conv_id>.json    {"messages": [...], "handle": ..., "constructed": bool}

The store holds NO endpoint / served-name / secret — rows carry only the blinded handle.
"""
from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path


class RunStore:
    def __init__(self, run_dir: str | Path):
        self.dir = Path(run_dir) / "store"
        self.dir.mkdir(parents=True, exist_ok=True)
        self._index_path = self.dir / "index.json"
        self._lock = asyncio.Lock()
        self._counter = {"conv": 0, "set": 0, "act": 0, "probe": 0, "dir": 0}
        (self.dir / "acts").mkdir(exist_ok=True)
        if self._index_path.exists():
            idx = self._read_index()
            for k in idx:
                kind, _, num = k.partition("_")
                if kind in self._counter and num.isdigit():
                    self._counter[kind] = max(self._counter[kind], int(num))

    # ── index ─────────────────────────────────────────────────────────────────────────────────
    def _read_index(self) -> dict:
        try:
            return json.loads(self._index_path.read_text() or "{}")
        except Exception:
            return {}

    def _write_index(self, idx: dict) -> None:
        tmp = self._index_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(idx, indent=1))
        tmp.replace(self._index_path)

    def _new_id(self, kind: str) -> str:
        self._counter[kind] += 1
        return f"{kind}_{self._counter[kind]:04d}"

    def _register(self, id_: str, **meta) -> None:
        idx = self._read_index()
        idx[id_] = {"created": time.time(), **meta}
        self._write_index(idx)

    def info(self, id_: str) -> dict | None:
        return self._read_index().get(id_)

    def exists(self, id_: str) -> bool:
        return id_ in self._read_index()

    def list_ids(self, kind: str | None = None) -> list[dict]:
        idx = self._read_index()
        out = []
        for k, v in idx.items():
            if kind and not k.startswith(kind + "_"):
                continue
            out.append({"id": k, **{kk: vv for kk, vv in v.items() if kk != "created"}})
        return out

    # ── conversations ─────────────────────────────────────────────────────────────────────────
    async def new_conv(self, handle: str, messages: list[dict], *, constructed: bool = False,
                       parent: str | None = None) -> str:
        async with self._lock:
            cid = self._new_id("conv")
            (self.dir / f"{cid}.json").write_text(json.dumps(
                {"handle": handle, "messages": messages, "constructed": constructed, "parent": parent},
                ensure_ascii=False))
            self._register(cid, kind="conv", tool="sample", handle=handle, n_turns=len(messages),
                           parents=[parent] if parent else [], constructed=constructed)
            return cid

    def get_conv(self, conv_id: str) -> dict | None:
        p = self.dir / f"{conv_id}.json"
        if not p.exists():
            return None
        return json.loads(p.read_text())

    # ── row sets ──────────────────────────────────────────────────────────────────────────────
    async def new_set(self, rows: list[dict], *, tool: str, parents: list[str] | None = None,
                      note: str | None = None, extra: dict | None = None) -> str:
        async with self._lock:
            sid = self._new_id("set")
            for i, r in enumerate(rows):
                r.setdefault("row", i)
                r["set_id"] = sid
            with open(self.dir / f"{sid}.jsonl", "w") as f:
                for r in rows:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
            self._register(sid, kind="set", tool=tool, n_rows=len(rows), parents=parents or [],
                           note=note, **(extra or {}))
            return sid

    def get_rows(self, set_id: str) -> list[dict] | None:
        p = self.dir / f"{set_id}.jsonl"
        if not p.exists():
            return None
        rows = []
        with open(p) as f:
            for line in f:
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
        return rows

    async def update_rows(self, set_id: str, rows: list[dict], *, note_update: dict | None = None) -> None:
        """Rewrite a set's rows in place (used by grade/monitor to annotate). Same id, same order."""
        async with self._lock:
            with open(self.dir / f"{set_id}.jsonl", "w") as f:
                for r in rows:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
            if note_update:
                idx = self._read_index()
                if set_id in idx:
                    idx[set_id].update(note_update)
                    self._write_index(idx)


    # ── white-box artifacts (activations / probes / directions) ───────────────────────────────
    async def new_artifact(self, kind: str, *, arr=None, payload: dict | None = None, meta: dict | None = None,
                           tool: str = "", parents: list[str] | None = None) -> str:
        """kind in {'act','probe','dir'}. `arr` (numpy) is saved as fp16 .npy under store/acts/; `payload`
        (JSON) is saved next to it. The agent only ever receives the id + `meta` (shapes/summaries)."""
        assert kind in ("act", "probe", "dir")
        async with self._lock:
            aid = self._new_id(kind)
            base = self.dir / "acts" / aid
            if arr is not None:
                import numpy as _np
                _np.save(str(base) + ".npy", _np.asarray(arr, dtype=_np.float16))
            if payload is not None:
                (self.dir / "acts" / f"{aid}.json").write_text(json.dumps(payload))
            self._register(aid, kind=kind, tool=tool, parents=parents or [], **(meta or {}))
            return aid

    def get_artifact(self, aid: str):
        """-> (arr float32 | None, payload dict | None, index meta | None)."""
        base = self.dir / "acts" / aid
        arr = payload = None
        if (base.with_suffix(".npy")).exists():
            import numpy as _np
            arr = _np.load(str(base) + ".npy").astype(_np.float32)
        if (base.with_suffix(".json")).exists():
            payload = json.loads(base.with_suffix(".json").read_text())
        return arr, payload, self.info(aid)


def summarize_rows(rows: list[dict]) -> dict:
    """Compact shape summary of a set (for tool returns): counts by handle/condition, graded/errored."""
    from collections import Counter
    by_handle = Counter(r.get("handle") for r in rows)
    by_cond = Counter(r.get("condition") for r in rows)
    graded = sum(1 for r in rows if r.get("correct") is not None)
    errs = sum(1 for r in rows if r.get("gen_error"))
    return {"n_rows": len(rows), "by_handle": dict(by_handle), "by_condition": dict(by_cond),
            "n_graded": graded, "n_generation_errors": errs}
