"""Include hidden compatibility files and inspect the Windows plugin archive."""
import hashlib
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
plugin = ROOT / "plugins/hey-gpt-codex"
manifest = json.loads((plugin / "plugin.json").read_text(encoding="utf-8"))
assert manifest["name"] == plugin.name
assert (plugin / "runtime/HeyGPTCodex/HeyGPTCodex.exe").is_file()
assert len(manifest["extensions"]["com.openai"]["interface"]["shortDescription"]) <= 30
archive = ROOT / "artifacts/Hey_GPT_Codex_Plugin_v0_1_0_Windows.zip"
with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as output:
    for path in sorted(plugin.rglob("*")):
        if path.is_symlink():
            raise ValueError("Symlinks are not allowed in the plugin archive")
        if path.is_file():
            if path.name in ("ipc.key", "preferences.json") or path.suffix in (".wav", ".pyc"):
                raise ValueError("Unexpected private or development file in plugin")
            output.write(path, path.relative_to(plugin.parent).as_posix())
with zipfile.ZipFile(archive) as output:
    names = set(output.namelist())
    for path in ("plugin.json", ".codex-plugin/plugin.json", ".mcp.json", "mcp.json", "hooks/hooks.json",
                 "skills/voice-control/SKILL.md", "Install.cmd", "README_RU.md",
                 "LICENSE", "THIRD_PARTY.md", "DEPENDENCY_LICENSES.txt"):
        assert "hey-gpt-codex/" + path in names, path
    assert output.testzip() is None
print(json.dumps({"archive": str(archive), "bytes": archive.stat().st_size,
                  "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(), "files": len(names)}, ensure_ascii=False))
