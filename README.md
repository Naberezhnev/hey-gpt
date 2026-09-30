# Hey GPT

A Windows helper for hands-free dictation in an **existing** ChatGPT or Codex conversation.

Say **Hi ChatGPT**, pause, wait for the recording signal, dictate, then say **Stop GPT** and pause. The helper operates the configured dictation controls, waits for transcription, removes a trailing stop phrase when the editor permits it, and optionally sends the message.

**Russian setup guide: [START_HERE_RU.md](START_HERE_RU.md).**

## v0.2 alpha: ready for a manual device trial

- Local command recognition uses [Vosk](https://github.com/alphacep/vosk-api) and [sounddevice](https://github.com/spatialaudio/python-sounddevice); an English Windows System.Speech recognizer is no longer required.
- A small English model downloads once (~40 MB) from the [official Vosk model list](https://alphacephei.com/vosk/models). Command recognition then runs locally.
- Russian setup window with microphone selection, an audio level indicator, and a phrase-check mode that does not operate the chat.
- Workflow controller, Windows UI Automation adapter, calibration, review mode, optional sending, and Ctrl+Alt+P pause.
- 35 local tests passed on Windows with Python 3.12.7.
- Both commands passed a synthetic English speech test; one ordinary sentence produced no command.
- The microphone stream opened locally. The brief probe detected no audible signal; live spoken commands and simultaneous browser microphone use remain to be tested.
- End-to-end compatibility with an actual ChatGPT/Codex interface is not yet established.

This is an independent project, not an official OpenAI application. No existing adoption or production compatibility is claimed.

## Requirements and launch

- Windows 10/11 x64, unlocked interactive desktop.
- Python 3.12 x64 with Tkinter and Python Launcher.
- A microphone and microphone permission for desktop applications and the target app.
- Accessible message-field and dictation/finish/send controls in the target app.
- Internet for the initial dependency and model downloads.

Double-click **Run.cmd**. It creates a local virtual environment, installs missing dependencies, and opens the setup window. Choose **Подготовить модель** if the model is missing, then **Проверить команды**. Say “Hi chat G P T” and “Stop G P T”, with a short pause after each phrase. The level meter should respond when you speak.

Only after that, bind the chat window and its four controls. Finish any calibration recording and clear its draft. Keep automatic sending off for the first live test, click **Включить управление чатом**, then return to the bound chat window.

For a standalone local diagnostic, run **Check.cmd**. It opens the microphone briefly without saving audio or operating the chat.

## Bound-window behavior

All configured controls belong to one window. A different target window clears the old controls. A selector with an accessibility ID uses that stable ID; otherwise its accessible name must match exactly. Ambiguous selectors are rejected without replacing the previous calibration.

Calibration reads the control under the cursor without requiring that window to be foreground. Actual reads and writes during dictation require the bound window to be foreground with the same title. Switching tabs or a title change requires rebinding.

In review mode, send the draft manually and click **Сбросить цикл** before the next recording. Ctrl+Alt+P or **Пауза** stops the helper microphone worker. It does not cancel a recording already running in the target app.

## Data and limitations

The helper processes microphone audio locally in memory. It emits only command, readiness, level, and error events to the setup window, never ordinary recognized text. It does not retain microphone audio or message text. Calibration selectors are stored under `%LOCALAPPDATA%\HeyGPT`; model files are stored there too.

ChatGPT/Codex performs message transcription under its own service/account rules. No model API key is needed by this helper.

- Fixed English control phrases; dictated messages may use languages supported by the target app.
- Vosk phrase recognition requires a short pause to finalize a command. Noise, distance, accents, and speaker playback still require user testing.
- Simultaneous microphone access by the helper and the target app is a prerequisite.
- Editors without writable ValuePattern leave the stop phrase for manual correction; automatic sending is blocked.
- Accessibility exposure varies between browsers and app versions. There is no coordinate-click or clipboard fallback.
- No custom wake phrase, phone support, answer reading, or standalone executable installer yet.

## Development checks

Portable tests do not import speech or Windows dependencies:

```sh
python -m unittest discover -s tests -v
python -m compileall -q hey_gpt tests scripts
```

Six adapter/setup-window tests run only on Windows with installed dependencies. To validate the actual Vosk model against temporary **synthetic** speech:

```powershell
.venv\Scripts\python.exe -m hey_gpt.model_setup
.venv\Scripts\python.exe scripts\validate_local_speech.py
```

The synthetic files contain generated test phrases and are deleted after the check. They do not contain microphone recordings. The legacy System.Speech bridge and its compilation check remain in the source for reference; the setup window uses Vosk.

See [docs/WINDOWS_VALIDATION.md](docs/WINDOWS_VALIDATION.md), [docs/REUSE_DECISION.md](docs/REUSE_DECISION.md), and [ROADMAP.md](ROADMAP.md).

## License

MIT for original project code. See [THIRD_PARTY.md](THIRD_PARTY.md) for dependency and model licenses.