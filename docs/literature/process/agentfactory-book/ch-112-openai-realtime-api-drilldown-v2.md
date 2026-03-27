# Chapter 112 — OpenAI Realtime API — Drilldown

## Source
Primary chapter URL: <https://agentfactory.panaversity.org/docs/Building-Realtime-Voice-Agents/openai-realtime-api>

## What this chapter is about

Chapter 112 teaches the direct path into OpenAI's speech-to-speech stack. Earlier voice chapters used frameworks such as LiveKit and Pipecat. This one drops below that layer and works with the Realtime API itself: WebRTC connection setup, session configuration, voice function calling, interruption handling, and turn detection.

The chapter's underlying question is practical: when should a team accept the extra control and extra work of direct API integration instead of staying inside a voice framework?

## Chapter outcome

By the end of the chapter, the learner should have:

- a working Realtime API connection over WebRTC,
- a reusable `openai-realtime` skill,
- a session configuration pattern for voice, modalities, and VAD,
- function-calling patterns adapted for spoken interfaces,
- barge-in handling and turn-detection strategies,
- a decision rule for choosing direct OpenAI integration versus a framework.

## Live publication caveat

The overview page renders this material as **Chapter 112** under **Part 10: Building Realtime Voice Agents**. The final lesson page currently exposes an older numbering scheme and renders the same material as **Chapter 82** under **Part 9**. The chapter sequence is coherent, but the site's numbering is not fully normalized.

## Drilldown by page

### 1) Overview
**Page:** <https://agentfactory.panaversity.org/docs/Building-Realtime-Voice-Agents/openai-realtime-api>

The overview frames the chapter in one sentence: use OpenAI's native speech-to-speech API directly. The listed goals are narrow and implementation-focused:

- connect through WebRTC,
- handle function calling and interruption,
- manage latency and cost expectations,
- capture the result as a reusable skill.

The lesson progression is short. The chapter has three lesson pages:

1. OpenAI Realtime Fundamentals,
2. Function Calling in Voice,
3. Barge-In and Custom Turn Detection.

The overview also makes the chapter's stance plain. This is not a broad survey of voice AI. It is a direct integration chapter.

### 2) OpenAI Realtime Fundamentals
**Page:** <https://agentfactory.panaversity.org/docs/Building-Realtime-Voice-Agents/openai-realtime-api/realtime-fundamentals>

This lesson introduces the protocol-level model. Its main claim is that native speech-to-speech reduces latency and preserves more conversational signal because the model works on audio directly instead of passing through a speech-to-text to language model to text-to-speech chain.

The lesson contrasts two architectures:

- a cascaded pipeline with separate STT, LLM, and TTS stages,
- a single native speech-to-speech model.

The tradeoff is clear. Native speech can cut boundary costs and keep intonation, pacing, hesitation, and pronunciation cues that a transcript flattens. The price is tighter provider coupling and a different operational surface.

The lesson then explains the Realtime API connection model. The learner is expected to understand these pieces:

- ephemeral token creation,
- `RTCPeerConnection`,
- microphone audio track,
- `DataChannel` for JSON events,
- SDP offer and answer exchange,
- ICE candidate negotiation,
- bidirectional audio plus event traffic after connection.

The chapter's most concrete technical constraint appears here: audio must be sent as **24 kHz**, **mono**, **PCM16**, **little-endian**. The lesson includes a conversion example and explains why the format is strict.

Session configuration is also introduced at this stage. The chapter treats `session.update` as the main control message for:

- voice selection,
- instructions,
- turn detection,
- input and output audio format,
- enabled modalities,
- temperature.

That matters because the later lessons build on the same event-driven model instead of switching to a different abstraction.

The practical message of the lesson is this: direct Realtime use is possible with ordinary code and WebRTC primitives, but the team now owns the connection, event handling, error handling, and safety posture that frameworks previously absorbed.

### 3) Function Calling in Voice
**Page:** <https://agentfactory.panaversity.org/docs/Building-Realtime-Voice-Agents/openai-realtime-api/voice-function-calling>

This lesson takes ordinary tool calling and reworks it for audio UX. Its thesis is that voice changes the ergonomics of tool use because silence is not neutral. A delay that feels acceptable in chat feels broken on a call.

The lesson builds the voice-tool pattern in three parts.

#### a) Voice-specific function definitions
The same OpenAI function schema still applies, but the descriptions need extra guidance. The chapter recommends that function definitions include:

- trigger phrases the user is likely to say,
- defaults to reduce clarification loops,
- natural-language parsing instructions for dates and similar fields,
- explicit warnings for destructive operations.

The examples use a task manager and define functions such as `create_task`, `list_tasks`, `complete_task`, and `delete_task`.

#### b) Spoken filler before and during tool execution
This is the lesson's central operational point. Before the tool runs, the model should acknowledge the request. During longer operations, the system may need interim speech such as "Still working on that, almost there..." The source treats filler as a normal part of voice tool design, not a cosmetic add-on.

The result is a two-stage spoken flow:

1. immediate acknowledgment,
2. concise completion message after the function result comes back.

That pattern is simple, but it prevents the dead-air problem that the lesson treats as one of the main failure modes of voice tooling.

