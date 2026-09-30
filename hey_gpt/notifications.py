"""Cancellable local speech. Readouts and replay stay in memory."""
import queue
import threading
import time


class Notifications:
    def __init__(self, activity=None):
        self.enabled = True
        self.mode = "tones"
        self.voice_id = ""
        self.voices = []
        self.error = ""
        self.queue = queue.Queue(maxsize=8)
        self.activity = activity or (lambda active: None)
        self._generation = 0
        self._closed = False
        self._speaking = False
        self._stopped = threading.Event()
        self._stopped.set()
        self._lock = threading.Lock()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    @property
    def speaking(self):
        return self._speaking

    def _put(self, text, readout=False):
        with self._lock:
            if self._closed:
                return
            try:
                self.queue.put_nowait((self._generation, text, readout))
            except queue.Full:
                pass

    def say(self, text):
        if self.enabled:
            self._put(text)

    def speak(self, text):
        """Explicit readout uses speech even when status notifications are tones."""
        self.stop()
        self._put(text, True)

    def tone(self, event="ready"):
        self.say("@" + event)

    def stop(self):
        with self._lock:
            self._generation += 1
            while True:
                try:
                    self.queue.get_nowait()
                except queue.Empty:
                    break
        return self._stopped.wait(.75)

    def _run(self):
        import comtypes
        import comtypes.client
        import winsound
        comtypes.CoInitialize()
        voice = None
        try:
            try:
                voice = comtypes.client.CreateObject("SAPI.SpVoice")
                tokens = list(voice.GetVoices())
                self.voices = [(token.Id, token.GetDescription()) for token in tokens]
                for token in tokens:
                    if "419" in token.GetAttribute("Language").split(";"):
                        voice.Voice = token
                        break
                default_voice = voice.Voice.Id
            except Exception as exc:
                self.error = "Голос Windows недоступен: " + str(exc)
            while True:
                item = self.queue.get()
                if item is None:
                    return
                generation, text, readout = item
                with self._lock:
                    if generation != self._generation or self._closed or (not readout and not self.enabled):
                        continue
                    self._stopped.clear()
                try:
                    if text.startswith("@") or (self.mode == "tones" and not readout):
                        event = text[1:] if text.startswith("@") else "done" if text == "Ответ готов" else "notice"
                        patterns = {"ready": [(1040, 100)], "done": [(740, 100), (1040, 160)],
                                    "pause": [(660, 100), (440, 100)], "notice": [(660, 120)]}
                        for frequency, duration in patterns.get(event, patterns["notice"]):
                            if generation != self._generation:
                                break
                            winsound.Beep(frequency, duration)
                    elif voice:
                        for token in tokens:
                            if token.Id == (self.voice_id or default_voice):
                                voice.Voice = token
                                break
                        self._speaking = True
                        self.activity(True)
                        if generation != self._generation or self._closed:
                            continue
                        # Asynchronous + IsNotXML: chat text is literal, not SAPI markup.
                        voice.Speak(text, 1 | 16)
                        while not voice.WaitUntilDone(25):
                            if generation != self._generation or self._closed:
                                voice.Speak("", 2 | 16)
                                break
                        if generation == self._generation and not self._closed:
                            deadline = time.monotonic() + .45
                            while generation == self._generation and time.monotonic() < deadline:
                                time.sleep(.025)
                    else:
                        self.error = "Голос Windows недоступен. Установи голос в параметрах Windows."
                        winsound.Beep(880, 180)
                except Exception as exc:
                    self.error = "Не удалось озвучить текст: " + str(exc)
                finally:
                    if self._speaking:
                        self._speaking = False
                        self.activity(False)
                    self._stopped.set()
        finally:
            comtypes.CoUninitialize()

    def close(self):
        self.stop()
        with self._lock:
            self._closed = True
        self.queue.put_nowait(None)
        self.thread.join(timeout=1)
