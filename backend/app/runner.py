"""Runs user code in a throw-away temp directory with a timeout and output cap.

SECURITY: this executes arbitrary code on the machine running the backend.
Fine for local use. If you deploy publicly, run the backend inside a locked-down
container (no network, read-only FS) or set ENABLE_CODE_EXECUTION=false.
"""
import asyncio
import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass

from .config import settings
from .errors import AppError

MAX_OUTPUT_BYTES = 64_000

_SQL_WRAPPER = '''
import sqlite3, sys
con = sqlite3.connect(":memory:")
script = open("main.sql", encoding="utf-8").read()
cur = con.cursor()
def split(script):
    buf = ""
    for piece in script.split(";"):
        buf += piece + ";"
        if sqlite3.complete_statement(buf):
            yield buf.strip()
            buf = ""
    if buf.strip(";").strip():
        yield buf.strip(";").strip()

for stmt in split(script):
    try:
        cur.execute(stmt)
    except sqlite3.Error as e:
        print(f"SQL error: {e}\\n  in: {stmt[:120]}", file=sys.stderr)
        sys.exit(1)
    if cur.description:
        cols = [d[0] for d in cur.description]
        rows = cur.fetchall()
        widths = [max(len(str(c)), *(len(str(r[i])) for r in rows)) if rows else len(str(c))
                  for i, c in enumerate(cols)]
        print(" | ".join(str(c).ljust(w) for c, w in zip(cols, widths)))
        print("-+-".join("-" * w for w in widths))
        for r in rows:
            print(" | ".join(str(v).ljust(w) for v, w in zip(r, widths)))
        print(f"({len(rows)} row{'s' if len(rows) != 1 else ''})\\n")
con.commit()
'''


@dataclass
class Lang:
    filename: str
    needs: list[str]            # executables that must exist
    compile: list[str] | None   # optional compile step
    run: list[str]              # run step
    limit_memory: bool = True   # RLIMIT_AS breaks JVM / Go, so those turn it off


def _ts_command() -> list[str] | None:
    if shutil.which("tsx"):
        return ["tsx", "main.ts"]
    if shutil.which("ts-node"):
        return ["ts-node", "main.ts"]
    node = shutil.which("node")
    if node:
        try:
            ver = subprocess.run([node, "--version"], capture_output=True, text=True, timeout=5).stdout
            major, minor = (int(x) for x in ver.strip().lstrip("v").split(".")[:2])
            if (major, minor) >= (22, 6):
                return ["node", "--experimental-strip-types", "--no-warnings", "main.ts"]
        except Exception:
            pass
    return None


def _py() -> str:
    return sys.executable or "python"


IS_WIN = os.name == "nt"
EXE = "main.exe" if IS_WIN else "main"


def _langs() -> dict[str, Lang]:
    ts = _ts_command()
    langs = {
        "python": Lang("main.py", [], None, [_py(), "-u", "main.py"]),
        "javascript": Lang("main.js", ["node"], None, ["node", "main.js"], limit_memory=False),
        "bash": Lang("main.sh", ["bash"], None, ["bash", "main.sh"]),
        "c": Lang("main.c", ["gcc"], ["gcc", "main.c", "-o", EXE, "-lm"], [os.path.join(".", EXE)]),
        "cpp": Lang("main.cpp", ["g++"], ["g++", "-std=c++17", "main.cpp", "-o", EXE], [os.path.join(".", EXE)]),
        "go": Lang("main.go", ["go"], None, ["go", "run", "main.go"], limit_memory=False),
        "rust": Lang("main.rs", ["rustc"], ["rustc", "main.rs", "-o", EXE], [os.path.join(".", EXE)]),
        "java": Lang("Main.java", ["java"], None, ["java", "Main.java"], limit_memory=False),
        "sql": Lang("main.sql", [], None, [_py(), "-c", _SQL_WRAPPER]),
        "csharp": Lang("Program.cs", ["dotnet-script"], None, ["dotnet-script", "Program.cs"], limit_memory=False),
    }
    if ts:
        langs["typescript"] = Lang("main.ts", [], None, ts, limit_memory=False)
    return langs


def available_languages() -> list[str]:
    if not settings.enable_code_execution:
        return []
    return [name for name, l in _langs().items() if all(shutil.which(x) for x in l.needs)]


def _limits(limit_memory: bool):
    """Applied in the child process (POSIX only)."""
    def apply():
        import resource
        resource.setrlimit(resource.RLIMIT_CPU, (settings.run_timeout_seconds + 5,) * 2)
        resource.setrlimit(resource.RLIMIT_FSIZE, (20_000_000,) * 2)
        if limit_memory:
            resource.setrlimit(resource.RLIMIT_AS, (1_000_000_000,) * 2)
    return apply if os.name == "posix" else None


