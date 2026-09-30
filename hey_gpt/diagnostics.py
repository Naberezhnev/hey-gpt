"""Opt-in local checks: no chat reads/writes and no recorded audio files."""
import argparse
import subprocess
import sys

from . import __version__
from .model_setup import model_path, valid_model


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--microphone", action="store_true")
    args = parser.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print("Hey GPT", __version__)
    print("Python", sys.version.split()[0])
    try:
        import tkinter as tk
        from .windows import WindowsAdapter
        root = tk.Tk()
        root.withdraw()
        root.update()
        root.destroy()
        WindowsAdapter()
        print("OK: окно настройки и Windows UI Automation")
        if not valid_model(model_path()):
            print("Нужна модель: открой Run.cmd → «Подготовить модель».")
            return 1
        from vosk import Model, SetLogLevel
        from .speech import recognizer
        SetLogLevel(-1)
        recognizer(Model(str(model_path())), 16000)
        print("OK: речевая модель и словарь команд")
        if args.microphone:
            print("Проверка микрофона 3 секунды. Аудио не сохраняется; кнопки чата не нажимаются.", flush=True)
            return subprocess.call([sys.executable, "-m", "hey_gpt.speech", "--probe", "3"])
        return 0
    except Exception as error:
        print("Ошибка:", error)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
