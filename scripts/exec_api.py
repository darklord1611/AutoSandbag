"""Remote code-execution API — runs on a Docker-capable host, called by a GPU pod.

WHY THIS EXISTS. RunPod pods are unprivileged containers: no CAP_SYS_ADMIN, all of
mount/user/PID `unshare` blocked (measured on two pods, 2026-08-15), so no container
runtime can ever run there. This host CAN run containers, so the sandbox moves here and
the pod calls it over HTTP.

THE SEAM. shared/code_evals.py:113 and shared/code_exec.py:96 both reduce to one
primitive: run `<python> -c PROGRAM` with optional stdin, get (returncode, stdout,
stderr). That is the entire API. `scripts/remote_python` is a drop-in shim that speaks it,
so the eval code needs no changes: --exec-python /path/to/remote_python.

TWO TIERS, because "one minimal image" is impossible:
  light : python:3.11-slim, ~130MB — HumanEval / MBPP / APPS / LiveCodeBench (stdlib-only,
          per code_evals.py:155).
  bcb   : the canonical BigCodeBench image already named in code_evals.py:33. Multi-GB and
          py3.10 by necessity — setup_code_exec_env.sh:6 explains why its 74 pinned libs
          cannot coexist with py>=3.11. Pulled lazily on first use, never at startup.

SPEED comes from the warm pool plus the transport, not from image size. Measured on this
host (2026-08-15), per trivial program:
    cold `docker run`                      218 ms
    warm container, `docker exec` CLI       81 ms   (the CLI client alone costs 77 ms)
    warm container, Engine API socket       57 ms   <- what this uses
    bare `python -c` on the host            25 ms   (the floor: interpreter startup)
So containers are long-lived and each program is ONE exec over /var/run/docker.sock,
in a fresh mktemp cwd, with periodic recycling so nothing leaks between tasks. This
matters because code_exec.py:62 runs up to 12 executions for a single stdio task.

AUTH IS MANDATORY. On a publicly exposed port this endpoint is remote code execution as a
service. The container is sandboxed; the host is not. No token -> refuses to start.

    EXEC_API_TOKEN=$(openssl rand -hex 32) python3 exec_api.py --port 8000
"""
from __future__ import annotations

import argparse
import http.client
import json
import os
import queue
import secrets
import signal
import socket
import struct
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# Tiers are right-sized images, slimmest first. A benchmark uses the SMALLEST image that
# carries the libs its hidden tests import: stdlib-only work stays on `light`; only
# BigCodeBench needs the multi-GB `bcb`. Add a benchmark with its own dependency set (say
# numpy+pandas only) as a NEW tier, via EXEC_API_TIERS_FILE (below) -- no code edit.
#
# Note on "slim for speed": measured on this host, execution latency (~65ms) and container
# cold-start (~900ms) are BOTH flat across image size -- Docker mounts layers lazily, and an
# unimported library costs nothing at runtime. So image bulk buys only disk + one-time pull;
# the warm pool, not a smaller image, is what makes grading fast. Don't trim an image for
# speed, and never trim the bcb image below BigCodeBench's canonical lib set -- a hidden test
# importing a dropped lib fails as if the model were wrong, silently corrupting an audit.
BUILTIN_TIERS = {
    # `python` is resolved inside the container, so the bcb tier gets its py3.10 automatically.
    "light": {"image": "python:3.11-slim", "python": "python"},
    "bcb": {"image": "ghcr.io/arcadiaimpact/inspect-eval-bigcodebench:latest", "python": "python"},
}
DEFAULT_TIER = "light"


