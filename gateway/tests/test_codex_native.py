"""Tests for the native Codex app-server client."""

import asyncio
import json
import os
import stat
import textwrap

import pytest

from lib.codex_native import (
    CodexAppServerClient,
    CodexAuthError,
    codex_effort,
    is_native_codex_model,
    strip_native_codex_prefix,
)


def _fake_codex_bin(
    tmp_path,
    account_type="chatgpt",
    request_approval=False,
    generic_message=False,
    large_delta=False,
    completion_message=False,
    argv_log_path=None,
):
    script = tmp_path / "fake-codex"
    argv_log = str(argv_log_path) if argv_log_path else ""
    script.write_text(textwrap.dedent(f"""\
        #!/usr/bin/env python3
        import json
        import sys

        if {argv_log!r}:
            with open({argv_log!r}, "w") as f:
                json.dump(sys.argv, f)

        def send(obj):
            print(json.dumps(obj), flush=True)

        for line in sys.stdin:
            msg = json.loads(line)
            mid = msg.get("id")
            method = msg.get("method")
            if method == "initialize":
                send({{"id": mid, "result": {{"codexHome": "/tmp/fake-codex"}}}})
            elif method == "initialized":
                continue
            elif method == "account/read":
                send({{"id": mid, "result": {{
                    "account": {{"type": "{account_type}", "email": "user@example.com", "planType": "pro"}},
                    "requiresOpenaiAuth": True
                }}}})
            elif method == "thread/start":
                params = msg.get("params") or dict()
                if params.get("sandbox") != "danger-full-access":
                    send(dict(id=mid, error=dict(message="missing danger sandbox")))
                    continue
                send({{"id": mid, "result": {{"thread": {{"id": "thr_fake"}}}}}})
            elif method == "thread/resume":
                params = msg.get("params") or dict()
                if params.get("sandbox") != "danger-full-access":
                    send(dict(id=mid, error=dict(message="missing danger sandbox")))
                    continue
                send({{"id": mid, "result": {{"thread": {{"id": msg["params"]["threadId"]}}}}}})
            elif method == "turn/start":
                params = msg.get("params") or dict()
                if params.get("model") != "gpt-5.5":
                    send(dict(id=mid, error=dict(message="bad model " + str(params.get("model")))))
                    continue
                if params.get("sandboxPolicy") != {{"type": "dangerFullAccess"}}:
                    send(dict(id=mid, error=dict(message="missing danger sandbox policy")))
                    continue
                if params.get("summary") != "detailed":
                    send(dict(id=mid, error=dict(message="missing detailed summary")))
                    continue
                if {request_approval!r}:
                    if params.get("approvalPolicy") != "never":
                        send(dict(id=mid, error=dict(message="missing bypass approval policy")))
                        continue
                    send({{"id": mid, "result": {{"turn": {{"id": "turn_fake", "status": "inProgress"}}}}}})
                    send({{"id": 99, "method": "item/commandExecution/requestApproval", "params": {{
                        "itemId": "cmd_1", "command": "printf ok", "cwd": "/tmp"
                    }}}})
                    response = json.loads(sys.stdin.readline())
                    if response.get("id") != 99 or response.get("result", {{}}).get("decision") != "accept":
                        send({{"method": "turn/completed", "params": {{
                            "turn": {{"id": "turn_fake", "status": "failed", "error": {{"message": "approval not accepted"}}}}
                        }}}})
                        continue
                    send({{"method": "item/completed", "params": {{
                        "item": {{"type": "agentMessage", "id": "item_fake", "text": "Approval accepted"}}
                    }}}})
                    send({{"method": "turn/completed", "params": {{
                        "turn": {{"id": "turn_fake", "status": "completed"}}
                    }}}})
                    continue
                send({{"id": mid, "result": {{"turn": {{"id": "turn_fake", "status": "inProgress"}}}}}})
                if {large_delta!r}:
                    send({{"method": "item/agentMessage/delta", "params": {{"delta": "x" * 200000}}}})
                    send({{"method": "item/completed", "params": {{
                        "item": {{"type": "agentMessage", "id": "item_fake", "text": "x" * 200000}}
                    }}}})
                elif {generic_message!r}:
                    send({{"method": "item/completed", "params": {{
                        "item": {{"type": "message", "role": "assistant", "id": "item_fake", "content": [
                            {{"type": "output_text", "text": "Hello Codex"}}
                        ]}}
                    }}}})
                elif {completion_message!r}:
                    pass
                else:
                    send({{"method": "item/agentMessage/delta", "params": {{"delta": "Hello "}}}})
                    send({{"method": "item/completed", "params": {{
                        "item": {{"type": "agentMessage", "id": "item_fake", "text": "Hello Codex"}}
                    }}}})
                send({{"method": "thread/tokenUsage/updated", "params": {{
                    "usage": {{"input_tokens": 10, "output_tokens": 2}}
                }}}})
                turn = {{"id": "turn_fake", "status": "completed"}}
                if {completion_message!r}:
                    turn["lastAgentMessage"] = "Hello from completion"
                send({{"method": "turn/completed", "params": {{"turn": turn}}}})
            else:
                send({{"id": mid, "result": {{}}}})
    """))
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    return str(script)


def test_model_prefix_helpers():
    assert is_native_codex_model("codex:gpt-5.5")
    assert is_native_codex_model("codex-native:gpt-5.4")
    assert not is_native_codex_model("gpt-5.5")
    assert strip_native_codex_prefix("codex:gpt-5.5") == "gpt-5.5"
    assert strip_native_codex_prefix("codex-native:gpt-5.4") == "gpt-5.4"
    assert codex_effort("max") == "high"
    assert codex_effort("adaptive") is None


