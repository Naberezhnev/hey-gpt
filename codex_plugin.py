"""Entry point for the local Codex plugin and its bundled Windows runtime."""
import json
import sys

from hey_gpt.codex_service import run_service, rpc, wait_for_voice
from hey_gpt.codex_session import session_id


def hook(event):
    target = session_id(event.get("session_id"))
    response = rpc({"action": "hook", "event": event})
    if response.get("listen"):
        result = wait_for_voice(target, response.get("wait_seconds", 3500))
        if result.get("message"):
            # Documented Stop continuation: only an actual, newly dictated message.
            return {"decision": "block", "reason": result["message"]}
        if result.get("error"):
            return {"systemMessage": "Hey GPT: " + result["error"]}
        return {}
    return response


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    mode = sys.argv[1] if len(sys.argv) > 1 else "mcp"
    if mode == "mcp":
        from hey_gpt.codex_mcp import MCPServer
        MCPServer().run()
    elif mode == "service":
        try:
            run_service()
        except OSError:
            # Another process already owns this user's named pipe.
            return 1
    elif mode == "hook":
        try:
            event = json.loads(sys.stdin.read(256 * 1024))
            if sys.platform == "win32":
                from hey_gpt.codex_win import codex_parent_pid
                event["host_pid"] = codex_parent_pid()
            value = hook(event)
        except Exception as exc:
            # A plugin failure must never block the user's normal task.
            value = {"systemMessage": "Hey GPT: " + str(exc)}
        print(json.dumps(value, ensure_ascii=False), flush=True)
    elif mode == "status":
        print(json.dumps(rpc({"action": "status"}), ensure_ascii=False, indent=2))
    elif mode == "disable":
        print(json.dumps(rpc({"action": "disable"}), ensure_ascii=False))
    else:
        raise ValueError("Mode: mcp, service, hook, status, disable")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