def load_tiers() -> dict:
    """Built-in tiers, optionally extended/overridden by a JSON file at $EXEC_API_TIERS_FILE.

    File shape: {"<name>": {"image": "<ref>", "python": "python3"}, ...}. `python` defaults
    to "python". This is how a new benchmark gets its own right-sized image without touching
    this file -- e.g. {"sci": {"image": "myrepo/sci-slim:1"}} for a numpy/pandas-only bench.
    """
    tiers = {k: dict(v) for k, v in BUILTIN_TIERS.items()}
    path = os.environ.get("EXEC_API_TIERS_FILE", "").strip()
    if path:
        with open(path) as f:
            user = json.load(f)
        if not isinstance(user, dict):
            raise SystemExit(f"{path}: expected a JSON object {{name: {{image,...}}}}")
        for name, cfg in user.items():
            if not isinstance(cfg, dict) or "image" not in cfg:
                raise SystemExit(f"{path}: tier {name!r} needs an object with an 'image'")
            tiers[name] = {"image": cfg["image"], "python": cfg.get("python", "python")}
    return tiers

# Every worker carries this label so a fresh server can reap the warm pool a previous one
# leaked. Graceful shutdown cleans up; a `kill -9` or a crash does not, and those orphans
# would otherwise accumulate forever -- the opposite of a slim host.
LABEL = "com.autosandbag.exec-api"

# Per-container hardening. --network none is what makes an untrusted-code endpoint tolerable;
# everything else bounds a runaway program rather than containing an attacker.
RUN_FLAGS = [
    "--detach", "--rm",
    "--label", LABEL,
    "--network", "none",
    "--memory", "2g",
    "--pids-limit", "256",
    "--cpus", "2.0",
    "--tmpfs", "/scratch:rw,exec,size=512m",
    "--workdir", "/scratch",
]
MAX_EXECS_PER_CONTAINER = 50   # recycle: bounds filesystem leakage between tasks
MAX_TIMEOUT = 120.0
MAX_PROGRAM_BYTES = 4 << 20


DOCKER_SOCK = os.environ.get("DOCKER_SOCK", "/var/run/docker.sock")
ENGINE_API = "/v1.43"

# One program = one exec, in a fresh mktemp cwd. `$0` is the program: `sh -c SCRIPT NAME`
# binds NAME to $0, which keeps the program out of the shell's parsing path entirely --
# no quoting or length games with arbitrary model-written code.
_WRAP = 'd=$(mktemp -d) && cd "$d" && exec "$1" -c "$0"'


def _docker(*args, timeout=None, **kw):
    """The docker CLI -- used ONLY for infrequent lifecycle ops (pull/run/kill/info)."""
    return subprocess.run(["docker", *args], capture_output=True, text=True, timeout=timeout, **kw)


def reap_orphans() -> int:
    """Kill any warm workers a previous server left behind (matched by LABEL)."""
    p = _docker("ps", "-q", "--filter", f"label={LABEL}", timeout=30)
    ids = p.stdout.split()
    if ids:
        _docker("kill", *ids, timeout=60)
    return len(ids)


class _UnixHTTP(http.client.HTTPConnection):
    """http.client over a unix socket -- bypasses the 77ms docker CLI client startup."""

    def __init__(self, timeout=None):
        super().__init__("localhost", timeout=timeout)

    def connect(self):
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        if self.timeout:
            s.settimeout(self.timeout)
        s.connect(DOCKER_SOCK)
        self.sock = s


def _engine(method: str, path: str, body=None, timeout=30):
    c = _UnixHTTP(timeout=timeout)
    try:
        payload = json.dumps(body) if body is not None else None
        c.request(method, ENGINE_API + path, payload,
                  {"Content-Type": "application/json"} if payload else {})
        return json.loads(c.getresponse().read() or b"null")
    finally:
        c.close()


def _demux(raw: bytes) -> tuple[str, str]:
    """Docker's stream framing: 8-byte header [type,0,0,0,len32be] then payload."""
    out, err, i = [], [], 0
    while i + 8 <= len(raw):
        n = struct.unpack(">I", raw[i + 4:i + 8])[0]
        (err if raw[i] == 2 else out).append(raw[i + 8:i + 8 + n])
        i += 8 + n
    return (b"".join(out).decode("utf-8", "replace"), b"".join(err).decode("utf-8", "replace"))


