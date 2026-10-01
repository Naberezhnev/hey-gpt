"""Read-only discovery in the installed Codex host; no task or model turn."""
import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import threading

ROOT = Path(__file__).resolve().parents[1]


def main():
    executable = shutil.which("codex.exe") or shutil.which("codex")
    if not executable:
        raise RuntimeError("Codex CLI is required for this optional installed-host check")
    log_path = ROOT / "artifacts/validation/codex-host.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log = log_path.open("w", encoding="utf-8")
    process = subprocess.Popen([executable, "app-server"], cwd=ROOT,
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=log, text=True, encoding="utf-8",
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    messages = queue.Queue()

    def read():
        for line in process.stdout:
            try:
                messages.put(json.loads(line))
            except ValueError:
                pass

    threading.Thread(target=read, daemon=True).start()

    def send(value):
        process.stdin.write(json.dumps(value) + "\n")
        process.stdin.flush()

    def request(identity, method, params):
        send({"id": identity, "method": method, "params": params})
        while True:
            value = messages.get(timeout=40)
            if value.get("id") == identity:
                assert "error" not in value, value.get("error")
                return value["result"]

    try:
        request(1, "initialize", {"clientInfo": {"name": "hey_gpt_validation", "version": "1"},
                                  "capabilities": {"experimentalApi": True}})
        send({"method": "initialized"})
        plugins = request(3, "plugin/list", {"cwds": [str(ROOT)], "marketplaceKinds": ["local"]})
        def ours(value):
            if isinstance(value, dict):
                if value.get("name") == "hey-gpt-codex":
                    return [{key: value[key] for key in ("name", "id", "pluginId", "installed", "enabled", "errors") if key in value}]
                return [item for child in value.values() for item in ours(child)]
            if isinstance(value, list):
                return [item for child in value for item in ours(child)]
            return []
        installed = [item for item in ours(plugins) if item.get("id") == "hey-gpt-codex@hey-gpt-local"]
        assert installed and installed[0]["installed"] and installed[0]["enabled"]
        detail = request(5, "plugin/read", {"pluginName": "hey-gpt-codex", "marketplacePath":
                         str(Path(os.environ["LOCALAPPDATA"]) / "HeyGPT/CodexPlugin/.agents/plugins/marketplace.json")})
        assert detail["plugin"]["mcpServers"] == ["hey-gpt"]
        assert len(detail["plugin"]["hooks"]) == 5
        skills = request(4, "skills/list", {"cwds": [str(ROOT)], "forceReload": True})
        assert "hey-gpt-codex:voice-control" in json.dumps(skills)
        inventory = request(6, "mcpServerStatus/list", {"serverName": "hey-gpt", "detail": "toolsAndAuthOnly"})
        assert len(inventory["data"]) == 1
        assert len(inventory["data"][0]["tools"]) == 7, "Codex could not discover the seven MCP tools"
        hooks = request(2, "hooks/list", {"cwds": [str(ROOT)]})
        selected = []
        for entry in hooks["data"]:
            selected.extend(h for h in entry["hooks"]
                            if "hey-gpt-codex" in (h.get("pluginId") or "")
                            or "hey-gpt-codex" in h.get("sourcePath", ""))
            errors = [error for error in entry["errors"]
                      if "hey-gpt-codex" in error.get("path", "")]
            assert not errors, errors
        if len(selected) != 5:
            print(json.dumps({"hook_entries": [{"count": len(entry["hooks"]),
                              "errors": len(entry["errors"]), "warnings": entry["warnings"]}
                             for entry in hooks["data"]]}))
        assert len(selected) == 5, "Expected the five Hey GPT lifecycle hooks"
        assert all("HeyGPTCodex.exe" in h["command"] for h in selected)
        # Do not print unrelated plugins, hook commands, or account metadata.
        found = "hey-gpt-codex@hey-gpt-local" in json.dumps(plugins)
        assert found, "Installed Hey GPT plugin was not discovered by Codex"
        print(json.dumps({"host": "Codex app-server", "plugin_discovered": found,
                          "mcp_tools": len(inventory["data"][0]["tools"]),
                          "hooks": [{"event": h["eventName"], "trust": h["trustStatus"],
                                     "timeout": h["timeoutSec"]} for h in selected],
                          "task_created": False, "model_turn_started": False,
                          "microphone_opened": False}, ensure_ascii=False))
    finally:
        process.stdin.close()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.terminate()
            process.wait(timeout=3)
        log.close()


if __name__ == "__main__":
    main()
