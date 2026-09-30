"""
`make doctor`: check this machine is ready to run evaluations, and say how to fix what isn't.

It checks, in order:
  1. which Python / virtual environment the framework is running in
  2. which env files were found
  3. whether DeepEval and Pegasus can be imported (Pegasus must be in *this* environment)
  4. the HTTPS certificate settings (VERIFY_TLS / CA_BUNDLE)
  5. the CORTEX settings for the chosen CORTEX_AUTH (api_key or devkit), then one tiny call to
     CORTEX to prove the judge model is reachable

Secrets are never printed — only whether they are set.
"""

from __future__ import annotations

import importlib.metadata
import importlib.util
import os
import sys

from src.core import env, paths, tls  # noqa: F401 — importing env loads env/.env

OK, WARN, FAIL = "OK  ", "WARN", "FAIL"


def run_doctor(ping: bool = True) -> int:
    """Print the report. Returns 0 when nothing FAILed, 1 otherwise."""
    problems = 0

    def line(status: str, what: str, detail: str = "") -> None:
        nonlocal problems
        problems += status == FAIL
        print(f"[{status}] {what:<22} {detail}")

    print("\nai-eval-suite doctor\n" + "-" * 72)

    # 1. Python environment — Pegasus has to be installed into this one.
    line(OK, "python", sys.executable)
    active = os.environ.get("VIRTUAL_ENV", "")
    line(OK if active else WARN, "virtual env",
         active or "none active — make uses the project's .venv (created by make setup)")

    # 2. Env files
    found = [p for p in (paths.ENV_DIR / ".env", paths.ROOT / ".env") if p.is_file()]
    agent_files = sorted(paths.ENV_DIR.glob(".env.*")) if paths.ENV_DIR.is_dir() else []
    agent_files = [p for p in agent_files if p.name != ".env.example"]
    line(OK if found else FAIL, "env files",
         ", ".join(_short(p) for p in found + agent_files)
         or "none — run make setup, then fill in env/.env")

    # 3. Judge libraries
    line(OK if _installed("deepeval") else FAIL, "deepeval", _version("deepeval") or "not installed — run make setup")
    if _installed("pegasus"):
        where = importlib.util.find_spec("pegasus").origin or ""
        line(OK, "pegasus", f"{_version_of_module('pegasus')}  {os.path.dirname(where)}")
    else:
        line(WARN, "pegasus", "not installed in this environment — Pegasus metrics will run on DeepEval.\n"
             "                              Fix: put your SAR token in env/.env (SAR_TOKEN_NAME / "
             "SAR_TOKEN_PASS_CODE), then run make setup.")

    # 4. Certificates
    if tls.ca_bundle():
        exists = os.path.isfile(tls.ca_bundle())
        missing = "" if exists else "  (file not found)"
        line(OK if exists else FAIL, "certificates", f"CA_BUNDLE={tls.ca_bundle()}{missing}")
    else:
        line(OK, "certificates", "checked (VERIFY_TLS=true)" if tls.verify_enabled()
             else "not checked (VERIFY_TLS=false — fine behind the office proxy)")

    # 5. CORTEX — api_key mode needs host + id + key; devkit mode needs the package and `make cortex-login`.
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
            # Pegasus takes the DevKit sign-in as its key: check it can be read (never printed).
            try:
                cortex_client.devkit_token()
                line(OK, "Pegasus credentials", f"DevKit sign-in -> {cortex_client.devkit_api_base()}")
            except Exception as exc:  # noqa: BLE001
                line(FAIL, "Pegasus credentials", f"{type(exc).__name__}: {str(exc)[:200]}  -> run make cortex-login")
        elif mode != "devkit":
            ok = cortex_client.pegasus_can_authenticate()
            line(OK if ok else WARN, "Pegasus credentials", "set" if ok else
                 "none (CORTEX_API_KEY, or CORTEX_CLIENT_ID + CORTEX_CLIENT_SECRET) — Pegasus metrics run on DeepEval")
    if ping and ready:
        try:
            from src.clients import cortex_client
            reply = cortex_client.deepeval_llm().generate("Reply with the single word OK.")
            line(OK, "CORTEX call", f"answered: {str(reply)[:40]!r}")
        except Exception as exc:  # noqa: BLE001 — the whole point is to show the error
            hint = ""
            if "CERTIFICATE_VERIFY_FAILED" in str(exc):
                hint = "  -> set VERIFY_TLS=false or CA_BUNDLE=<corporate CA file> in env/.env"
            elif mode == "devkit" and any(w in str(exc).lower() for w in ("login", "credential", "401", "token")):
                hint = "  -> run make cortex-login"
            line(FAIL, "CORTEX call", f"{type(exc).__name__}: {str(exc)[:300]}{hint}")

    print("-" * 72)
    print("All good.\n" if not problems else f"{problems} problem(s) above.\n")
    return 0 if not problems else 1


def _short(path) -> str:  # noqa: ANN001
    """A path relative to the repo when it's inside it, else the full path."""
    try:
        return str(path.relative_to(paths.ROOT))
    except ValueError:
        return str(path)


def _installed(module: str) -> bool:
    return importlib.util.find_spec(module) is not None


def _version(distribution: str) -> str:
    try:
        return importlib.metadata.version(distribution)
    except importlib.metadata.PackageNotFoundError:
        return ""


def _version_of_module(module: str) -> str:
    """Pegasus' distribution name isn't known here, so ask the module itself."""
    try:
        return str(getattr(__import__(module), "__version__", "") or "installed")
    except Exception:  # noqa: BLE001
        return "installed (import failed — try: python -c 'import pegasus')"
