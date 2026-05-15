"""Native Codex app-server client for ChatGPT-authenticated Codex runs."""

import asyncio
import json
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional


CODEX_NATIVE_PREFIXES = ("codex:", "codex-native:")
API_KEY_ENV_KEYS = ("OPENAI_API_KEY", "CODEX_API_KEY")
CODEX_DANGER_FULL_ACCESS_MODE = "danger-full-access"
CODEX_DANGER_FULL_ACCESS_POLICY = {"type": "dangerFullAccess"}
CODEX_APP_SERVER_STREAM_LIMIT_BYTES = 32 * 1024 * 1024
CODEX_APP_SERVER_FEATURES = ("builtin_mcp",)
CODEX_APP_SERVER_PLUGIN_IDS = (
    "browser@openai-bundled",
    "chrome@openai-bundled",
    "computer-use@openai-bundled",
)


class CodexNativeError(RuntimeError):
    """Base error for native Codex runner failures."""


class CodexAuthError(CodexNativeError):
    """Raised when Codex is not using ChatGPT subscription auth."""


def is_native_codex_model(model: Optional[str]) -> bool:
    """Return True for models that should use Codex app-server directly."""
    if not model:
        return False
    lower = model.lower()
    return any(lower.startswith(prefix) for prefix in CODEX_NATIVE_PREFIXES)


def strip_native_codex_prefix(model: str) -> str:
    """Remove the Klava routing prefix from a Codex model id."""
    lower = model.lower()
    for prefix in CODEX_NATIVE_PREFIXES:
        if lower.startswith(prefix):
            return model[len(prefix):]
    return model


def codex_effort(effort: Optional[str]) -> Optional[str]:
    """Map Klava effort choices to Codex app-server effort values."""
    if effort in {"low", "medium", "high"}:
        return effort
    if effort == "max":
        return "high"
    return None


def _message_content_text(content: Any) -> str:
    """Extract assistant text from Codex generic message content arrays."""
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for item in content:
        if isinstance(item, str):
            parts.append(item)
        elif isinstance(item, dict):
            text = item.get("text") or item.get("content")
            if isinstance(text, str):
                parts.append(text)
    return "".join(parts)


def _completed_item_text(item: dict[str, Any]) -> Optional[str]:
    item_type = item.get("type")
    if item_type == "agentMessage":
        return str(item.get("text") or "")
    if item_type == "message" and item.get("role") == "assistant":
        return _message_content_text(item.get("content"))
    return None


