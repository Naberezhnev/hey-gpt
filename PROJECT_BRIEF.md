# Hey GPT — project brief

## Problem

People working in ChatGPT or Codex often step away while a response or task runs. Adding an instruction through dictation requires returning to the computer and manually pressing the microphone and send controls. An existing voice conversation does not solve the initial hands-free activation step for every workflow.

## Proposed product

A small opt-in desktop helper that adds fixed voice activation to the currently selected conversation without replacing that conversation or copying it into a separate assistant.

The initial interaction is: **Hi ChatGPT → recording confirmation → dictate → Stop GPT → transcription → optional Send**.

## Why this implementation is deliberately narrow

The target app already records and transcribes messages. The helper recognizes only control phrases and operates existing buttons. That avoids rebuilding conversation storage, model access, and a speech assistant. The first release targets one Windows computer and a calibrated UI.

## Architecture

1. Windows System.Speech recognizes the fixed command grammar locally.
2. A Python controller tracks Ready, Starting, Recording, Transcribing, Review, and Error states.
3. A Windows UI Automation adapter resolves calibrated accessible controls in one bound foreground window.
4. The helper waits for the recording control to appear before signaling readiness.
5. The target app handles dictation and returns text to its composer.
6. The helper waits for transcription to settle, checks the Send control, removes a trailing stop command if writable, and optionally invokes Send.

The helper does not need a model API for the initial workflow. It does not retain audio or conversation content. It reads the composer transiently for readiness and stop-command cleanup.

## Intended users and benefits to validate

- Creators who move between physical activity and computer-based work.
- Developers who add instructions while a task is running.
- People who find repeated keyboard/mouse interaction difficult.

The hypothesis is fewer manual interactions while preserving the current conversation. Accessibility benefit and compatibility must be tested with users; they are not yet demonstrated outcomes.

## Current evidence

Initial source implementation exists. Eighteen portable workflow and cleanup tests pass. Documentation, a Windows compilation check, and CI configuration are included. Live microphone sharing, legacy recognizer availability, UI selectors, and end-to-end sending remain unverified.

There is no public adoption metric yet. A launch video, pilot feedback, and real-device measurements are planned after first validation.

## Support request

We intend to seek consideration for Codex for Open Source as an early-stage project. ChatGPT Pro with Codex would support debugging, reviewing changes, handling user reports, and maintenance. If an API organization is available, API credits could support a future evaluation harness that compares reference intents with recognition/transcription results and tests optional read-aloud workflows. The initial command/click prototype does not consume API credits.

The project is presented as experimental and in development. No reward, native product integration, or acceptance into an OpenAI program is assumed.
