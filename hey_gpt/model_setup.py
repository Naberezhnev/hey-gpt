"""One-time HTTPS model download. Never downloads during microphone listening."""
import os
from pathlib import Path, PurePosixPath
import tempfile
import urllib.request
import zipfile

MODEL_NAME = "vosk-model-small-en-us-0.15"
MODEL_URL = "https://alphacephei.com/vosk/models/" + MODEL_NAME + ".zip"
REQUIRED = ("am/final.mdl", "conf/model.conf", "graph/HCLr.fst", "graph/Gr.fst")


def model_path():
    return Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "HeyGPT" / "models" / MODEL_NAME


def valid_model(path):
    return all((Path(path) / part).is_file() for part in REQUIRED)


def extract_model(archive, destination):
    """Validate every member before writing; the installer owns this temp folder."""
    destination = Path(destination).resolve()
    with zipfile.ZipFile(archive) as source:
        if sum(item.file_size for item in source.infolist()) > 250 * 1024 * 1024:
            raise ValueError("Model archive is unexpectedly large")
        for item in source.infolist():
            path = PurePosixPath(item.filename)
            if (path.is_absolute() or ".." in path.parts or "\\" in item.filename
                    or not path.parts or path.parts[0] != MODEL_NAME
                    or ((item.external_attr >> 16) & 0o170000) == 0o120000):
                raise ValueError("Unsafe model archive member")
            if not (destination / item.filename).resolve().is_relative_to(destination):
                raise ValueError("Model archive escapes destination")
        source.extractall(destination)
    result = destination / MODEL_NAME
    if not valid_model(result):
        raise ValueError("Model archive is incomplete")
    return result


def ensure_model(progress=print):
    target = model_path()
    if valid_model(target):
        return target
    if target.exists():
        raise RuntimeError("Папка речевой модели повреждена: " + str(target))
    target.parent.mkdir(parents=True, exist_ok=True)
    progress("Загрузка локальной речевой модели (~40 МБ)…")
    # TemporaryDirectory can only remove the installer-created folder here.
    with tempfile.TemporaryDirectory(prefix="hey-gpt-", dir=target.parent) as temporary:
        archive = Path(temporary) / "model.zip"
        request = urllib.request.Request(MODEL_URL, headers={"User-Agent": "HeyGPT/0.2"})
        with urllib.request.urlopen(request, timeout=30) as response, archive.open("wb") as output:
            total = int(response.headers.get("Content-Length", 0))
            received = 0
            announced = -1
            while chunk := response.read(256 * 1024):
                received += len(chunk)
                if received > 100 * 1024 * 1024:
                    raise ValueError("Model download is unexpectedly large")
                output.write(chunk)
                percent = int(received * 100 / total) if total else 0
                if percent // 10 > announced:
                    progress(f"Загрузка модели: {percent}%" if total else f"Загружено: {received // 1024 // 1024} МБ")
                    announced = percent // 10
            if total and received != total:
                raise ValueError("Model download was interrupted")
        progress("Распаковка и проверка модели…")
        extracted = extract_model(archive, temporary)
        try:
            extracted.rename(target)
        except OSError:
            # A second app instance may have completed the same installation.
            if not valid_model(target):
                raise
    progress("Локальная модель готова.")
    return target


if __name__ == "__main__":
    import sys
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    try:
        print(ensure_model())
    except Exception as error:
        print("Не удалось подготовить модель:", error)
        raise SystemExit(1)
