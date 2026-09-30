# Hey GPT

An experimental Windows helper for hands-free dictation in an **existing** ChatGPT or Codex conversation.

Say **“Hi ChatGPT”**, wait for the recording signal, dictate a message, then say **“Stop GPT”**. The helper is designed to invoke the configured dictation button, finish recording, wait for the resulting text, remove a trailing stop command when the editor permits it, and optionally invoke Send.

## Current status: source alpha, live validation pending

- Python workflow controller, Windows UI Automation adapter, setup window, and local Windows speech bridge are implemented.
- 18 deterministic workflow/cleanup tests pass in the development environment.
- No live Windows microphone, browser dictation, or Codex interface test has been completed yet.
- The Windows speech bridge compilation check passed locally on Windows with Python 3.12.7; Tkinter and the UI Automation adapter also initialized successfully.
- No existing user base, downloads, or production compatibility is claimed.

This is an independent project developed with assistance from Codex. It is not an official OpenAI application or a modification of ChatGPT itself.

## First version

- Fixed English commands: “Hi ChatGPT” and “Stop GPT”.
- Local command recognition using the installed Windows System.Speech recognizer.
- The selected ChatGPT/Codex interface performs the message transcription.
- UI Automation finds configured controls by their accessible name, ID, and type.
- Calibration is limited to one window; ambiguous selectors stop the workflow.
- Waits for recording state and stable transcript rather than blindly sleeping and sending.
- Review mode by default; optional automatic sending after verification.
- Ctrl+Alt+P pauses the helper. Closing the helper also stops command recognition.
- No helper audio recordings, screenshots, prompt logs, API keys, or cloud inference calls.

## Requirements

- Windows 10/11 with an interactive, unlocked desktop.
- Python 3.12 with the standard Tkinter component and Python launcher (`py`). Python 3.13 is a candidate, not yet validated.
- Windows PowerShell 5.1 and .NET Framework System.Speech.
- An installed English **legacy System.Speech recognition engine**. Windows Voice Access alone may not provide this engine; the helper reports an error if none is found.
- A working default microphone; ChatGPT must already have microphone permission.
- Accessible microphone, finish-recording, send, and message-field controls in the target interface.

The first launch needs internet access to install `uiautomation` and its dependency. Later command recognition does not require an OpenAI API key. ChatGPT's own dictation still uses its service and account.

## Run

1. Extract the entire project folder.
2. Install Python 3.12 from https://www.python.org/downloads/windows/ if needed.
3. Double-click `Run.cmd`. It creates a local virtual environment and installs the pinned Windows dependency.
4. Keep the intended chat window open, with ChatGPT or Codex in its window title.
5. Click **Bind/rebind chat window**, then place the cursor over that chat window within four seconds.
6. Calibrate the **Message field** and **Dictation microphone** in the same way.
7. Start a short dictation manually. Calibrate its **Finish recording** button while it is visible, then finish the test recording manually.
8. With a draft present, calibrate **Send message**. Clear that draft afterwards.
9. Leave automatic sending off for the first test. Click **Enable listening**, then return to the bound chat.
10. Say “Hi ChatGPT”. Wait for the signal confirming that the recording control appeared; dictate; say “Stop GPT”.
11. Review the result. After successful microphone-sharing, selector, and transcription tests, enable automatic sending if desired.

In review mode, send the draft manually and click **Reset workflow** before the next cycle. In automatic mode, a successful send returns the controller to Ready. If the tab title changes, rebind the intended chat window.

Pause only stops this helper. It does not cancel an ongoing recording inside ChatGPT; finish or cancel that recording manually.

## Known limitations

- Concurrent microphone access by System.Speech and browser dictation is a prerequisite that needs testing on the target computer.
- Commands are English; the dictated message can be in another language supported by the target app. Trailing English and common Russian spellings of Stop GPT are handled.
- Some browser editors expose readable TextPattern without writable ValuePattern. If the helper cannot remove the stop phrase and verify the result, it leaves the draft for manual correction and does not auto-send.
- Accessible controls vary with browser, app version, and language. Chromium/Electron may require accessibility exposure, such as `--force-renderer-accessibility`; this must be checked on the target device.
- The target window must remain in the foreground with the exact bound title. Moving/resizing it should not matter to selectors; changing tabs can require rebinding.
- There is no coordinate fallback, custom wake phrase, phone support, voice reading, or verified universal Codex compatibility in v0.1.
- The fixed grammar and confidence threshold need measurements for false activations, accents, distance, and speaker feedback.
- UI Automation does not provide a native ChatGPT integration; interface changes can require recalibration.

## Development

Portable tests do not require Windows dependencies:

```sh
python -m unittest discover -s tests -v
python -m compileall -q hey_gpt tests
```

On Windows, compile-check the actual embedded speech bridge without opening the microphone:

```powershell
powershell -NoProfile -File scripts/validate_speech.ps1
```

CI is configured for Linux and Windows. Passing workflow tests demonstrates controller behavior with a simulated adapter; it does not demonstrate real microphone or GUI compatibility.

See [PROJECT_BRIEF.md](PROJECT_BRIEF.md), [ROADMAP.md](ROADMAP.md), and [docs/WINDOWS_VALIDATION.md](docs/WINDOWS_VALIDATION.md).

## License

MIT for this project's original code. Third-party dependencies retain their respective licenses; `uiautomation` uses Apache-2.0. Windows components are supplied separately by Microsoft.