def engine_exec(cid: str, cmd: list[str], stdin: str, timeout: float) -> dict:
    """Run cmd in a live container over the Engine API. Raises TimeoutError past `timeout`."""
    eid = _engine("POST", f"/containers/{cid}/exec",
                  {"AttachStdin": True, "AttachStdout": True, "AttachStderr": True, "Cmd": cmd})["Id"]

    c = _UnixHTTP(timeout=timeout)
    try:
        c.request("POST", f"{ENGINE_API}/exec/{eid}/start",
                  json.dumps({"Detach": False, "Tty": False}),
                  {"Content-Type": "application/json", "Connection": "Upgrade", "Upgrade": "tcp"})
        resp = c.getresponse()
        s = c.sock
        s.settimeout(timeout)
        if stdin:
            s.sendall(stdin.encode())
        try:
            s.shutdown(socket.SHUT_WR)
        except OSError:
            pass
        chunks = []
        while True:
            try:
                b = s.recv(65536)
            except socket.timeout:
                raise TimeoutError
            if not b:
                break
            chunks.append(b)
        resp.close()
    finally:
        c.close()

    out, err = _demux(b"".join(chunks))
    rc = _engine("GET", f"/exec/{eid}/json").get("ExitCode")
    return {"returncode": rc if isinstance(rc, int) else -1,
            "stdout": out, "stderr": err, "timed_out": False}


