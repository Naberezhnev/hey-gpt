"""Local status announcements. Never reads chat content."""
import queue
import threading

class Notifications:
    def __init__(self):
        self.enabled = True
        self.mode = "tones"
        self.queue = queue.Queue(maxsize=8)
        threading.Thread(target=self._run, daemon=True).start()

    def say(self, text):
        if self.enabled:
            try:
                self.queue.put_nowait(text)
            except queue.Full:
                pass

    def tone(self, event="ready"):
        self.say("@" + event)

    def _run(self):
        import comtypes
        import comtypes.client
        import winsound
        comtypes.CoInitialize()
        voice = None
        try:
            try:
                voice = comtypes.client.CreateObject("SAPI.SpVoice")
                for token in voice.GetVoices():
                    if "419" in token.GetAttribute("Language").split(";"):
                        voice.Voice = token
                        break
            except Exception:
                pass
            while True:
                text = self.queue.get()
                if text is None:
                    return
                if not self.enabled:
                    continue
                try:
                    if text.startswith("@") or self.mode == "tones":
                        event = text[1:] if text.startswith("@") else "done" if text == "Ответ готов" else "notice"
                        patterns = {"ready": [(1040, 100)], "done": [(740, 100), (1040, 160)],
                                    "pause": [(660, 100), (440, 100)], "notice": [(660, 120)]}
                        for frequency, duration in patterns.get(event, patterns["notice"]):
                            winsound.Beep(frequency, duration)
                    elif voice:
                        voice.Speak(text)
                    else:
                        winsound.Beep(880, 180)
                except Exception:
                    winsound.MessageBeep()
        finally:
            comtypes.CoUninitialize()

    def close(self):
        try:
            self.queue.put_nowait(None)
        except queue.Full:
            pass