def _completion_text(payload: dict[str, Any]) -> str:
    """Extract final assistant text from Codex turn/task completion payloads."""
    if not isinstance(payload, dict):
        return ""
    for key in ("last_agent_message", "lastAgentMessage", "final_message", "finalMessage"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value
    for key in ("summary", "output", "text", "message"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return ""


@dataclass
class CodexTurnResult:
    thread_id: str
    turn_id: Optional[str] = None
    status: str = "completed"
    text: str = ""
    usage: dict[str, Any] = field(default_factory=dict)
    model: Optional[str] = None


class CodexAppServerClient:
    """Small JSON-RPC client for `codex app-server --listen stdio://`."""

    def __init__(
        self,
        codex_bin: Optional[str] = None,
        cwd: Optional[Path] = None,
        require_chatgpt_auth: bool = True,
    ):
        self.codex_bin = codex_bin or os.environ.get("CODEX_BIN") or shutil.which("codex") or "codex"
        self.cwd = Path(cwd or Path.home())
        self.require_chatgpt_auth = require_chatgpt_auth
        self.proc: Optional[asyncio.subprocess.Process] = None
        self._next_id = 0
        self._stderr_lines: list[str] = []
        self._stderr_task: Optional[asyncio.Task] = None

    async def connect(self) -> None:
        env = os.environ.copy()
        for key in API_KEY_ENV_KEYS:
            env.pop(key, None)

        args = [
            self.codex_bin,
            "app-server",
            "-c",
            'forced_login_method="chatgpt"',
        ]
        for feature in CODEX_APP_SERVER_FEATURES:
            args.extend(["--enable", feature])
        for plugin_id in CODEX_APP_SERVER_PLUGIN_IDS:
            args.extend(["-c", f'plugins."{plugin_id}".enabled=true'])
        args.extend(["--listen", "stdio://"])

        self.proc = await asyncio.create_subprocess_exec(
            *args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(self.cwd),
            env=env,
            limit=CODEX_APP_SERVER_STREAM_LIMIT_BYTES,
        )
        self._stderr_task = asyncio.create_task(self._collect_stderr())
        await self.request(
            "initialize",
            {
                "clientInfo": {
                    "name": "klava",
                    "title": "Klava",
                    "version": "0.1.0",
                }
            },
        )
        await self.notify("initialized", {})
        if self.require_chatgpt_auth:
            await self.assert_chatgpt_auth()

    async def close(self) -> None:
        if self.proc is None:
            return
        proc = self.proc
        self.proc = None
        if proc.returncode is None:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout=2)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
        if self._stderr_task:
            self._stderr_task.cancel()

    async def assert_chatgpt_auth(self) -> None:
        result = await self.request("account/read", {"refreshToken": True})
        account = result.get("account") or {}
        account_type = account.get("type")
        if account_type != "chatgpt":
            raise CodexAuthError(
                "Codex native runner requires ChatGPT auth, but app-server "
                f"reported {account_type or 'no account'}. Run `codex login` "
                "with ChatGPT and do not use OPENAI_API_KEY/CODEX_API_KEY."
            )

    async def start_or_resume_thread(
        self,
        thread_id: Optional[str],
        cwd: Optional[Path] = None,
        developer_instructions: Optional[str] = None,
        base_instructions: Optional[str] = None,
        sandbox: Optional[str] = CODEX_DANGER_FULL_ACCESS_MODE,
        approval_policy: Optional[str] = None,
    ) -> str:
        params: dict[str, Any] = {"cwd": str(cwd or self.cwd)}
        if sandbox:
            params["sandbox"] = sandbox
        if approval_policy:
            params["approvalPolicy"] = approval_policy
        if developer_instructions:
            params["developerInstructions"] = developer_instructions
        if base_instructions:
            params["baseInstructions"] = base_instructions
        if thread_id:
            params["threadId"] = thread_id
            result = await self.request("thread/resume", params)
        else:
            result = await self.request("thread/start", params)
        thread = result.get("thread") or {}
        resolved = thread.get("id") or result.get("threadId")
        if not resolved:
            raise CodexNativeError(f"Codex app-server did not return a thread id: {result}")
        return str(resolved)

    async def read_thread(self, thread_id: str, include_turns: bool = True) -> dict[str, Any]:
        """Read a persisted Codex thread, including turns/items for history UI."""
        result = await self.request(
            "thread/read",
            {"threadId": thread_id, "includeTurns": include_turns},
        )
        thread = result.get("thread") or {}
        if not isinstance(thread, dict):
            raise CodexNativeError(f"Codex app-server did not return a thread: {result}")
        return thread

    async def run_turn(
        self,
        thread_id: str,
        prompt: str,
        model: str,
        effort: Optional[str] = None,
        cwd: Optional[Path] = None,
        mode: str = "bypass",
        summary: Optional[str] = "detailed",
        on_text_delta: Optional[Callable[[str], Awaitable[None]]] = None,
        on_notification: Optional[Callable[[dict[str, Any]], Awaitable[None]]] = None,
    ) -> CodexTurnResult:
        params: dict[str, Any] = {
            "threadId": thread_id,
            "input": [{"type": "text", "text": prompt}],
            "cwd": str(cwd or self.cwd),
            "model": strip_native_codex_prefix(model),
            "sandboxPolicy": CODEX_DANGER_FULL_ACCESS_POLICY,
        }
        mapped_effort = codex_effort(effort)
        if mapped_effort:
            params["effort"] = mapped_effort
        if summary in {"auto", "concise", "detailed", "none"}:
            params["summary"] = summary
        if mode == "bypass":
            params["approvalPolicy"] = "never"

        start = await self.request("turn/start", params, on_notification=on_notification)
        turn = start.get("turn") or {}
        turn_id = turn.get("id")
        text = ""
        usage: dict[str, Any] = {}
        status = str(turn.get("status") or "inProgress")

        while True:
            msg = await self.read_message()
            if await self._handle_server_request(msg, mode=mode):
                continue
            if "method" not in msg:
                continue
            if on_notification:
                await on_notification(msg)
            method = msg.get("method")
            payload = msg.get("params") or {}

            if method in {"item/agentMessage/delta", "item/message/delta"}:
                delta = payload.get("delta") or payload.get("textDelta") or payload.get("text") or ""
                if delta:
                    text += str(delta)
            elif method == "item/completed":
                item = payload.get("item") or {}
                full_text = _completed_item_text(item)
                if full_text is not None:
                    if full_text != text:
                        text = full_text
            elif method == "thread/tokenUsage/updated":
                usage = payload.get("usage") or payload.get("tokenUsage") or usage
            elif method == "turn/completed":
                completed = payload.get("turn") or {}
                status = str(completed.get("status") or status)
                final_text = _completion_text(completed) or text
                if final_text and final_text != text:
                    text = final_text
                if completed.get("usage"):
                    usage = completed.get("usage") or usage
                error = completed.get("error")
                if status == "failed" and error:
                    message = error.get("message") if isinstance(error, dict) else str(error)
                    raise CodexNativeError(message or "Codex turn failed")
                if final_text and on_text_delta:
                    await on_text_delta(final_text)
                break

        return CodexTurnResult(
            thread_id=thread_id,
            turn_id=str(turn_id) if turn_id else None,
            status=status,
            text=text,
            usage=usage if isinstance(usage, dict) else {},
            model=strip_native_codex_prefix(model),
        )

    async def request(
        self,
        method: str,
        params: Optional[dict[str, Any]] = None,
        mode: str = "bypass",
        on_notification: Optional[Callable[[dict[str, Any]], Awaitable[None]]] = None,
    ) -> dict[str, Any]:
        request_id = self._next_id
        self._next_id += 1
        await self._write({"id": request_id, "method": method, "params": params or {}})
        while True:
            msg = await self.read_message()
            if await self._handle_server_request(msg, mode=mode):
                continue
            if msg.get("id") == request_id:
                if "error" in msg:
                    error = msg["error"]
                    if isinstance(error, dict):
                        raise CodexNativeError(error.get("message") or json.dumps(error))
                    raise CodexNativeError(str(error))
                result = msg.get("result") or {}
                return result if isinstance(result, dict) else {"value": result}
            if "method" in msg and on_notification:
                await on_notification(msg)

    async def _handle_server_request(self, msg: dict[str, Any], mode: str = "bypass") -> bool:
        """Respond to app-server requests that would otherwise stall the turn.

        Codex app-server can send JSON-RPC requests back to the client for tool
        approvals, dynamic tool calls, or auth refresh. Klava currently has no
        native Codex approval UI, so bypass mode mirrors the dashboard's existing
        "run without asking" behavior and accepts command/file approvals.
        Unsupported interactive requests are declined with a structured error.
        """
        if "id" not in msg or "method" not in msg:
            return False

        method = str(msg.get("method") or "")
        request_id = msg.get("id")
        if method in {"item/commandExecution/requestApproval", "execCommandApproval"}:
            decision = "accept" if mode == "bypass" else "decline"
            await self._write({"id": request_id, "result": {"decision": decision}})
            return True
        if method in {"item/fileChange/requestApproval", "applyPatchApproval"}:
            decision = "accept" if mode == "bypass" else "decline"
            await self._write({"id": request_id, "result": {"decision": decision}})
            return True
        if method == "item/permissions/requestApproval":
            if mode == "bypass":
                await self._write({
                    "id": request_id,
                    "result": {
                        "permissions": {"network": {"enabled": True}, "fileSystem": {"writableRoots": []}},
                        "scope": "turn",
                    },
                })
            else:
                await self._write({
                    "id": request_id,
                    "error": {"code": -32000, "message": "Permission request declined by Klava"},
                })
            return True
        if method in {"item/tool/requestUserInput", "mcpServer/elicitation/request", "item/tool/call"}:
            await self._write({
                "id": request_id,
                "error": {"code": -32000, "message": f"Unsupported native Codex client request: {method}"},
            })
            return True
        if method == "account/chatgptAuthTokens/refresh":
            await self._write({
                "id": request_id,
                "error": {"code": -32000, "message": "ChatGPT token refresh is not implemented by Klava"},
            })
            return True
        return False

    async def notify(self, method: str, params: Optional[dict[str, Any]] = None) -> None:
        await self._write({"method": method, "params": params or {}})

    async def read_message(self) -> dict[str, Any]:
        if self.proc is None or self.proc.stdout is None:
            raise CodexNativeError("Codex app-server is not connected")
        line = await self.proc.stdout.readline()
        if not line:
            stderr = "\n".join(self._stderr_lines[-5:])
            raise CodexNativeError(f"Codex app-server exited unexpectedly. {stderr}".strip())
        return json.loads(line.decode("utf-8"))

    async def _write(self, payload: dict[str, Any]) -> None:
        if self.proc is None or self.proc.stdin is None:
            raise CodexNativeError("Codex app-server is not connected")
        self.proc.stdin.write((json.dumps(payload, separators=(",", ":")) + "\n").encode("utf-8"))
        await self.proc.stdin.drain()

    async def _collect_stderr(self) -> None:
        if self.proc is None or self.proc.stderr is None:
            return
        try:
            while True:
                line = await self.proc.stderr.readline()
                if not line:
                    return
                self._stderr_lines.append(line.decode("utf-8", errors="replace").rstrip())
                if len(self._stderr_lines) > 20:
                    self._stderr_lines = self._stderr_lines[-20:]
        except asyncio.CancelledError:
            return
