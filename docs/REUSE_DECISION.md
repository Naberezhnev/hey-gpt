# Reuse decision — September 30, 2026

The speech engine should be reused; only the app-specific controller and integration need project code.

- **Vosk:** selected for the first fixed-command trial. It runs locally, accepts constrained phrase grammars, needs no service key, and offers a ~40 MB English model under Apache-2.0. Source: https://alphacephei.com/vosk/models and https://github.com/alphacep/vosk-api.
- **openWakeWord:** a future candidate for dedicated wake-word detection. Its documented default models do not include Hi ChatGPT or Stop GPT. Project code is Apache-2.0; bundled pretrained models use CC BY-NC-SA 4.0. A matching model and its license would need separate verification. Source: https://github.com/dscripka/openWakeWord.
- **Hey Open:** a closely related Windows project with wake activation and browser automation. Its documented message-transcription path uses an OpenAI API key, while Hey GPT delegates dictation to the existing app. No files were copied. Source: https://github.com/davidgarthe/hey-open.
- **Porcupine:** provides dedicated local wake-word detection, but the documented Python integration requires an AccessKey. It adds a service credential step to installation. Source: https://github.com/Picovoice/porcupine.

This is an implementation choice for an early trial, not a benchmark claiming Vosk is the most accurate wake-word engine. Synthetic command checks passed; live activation accuracy, noise behavior, and microphone sharing remain acceptance gates.

## Voice briefing — October 1, 2026

Reviewed https://github.com/Dworrall21/chatgpt-bridge/blob/main/dom-selectors.md for the distinction between assistant/user messages and https://github.com/yinkaisheng/Python-UIAutomation-for-Windows for accessibility access. No source files were copied. The local reader uses assistant speaker boundaries, tested against a real ChatGPT accessibility tree, rather than browser DOM selectors or clipboard clicks. GPT generates the optional short section in the existing chat; an explicitly labelled extractive fallback needs no extra model. Speech uses installed Windows SAPI voices. Full structured Codex form/approval integration remains future work.
