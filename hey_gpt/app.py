"""Setup UI; microphone and desktop actions start only through explicit controls."""
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk

from .core import Controller, State
from .model_setup import ensure_model, model_path, valid_model
from .settings import load_selectors, save_selectors

STATE_TEXT = {
    State.IDLE: "Готово. Скажи Hi ChatGPT в выбранном окне чата.",
    State.STARTING: "Жду начала записи в чате…",
    State.RECORDING: "Запись началась. Диктуй; затем скажи Stop GPT.",
    State.TRANSCRIBING: "Жду расшифровку сообщения…",
    State.REVIEW: "Текст готов. Проверь и отправь его вручную; затем нажми «Сбросить цикл».",
    State.ERROR: "Цикл остановлен после ошибки.",
}
ROLES = [("window", "1. Выбрать окно чата"), ("composer", "2. Поле сообщения"),
         ("microphone", "3. Кнопка диктовки"), ("finish", "4. Завершить запись"),
         ("send", "5. Отправить сообщение")]


class Application:
    def __init__(self, root):
        import winsound
        from .windows import WindowsAdapter, emergency_pressed
        self.beep = lambda: winsound.MessageBeep(winsound.MB_OK)
        self.emergency_pressed = emergency_pressed
        self.root = root
        self.path = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "HeyGPT" / "selectors.json"
        selectors, warning = load_selectors(self.path)
        self.adapter = WindowsAdapter(selectors)
        self.controller = Controller(self.adapter, clock=time.monotonic)
        self.events = queue.Queue()
        self.process = None
        self.ready = False
        self.mode = None
        self.capturing = False
        self.preparing = False
        self.closed = False
        self.capture_job = None
        self.last_state = None
        self.speech_error = ""
        self.devices = [None]
        self.root.title("Hey GPT — голосовое управление")
        self.root.geometry("880x760")
        self.root.minsize(800, 700)
        self.status = tk.StringVar(value=warning or "Подготовь модель, проверь команды, затем настрой кнопки чата.")
        self.auto_send = tk.BooleanVar(value=False)
        self.model_status = tk.StringVar()
        self.level = tk.IntVar(value=0)
        self.command_status = tk.StringVar(value="Команды ещё не проверены.")

        ttk.Label(root, text="Hi ChatGPT → диктовка · Stop GPT → завершение", font=("Segoe UI", 14)).pack(pady=12)
        ttk.Label(root, text="Говори название GPT по буквам: «джи пи ти». После команды сделай короткую паузу.").pack()
        speech = ttk.LabelFrame(root, text="1. Подготовка и проверка микрофона", padding=10)
        speech.pack(fill="x", padx=15, pady=10)
        ttk.Label(speech, textvariable=self.model_status).grid(row=0, column=0, columnspan=3, sticky="w")
        ttk.Button(speech, text="Подготовить модель", command=self.prepare_model).grid(row=1, column=0, pady=8, sticky="w")
        ttk.Button(speech, text="Проверить команды", command=lambda: self.start("test")).grid(row=1, column=1, padx=8)
        ttk.Button(speech, text="Остановить", command=self.pause).grid(row=1, column=2)
        ttk.Label(speech, text="Микрофон:").grid(row=2, column=0, sticky="w")
        self.device_combo = ttk.Combobox(speech, state="readonly", width=68)
        self.device_combo.grid(row=2, column=1, columnspan=2, sticky="ew")
        self.device_combo.bind("<<ComboboxSelected>>", lambda event: self.pause())
        ttk.Progressbar(speech, variable=self.level, maximum=100).grid(row=3, column=0, columnspan=3, sticky="ew", pady=8)
        ttk.Label(speech, textvariable=self.command_status, wraplength=800).grid(row=4, column=0, columnspan=3, sticky="w")
        ttk.Button(speech, text="Доступ к микрофону в Windows", command=lambda: os.startfile("ms-settings:privacy-microphone")).grid(row=5, column=0, columnspan=3, sticky="w", pady=(6, 0))
        setup = ttk.LabelFrame(root, text="2. Кнопки нужного чата", padding=10)
        setup.pack(fill="x", padx=15, pady=5)
        ttk.Label(setup, text="Нажми кнопку ниже и за 4 секунды наведи курсор на нужный элемент чата.").grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))
        self.labels = {}
        for index, (role, label) in enumerate(ROLES, 1):
            ttk.Button(setup, text=label, command=lambda r=role: self.capture(r)).grid(row=index, column=0, sticky="ew", pady=3)
            self.labels[role] = tk.StringVar()
            ttk.Label(setup, textvariable=self.labels[role], wraplength=500).grid(row=index, column=1, sticky="w", padx=10)
        ttk.Label(setup, text="Для шага 4 начни запись вручную. Для шага 5 подготовь черновик.\nПосле настройки закончи запись и очисти черновик.", wraplength=800).grid(row=6, column=0, columnspan=2, sticky="w", pady=8)
        ttk.Checkbutton(root, text="Отправлять автоматически после расшифровки (сначала проверь вручную)", variable=self.auto_send).pack(pady=6)
        actions = ttk.Frame(root)
        actions.pack(pady=8)
        ttk.Button(actions, text="Включить управление чатом", command=lambda: self.start("workflow")).pack(side="left", padx=5)
        ttk.Button(actions, text="Пауза", command=self.pause).pack(side="left", padx=5)
        ttk.Button(actions, text="Сбросить цикл", command=self.reset).pack(side="left", padx=5)
        ttk.Label(root, textvariable=self.status, wraplength=830, foreground="#174a7e").pack(padx=15, pady=8)
        ttk.Label(root, text="Ctrl+Alt+P — пауза. В режиме проверки кнопки чата не нажимаются.\nРаспознавание локальное; помощник не сохраняет аудио и сообщения.").pack(pady=4)
        self.refresh_labels()
        self.refresh_model()
        self.refresh_devices()
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.after(150, self.pump)

    def refresh_model(self):
        self.model_status.set("Модель готова. Английский речевой компонент Windows не требуется."
                              if valid_model(model_path()) else "Модель не установлена. Нужна однократная загрузка ~40 МБ.")

    def refresh_devices(self):
        names = ["Микрофон Windows по умолчанию"]
        self.devices = [None]
        try:
            import sounddevice as sd
            for index, device in enumerate(sd.query_devices()):
                if device["max_input_channels"]:
                    self.devices.append(index)
                    host = sd.query_hostapis(device["hostapi"])["name"]
                    names.append(f"{device['name']} ({host})")
        except Exception as error:
            self.status.set("Не удалось найти микрофон: " + str(error))
        self.device_combo["values"] = names
        self.device_combo.current(0)

    def refresh_labels(self):
        self.labels["window"].set(self.adapter.window_title or "Не выбрано; выбирай окно при каждом запуске")
        for role in self.labels.keys() - {"window"}:
            selector = self.adapter.selectors.get(role)
            self.labels[role].set((selector.name or selector.automation_id) if selector else "Не настроено")

    def pause(self, show_status=True):
        child, self.process = self.process, None
        if child is not None and child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=2)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=2)
        self.ready = False
        self.mode = None
        self.level.set(0)
        self.controller.reset()
        self.last_state = None
        if show_status:
            self.status.set("Прослушивание остановлено. Запись, уже начатую в чате, закончи или отмени вручную.")

    def prepare_model(self):
        if self.preparing or self.capturing:
            return
        self.pause(False)
        self.preparing = True
        self.status.set("Подготовка речевой модели…")
        def work():
            try:
                ensure_model(lambda message: self.events.put(("setup_progress", message)))
                self.events.put(("setup_done", None))
            except Exception as error:
                self.events.put(("setup_error", str(error)))
        threading.Thread(target=work, daemon=True).start()

    def capture(self, role):
        if self.capturing or self.preparing:
            return
        self.pause(False)
        self.capturing = True
        self.status.set("Наведи курсор на нужный элемент чата. Выбор через 4 секунды…")
        self.capture_job = self.root.after(4000, lambda: self.finish_capture(role))

    def finish_capture(self, role):
        self.capture_job = None
        try:
            self.adapter.capture_at_cursor(role)
            save_selectors(self.path, self.adapter.export())
            self.status.set("Элемент выбран. Продолжай настройку кнопок.")
        except Exception as error:
            self.status.set("Ошибка настройки: " + str(error))
        finally:
            self.refresh_labels()
            self.capturing = False

    def read_events(self, child):
        assert child.stdout is not None
        try:
            for line in child.stdout:
                try:
                    payload = json.loads(line)
                except ValueError:
                    continue
                if isinstance(payload, dict):
                    self.events.put((child, payload))
        finally:
            child.stdout.close()

    def start(self, mode):
        if self.capturing or self.preparing:
            return
        self.pause(False)
        self.speech_error = ""
        if not valid_model(model_path()):
            self.status.set("Сначала нажми «Подготовить модель».")
            return
        if mode == "workflow":
            missing = {"composer", "microphone", "finish", "send"} - self.adapter.selectors.keys()
            if not self.adapter.hwnd or missing:
                self.status.set("Сначала выбери окно чата и настрой все четыре элемента.")
                return
        self.controller.auto_send = self.auto_send.get()
        try:
            executable = Path(sys.executable)
            if executable.name.lower() == "pythonw.exe":
                executable = executable.with_name("python.exe")
            arguments = [str(executable), "-u", "-m", "hey_gpt.speech"]
            device = self.devices[self.device_combo.current()]
            if device is not None:
                arguments += ["--device", str(device)]
            self.process = subprocess.Popen(arguments, cwd=Path(__file__).resolve().parent.parent,
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, encoding="utf-8",
                errors="replace", creationflags=subprocess.CREATE_NO_WINDOW)
            self.mode = mode
            threading.Thread(target=self.read_events, args=(self.process,), daemon=True).start()
            self.status.set("Запускаю локальное распознавание…")
            self.command_status.set("Скажи Hi ChatGPT, затем Stop GPT. После каждой команды сделай паузу.")
        except OSError as error:
            self.status.set("Не удалось запустить распознавание: " + str(error))

    def reset(self):
        self.controller.reset()
        self.last_state = None
        self.status.set("Цикл сброшен. Очисти черновик и закончи запись в чате перед следующей командой.")

    def pump(self):
        if self.closed:
            return
        try:
            if self.process and self.emergency_pressed():
                self.pause()
            while not self.events.empty():
                source, payload = self.events.get_nowait()
                if source == "setup_progress":
                    self.status.set(payload)
                elif source in ("setup_done", "setup_error"):
                    self.preparing = False
                    self.refresh_model()
                    self.status.set("Модель готова. Нажми «Проверить команды»." if source == "setup_done"
                                    else "Ошибка подготовки модели: " + payload)
                elif source is self.process:
                    event = payload.get("event")
                    if event == "ready":
                        self.ready = True
                        self.status.set("Проверка команд включена. Скажи Hi ChatGPT и Stop GPT."
                                        if self.mode == "test" else "Слушаю. Вернись в выбранное окно чата и скажи Hi ChatGPT.")
                    elif event == "level":
                        self.level.set(payload.get("value", 0))
                    elif event == "command" and self.ready:
                        command = payload.get("command")
                        if command in ("WAKE", "STOP"):
                            self.command_status.set("Распознано: " + ("Hi ChatGPT" if command == "WAKE" else "Stop GPT"))
                            if self.mode == "workflow":
                                self.controller.command(command)
                                self.show_state()
                    elif event == "error":
                        self.speech_error = payload.get("message", "Ошибка микрофона.")
                        self.pause(False)
                        self.status.set("Ошибка: " + self.speech_error)
            if self.process and self.process.poll() is not None:
                code = self.process.returncode
                self.pause(False)
                self.status.set(self.speech_error or f"Распознавание остановилось (код {code}). Повтори проверку команд.")
            if self.ready and self.mode == "workflow":
                self.controller.tick()
                self.show_state()
        except Exception as error:
            self.pause(False)
            self.status.set("Ошибка: " + str(error))
        self.root.after(150, self.pump)

    def show_state(self):
        state = self.controller.state
        if state is not self.last_state:
            if state is State.RECORDING:
                self.beep()
            self.status.set(self.controller.error or STATE_TEXT[state])
            self.last_state = state

    def close(self):
        self.closed = True
        if self.capture_job is not None:
            self.root.after_cancel(self.capture_job)
        self.pause(False)
        self.root.destroy()


def main():
    if sys.platform != "win32":
        raise SystemExit("Hey GPT requires Windows 10/11.")
    root = tk.Tk()
    try:
        Application(root)
    except Exception as error:
        messagebox.showerror("Hey GPT — ошибка запуска", "Не удалось открыть приложение. Запусти Check.cmd.\n\n" + str(error), parent=root)
        root.destroy()
        raise
    root.mainloop()


if __name__ == "__main__":
    main()
