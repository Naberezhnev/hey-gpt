"""Compact dashboard with explicit listening modes and separate setup."""
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import messagebox
import customtkinter as ctk
from .core import Controller, State
from .model_setup import ensure_model, model_path, valid_model
from .notifications import Notifications
from .settings import load_selectors, save_selectors, load_preferences, save_preferences
from .briefing import make_briefing

BG, INK, MUTED, BLUE = "#F3F5F9", "#17283F", "#637187", "#2364E8"
STATE_TEXT = {
    State.IDLE: "Скажи Hi ChatGPT, Hi GPT или «Привет джи пи ти». После сигнала диктуй сообщение.",
    State.STARTING: "Включаю диктовку в выбранном чате…",
    State.RECORDING: "Диктуй. Для завершения скажи Stop GPT или «Стоп джи пи ти», затем сделай паузу.",
    State.TRANSCRIBING: "Чат расшифровывает запись. Жду готовый текст…",
    State.REVIEW: "Текст готов к проверке. Отправь его в чате; следующая команда начнёт новый цикл.",
    State.SENDING: "Проверяю, что сообщение отправлено…",
    State.WAITING: "Жду завершения ответа. После него прозвучит сигнал или краткая сводка.",
    State.ERROR: "Исправь причину и повтори голосовую команду.",
    State.PAUSING: "Останавливаю запись. Этот черновик отправлен не будет.",
    State.PAUSED: "Действия на паузе. Скажи Hi GPT для продолжения. Микрофон слушает команды.",
}
STATE_TITLES = {State.IDLE: "Слушаю команду", State.STARTING: "Начинаю запись",
    State.RECORDING: "Можно говорить", State.TRANSCRIBING: "Готовлю сообщение",
    State.REVIEW: "Проверь текст", State.SENDING: "Отправляю", State.WAITING: "Задача выполняется",
    State.ERROR: "Требуется внимание", State.PAUSING: "Отменяю диктовку", State.PAUSED: "Действия на паузе"}
ROLES = [("window", "Выбрать окно курсором"), ("composer", "Поле сообщения"),
         ("microphone", "Кнопка диктовки"), ("finish", "Завершить запись"), ("send", "Отправить")]