class Pool:
    """Warm containers for one tier. acquire() -> container id; release() returns or recycles it."""

    def __init__(self, tier: str, image: str, python: str, size: int):
        self.tier, self.image, self.python, self.size = tier, image, python, size
        self._idle: queue.Queue[str] = queue.Queue()
        self._uses: dict[str, int] = {}
        self._lock = threading.Lock()
        self._pulled = False

    def _ensure_image(self):
        with self._lock:
            if self._pulled:
                return
            if _docker("image", "inspect", self.image).returncode != 0:
                print(f"[{self.tier}] pulling {self.image} (first use, may take a while)", flush=True)
                p = _docker("pull", self.image, timeout=3600)
                if p.returncode != 0:
                    raise RuntimeError(f"pull failed for {self.image}: {p.stderr.strip()[:300]}")
            self._pulled = True

    def _start(self) -> str:
        self._ensure_image()
        p = _docker("run", *RUN_FLAGS, self.image, "sleep", "infinity", timeout=180)
        if p.returncode != 0:
            raise RuntimeError(f"container start failed: {p.stderr.strip()[:300]}")
        cid = p.stdout.strip()
        with self._lock:
            self._uses[cid] = 0
        return cid

    def acquire(self) -> str:
        try:
            return self._idle.get_nowait()
        except queue.Empty:
            return self._start()

    def release(self, cid: str, *, broken: bool = False):
        with self._lock:
            n = self._uses.get(cid, 0) + 1
            self._uses[cid] = n
        if broken or n >= MAX_EXECS_PER_CONTAINER or self._idle.qsize() >= self.size:
            self.kill(cid)
        else:
            self._idle.put(cid)

    def kill(self, cid: str):
        with self._lock:
            self._uses.pop(cid, None)
        subprocess.Popen(["docker", "kill", cid],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def shutdown(self):
        while True:
            try:
                self.kill(self._idle.get_nowait())
            except queue.Empty:
                return


POOLS: dict[str, Pool] = {}


def run_program(tier: str, program: str, stdin: str | None, timeout: float) -> dict:
    """One program in a warm container, in a fresh cwd. Mirrors subprocess.run's contract."""
    pool = POOLS[tier]
    try:
        cid = pool.acquire()
    except Exception as e:
        return {"returncode": -1, "stdout": "", "stderr": f"exec-host: {e}", "timed_out": False}

    broken = False
    try:
        return engine_exec(cid, ["sh", "-c", _WRAP, program, pool.python], stdin or "", timeout)
    except TimeoutError:
        # The API stream gave up; the process inside has NOT stopped. Only killing the
        # container reclaims it, so this one is never returned to the pool.
        broken = True
        return {"returncode": -1, "stdout": "", "stderr": "timeout", "timed_out": True}
    except Exception as e:
        broken = True
        return {"returncode": -1, "stdout": "", "stderr": f"exec-host: {e}", "timed_out": False}
    finally:
        pool.release(cid, broken=broken)


class Handler(BaseHTTPRequestHandler):
    server_version = "exec-api/1.0"
    token = ""

    def _send(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authed(self) -> bool:
        got = self.headers.get("Authorization", "")
        got = got[7:] if got.startswith("Bearer ") else self.headers.get("X-Exec-Token", "")
        return secrets.compare_digest(got, self.token)

    def do_GET(self):
        if self.path != "/health":
            return self._send({"error": "not found"}, 404)
        if not self._authed():
            return self._send({"error": "unauthorized"}, 401)
        ok = _docker("info", timeout=30).returncode == 0
        self._send({"ok": ok, "docker": ok,
                    "tiers": {t: {"image": p.image, "idle": p._idle.qsize()} for t, p in POOLS.items()}})

    def do_POST(self):
        if self.path != "/exec":
            return self._send({"error": "not found"}, 404)
        if not self._authed():
            return self._send({"error": "unauthorized"}, 401)
        n = int(self.headers.get("Content-Length") or 0)
        if n > MAX_PROGRAM_BYTES:
            return self._send({"error": "program too large"}, 413)
        try:
            req = json.loads(self.rfile.read(n) or b"{}")
        except json.JSONDecodeError:
            return self._send({"error": "bad json"}, 400)

        program = req.get("program")
        if not isinstance(program, str):
            return self._send({"error": "program (str) required"}, 400)
        tier = req.get("tier") or DEFAULT_TIER
        if tier not in POOLS:
            return self._send({"error": f"unknown tier {tier!r}; have {sorted(POOLS)}"}, 400)
        try:
            timeout = min(float(req.get("timeout") or 6.0), MAX_TIMEOUT)
        except (TypeError, ValueError):
            return self._send({"error": "timeout must be a number"}, 400)
        self._send(run_program(tier, program, req.get("stdin"), timeout))

    def log_message(self, *a):
        pass


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--pool-size", type=int, default=4, help="warm containers kept idle per tier")
    ap.add_argument("--prewarm", default="light",
                    help="comma-separated tiers to start eagerly, or 'all' ('' for none). "
                         "Prewarming pulls the image, so 'all' front-loads the bcb multi-GB pull.")
    args = ap.parse_args()

    token = os.environ.get("EXEC_API_TOKEN", "").strip()
    if not token:
        raise SystemExit("refusing to start: set EXEC_API_TOKEN (this endpoint executes arbitrary code).\n"
                         "  EXEC_API_TOKEN=$(openssl rand -hex 32)")
    Handler.token = token

    if _docker("info", timeout=60).returncode != 0:
        raise SystemExit("refusing to start: no usable Docker daemon on this host.")

    orphans = reap_orphans()
    if orphans:
        print(f"reaped {orphans} orphaned worker(s) from a previous run", flush=True)

    for tier, cfg in load_tiers().items():
        POOLS[tier] = Pool(tier, cfg["image"], cfg["python"], args.pool_size)
    print(f"tiers registered: {', '.join(f'{t}={p.image}' for t, p in POOLS.items())}", flush=True)

    prewarm = list(POOLS) if args.prewarm.strip() == "all" \
        else [t.strip() for t in args.prewarm.split(",") if t.strip()]
    for tier in prewarm:
        if tier in POOLS:
            POOLS[tier].release(POOLS[tier].acquire())
            print(f"[{tier}] prewarmed", flush=True)

    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"exec-api listening on {args.host}:{args.port} | tiers: {sorted(POOLS)}", flush=True)

    # SIGTERM (docker stop, systemd, kill) shuts down as cleanly as Ctrl-C, so warm workers
    # are reaped instead of orphaned. A kill -9 still can't be caught -- that's what the
    # startup reaper above is the backstop for.
    signal.signal(signal.SIGTERM, lambda *_: srv.shutdown())
    server_thread = threading.Thread(target=srv.serve_forever)
    server_thread.start()
    try:
        server_thread.join()
    except KeyboardInterrupt:
        srv.shutdown()
        server_thread.join()
    finally:
        for p in POOLS.values():
            p.shutdown()


if __name__ == "__main__":
    main()
