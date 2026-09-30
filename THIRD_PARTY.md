# Third-party components

Original Hey GPT code is MIT-licensed. Dependencies and downloaded models retain their own licenses.

| Component | Use | License/source |
|---|---|---|
| Vosk API 0.3.45 | Local recognition engine | Apache-2.0 — https://github.com/alphacep/vosk-api |
| vosk-model-small-en-us-0.15 | English command model, downloaded separately | Apache-2.0 — https://alphacephei.com/vosk/models |
| sounddevice 0.5.6 | Microphone capture | MIT — https://github.com/spatialaudio/python-sounddevice |
| PortAudio | Audio backend distributed with the Windows sounddevice package | MIT — https://www.portaudio.com/license.html |
| uiautomation 2.0.29 | Windows accessible controls | Apache-2.0 — https://github.com/yinkaisheng/Python-UIAutomation-for-Windows |
| comtypes | Windows COM bindings | MIT — https://github.com/enthought/comtypes |

Pip installs additional transitive dependencies under their own licenses. No third-party model binaries are committed to this repository. Model download uses the official Vosk host over HTTPS. This project does not relicense model files.

The microphone-stream API usage follows the documented Vosk/sounddevice interface; no code or model files were copied from Hey Open, openWakeWord, RealtimeSTT, or Porcupine.