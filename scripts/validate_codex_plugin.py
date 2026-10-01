"""Real stdio MCP + authenticated Windows IPC, with microphone kept OFF."""
import argparse
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--exe", type=Path)
    args = parser.parse_args()
    folder = ROOT / "artifacts/validation"
    folder.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="codex-plugin-", dir=folder) as temporary:
        assert Path(temporary).resolve().is_relative_to(folder.resolve())
        env = dict(os.environ, HEY_GPT_CODEX_DATA=temporary)
        command = [str(args.exe.resolve()), "mcp"] if args.exe else [sys.executable, str(ROOT / "codex_plugin.py"), "mcp"]
        proc = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                encoding="utf-8", text=True, env=env,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        messages = queue.Queue()
        def read():
            for line in proc.stdout:
                try:
                    messages.put(json.loads(line))
                except ValueError:
                    messages.put({"bad_protocol_output": True})
        threading.Thread(target=read, daemon=True).start()
        def request(identity, method, params):
            proc.stdin.write(json.dumps({"jsonrpc": "2.0", "id": identity, "method": method, "params": params}) + "\n")
            proc.stdin.flush()
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                value = messages.get(timeout=15)
                assert not value.get("bad_protocol_output"), value
                if value.get("id") == identity:
                    assert "error" not in value, value
                    return value["result"]
            raise TimeoutError(method)
        try:
            initialized = request(1, "initialize", {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "hey-gpt-validation", "version": "1"}})
            proc.stdin.write('{"jsonrpc":"2.0","method":"notifications/initialized"}\n')
            proc.stdin.flush()
            discovered = request(2, "tools/list", {})
            assert len(discovered["tools"]) == 7
            result = request(3, "tools/call", {"name": "voice_status", "arguments": {}})
            assert not result.get("isError"), result
            status = json.loads(result["content"][0]["text"])
            assert status["enabled"] is False and status["microphone_ready"] is False
            negative = request(4, "tools/call", {"name": "voice_enable", "arguments": {"session_id": "task-A", "command": "not allowed"}})
            assert negative["isError"]
            # Hook command uses the exact same executable from a different cwd.
            hook_command = [str(args.exe.resolve()), "hook"] if args.exe else [sys.executable, str(ROOT / "codex_plugin.py"), "hook"]
            if args.exe:
                hook_config = json.loads((ROOT / "plugins/hey-gpt-codex/hooks/hooks.json").read_text(encoding="utf-8"))
                command_windows = hook_config["hooks"]["SessionStart"][0]["hooks"][0]["commandWindows"]
                env["PLUGIN_ROOT"] = str(args.exe.resolve().parent.parent.parent)
                hook_command = ["powershell.exe", "-NoProfile", "-Command",
                                "[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false); " + command_windows]
            response = subprocess.run(hook_command, input=json.dumps({"session_id": "test-session", "hook_event_name": "SessionStart", "source": "startup"}),
                                      stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8", env=env,
                                      cwd=temporary, timeout=15, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            assert response.returncode == 0, response.stderr
            output = json.loads(response.stdout)
            assert "test-session" in output["hookSpecificOutput"]["additionalContext"]
            result = request(5, "tools/call", {"name": "voice_status"})
            status = json.loads(result["content"][0]["text"])
            assert status["enabled"] is False
            print(json.dumps({"runtime": "frozen" if args.exe else "source", "mcp_startup": True,
                              "tools": len(discovered["tools"]), "ipc": True, "hook": True,
                              "manifest_windows_command": bool(args.exe),
                              "microphone_opened": False, "invalid_arguments_rejected": True}, ensure_ascii=False))
        finally:
            proc.stdin.close()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.terminate()
                proc.wait(timeout=3)
            # Use this test's private pipe/key; never shut down the user's service.
            from hey_gpt.codex_service import rpc
            previous = os.environ.get("HEY_GPT_CODEX_DATA")
            os.environ["HEY_GPT_CODEX_DATA"] = temporary
            try:
                rpc({"action": "shutdown"}, start=False)
                time.sleep(.6)
            finally:
                if previous is None:
                    os.environ.pop("HEY_GPT_CODEX_DATA", None)
                else:
                    os.environ["HEY_GPT_CODEX_DATA"] = previous


if __name__ == "__main__":
    main()
