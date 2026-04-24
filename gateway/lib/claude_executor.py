"""Claude executor using Agent SDK for automated job execution."""

import asyncio
import json
import os
import signal
import threading
import time
from pathlib import Path
from typing import Dict, Optional, List, AsyncIterator, Callable

from claude_agent_sdk import (
    ClaudeSDKClient, ClaudeAgentOptions,
    AssistantMessage, ResultMessage, TextBlock, ToolUseBlock,
)

from .process_reaper import kill_sdk_subprocess
from . import config as _cfg

# Default directory for detached job output files
DETACHED_OUTPUT_DIR = "/tmp/claude_jobs"

# MCP config path
MCP_CONFIG = str(_cfg.mcp_servers_file())
DEFAULT_MODEL = _cfg.default_model()

# SDK stdout JSON buffer ceiling. claude-agent-sdk defaults to 1 MiB, which is
# too small for long opus runs — a single tool_use_result (WebFetch, Read of a
# big file, long assistant text block) can blow past 1 MiB and crash the
# reader with SDKJSONDecodeError("JSON message exceeded maximum buffer size"),
# killing the consumer with Exit code 1 mid-task. 16 MiB comfortably holds
# any realistic SDK message while still bounding RAM.
# Regression: 2026-04-23 blog post task (opus, 19 min) tripped 1 MiB limit
# in the consumer 4x in 24h before this fix.
# Override via env: CLAUDE_SDK_MAX_BUFFER_SIZE=<bytes>.
_DEFAULT_SDK_MAX_BUFFER_SIZE = 16 * 1024 * 1024


def _resolve_max_buffer_size() -> int:
    """Return the SDK buffer cap, honoring CLAUDE_SDK_MAX_BUFFER_SIZE env."""
    raw = os.environ.get("CLAUDE_SDK_MAX_BUFFER_SIZE")
    if not raw:
        return _DEFAULT_SDK_MAX_BUFFER_SIZE
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return _DEFAULT_SDK_MAX_BUFFER_SIZE
    return value if value > 0 else _DEFAULT_SDK_MAX_BUFFER_SIZE