#### c) Confirmation and error handling
The lesson also tightens the rules around destructive actions. It recommends a two-step confirmation pattern for irreversible operations such as deleting tasks, clearing all tasks, sending email, or canceling subscriptions.

The timeout detail matters. Confirmations should expire instead of staying live forever, because stale confirmations create unsafe follow-on behavior.

The error section is equally voice-specific. The lesson distinguishes between:

- user errors that require clarification,
- temporary failures that justify a retry offer,
- permanent failures that need a fallback,
- unknown failures that need a short, calm recovery line.

The message design principle is sound: spoken error recovery must be short, actionable, and screen-free.

### 4) Barge-In and Custom Turn Detection
**Page:** <https://agentfactory.panaversity.org/docs/Building-Realtime-Voice-Agents/openai-realtime-api/barge-in-custom-turn>

This lesson covers the interaction mechanics that make voice agents feel interruptible instead of prerecorded.

Its first argument is that barge-in is not a corner case. Users interrupt constantly to correct, stop, or redirect the system. A voice agent that keeps talking after the user starts speaking is treated as broken.

The lesson explains the barge-in flow through Realtime API events:

- `input_audio_buffer.speech_started`,
- interruption of the agent's outgoing audio,
- continued user speech,
- `input_audio_buffer.speech_stopped`,
- generation of a new response.

The implementation burden falls on the client. The source shows an `AudioPlayer` that can clear its playback buffer and stop immediately when interruption begins. That is the real technical requirement behind "support barge-in": audio playback has to be cancelable, not just the model response.

The second half of the lesson is about turn detection.

#### a) Server VAD
The default mode is server-side voice activity detection. The chapter exposes three main tuning knobs:

- `threshold`,
- `prefix_padding_ms`,
- `silence_duration_ms`.

It then maps those settings to use cases:

- fast customer-service style response,
- patient coaching or therapy-style listening,
- noisy environments with more aggressive filtering.

A useful design detail appears here: the lesson recommends changing VAD settings during a session when the context changes. A yes-or-no confirmation turn should not use the same silence threshold as an open-ended reflective answer.

#### b) Manual turn detection
The chapter then drops server VAD entirely and switches to `type: "none"` for cases where the application must decide when a turn ends. The lesson's examples include:

- push-to-talk,
- wake-word activation,
- semantic turn detection,
- dictation or multi-party cases where pauses do not equal completion.

The operational rule is explicit: with manual mode, the client must decide when to `commit` or `clear` the input audio buffer.

#### c) Voice plus vision
The lesson also shows how image input fits into a Realtime conversation. The client can send a `conversation.item.create` event containing `input_image` plus accompanying `input_text`, which opens use cases such as screen diagnosis, document reading, and camera-guided assistance.

#### d) Direct API versus framework choice
The lesson closes with the chapter's strategic conclusion. It offers a decision matrix and an explicit 80/20 rule.

The tradeoff is straightforward:

- **Direct API** gives full WebRTC control, tighter latency tuning, and full visibility into the event stream.
- **Frameworks** give faster setup, better provider flexibility, built-in scaling patterns, and lower team burden.

The chapter's recommendation is conservative: about 80% of voice projects should stay on frameworks. Teams should drop to direct API only when they have a specific reason, such as unusual latency requirements, custom transport control, or a Realtime API feature gap that the framework cannot expose cleanly.

## Chapter synthesis

Across the three lesson pages, the chapter makes one coherent case.

First, direct Realtime integration changes what the model can hear and how quickly it can answer. Second, voice tool use has different UX rules from chat tool use because silence, interruption, and destructive commands behave differently when the user is listening instead of reading. Third, the last mile of voice quality depends on interaction mechanics such as barge-in, VAD tuning, and cancellation, not just on model quality.

The chapter does not argue that direct API is the default choice. It argues that direct API is justified when a team needs low-level control badly enough to own the extra protocol, audio, UX, and safety work.

## What to remember

- Native speech-to-speech reduces transcription overhead and preserves audio cues.
- Realtime integration depends on WebRTC plus DataChannel events, not a high-level framework abstraction.
- Voice function calling needs acknowledgments, filler, and explicit confirmation rules.
- Barge-in requires immediate audio playback cancellation, not just model-side interruption.
- Turn detection should be tuned per use case and sometimes controlled manually.
- Most teams should still prefer frameworks unless they have a concrete need for direct control.

## Page list

1. Overview  
   <https://agentfactory.panaversity.org/docs/Building-Realtime-Voice-Agents/openai-realtime-api>
2. OpenAI Realtime Fundamentals  
   <https://agentfactory.panaversity.org/docs/Building-Realtime-Voice-Agents/openai-realtime-api/realtime-fundamentals>
3. Function Calling in Voice  
   <https://agentfactory.panaversity.org/docs/Building-Realtime-Voice-Agents/openai-realtime-api/voice-function-calling>
4. Barge-In and Custom Turn Detection  
   <https://agentfactory.panaversity.org/docs/Building-Realtime-Voice-Agents/openai-realtime-api/barge-in-custom-turn>

## Notes on live chapter shape

The current authored next-page flow ends on **Barge-In and Custom Turn Detection** and then links straight to **Chapter 113: Gemini Live API**. In the live navigation I did not find a separately exposed Chapter 112 quiz page.