def test_app_server_streaming_turn_uses_chatgpt_auth(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-should-not-leak")
    fake = _fake_codex_bin(tmp_path, account_type="chatgpt")
    client = CodexAppServerClient(codex_bin=fake, cwd=tmp_path)
    deltas = []

    async def run():
        try:
            await client.connect()
            thread_id = await client.start_or_resume_thread(None, cwd=tmp_path)
            result = await client.run_turn(
                thread_id=thread_id,
                prompt="Say hello",
                model="codex:gpt-5.5",
                effort="medium",
                cwd=tmp_path,
                on_text_delta=lambda d: _append_async(deltas, d),
            )
        finally:
            await client.close()
        return thread_id, result

    thread_id, result = asyncio.run(run())

    assert thread_id == "thr_fake"
    assert result.thread_id == "thr_fake"
    assert result.turn_id == "turn_fake"
    assert result.text == "Hello Codex"
    assert deltas == ["Hello ", "Codex"]
    assert result.usage == {"input_tokens": 10, "output_tokens": 2}
    assert result.model == "gpt-5.5"
    assert "OPENAI_API_KEY" in os.environ


def test_app_server_enables_browser_and_computer_use_plugins(tmp_path):
    argv_log = tmp_path / "argv.json"
    fake = _fake_codex_bin(tmp_path, argv_log_path=argv_log)
    client = CodexAppServerClient(codex_bin=fake, cwd=tmp_path)

    async def run():
        try:
            await client.connect()
        finally:
            await client.close()

    asyncio.run(run())

    argv = json.loads(argv_log.read_text())
    assert argv[:2] == [str(fake), "app-server"]
    assert "--enable" in argv
    assert "builtin_mcp" in argv
    assert 'plugins."browser@openai-bundled".enabled=true' in argv
    assert 'plugins."chrome@openai-bundled".enabled=true' in argv
    assert 'plugins."computer-use@openai-bundled".enabled=true' in argv


def test_app_server_accepts_command_approval_in_bypass_mode(tmp_path):
    fake = _fake_codex_bin(tmp_path, request_approval=True)
    client = CodexAppServerClient(codex_bin=fake, cwd=tmp_path)

    async def run():
        try:
            await client.connect()
            thread_id = await client.start_or_resume_thread(None, cwd=tmp_path)
            return await client.run_turn(
                thread_id=thread_id,
                prompt="Run a command",
                model="codex:gpt-5.5",
                mode="bypass",
                cwd=tmp_path,
            )
        finally:
            await client.close()

    result = asyncio.run(run())

    assert result.status == "completed"
    assert result.text == "Approval accepted"


def test_app_server_streams_generic_assistant_message_items(tmp_path):
    fake = _fake_codex_bin(tmp_path, generic_message=True)
    client = CodexAppServerClient(codex_bin=fake, cwd=tmp_path)
    deltas = []

    async def run():
        try:
            await client.connect()
            thread_id = await client.start_or_resume_thread(None, cwd=tmp_path)
            return await client.run_turn(
                thread_id=thread_id,
                prompt="Say hello",
                model="codex:gpt-5.5",
                cwd=tmp_path,
                on_text_delta=lambda d: _append_async(deltas, d),
            )
        finally:
            await client.close()

    result = asyncio.run(run())

    assert result.text == "Hello Codex"
    assert deltas == ["Hello Codex"]


def test_app_server_streams_final_completion_message(tmp_path):
    fake = _fake_codex_bin(tmp_path, completion_message=True)
    client = CodexAppServerClient(codex_bin=fake, cwd=tmp_path)
    deltas = []

    async def run():
        try:
            await client.connect()
            thread_id = await client.start_or_resume_thread(None, cwd=tmp_path)
            return await client.run_turn(
                thread_id=thread_id,
                prompt="Say hello",
                model="codex:gpt-5.5",
                cwd=tmp_path,
                on_text_delta=lambda d: _append_async(deltas, d),
            )
        finally:
            await client.close()

    result = asyncio.run(run())

    assert result.text == "Hello from completion"
    assert deltas == ["Hello from completion"]


def test_app_server_reads_large_json_rpc_lines(tmp_path):
    fake = _fake_codex_bin(tmp_path, large_delta=True)
    client = CodexAppServerClient(codex_bin=fake, cwd=tmp_path)
    deltas = []

    async def run():
        try:
            await client.connect()
            thread_id = await client.start_or_resume_thread(None, cwd=tmp_path)
            return await client.run_turn(
                thread_id=thread_id,
                prompt="Write a long message",
                model="codex:gpt-5.5",
                cwd=tmp_path,
                on_text_delta=lambda d: _append_async(deltas, d),
            )
        finally:
            await client.close()

    result = asyncio.run(run())

    assert len(result.text) == 200000
    assert [len(d) for d in deltas] == [200000]


def test_app_server_rejects_api_key_auth(tmp_path):
    fake = _fake_codex_bin(tmp_path, account_type="apiKey")
    client = CodexAppServerClient(codex_bin=fake, cwd=tmp_path)

    async def run():
        try:
            with pytest.raises(CodexAuthError):
                await client.connect()
        finally:
            await client.close()

    asyncio.run(run())


async def _append_async(items, value):
    items.append(value)
