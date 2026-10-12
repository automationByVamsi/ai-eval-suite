"""`make doctor`: check this machine is ready to run evaluations and say how to fix what isn't.

Checks Python env, env files, judge libraries, certificates and CORTEX; never prints secrets.
"""

from __future__ import annotations

import importlib.metadata
import importlib.util
import os
import sys

from src.core import env, paths, tls  # noqa: F401 — importing env loads env/.env

OK, WARN, FAIL = "OK  ", "WARN", "FAIL"


def run_doctor(ping: bool = True) -> int:
    """Print the readiness report; returns 0 when nothing FAILed, 1 otherwise."""
    problems = 0

    def line(status: str, what: str, detail: str = "") -> None:
        nonlocal problems
        problems += status == FAIL
        print(f"[{status}] {what:<22} {detail}")

    print("\nai-eval-suite doctor\n" + "-" * 72)

    # Pegasus has to be installed into this Python environment.
    line(OK, "python", sys.executable)
    active = os.environ.get("VIRTUAL_ENV", "")
    line(OK if active else WARN, "virtual env",
         active or "none active — make uses the project's .venv (created by make setup)")

    found = [p for p in (paths.ENV_DIR / ".env", paths.ROOT / ".env") if p.is_file()]
    agent_files = sorted(paths.ENV_DIR.glob(".env.*")) if paths.ENV_DIR.is_dir() else []
    agent_files = [p for p in agent_files if p.name != ".env.example"]
    line(OK if found else FAIL, "env files",
         ", ".join(_short(p) for p in found + agent_files)
         or "none — run make setup, then fill in env/.env")

    line(OK if _installed("deepeval") else FAIL, "deepeval", _version("deepeval") or "not installed — run make setup")
    if _installed("pegasus"):
        spec = importlib.util.find_spec("pegasus")
        where = (spec.origin if spec else "") or ""
        line(OK, "pegasus", f"{_version_of_module('pegasus')}  {os.path.dirname(where)}")
    else:
        line(WARN, "pegasus", "not installed in this environment — Pegasus metrics will run on DeepEval.\n"
             "                              Fix: put your SAR token in env/.env (SAR_TOKEN_NAME / "
             "SAR_TOKEN_PASS_CODE), then run make setup.")

    if tls.ca_bundle():
        exists = os.path.isfile(tls.ca_bundle())
        missing = "" if exists else "  (file not found)"
        line(OK if exists else FAIL, "certificates", f"CA_BUNDLE={tls.ca_bundle()}{missing}")
    else:
        line(OK, "certificates", "checked (VERIFY_TLS=true)" if tls.verify_enabled()
             else "not checked (VERIFY_TLS=false — fine behind the office proxy)")

    # api_key mode needs host + id + key; devkit mode needs the package and `make cortex-login`.
    mode = (os.environ.get("CORTEX_AUTH") or "api_key").strip().lower()
    line(OK if mode in ("api_key", "devkit") else FAIL, "CORTEX_AUTH", mode)
    line(OK, "CORTEX_MODEL", os.environ.get("CORTEX_MODEL", "vertex_ai/gemini-2.5-pro (default)"))
    ready = True
    if mode == "devkit":
        has_devkit = _installed("cortex")
        ready = has_devkit
        line(OK if has_devkit else FAIL, "CorteX DevKit",
             "installed (sign in once with: make cortex-login)" if has_devkit
             else "not installed — add the SAR token to env/.env, then make setup")
        if os.environ.get("CORTEX_ENV"):
            line(OK, "CORTEX_ENV", os.environ["CORTEX_ENV"])
    else:
        host = os.environ.get("CORTEX_HOST", "").strip()
        ready = bool(host)
        line(OK if host else FAIL, "CORTEX_HOST", host or "not set in env/.env")
        for name in ("CORTEX_CLIENT_ID", "CORTEX_API_KEY"):
            is_set = bool(os.environ.get(name, "").strip())
            line(OK if is_set else (FAIL if name == "CORTEX_CLIENT_ID" else WARN), name,
                 "set" if is_set else "not set in env/.env")
    if _installed("pegasus"):
        from src.clients import cortex_client
        if mode == "devkit" and ready:
            env = os.environ.get("CORTEX_ENV", "").strip() or "prd"
            line(OK, "Pegasus credentials", f"DevKit sign-in (Pegasus adapter cortex_v2, CORTEX_ENV={env})")
        elif mode != "devkit":
            ok = cortex_client.pegasus_can_authenticate()
            line(OK if ok else WARN, "Pegasus credentials", "set" if ok else
                 "none (CORTEX_API_KEY, or CORTEX_CLIENT_ID + CORTEX_CLIENT_SECRET) — Pegasus metrics run on DeepEval")
    if ping and ready:
        try:
            from src.clients import cortex_client
            llm = cortex_client.deepeval_llm()
            reply = llm.generate("Reply with the single word OK.")
            line(OK, "CORTEX call", f"answered: {str(reply)[:40]!r}  ({llm.target()})")
        except Exception as exc:  # noqa: BLE001 — the whole point is to show the error
            hint = ""
            if "CERTIFICATE_VERIFY_FAILED" in str(exc):
                hint = "  -> set VERIFY_TLS=false or CA_BUNDLE=<corporate CA file> in env/.env"
            elif mode == "devkit" and any(w in str(exc).lower() for w in ("login", "credential", "401", "token")):
                hint = "  -> run make cortex-login"
            line(FAIL, "CORTEX call", f"{type(exc).__name__}: {str(exc)[:300]}{hint}")

    # One real Pegasus metric proves Pegasus and its CORTEX sign-in end to end.
    if ping and ready and _installed("pegasus"):
        from src.clients import cortex_client
        from src.metrics import judges
        if cortex_client.pegasus_can_authenticate():
            result = judges.run_judge("relevance", {"engine": "pegasus"}, {
                "question": "What is the capital of France?",
                "answer": "Paris is the capital of France.",
            })
            if result.score is not None:
                line(OK, "Pegasus metric", f"relevance score={result.score:.2f} [pegasus]")
            else:
                line(FAIL, "Pegasus metric", f"relevance: {result.reason[:300]}")

    print("-" * 72)
    print("All good.\n" if not problems else f"{problems} problem(s) above.\n")
    return 0 if not problems else 1


def _short(path) -> str:  # noqa: ANN001
    """Return the path relative to the repo when inside it, else the full path."""
    try:
        return str(path.relative_to(paths.ROOT))
    except ValueError:
        return str(path)


def _installed(module: str) -> bool:
    """True if the module can be imported."""
    return importlib.util.find_spec(module) is not None


def _version(distribution: str) -> str:
    """Return the installed distribution's version, or "" if it isn't installed."""
    try:
        return importlib.metadata.version(distribution)
    except importlib.metadata.PackageNotFoundError:
        return ""


def _version_of_module(module: str) -> str:
    """Return a module's __version__ (Pegasus' distribution name isn't known, so ask the module)."""
    try:
        return str(getattr(__import__(module), "__version__", "") or "installed")
    except Exception:  # noqa: BLE001
        return "installed (import failed — try: python -c 'import pegasus')"
