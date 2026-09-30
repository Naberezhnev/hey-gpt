# Roadmap

## v0.1: fixed commands on one Windows device

Implemented in source:
- Hi ChatGPT / Stop GPT grammar with local Vosk recognition and a one-time model download.
- Calibrated accessible controls; one bound foreground window.
- Start/finish/transcription workflow and optional automatic sending.
- Stop phrase cleanup when the editor exposes a writable value.
- Visible listening state, pause control, and Ctrl+Alt+P.
- Russian setup UI with a microphone selector, level indicator, and command-test mode.
- 35 local tests and synthetic command recognition checks passed.

Next acceptance gates:
- Verify live command recognition and audible microphone input on the test computer.
- Demonstrate concurrent helper/browser microphone access.
- Bind and invoke controls in the user's actual browser.
- Confirm at least ten consecutive clean end-to-end sends in a non-sensitive test conversation.
- Measure behavior when the window changes, transcription is delayed, and the stop phrase is included.

## v0.2: pilot and installation

- Package a simple Windows installer/executable after the first verified cycle.
- Improve editor cleanup for contenteditable controls where ValuePattern is unavailable.
- Add browser-specific adapters if necessary, with explicit supported versions.
- Measure activation delay, false activations, missed commands, CPU usage, and distance from the microphone.
- Gather pilot feedback before claiming broader accessibility benefits.

## Later, only after the basic workflow proves useful

- Custom wake phrases and additional command languages.
- Read the latest answer aloud and stop reading by voice.
- Verified adapters for other Codex surfaces.
- Dedicated on-device wake-word detector if Vosk command recognition needs better latency or false-activation performance.
- macOS and phone feasibility investigation.
- Optional documented Codex App Server integration rather than UI button automation.

These are future ideas, not features shipped in the current source alpha.