def _clip(b: bytes) -> str:
    text = b[:MAX_OUTPUT_BYTES].decode("utf-8", errors="replace")
    return text + "\n…[output truncated]" if len(b) > MAX_OUTPUT_BYTES else text


def _kill_tree(proc: subprocess.Popen) -> None:
    try:
        if IS_WIN:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)
        else:
            os.killpg(proc.pid, 9)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def _clean_env(cwd: str) -> dict:
    """Pass only what's needed. In particular, never leak LLM_API_KEY to user code."""
    env = {"PATH": os.environ.get("PATH", ""), "HOME": cwd, "TMPDIR": cwd, "TEMP": cwd, "TMP": cwd,
           "GOCACHE": os.path.join(cwd, ".gocache"), "GOPATH": os.path.join(cwd, ".gopath"),
           "PYTHONIOENCODING": "utf-8", "LANG": "C.UTF-8"}
    if IS_WIN:
        for k in ("SystemRoot", "SYSTEMDRIVE", "COMSPEC", "PATHEXT", "WINDIR", "USERPROFILE", "LOCALAPPDATA", "APPDATA", "ProgramFiles", "ProgramFiles(x86)"):
            if k in os.environ:
                env[k] = os.environ[k]
    return env


def _exec_sync(cmd: list[str], cwd: str, stdin: bytes, lang: Lang, timeout: float):
    # Resolve the executable to a full path (Windows needs this, and it avoids PATH tricks in cwd).
    if not os.path.dirname(cmd[0]):
        cmd = [shutil.which(cmd[0]) or cmd[0], *cmd[1:]]
    kwargs: dict = {}
    if IS_WIN:
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
    else:
        kwargs["start_new_session"] = True
        kwargs["preexec_fn"] = _limits(lang.limit_memory)
    try:
        proc = subprocess.Popen(cmd, cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, env=_clean_env(cwd), **kwargs)
    except FileNotFoundError:
        raise AppError("RUNTIME_UNAVAILABLE", f"Could not start '{cmd[0]}'. Is it installed and on PATH?", 422)
    try:
        out, err = proc.communicate(stdin, timeout=timeout)
        return proc.returncode, out, err, False
    except subprocess.TimeoutExpired:
        _kill_tree(proc)
        out, err = proc.communicate()
        return -1, out, err, True


async def _exec(cmd: list[str], cwd: str, stdin: bytes, lang: Lang, timeout: float):
    # Run in a worker thread: works with every asyncio event loop (incl. Windows' selector loop).
    return await asyncio.to_thread(_exec_sync, cmd, cwd, stdin, lang, timeout)


async def run_code(language: str, code: str, stdin: str = "") -> dict:
    if not settings.enable_code_execution:
        raise AppError("EXECUTION_DISABLED", "Code execution is disabled on this server.", 403)

    langs = _langs()
    lang = langs.get(language)
    if lang is None:
        raise AppError("UNSUPPORTED_LANGUAGE", f"Running '{language}' is not supported.", 400)
    missing = [x for x in lang.needs if not shutil.which(x)]
    if missing:
        raise AppError("RUNTIME_UNAVAILABLE",
                       f"'{missing[0]}' is not installed on the server, so {language} can't run. "
                       f"Install it and restart the backend.", 422)

    timeout = settings.run_timeout_seconds
    started = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="devstudio-", ignore_cleanup_errors=True) as tmp:
        with open(os.path.join(tmp, lang.filename), "w", encoding="utf-8") as f:
            f.write(code)
        data = stdin.encode("utf-8")

        if lang.compile:
            rc, out, err, timed_out = await _exec(lang.compile, tmp, b"", lang, timeout * 3)
            if rc != 0 or timed_out:
                return {"language": language, "stdout": _clip(out), "stderr": _clip(err) or "Compilation timed out",
                        "exit_code": rc, "timed_out": timed_out, "phase": "compile",
                        "duration_ms": int((time.perf_counter() - started) * 1000)}

        rc, out, err, timed_out = await _exec(lang.run, tmp, data, lang, timeout)

    stderr = _clip(err)
    if timed_out:
        stderr += f"\nTime limit of {timeout:g}s exceeded. The program was stopped."
    return {"language": language, "stdout": _clip(out), "stderr": stderr.strip("\n"),
            "exit_code": rc, "timed_out": timed_out, "phase": "run",
            "duration_ms": int((time.perf_counter() - started) * 1000)}