class ClaudeExecutor:
    """Execute Claude commands via Agent SDK (streaming mode)."""

    def __init__(self, log_callback=None):
        self.log = log_callback or print

    def _build_options(
        self,
        mode: str = "isolated",
        session_id: Optional[str] = None,
        model: str = DEFAULT_MODEL,
        allowed_tools: Optional[List[str]] = None,
        add_dirs: Optional[List[str]] = None,
        skip_permissions: bool = False,
        effort: Optional[str] = None,
        max_budget_usd: Optional[float] = None,
        betas: Optional[List[str]] = None,
        max_turns: Optional[int] = None,
        fallback_model: Optional[str] = None,
        thinking: Optional[Dict] = None,
        resume_session_id: Optional[str] = None,
    ) -> ClaudeAgentOptions:
        """Build ClaudeAgentOptions for SDK."""
        opts = {}

        opts["model"] = model or DEFAULT_MODEL

        if mode == "main" and session_id:
            opts["resume"] = session_id
        elif resume_session_id:
            # Explicit resume request (e.g. Klava continue-in-session path) —
            # works in isolated mode too. Lets a queued follow-up preserve the
            # original executor's context instead of cold-starting.
            opts["resume"] = resume_session_id

        opts["allowed_tools"] = allowed_tools or ["*"]

        if add_dirs:
            opts["add_dirs"] = [os.path.expanduser(d) for d in add_dirs]

        if skip_permissions:
            opts["permission_mode"] = "bypassPermissions"

        opts["cwd"] = Path.home()

        if os.path.exists(MCP_CONFIG):
            opts["mcp_servers"] = MCP_CONFIG

        if effort:
            opts["effort"] = effort

        if max_budget_usd is not None:
            opts["max_budget_usd"] = max_budget_usd

        if betas:
            opts["betas"] = betas

        # Prevent runaway sessions - cap conversation turns
        if max_turns is not None:
            opts["max_turns"] = max_turns

        # Auto-fallback on rate limits (e.g., opus -> sonnet)
        if fallback_model:
            opts["fallback_model"] = fallback_model

        # Fine-grained thinking budget (replaces deprecated max_thinking_tokens)
        if thinking:
            opts["thinking"] = thinking

        opts["setting_sources"] = ["user", "project"]

        # Raise SDK stdout JSON buffer cap — see _DEFAULT_SDK_MAX_BUFFER_SIZE.
        opts["max_buffer_size"] = _resolve_max_buffer_size()

        # Ensure USER env var is passed to subprocess (required for macOS keychain auth)
        import getpass
        env_vars = {}
        if "USER" not in os.environ:
            try:
                env_vars["USER"] = getpass.getuser()
            except Exception:
                pass
        if env_vars:
            opts["env"] = env_vars

        return ClaudeAgentOptions(**opts)

    async def _run_streaming(
        self,
        prompt: str,
        options: ClaudeAgentOptions,
        timeout: int,
        text_callback: Optional[Callable] = None,
        tool_callback: Optional[Callable] = None,
    ) -> Dict:
        """Run query via ClaudeSDKClient (streaming mode).

        Uses persistent client connection for better performance,
        hook support, and interrupt capability.
        """
        result_msg = None
        text_parts = []
        todos = []
        client = None

        # Capture subprocess stderr for debugging via callback
        stderr_lines = []
        def _stderr_cb(line: str):
            stderr_lines.append(line)
            if len(stderr_lines) <= 5:
                self.log(f"SDK stderr: {line[:200]}")

        # Use system CLI binary (more up-to-date than bundled) and capture stderr
        import shutil
        system_cli = shutil.which("claude")
        if not system_cli:
            # Check common locations not in cron PATH
            for p in [Path.home() / ".local/bin/claude", Path("/usr/local/bin/claude")]:
                if p.exists():
                    system_cli = str(p)
                    break
        override = {}
        if system_cli:
            override["cli_path"] = system_cli
            self.log(f"Using system CLI: {system_cli}")
        override["stderr"] = _stderr_cb
        options = options.__class__(**{**options.__dict__, **override})

        try:
            async with asyncio.timeout(timeout):
                async with ClaudeSDKClient(options) as client:
                    await client.connect()
                    await client.query(prompt)

                    async for message in client.receive_messages():
                        if isinstance(message, AssistantMessage):
                            # Check for auth errors in assistant message
                            error_attr = getattr(message, 'error', None)
                            if error_attr == 'authentication_failed':
                                auth_text = ""
                                for block in message.content:
                                    if isinstance(block, TextBlock):
                                        auth_text = block.text
                                return {
                                    "error": auth_text or "Not logged in",
                                    "session_id": None,
                                    "cost": 0.0,
                                    "duration": 0,
                                    "exit_code": 1,
                                }
                            for block in message.content:
                                if isinstance(block, TextBlock):
                                    text_parts.append(block.text)
                                    if text_callback:
                                        text_callback(block.text)
                                elif isinstance(block, ToolUseBlock):
                                    if block.name == "TodoWrite":
                                        # Extract todos from TodoWrite tool call
                                        if block.input and "todos" in block.input:
                                            todos = block.input["todos"]
                                    if tool_callback:
                                        tool_callback(block.name, block.input or {})
                        elif isinstance(message, ResultMessage):
                            result_msg = message
                            break  # ResultMessage is final - iterator won't terminate on its own
        except TimeoutError:
            self.log(f"Streaming query timed out after {timeout}s, cleaning up...")
            # Explicitly kill the SDK process and its MCP children
            if client:
                try:
                    await client.disconnect()
                except BaseException:
                    pass
            return {
                "error": f"Timeout after {timeout}s",
                "session_id": None,
                "cost": 0.0,
                "duration": timeout,
                "exit_code": -1,
            }
        except Exception as e:
            stderr_content = "\n".join(stderr_lines)
            error_str = str(e)
            self.log(f"SDK exception: {type(e).__name__}: {error_str[:200]}")
            self.log(f"SDK stderr lines captured: {len(stderr_lines)}")
            if stderr_content:
                error_str = f"{error_str}\nstderr: {stderr_content[:500]}"
                self.log(f"SDK subprocess stderr: {stderr_content[:500]}")
            else:
                self.log("SDK subprocess: NO stderr captured")
            # Extract "Not logged in" from ProcessError stderr
            if "Not logged in" in error_str or "authentication_failed" in error_str:
                self.log(f"AUTH ERROR: Claude not logged in. Run: env -u CLAUDECODE CLAUDE_CONFIG_DIR={_cfg.claude_config_dir()} claude login")
                return {
                    "error": "Not logged in - run claude login",
                    "session_id": None,
                    "cost": 0.0,
                    "duration": 0,
                    "exit_code": 1,
                }
            raise  # Re-raise non-auth errors
        finally:
            # Force-kill SDK subprocess to prevent zombie accumulation.
            # The async with __aexit__ calls disconnect() -> transport.close() -> terminate(),
            # but SIGTERM is unreliable. This ensures the process is dead via SIGKILL.
            kill_sdk_subprocess(client)

        if not result_msg:
            return {
                "error": "No result received from SDK",
                "session_id": None,
                "cost": 0.0,
                "duration": 0,
                "exit_code": -1,
            }

        error = None
        if result_msg.is_error:
            error = result_msg.result or "Unknown error"

        return {
            "result": result_msg.result or "\n".join(text_parts),
            "session_id": result_msg.session_id,
            "cost": result_msg.total_cost_usd or 0.0,
            "duration": (result_msg.duration_ms or 0) / 1000,
            "tokens": {
                "input": (result_msg.usage or {}).get("input_tokens", 0),
                "output": (result_msg.usage or {}).get("output_tokens", 0),
                "cache_read": (result_msg.usage or {}).get("cache_read_input_tokens", 0),
            },
            "num_turns": result_msg.num_turns,
            "error": error,
            "exit_code": 1 if result_msg.is_error else 0,
            "todos": todos,
        }

    def run(
        self,
        prompt: str,
        mode: str = "isolated",
        session_id: Optional[str] = None,
        model: str = DEFAULT_MODEL,
        timeout: int = 300,
        allowed_tools: Optional[List[str]] = None,
        add_dirs: Optional[List[str]] = None,
        skip_permissions: bool = False,
        effort: Optional[str] = None,
        max_budget_usd: Optional[float] = None,
        betas: Optional[List[str]] = None,
        text_callback: Optional[Callable] = None,
        tool_callback: Optional[Callable] = None,
        max_turns: Optional[int] = None,
        fallback_model: Optional[str] = None,
        thinking: Optional[Dict] = None,
        resume_session_id: Optional[str] = None,
    ) -> Dict:
        """Execute Claude query (blocks until completion).

        Uses streaming mode via ClaudeSDKClient for full hook/interrupt support.

        Returns:
            Dict with: {result, session_id, cost, duration, error}
        """
        if mode == "main" and not session_id:
            return {"error": "session_id required for mode='main'"}

        options = self._build_options(
            mode=mode, session_id=session_id, model=model,
            allowed_tools=allowed_tools, add_dirs=add_dirs,
            skip_permissions=skip_permissions, effort=effort,
            max_budget_usd=max_budget_usd, betas=betas,
            max_turns=max_turns, fallback_model=fallback_model,
            thinking=thinking,
            resume_session_id=resume_session_id,
        )

        self.log(f"Executing streaming query: model={model}, mode={mode}...")

        try:
            result = asyncio.run(
                self._run_streaming(prompt, options, timeout, text_callback, tool_callback)
            )
            return result
        except BaseException as e:
            self.log(f"Execution failed: {e}")
            if isinstance(e, (KeyboardInterrupt, SystemExit)):
                raise
            return {
                "error": str(e),
                "session_id": session_id,
                "cost": 0.0,
                "duration": 0,
                "exit_code": -1,
            }

    def run_detached(
        self,
        prompt: str,
        run_id: str,
        mode: str = "isolated",
        session_id: Optional[str] = None,
        model: str = DEFAULT_MODEL,
        timeout: int = 300,
        allowed_tools: Optional[List[str]] = None,
        add_dirs: Optional[List[str]] = None,
        skip_permissions: bool = False,
        output_dir: str = DETACHED_OUTPUT_DIR,
        effort: Optional[str] = None,
        max_budget_usd: Optional[float] = None,
        betas: Optional[List[str]] = None,
        max_turns: Optional[int] = None,
        fallback_model: Optional[str] = None,
        thinking: Optional[Dict] = None,
    ) -> Dict:
        """Launch Claude query in a background thread (survives caller returning).

        Uses streaming mode via ClaudeSDKClient.
        Use wait_for_result() to block until completion.

        Returns:
            Dict with: {status, run_id, output_dir} on success, or {error} on failure.
        """
        if mode == "main" and not session_id:
            return {"error": "session_id required for mode='main'"}

        out_dir = Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        options = self._build_options(
            mode=mode, session_id=session_id, model=model,
            allowed_tools=allowed_tools, add_dirs=add_dirs,
            skip_permissions=skip_permissions, effort=effort,
            max_budget_usd=max_budget_usd, betas=betas,
            max_turns=max_turns, fallback_model=fallback_model,
            thinking=thinking,
        )

        # Store result in a mutable container for thread communication
        result_holder = {"done": threading.Event(), "result": None}
        result_file = out_dir / f"{run_id}.result.json"
        # Hard deadline: wall-clock kill if asyncio.timeout fails
        hard_deadline = time.time() + timeout + 60

        def _run_in_thread():
            try:
                result = asyncio.run(
                    self._run_streaming(prompt, options, timeout)
                )
                result_holder["result"] = result
            except BaseException as e:
                result_holder["result"] = {
                    "error": str(e),
                    "session_id": session_id,
                    "cost": 0.0,
                    "duration": 0,
                    "exit_code": -1,
                }
            finally:
                # Kill any orphaned SDK subprocesses that survived the session
                # (client.disconnect() doesn't always terminate the subprocess)
                try:
                    ClaudeExecutor._kill_orphaned_children(os.getpid(), run_id, self.log)
                except Exception:
                    pass
                # Write result file as completion signal (backward compat)
                try:
                    result_file.write_text(json.dumps({
                        "exit_code": result_holder["result"].get("exit_code", -1),
                        "completed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    }))
                except Exception:
                    pass
                result_holder["done"].set()

        def _hard_kill_watchdog():
            """Wall-clock watchdog that kills SDK children if asyncio.timeout fails.

            asyncio.timeout can fail to cancel if receive_messages() blocks in
            a non-cancellable way, or if macOS system sleep pauses the event loop.
            This thread polls wall clock every 10s and hard-kills at deadline.
            """
            while time.time() < hard_deadline:
                if result_holder["done"].is_set():
                    return
                time.sleep(10)
            if not result_holder["done"].is_set():
                self.log(f"HARD KILL: {run_id} exceeded wall-clock deadline "
                         f"({timeout + 60}s), force-killing children")
                ClaudeExecutor._kill_orphaned_children(os.getpid(), run_id, self.log)
                try:
                    from lib.process_reaper import reap_orphaned_children
                    reap_orphaned_children(parent_pid=os.getpid(), max_age_seconds=0)
                except Exception:
                    pass

        thread = threading.Thread(target=_run_in_thread, daemon=True)
        thread.start()
        watchdog = threading.Thread(target=_hard_kill_watchdog, daemon=True)
        watchdog.start()

        self.log(f"Detached launch: run_id={run_id}, model={model}")
        # Store thread and result_holder for wait_for_result
        if not hasattr(self, "_detached_jobs"):
            self._detached_jobs = {}
        self._detached_jobs[run_id] = result_holder

        return {
            "status": "launched",
            "pid": os.getpid(),  # parent PID for state tracking compatibility
            "run_id": run_id,
            "output_dir": output_dir,
        }

    def wait_for_result(
        self,
        run_id: str,
        timeout: int = 300,
        poll_interval: float = 2.0,
        output_dir: str = DETACHED_OUTPUT_DIR,
        session_id: Optional[str] = None,
    ) -> Dict:
        """Block until a detached job completes and return its result."""
        # Check if we have the in-memory result holder
        holder = getattr(self, "_detached_jobs", {}).get(run_id)
        if holder:
            # Poll with wall-clock checks instead of Event.wait(timeout).
            # On macOS, Event.wait uses pthread_cond_timedwait which pauses
            # during system sleep - a 600s timeout can stretch to 6000s+
            # if the machine sleeps overnight.
            deadline = time.time() + timeout
            while time.time() < deadline:
                if holder["done"].wait(timeout=min(5.0, max(0, deadline - time.time()))):
                    result = holder["result"]
                    self._detached_jobs.pop(run_id, None)
                    result_file = Path(output_dir) / f"{run_id}.result.json"
                    result_file.unlink(missing_ok=True)
                    return result

            self.log(f"Detached job {run_id} timed out after {timeout}s (wall clock)")
            self._kill_orphaned_children(os.getpid(), run_id, self.log)
            # Also try reap_orphaned_children for processes that escaped the tree
            try:
                from lib.process_reaper import reap_orphaned_children
                reap_orphaned_children(parent_pid=os.getpid(), max_age_seconds=0)
            except Exception:
                pass
            self._detached_jobs.pop(run_id, None)
            return {
                "error": f"Timeout after {timeout}s",
                "result": "",
                "session_id": session_id,
                "cost": 0.0,
                "duration": 0,
                "exit_code": -1,
            }

        # Fallback: poll for result file (backward compat with old-style detached jobs)
        result_file = Path(output_dir) / f"{run_id}.result.json"
        out_file = Path(output_dir) / f"{run_id}.out"

        start_time = time.time()
        while time.time() - start_time < timeout:
            if result_file.exists():
                stdout = ""
                if out_file.exists():
                    try:
                        stdout = out_file.read_text()
                    except OSError:
                        pass
                # Clean up
                for f in (result_file, out_file):
                    try:
                        f.unlink(missing_ok=True)
                    except OSError:
                        pass
                return {
                    "result": stdout,
                    "session_id": session_id,
                    "cost": 0.0,
                    "duration": time.time() - start_time,
                    "exit_code": 0,
                }
            time.sleep(poll_interval)

        return {
            "error": f"Timeout after {timeout}s",
            "session_id": session_id,
            "cost": 0.0,
            "duration": timeout,
            "exit_code": -1,
        }

    @staticmethod
    def _kill_orphaned_children(parent_pid: int, run_id: str, log=None):
        """Kill SDK-spawned child processes (claude binary + MCP servers) after timeout.

        When a detached job times out, the daemon thread holding asyncio.run()
        may keep the subprocess tree alive. This finds and kills those orphans.
        """
        import subprocess
        try:
            # Find all child processes of the cron-scheduler (our PID)
            result = subprocess.run(
                ["pgrep", "-P", str(parent_pid)],
                capture_output=True, text=True, timeout=5,
            )
            child_pids = [int(p) for p in result.stdout.strip().split() if p.strip()]

            for cpid in child_pids:
                try:
                    # Check if this is a claude_agent_sdk process
                    cmdline = subprocess.run(
                        ["ps", "-p", str(cpid), "-o", "command="],
                        capture_output=True, text=True, timeout=5,
                    ).stdout.strip()
                    if "/claude" in cmdline and ("claude_agent_sdk" in cmdline or ".local/bin/claude" in cmdline):
                        # Kill process group to take out MCP servers too
                        # BUT only if it's a different group from ours (otherwise we'd kill the scheduler!)
                        try:
                            child_pgid = os.getpgid(cpid)
                            my_pgid = os.getpgid(os.getpid())
                            if child_pgid != my_pgid:
                                os.killpg(child_pgid, signal.SIGTERM)
                            else:
                                # Same process group - kill just the child, not our whole group
                                os.kill(cpid, signal.SIGTERM)
                        except (OSError, ProcessLookupError):
                            os.kill(cpid, signal.SIGTERM)
                        if log:
                            log(f"Killed orphaned SDK process {cpid} for {run_id}")
                except (OSError, ProcessLookupError, subprocess.TimeoutExpired):
                    pass
        except (subprocess.TimeoutExpired, Exception) as e:
            if log:
                log(f"Orphan cleanup failed for {run_id}: {e}")

    @staticmethod
    def reap_stale_children(parent_pid: int, max_age_seconds: int = 7200, log=None):
        """Kill any child claude processes older than max_age_seconds.

        Safety net that runs periodically to catch zombies the per-job
        orphan killer missed (e.g., due to binary path mismatch).
        """
        import subprocess
        try:
            result = subprocess.run(
                ["pgrep", "-P", str(parent_pid)],
                capture_output=True, text=True, timeout=5,
            )
            child_pids = [int(p) for p in result.stdout.strip().split() if p.strip()]
            killed = 0
            for cpid in child_pids:
                try:
                    # Get elapsed time in seconds
                    etime_str = subprocess.run(
                        ["ps", "-p", str(cpid), "-o", "etime=,command="],
                        capture_output=True, text=True, timeout=5,
                    ).stdout.strip()
                    if not etime_str or "claude" not in etime_str:
                        continue
                    # Parse etime format: [[dd-]hh:]mm:ss
                    etime_part = etime_str.split()[0]
                    parts = etime_part.replace("-", ":").split(":")
                    parts = [int(p) for p in parts]
                    if len(parts) == 2:
                        elapsed = parts[0] * 60 + parts[1]
                    elif len(parts) == 3:
                        elapsed = parts[0] * 3600 + parts[1] * 60 + parts[2]
                    elif len(parts) == 4:
                        elapsed = parts[0] * 86400 + parts[1] * 3600 + parts[2] * 60 + parts[3]
                    else:
                        continue
                    if elapsed > max_age_seconds:
                        os.kill(cpid, signal.SIGTERM)
                        killed += 1
                        if log:
                            log(f"Reaped stale claude process {cpid} (age={elapsed}s)")
                except (OSError, ProcessLookupError, ValueError, subprocess.TimeoutExpired):
                    pass
            if killed and log:
                log(f"Reaper: killed {killed} stale claude processes")
            return killed
        except Exception as e:
            if log:
                log(f"Reaper failed: {e}")
            return 0

    @staticmethod
    def read_detached_result(
        run_id: str,
        output_dir: str = DETACHED_OUTPUT_DIR,
    ) -> Optional[Dict]:
        """Non-blocking check: return parsed result if job completed, None if still running."""
        result_file = Path(output_dir) / f"{run_id}.result.json"
        if not result_file.exists():
            return None
        try:
            return json.loads(result_file.read_text().strip())
        except (json.JSONDecodeError, OSError):
            return {"exit_code": -1}