class Application:
    def __init__(self, root, replay_wave=None):
        from .windows import WindowsAdapter, emergency_pressed
        self.root, self.emergency_pressed = root, emergency_pressed
        self.replay_wave = replay_wave
        self.path = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "HeyGPT" / "selectors.json"
        selectors, warning = load_selectors(self.path)
        self.adapter = WindowsAdapter(selectors)
        self.controller = Controller(self.adapter, clock=time.monotonic)
        self.events = queue.Queue()
        self.notifications = Notifications(activity=lambda active: self.events.put(("narration", active)))
        self.preferences_path = self.path.with_name("preferences.json")
        preferences = load_preferences(self.preferences_path)
        self.notifications.voice_id = preferences.get("voice_id", "")
        self.last_briefing = None
        self.narrating = False
        self._voice_names = []
        self._voice_ids = []
        self._shown_audio_error = ""
        self.process = None
        self.ready = False
        self.mode = None
        self.capturing = self.preparing = self.closed = False
        self.closing = False
        self.capture_job = self.last_state = None
        self.speech_error = ""
        self.next_monitor = 0
        self.devices, self.device_names = [None], ["Микрофон Windows по умолчанию"]
        self.windows = []
        self.status = tk.StringVar(value=warning or "Выбери чат в настройках, затем включи помощника.")
        self.auto_send, self.sound = tk.BooleanVar(value=True), tk.BooleanVar(value=True)
        self.voice_summary = tk.BooleanVar(value=preferences.get("voice_summary", False))
        self.model_status, self.level = tk.StringVar(), tk.IntVar(value=0)
        self.command_status = tk.StringVar(value="Микрофон выключен")
        self.mode_text = tk.StringVar(value="НА ПАУЗЕ")
        self.title_text = tk.StringVar(value="Готов к разговору")
        self.target_text = tk.StringVar(value="Чат ещё не выбран")
        root.title("Hey GPT — голосовой помощник")
        root.geometry("720x700")
        root.minsize(640, 620)
        root.configure(**({"fg_color": BG} if isinstance(root, ctk.CTk) else {"bg": BG}))
        ctk.set_appearance_mode("light")
        self.build_ui()
        self.root.after(500, self.refresh_voices)
        self.refresh_labels()
        self.refresh_model()
        self.refresh_devices()
        self.refresh_windows()
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.after(100, self.pump)

    def label(self, parent, text="", variable=None, size=14, color=INK, **kwargs):
        return ctk.CTkLabel(parent, text=text, textvariable=variable, font=("Segoe UI", size), text_color=color, **kwargs)

    def build_ui(self):
        top = ctk.CTkFrame(self.root, fg_color=BG)
        top.pack(fill="x", padx=28, pady=(22, 12))
        ctk.CTkLabel(top, text="H", width=44, height=44, corner_radius=14, fg_color=BLUE,
            text_color="white", font=("Segoe UI", 24, "bold")).pack(side="left")
        self.label(top, "Hey GPT", size=24).pack(side="left", padx=12)
        self.label(top, "Продолжай голосом", size=12, color=MUTED).pack(side="right")
        self.tabs = ctk.CTkTabview(self.root, fg_color=BG, segmented_button_selected_color=BLUE)
        self.tabs.pack(fill="both", expand=True, padx=22, pady=(0, 10))
        home, setup = self.tabs.add("Помощник"), self.tabs.add("Настройки")
        self.label(home, "Продолжай, где бы ты ни был", size=27, anchor="w").pack(fill="x", pady=(18, 4))
        self.label(home, "Голосом запускай диктовку и узнавай, когда ответ готов.", color=MUTED,
            anchor="w").pack(fill="x", pady=(0, 18))
        card = ctk.CTkFrame(home, fg_color="white", corner_radius=20)
        card.pack(fill="both", expand=True)
        self.label(card, variable=self.mode_text, size=12, color=BLUE).pack(pady=(24, 8))
        self.label(card, variable=self.title_text, size=28).pack(pady=(0, 12))
        self.meter = ctk.CTkProgressBar(card, width=230, height=6, progress_color=BLUE)
        self.meter.pack(pady=(0, 12))
        self.meter.set(0)
        self.label(card, variable=self.command_status, size=12, color=MUTED).pack()
        self.label(card, variable=self.status, size=14, wraplength=540, height=80).pack(fill="x", padx=22, pady=14)
        self.main_button = ctk.CTkButton(card, text="Включить помощника", height=46, width=250,
            corner_radius=12, font=("Segoe UI", 15), fg_color=BLUE, command=self.toggle)
        self.main_button.pack(pady=(0, 16))
        ctk.CTkButton(card, text="Пауза действий · без отправки", fg_color="transparent", text_color=MUTED,
            hover_color=BG, command=self.suspend).pack(pady=(0, 8))
        ctk.CTkButton(card, text="Повторить сводку / вопрос", fg_color="transparent", text_color=BLUE,
            hover_color=BG, command=self.repeat_briefing).pack(pady=(0, 8))
        self.label(card, variable=self.target_text, size=12, color=MUTED, wraplength=520).pack(pady=(0, 22))
        guide = ctk.CTkFrame(home, fg_color=BG)
        guide.pack(fill="x", pady=(18, 8))
        for number, name, detail in [("01", "Позови", "Hi GPT / Привет GPT"),
                ("02", "Продиктуй", "После короткого сигнала"), ("03", "Продолжай", "Stop GPT → отправка")]:
            part = ctk.CTkFrame(guide, fg_color=BG)
            part.pack(side="left", expand=True, fill="x")
            self.label(part, number + "  " + name).pack(anchor="w")
            self.label(part, detail, size=11, color=MUTED).pack(anchor="w", pady=4)
        self.label(home, "«Пауза GPT» — без отправки  ·  Ctrl+Alt+P — выключить микрофон",
            size=11, color=MUTED).pack(pady=(8, 0))
        scroll = ctk.CTkScrollableFrame(setup, fg_color="white", corner_radius=16)
        scroll.pack(fill="both", expand=True, pady=(12, 0))
        self.label(scroll, "Чат для голосового управления", size=20, anchor="w").pack(fill="x", padx=14, pady=(16, 8))
        self.label(scroll, "Открой нужный разговор. Выбери его окно и привяжи текущую вкладку.",
            color=MUTED, wraplength=560, anchor="w").pack(fill="x", padx=14, pady=(0, 10))
        row = ctk.CTkFrame(scroll, fg_color="transparent")
        row.pack(fill="x", padx=14)
        self.window_combo = ctk.CTkComboBox(row, state="readonly", width=380, values=["Выбери окно"])
        self.window_combo.pack(side="left", fill="x", expand=True)
        ctk.CTkButton(row, text="Обновить", width=100, command=self.refresh_windows).pack(side="left", padx=(8, 0))
        ctk.CTkButton(scroll, text="Подключить выбранный чат", height=38, command=self.bind_selected).pack(fill="x", padx=14, pady=10)
        self.label(scroll, variable=self.target_text, size=12, color=MUTED, wraplength=560).pack(padx=14)
        self.label(scroll, "Микрофон и команды", size=20, anchor="w").pack(fill="x", padx=14, pady=(22, 10))
        self.device_combo = ctk.CTkComboBox(scroll, state="readonly", command=lambda value: self.pause())
        self.device_combo.pack(fill="x", padx=14)
        self.label(scroll, variable=self.model_status, size=12, color=MUTED, wraplength=560).pack(padx=14, pady=8)
        row = ctk.CTkFrame(scroll, fg_color="transparent")
        row.pack(fill="x", padx=14)
        ctk.CTkButton(row, text="Загрузить модели", command=self.prepare_model).pack(side="left", expand=True, padx=(0, 6))
        ctk.CTkButton(row, text="Проверить команды", command=lambda: self.start("test")).pack(side="left", expand=True)
        self.label(scroll, "В проверке кнопки чата не нажимаются. GPT произноси по буквам: «джи пи ти».",
            color=MUTED, size=12, wraplength=560).pack(padx=14, pady=10)
        ctk.CTkSwitch(scroll, text="Автоматически отправлять после расшифровки", variable=self.auto_send,
            command=lambda: setattr(self.controller, "auto_send", self.auto_send.get())).pack(anchor="w", padx=14, pady=8)
        ctk.CTkSwitch(scroll, text="Звуковые уведомления", variable=self.sound,
            command=lambda: setattr(self.notifications, "enabled", self.sound.get())).pack(anchor="w", padx=14, pady=8)
        self.audio_mode = ctk.CTkComboBox(scroll, state="readonly", values=["Короткие сигналы", "Голос Windows"],
            command=lambda value: setattr(self.notifications, "mode", "voice" if value == "Голос Windows" else "tones"))
        self.audio_mode.set("Короткие сигналы")
        self.audio_mode.pack(fill="x", padx=14, pady=8)
        ctk.CTkButton(scroll, text="Проверить уведомление о готовности", fg_color=MUTED,
            command=lambda: self.notifications.say("Ответ готов")).pack(anchor="w", padx=14, pady=8)
        self.label(scroll, "Краткая сводка и вопросы", size=20, anchor="w").pack(fill="x", padx=14, pady=(22, 10))
        ctk.CTkSwitch(scroll, text="Зачитывать сводку и вопросы после ответа", variable=self.voice_summary,
            command=self.change_briefing).pack(anchor="w", padx=14, pady=8)
        self.label(scroll, "При включении к твоим сообщениям добавляется просьба к GPT написать сводку. "
            "Отдельный API не используется. Вопросы читаются с вариантами ответа. Скажи «Повтори», чтобы услышать ещё раз.",
            color=MUTED, size=12, wraplength=560, justify="left").pack(fill="x", padx=14, pady=8)
        self.voice_combo = ctk.CTkComboBox(scroll, state="readonly", values=["Голос Windows по умолчанию"],
            command=self.select_voice)
        self.voice_combo.set("Голос Windows по умолчанию")
        self.voice_combo.pack(fill="x", padx=14, pady=8)
        ctk.CTkButton(scroll, text="Прослушать выбранный голос", fg_color=MUTED,
            command=lambda: self.notifications.speak("Привет. Я буду зачитывать краткие итоги и вопросы из твоего чата.")).pack(anchor="w", padx=14, pady=8)
        ctk.CTkButton(scroll, text="Проверить чтение последнего ответа", fg_color=MUTED,
            command=self.read_briefing).pack(anchor="w", padx=14, pady=8)
        self.label(scroll, "Во время озвучки команды временно не распознаются, чтобы помощник не слышал себя. "
            "После озвучки скажи Hi GPT, продиктуй ответ и закончи Stop GPT. Ctrl+Alt+P сразу останавливает звук и микрофон.",
            color=MUTED, size=12, wraplength=560, justify="left").pack(fill="x", padx=14, pady=8)
        self.label(scroll, "Последняя сводка и вопросы", size=14, anchor="w").pack(fill="x", padx=14, pady=(8, 4))
        self.readout_box = ctk.CTkTextbox(scroll, height=140, wrap="word")
        self.readout_box.pack(fill="x", padx=14, pady=8)
        self.readout_box.configure(state="disabled")
        ctk.CTkButton(scroll, text="Проверить запуск диктовки", fg_color=MUTED,
            command=self.check_dictation).pack(anchor="w", padx=14, pady=8)
        self.label(scroll, "Ручная настройка элементов", size=20, anchor="w").pack(fill="x", padx=14, pady=(22, 4))
        self.label(scroll, "Если кнопки не найдены: нажми шаг и за 4 секунды наведи курсор на элемент. Для завершения сначала начни запись; для отправки подготовь черновик.",
            color=MUTED, size=12, wraplength=560, justify="left").pack(fill="x", padx=14, pady=8)
        self.labels = {}
        for role, name in ROLES:
            row = ctk.CTkFrame(scroll, fg_color="transparent")
            row.pack(fill="x", padx=14, pady=4)
            ctk.CTkButton(row, text=name, width=210, fg_color=MUTED, command=lambda r=role: self.capture(r)).pack(side="left")
            self.labels[role] = tk.StringVar()
            self.label(row, variable=self.labels[role], size=11, color=MUTED, wraplength=300).pack(side="left", padx=12)
        self.label(scroll, "После настройки останови запись и очисти тестовый черновик в чате.", size=12,
            color=MUTED, wraplength=560).pack(padx=14, pady=(8, 20))

    def refresh_model(self):
        en, ru = valid_model(model_path()), valid_model(model_path("ru"))
        self.model_status.set("Английские и русские команды готовы." if en and ru else
            "Английские команды готовы. Загрузи модель для «Привет GPT»." if en else "Загрузка двух моделей: около 85 МБ, один раз.")

    def refresh_devices(self):
        try:
            import sounddevice as sd
            for index, device in enumerate(sd.query_devices()):
                if device["max_input_channels"] and sd.query_hostapis(device["hostapi"])["name"] == "Windows WASAPI":
                    self.devices.append(index)
                    self.device_names.append(device["name"])
        except Exception as error:
            self.status.set("Не удалось найти микрофон: " + str(error))
        self.device_combo.configure(values=self.device_names)
        self.device_combo.set(self.device_names[0])

    def refresh_windows(self):
        self.windows = self.adapter.available_windows()
        self.window_combo.configure(values=[name for hwnd, name in self.windows] or ["Открой ChatGPT или Codex"])
        self.window_combo.set(self.windows[0][1] if self.windows else "Открой ChatGPT или Codex")

    def bind_selected(self):
        if self.capturing or self.preparing:
            return
        self.pause(False)
        if self.controller.state is State.PAUSING:
            self.status.set("Дождись остановки записи перед сменой чата.")
            return
        try:
            index = [name for hwnd, name in self.windows].index(self.window_combo.get())
            self.adapter.bind_window(self.windows[index][0])
            self.clear_briefing()
            self.adapter.discover()
            save_selectors(self.path, self.adapter.export())
            self.status.set("Чат подключён. Включи помощника и скажи Hi GPT.")
            self.tabs.set("Помощник")
        except Exception as error:
            self.status.set("Подключение: " + str(error))
        self.refresh_labels()

    def refresh_labels(self):
        self.target_text.set("Чат: " + self.adapter.window_title if self.adapter.hwnd else "Чат ещё не выбран")
        self.labels["window"].set(self.adapter.window_title or "Выбирай при каждом запуске")
        for role in self.labels.keys() - {"window"}:
            selector = self.adapter.selectors.get(role)
            self.labels[role].set((selector.name or selector.automation_id) if selector else "Не настроено")

    def toggle(self):
        self.pause() if self.process else self.start("workflow")

    def pause(self, show_status=True):
        self.notifications.stop()
        if self.mode == "workflow" and self.process:
            self.controller.suspend()
        child, self.process = self.process, None
        if child is not None and child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=2)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=2)
        if child is not None and getattr(child, "stdin", None):
            child.stdin.close()
        self.ready, self.mode = False, None
        self.level.set(0)
        self.meter.set(0)
        if self.controller.state is not State.PAUSING:
            self.controller.reset()
        self.last_state = None
        self.mode_text.set("НА ПАУЗЕ")
        self.title_text.set("Микрофон выключен")
        self.command_status.set("Команды не прослушиваются")
        self.main_button.configure(text="Включить помощника", fg_color=BLUE)
        if show_status:
            self.status.set("Микрофон выключен. Автоматическая отправка отменена." if self.controller.state is not State.PAUSING
                else "Микрофон выключен. Завершаю запись в чате без отправки…")

    def suspend(self):
        self.notifications.stop()
        if self.mode == "workflow":
            self.controller.command("PAUSE")
            self.show_state()
        else:
            self.pause()

    def prepare_model(self):
        if self.preparing or self.capturing:
            return
        self.pause(False)
        if self.controller.state is State.PAUSING:
            self.status.set("Сначала дождись остановки записи; затем загрузи модели.")
            return
        self.preparing = True
        self.status.set("Загружаю локальные речевые модели…")
        self.tabs.set("Помощник")
        def work():
            try:
                for language in ("en", "ru"):
                    ensure_model(lambda message: self.events.put(("setup_progress", message)), language)
                self.events.put(("setup_done", None))
            except Exception as error:
                self.events.put(("setup_error", str(error)))
        threading.Thread(target=work, daemon=True).start()

    def capture(self, role):
        if self.capturing or self.preparing:
            return
        self.pause(False)
        if self.controller.state is State.PAUSING:
            self.status.set("Дождись остановки записи перед настройкой элементов.")
            return
        self.capturing = True
        self.status.set("Наведи курсор на нужный элемент чата. Выбор через 4 секунды…")
        self.tabs.set("Помощник")
        self.capture_job = self.root.after(4000, lambda: self.finish_capture(role))

    def finish_capture(self, role):
        self.capture_job = None
        try:
            self.adapter.capture_at_cursor(role)
            if role == "window":
                self.clear_briefing()
            save_selectors(self.path, self.adapter.export())
            self.status.set("Элемент выбран. Продолжи настройку или включи помощника.")
        except Exception as error:
            self.status.set("Ошибка настройки: " + str(error))
        finally:
            self.refresh_labels()
            self.capturing = False

    def read_events(self, child):
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
        if self.controller.state is State.PAUSING:
            self.status.set("Дождись остановки текущей записи перед новым запуском.")
            return
        self.speech_error = ""
        if not valid_model(model_path()):
            self.status.set("Загрузи модели в настройках.")
            return
        if mode == "workflow" and (not self.adapter.hwnd or {"composer", "microphone", "finish", "send"} - self.adapter.selectors.keys()):
            self.status.set("Подключи нужный чат в настройках.")
            self.tabs.set("Настройки")
            return
        self.controller.auto_send = self.auto_send.get()
        self.controller.voice_summary = self.voice_summary.get()
        try:
            if getattr(sys, "frozen", False):
                arguments = [str(Path(sys.executable).parent / "voice" / "HeyGPTVoice.exe")]
            else:
                executable = Path(sys.executable)
                if executable.name.lower() == "pythonw.exe":
                    executable = executable.with_name("python.exe")
                arguments = [str(executable), "-u", "-m", "hey_gpt.speech"]
            device = self.devices[self.device_names.index(self.device_combo.get())]
            if device is not None:
                arguments += ["--device", str(device)]
            if self.replay_wave:
                arguments += ["--wav", str(self.replay_wave), "--keep-alive"]
            self.process = subprocess.Popen(arguments,
                cwd=Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent,
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, encoding="utf-8",
                stdin=subprocess.PIPE, errors="replace", creationflags=subprocess.CREATE_NO_WINDOW)
            self.mode = mode
            threading.Thread(target=self.read_events, args=(self.process,), daemon=True).start()
            self.status.set("Запускаю локальное распознавание…")
            self.title_text.set("Подключаю микрофон")
            self.mode_text.set("СИНТЕТИЧЕСКИЙ ТЕСТ" if self.replay_wave else "ПРОВЕРКА КОМАНД" if mode == "test" else "ГОЛОСОВОЕ УПРАВЛЕНИЕ")
            self.main_button.configure(text="Выключить микрофон", fg_color=INK)
            self.tabs.set("Помощник")
        except OSError as error:
            self.status.set("Не удалось запустить распознавание: " + str(error))

    def reset(self):
        self.controller.reset()
        self.last_state = None

    def check_dictation(self):
        if self.capturing or self.preparing:
            return
        self.pause(False)
        if self.controller.state is State.PAUSING:
            self.status.set("Дождись остановки предыдущей записи.")
            return
        self.controller.command("WAKE")
        self.show_state()
        if self.controller.state is State.STARTING:
            self.root.after(1500, self.finish_dictation_check)
        self.tabs.set("Помощник")

    def finish_dictation_check(self):
        if self.closed:
            return
        self.controller.tick()
        if self.controller.state is State.RECORDING:
            self.controller.command("STOP")
            if self.controller.state is State.ERROR:
                self.show_state()
                return
            self.title_text.set("Диктовка работает")
            self.status.set("Запуск и остановка диктовки проверены. Если чат создал тестовый черновик, очисти его перед включением помощника.")
            self.notifications.say("Диктовка работает")
        else:
            self.controller.fail(RuntimeError("Кнопка нажата, но начало записи не подтверждено. Проверь настройку диктовки."))
            self.show_state()

    def pump(self):
        if self.closed:
            return
        try:
            if self.process and self.emergency_pressed():
                self.pause()
            while not self.events.empty():
                source, payload = self.events.get_nowait()
                if source == "narration":
                    self.narrating = payload
                    self.mute_worker(payload)
                    if not payload and self.mode == "workflow" and self.controller.state is State.IDLE:
                        self.title_text.set("Жду твоего ответа" if self.last_briefing and self.last_briefing.questions else "Слушаю команду")
                elif source == "setup_progress":
                    self.status.set(payload)
                elif source in ("setup_done", "setup_error"):
                    self.preparing = False
                    self.refresh_model()
                    self.status.set("Модели готовы. Подключи чат и включи помощника." if source == "setup_done" else "Ошибка загрузки: " + payload)
                elif source is self.process:
                    event = payload.get("event")
                    if event == "ready":
                        self.ready = True
                        self.title_text.set("Проверка микрофона" if self.mode == "test" else "Слушаю команду")
                        self.status.set("Скажи Hi GPT или «Привет джи пи ти», затем Stop GPT. В этом режиме чат не управляется." if self.mode == "test" else STATE_TEXT[State.IDLE])
                        self.command_status.set("Микрофон: " + payload.get("device", "подключён"))
                    elif event == "level":
                        self.level.set(payload.get("value", 0))
                        self.meter.set(min(1, payload.get("value", 0) / 30))
                    elif event == "command" and self.ready:
                        command = payload.get("command")
                        if self.narrating:
                            continue
                        if command in ("WAKE", "STOP", "PAUSE", "REPEAT"):
                            self.command_status.set(time.strftime("%H:%M:%S") + " · Распознано: " + {"WAKE": "Hi ChatGPT / Привет GPT", "STOP": "Stop GPT", "PAUSE": "Пауза GPT", "REPEAT": "Повтори"}[command])
                            if self.mode == "workflow":
                                if command == "REPEAT":
                                    self.repeat_briefing()
                                else:
                                    if command in ("WAKE", "PAUSE") and not self.notifications.stop():
                                        self.status.set("Озвучка ещё останавливается. Повтори команду через секунду.")
                                        continue
                                    self.controller.command(command)
                                    self.show_state()
                    elif event == "error":
                        self.speech_error = payload.get("message", "Ошибка микрофона.")
                        self.pause(False)
                        self.status.set("Ошибка: " + self.speech_error)
                        self.title_text.set("Проверь микрофон")
                        self.notifications.say("Микрофон отключён. Проверь подключение.")
            if self.process and self.process.poll() is not None:
                code = self.process.returncode
                self.pause(False)
                self.status.set(self.speech_error or f"Распознавание остановилось (код {code}). Включи помощника снова.")
            if self.ready and self.mode == "workflow":
                now = time.monotonic()
                if self.controller.state not in (State.IDLE, State.WAITING) or now >= self.next_monitor:
                    self.controller.observe_current()
                    self.controller.tick()
                    self.next_monitor = now + 1
                    self.show_state()
            elif self.controller.state is State.PAUSING:
                self.controller.tick()
                self.show_state()
            audio_error = self.notifications.error
            if isinstance(audio_error, str) and audio_error and audio_error != self._shown_audio_error:
                self._shown_audio_error = audio_error
                self.status.set(audio_error)
                self.title_text.set("Проверь озвучку")
        except Exception as error:
            self.pause(False)
            self.status.set("Ошибка: " + str(error))
        self.root.after(100, self.pump)

    def show_state(self):
        state = self.controller.state
        if state is not self.last_state:
            self.title_text.set(STATE_TITLES[state])
            self.status.set(self.controller.error or STATE_TEXT[state])
            if state is State.RECORDING:
                self.notifications.tone("ready")
            elif state is State.PAUSED:
                self.notifications.tone("pause")
            phrases = {State.WAITING: "Сообщение отправлено" if self.controller.sent_by_us else "Задача выполняется",
                State.REVIEW: "Текст готов. Проверь сообщение", State.ERROR: "Нужна помощь. Проверь окно помощника"}
            if state in phrases:
                self.notifications.say(phrases[state])
            elif state is State.IDLE and self.last_state is State.WAITING:
                if self.voice_summary.get():
                    self.clear_briefing()
                    self.read_briefing()
                else:
                    self.notifications.say("Ответ готов")
            self.last_state = state

    def mute_worker(self, muted):
        if self.process and self.process.poll() is None and self.process.stdin:
            try:
                self.process.stdin.write(json.dumps({"mute": bool(muted)}) + "\n")
                self.process.stdin.flush()
            except (OSError, ValueError):
                pass

    def save_voice_preferences(self):
        try:
            save_preferences(self.preferences_path, {"voice_summary": self.voice_summary.get(),
                "voice_id": self.notifications.voice_id})
        except OSError as error:
            self.status.set("Настройки голоса не сохранены: " + str(error))

    def change_briefing(self):
        self.controller.voice_summary = self.voice_summary.get()
        if not self.voice_summary.get():
            self.notifications.stop()
        self.save_voice_preferences()

    def refresh_voices(self):
        if self.closed:
            return
        voices = self.notifications.voices
        if voices:
            self._voice_ids = [""] + [identifier for identifier, name in voices]
            self._voice_names = ["Голос Windows по умолчанию"] + [name for identifier, name in voices]
            self.voice_combo.configure(values=self._voice_names)
            selected = self.notifications.voice_id
            self.voice_combo.set(self._voice_names[self._voice_ids.index(selected)] if selected in self._voice_ids else self._voice_names[0])
        else:
            self.root.after(1000, self.refresh_voices)

    def select_voice(self, value):
        if value in self._voice_names:
            self.notifications.stop()
            self.notifications.voice_id = self._voice_ids[self._voice_names.index(value)]
            self.save_voice_preferences()

    def read_briefing(self):
        if self.controller.state not in (State.IDLE, State.PAUSED, State.ERROR, State.REVIEW):
            self.status.set("Дождись завершения записи или ответа перед чтением.")
            return
        try:
            busy, _ = self.adapter.response_status()
            if busy:
                raise ValueError("Ответ ещё формируется. Сводка появится после его завершения.")
            briefing = make_briefing(self.adapter.read_response())
            self.last_briefing = briefing
            self.title_text.set("Жду твоего ответа" if briefing.questions else "Зачитываю сводку")
            self.present_briefing(briefing)
            self.notifications.speak(briefing.spoken)
        except Exception as error:
            self.status.set("Ответ готов, но сводка недоступна: " + str(error))
            self.notifications.speak("Ответ готов, но текст для сводки недоступен. Проверь чтение в настройках.")

    def repeat_briefing(self):
        if self.controller.state in (State.STARTING, State.RECORDING, State.TRANSCRIBING, State.SENDING, State.PAUSING):
            self.status.set("Повторение доступно после завершения диктовки.")
            return
        if not self.last_briefing:
            self.status.set("Сводки ещё нет. Проверь чтение последнего ответа в настройках.")
            return
        self.present_briefing(self.last_briefing)
        self.notifications.speak(self.last_briefing.spoken)

    def present_briefing(self, briefing):
        preview = briefing.summary[:210] + ("…" if len(briefing.summary) > 210 else "")
        if briefing.questions:
            preview += f"\nВопросов: {len(briefing.questions)}. Прослушай их и ответь через Hi GPT."
        self.status.set(preview)
        self.readout_box.configure(state="normal")
        self.readout_box.delete("1.0", "end")
        self.readout_box.insert("1.0", briefing.spoken)
        self.readout_box.configure(state="disabled")

    def clear_briefing(self):
        self.last_briefing = None
        self.readout_box.configure(state="normal")
        self.readout_box.delete("1.0", "end")
        self.readout_box.configure(state="disabled")

    def close(self):
        if self.closed:
            return
        if not self.closing:
            self.closing = True
            if self.capture_job is not None:
                self.root.after_cancel(self.capture_job)
                self.capture_job = None
            self.pause(False)
            self.main_button.configure(state="disabled")
        if self.controller.state is State.PAUSING:
            self.controller.tick()
            if self.controller.state is State.PAUSING:
                self.root.after(100, self.close)
                return
        self.closed = True
        self.notifications.close()
        self.root.destroy()

def main():
    if sys.platform != "win32":
        raise SystemExit("Hey GPT requires Windows 10/11.")
    root = ctk.CTk()
    try:
        import argparse
        parser = argparse.ArgumentParser()
        parser.add_argument("--replay", type=Path, help="Developer test with synthetic command WAV; does not open microphone")
        parser.add_argument("--self-check-output", type=Path, help="Developer smoke check: write local GUI/worker readiness JSON, then exit")
        args = parser.parse_args()
        app = Application(root, args.replay)
        if args.self_check_output:
            root.withdraw()
            app.start("test")
            def check():
                from . import __version__
                report = {"version": __version__, "ui_ready": True, "microphone_worker_ready": app.ready,
                    "status": app.status.get(), "default_audio": app.notifications.mode,
                    "speech_voice_ready": bool(app.notifications.voices)}
                args.self_check_output.parent.mkdir(parents=True, exist_ok=True)
                args.self_check_output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
                app.close()
            root.after(6000, check)
    except Exception as error:
        messagebox.showerror("Hey GPT — ошибка запуска", str(error), parent=root)
        root.destroy()
        raise
    root.mainloop()

if __name__ == "__main__":
    main()
