"""Small setup UI; desktop automation runs only after explicit Start."""
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk

from .core import Controller, State


def main():
    if sys.platform != "win32":
        raise SystemExit("The desktop prototype requires Windows 10/11.")
    import winsound
    from .windows import WindowsAdapter, emergency_pressed

    path = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "HeyGPT" / "selectors.json"
    try:
        selectors = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except (ValueError, OSError):
        selectors = {}
    adapter = WindowsAdapter(selectors)
    controller = Controller(adapter, clock=time.monotonic)
    events = queue.Queue()
    root = tk.Tk()
    root.title("Hey GPT — experimental Windows prototype")
    root.geometry("700x550")
    status = tk.StringVar(value="Set up the controls, then enable listening.")
    auto_send = tk.BooleanVar(value=False)
    process = None
    ready = False
    capturing = False
    last_state = None
    speech_error = ""

    ttk.Label(root, text="Hi ChatGPT → dictation · Stop GPT → finish", font=("Segoe UI", 13)).pack(pady=12)
    ttk.Label(root, text="Keep the configured chat in the foreground. Ctrl+Alt+P pauses listening.").pack()
    ttk.Label(root, text="Calibration: click a setup button, then move the cursor to the target within 4 seconds.").pack(pady=8)
    setup = ttk.Frame(root)
    setup.pack(fill="x", padx=15)
    labels = {}

    def pause():
        nonlocal process, ready
        if process:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
            process = None
        ready = False
        while not events.empty():
            try:
                events.get_nowait()
            except queue.Empty:
                break
        controller.reset()
        status.set("Listening paused. If ChatGPT is still recording, finish/cancel it manually.")

    def finish_capture(role):
        nonlocal capturing
        try:
            if role == "window":
                adapter.hwnd = None
            selected = adapter.capture_at_cursor(role)
            if role in labels:
                labels[role].set(selected)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(adapter.export(), ensure_ascii=False, indent=2), encoding="utf-8")
            status.set("Captured " + role + ": " + selected)
        except Exception as exc:
            status.set("Setup error: " + str(exc))
        finally:
            capturing = False

    def capture(role):
        nonlocal capturing
        if capturing:
            return
        pause()
        capturing = True
        status.set("Move the cursor onto " + role + ". Capturing in 4 seconds…")
        root.after(4000, lambda: finish_capture(role))

    names = [("window", "1. Bind/rebind chat window"), ("composer", "2. Message field"),
             ("microphone", "3. Dictation microphone"), ("finish", "4. Finish recording"),
             ("send", "5. Send message")]
    for index, (role, name) in enumerate(names):
        ttk.Button(setup, text=name, command=lambda r=role: capture(r)).grid(row=index, column=0, sticky="ew", pady=4)
        labels[role] = tk.StringVar(value="Not set" if role not in adapter.selectors else "Loaded; rebind window")
        ttk.Label(setup, textvariable=labels[role], wraplength=410).grid(row=index, column=1, sticky="w", padx=10)
    ttk.Label(root, text="For step 4: start a brief recording manually, then capture its FINISH button.\n"
              "Capture Send while a draft is present; clear that draft before listening.", wraplength=650).pack(pady=12)
    ttk.Checkbutton(root, text="Automatically send after transcription (test review mode first)", variable=auto_send).pack()
    controls = ttk.Frame(root)
    controls.pack(pady=12)

    def read_events(child):
        assert child.stdout is not None
        for line in child.stdout:
            events.put((child, line.strip().lstrip("\ufeff")))

    def start():
        nonlocal process, ready
        if capturing:
            return
        pause()
        missing = {"composer", "microphone", "finish", "send"} - adapter.selectors.keys()
        if not adapter.hwnd or missing:
            status.set("Complete calibration first; missing: " + ", ".join(sorted(missing)))
            return
        controller.auto_send = auto_send.get()
        try:
            process = subprocess.Popen(
                ["powershell.exe", "-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass",
                 "-File", str(Path(__file__).with_name("listen.ps1"))],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                errors="replace", creationflags=subprocess.CREATE_NO_WINDOW,
            )
            ready = False
            threading.Thread(target=read_events, args=(process,), daemon=True).start()
            status.set("Starting local phrase recognition; switch to the configured chat.")
        except OSError as exc:
            status.set(str(exc))

    def reset():
        controller.reset()
        status.set("Ready. Clear any previous draft/recording before saying Hi ChatGPT.")

    ttk.Button(controls, text="Enable listening", command=start).pack(side="left", padx=5)
    ttk.Button(controls, text="Pause", command=pause).pack(side="left", padx=5)
    ttk.Button(controls, text="Reset workflow", command=reset).pack(side="left", padx=5)
    ttk.Label(root, textvariable=status, wraplength=650, foreground="#174a7e").pack(padx=15, pady=8)
    ttk.Label(root, text="Audio is not saved by this helper. ChatGPT handles your dictated message.\n"
              "This alpha has not yet been tested against a live Windows ChatGPT/Codex interface.", wraplength=650).pack(padx=15, pady=8)

    def pump():
        nonlocal ready, last_state, speech_error
        if emergency_pressed():
            pause()
        while not events.empty():
            child, line = events.get_nowait()
            if child is not process:
                continue
            if line == "READY":
                ready = True
                status.set("Listening. Return to the configured chat; say Hi ChatGPT.")
            elif line in ("WAKE", "STOP") and ready:
                controller.command(line)
                status.set(controller.error or controller.state.value)
            elif line.startswith("ERROR "):
                ready = False
                speech_error = line
                status.set(line)
            elif line:
                speech_error = line
        if process and process.poll() is not None:
            ready = False
            status.set(speech_error or "Speech recognition stopped. Pause and enable listening again.")
        if ready:
            controller.tick()
            if controller.state is not last_state:
                if controller.state is State.RECORDING:
                    winsound.MessageBeep(winsound.MB_OK)
                status.set(controller.error or controller.state.value)
                last_state = controller.state
        root.after(150, pump)

    def close():
        pause()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", close)
    root.after(150, pump)
    root.mainloop()


if __name__ == "__main__":
    main()
