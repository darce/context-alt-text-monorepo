# Chapter 114 Drilldown Summary: Phone & Browser Integration

## Source record
- Book / site: AI Agent Factory
- Part: Part 10, *Building Realtime Voice Agents*
- Chapter: Chapter 114, *Phone & Browser Integration*
- Primary URL: https://agentfactory.panaversity.org/docs/Building-Realtime-Voice-Agents/phone-browser-integration
- Lesson pages covered: Build Your Integration Skills; Phone Integration with SIP & Twilio; Browser Audio Capture & VAD; Production Telephony Patterns; Chapter 114: Phone & Browser Integration - Lesson Plan
- Accessed: 2026-03-26

## Central claim
This chapter argues that voice agents do not become real services until they are connected to real channels. Its solution is to split channel integration into two reusable skills, one for telephony and one for browser audio, then extend both with production patterns so the same agent can be reached by phone or through the browser with explicit decisions about latency, cost, compliance, and reliability.

## Chapter overview
The chapter starts by defining the channel problem. Voice agents built in earlier chapters can already reason and speak, but they are still isolated inside framework demos or direct API examples. This chapter turns them outward. It creates one skill for phone networks and one for browser capture because those domains look adjacent at the product surface while differing sharply in protocols, audio quality, infrastructure, and failure modes.

The middle of the chapter teaches the two channel paths separately. The telephony lesson covers SIP signaling, provider choice, inbound and outbound call patterns, and the way PSTN audio changes model behavior and prompt design. The browser lesson covers secure microphone access, AudioWorklet-based processing, in-browser VAD, and transport selection between WebRTC and WebSocket.

The final lesson moves from integration to operation. It replaces simple demos with conversational IVR, compliant recording flows, and provider failover. The lesson-plan page makes the instructional pattern explicit: this is a skill-first chapter with two skills created up front, improved after each lesson, and composed later in the production capstone.

## Section-by-section drilldown

### 1) Chapter landing page
The landing page frames the chapter as the bridge from voice infrastructure to reachable voice products. Its stated goal is to connect agents to real channels: SIP, Twilio, and Telnyx on the phone side, and browser audio plus WebRTC on the web side. The page is brief, but it establishes the chapter's structure clearly.

Its progression matters. Students do not begin with a finished app. They begin by building reusable integration skills, then learn phone patterns, then browser patterns, then end-to-end production patterns. The outcome is twofold: working channel connectivity and durable skills that can be reused outside this chapter.

### 2) Build Your Integration Skills
This lesson is the chapter's organizing move. It states that phone integration and browser audio belong together at the business level but should be modeled separately at the implementation level. Telephony is defined by SIP, webhooks, provider economics, and PSTN constraints. Browser audio is defined by Web Audio API, AudioWorklet, browser permissions, VAD, and transport decisions. The lesson argues that treating them as one skill would blur the boundaries that later engineering choices depend on.

The chapter therefore starts with two explicit skills: `voice-telephony` and `web-audio-capture`. The lesson has students write a `LEARNING-SPEC.md` that fixes scope before any generation begins. The telephony skill is meant to cover SIP, Twilio, Telnyx, LiveKit SIP, call-flow patterns, and the effect of 8kHz phone audio on model choice. The browser skill is meant to cover `getUserMedia`, AudioWorklet, Silero VAD in WebAssembly, browser security requirements, and WebRTC versus WebSocket transport.

The rest of the lesson is procedural by design. Students fetch current documentation rather than rely on model memory, then create both skills from that documentation. The lesson's real claim is that skill-first work produces narrower and more dependable guidance than jumping directly into ad hoc implementation. These skills are not finished after Lesson 0. They are the evolving artifacts that each later lesson is supposed to refine.

### 3) Phone Integration with SIP & Twilio
This lesson turns phone access into a concrete engineering problem. It begins with SIP because provider APIs are secondary to understanding how calls are signaled and routed. SIP is presented as the session-control layer, while RTP carries the actual audio once a call is established. From there, the lesson contrasts two integration styles: native SIP paths, which reduce indirection and fit telephony-native systems, and HTTP webhook paths, which are easier to adopt with mainstream providers and web application stacks.

The lesson then places LiveKit's native SIP support beside Twilio's webhook model. LiveKit is used to show direct telephony routing through trunks and dispatch rules into rooms or call-specific sessions. Twilio is used to show the practical flow most teams will recognize first: provision a number, receive incoming webhooks, respond with TwiML, and connect the call to the voice agent. The lesson also covers outbound calling and call-status tracking, so telephony is treated as two-way infrastructure rather than a one-direction inbound demo.

Telnyx enters as the economic comparison, not as a separate conceptual system. The lesson presents it as a cheaper parallel option for teams that expect significant call volume and want to trade some convenience or ecosystem familiarity for lower per-minute cost. That cost comparison is not just procurement detail. It supports the chapter's broader claim that channel architecture has to be reasoned about in terms of operating economics, not only developer ergonomics.

The lesson closes on PSTN constraints. Phone audio is treated as a materially different input condition from browser audio. Lower fidelity affects transcription behavior, confirmation strategies, and prompt design. The lesson therefore pushes builders to adapt the agent for phone conditions rather than assume a browser-tuned conversation loop will transfer unchanged.

### 4) Browser Audio Capture & VAD
This lesson makes the browser path concrete and strips away the idea that microphone capture is trivial. Its first point is that browser voice starts with policy and platform constraints, not with streaming. Microphone access requires a secure context, which means HTTPS outside localhost. If that requirement is ignored, the rest of the architecture does not matter because capture never starts.

From there, the lesson focuses on low-latency processing. `getUserMedia` acquires the microphone stream, but the architectural center of the lesson is AudioWorklet. AudioWorklet is presented as the correct browser primitive because it moves audio work off the main thread and avoids the latency and scheduling problems of older approaches. The lesson treats this as a practical performance decision, not a stylistic API preference.

The next layer is client-side VAD. Silero VAD running in the browser through WebAssembly and ONNX Runtime is used to reduce round-trip delay and avoid sending silence or noise to the backend unnecessarily. The lesson's logic is straightforward: if the browser can decide when speech starts and ends locally, turn-taking improves and infrastructure cost drops. This is also where the chapter begins to show that browser integration is more than microphone capture; it is early audio intelligence executed at the edge.

The transport comparison then separates WebRTC from WebSocket. WebRTC is framed as the production path when NAT traversal, adaptive media handling, and more demanding real-time conditions matter. WebSocket is framed as the simpler route for prototypes, controlled environments, and backends that already assume direct binary streams. The lesson does not force one answer. It wants the builder to choose transport from network conditions and deployment context rather than from habit.

The lesson ends with a complete browser client path that joins capture, worklet processing, VAD, transport, and agent response playback. It then directs students to expand the `web-audio-capture` skill with code templates, VAD integration guidance, and a transport decision tree, which reinforces the chapter's pattern of turning each lesson into a skill refinement pass.

### 5) Production Telephony Patterns
This lesson treats basic phone connectivity as insufficient for real operation. Its first major shift is IVR. Instead of centering keypad trees, the lesson argues for conversational IVR built around intent detection, with DTMF kept as a fallback rather than the primary interface. The point is not that menus disappear entirely. It is that language understanding should become the main routing layer when the agent can already classify requests and preserve context.

The lesson then extends routing into handoff and continuity. Transfers are not modeled as blind jumps between endpoints. They are supposed to carry caller context, conversation summary, extracted entities, and sentiment so the receiving agent or human picks up with context instead of restarting the interaction. That makes the chapter's phone design more like session orchestration than traditional call switching.

Recording and compliance form the second production pillar. The lesson treats recording as a jurisdictional and workflow problem, not merely a toggle. Consent announcements, retention, deletion, and pause-and-resume behavior for sensitive segments such as PCI flows are all part of the implementation. This matters because the chapter is not content with saying that recording laws vary. It tries to turn that fact into operational branches the skill should know how to guide.

The final production pillar is failover. The lesson introduces multi-provider routing, health checks, degraded and unhealthy provider states, graceful degradation paths such as voicemail or callbacks, and cost-aware provider selection. Twilio may remain the preferred primary path, but the architecture is expected to survive provider outages, network failures, and capacity spikes. By the end of the lesson, both skills are no longer teaching only integration primitives. They are supposed to encode production constraints and fallback behavior.

### 6) Chapter 114 lesson plan page
The lesson-plan page clarifies the educational pattern more explicitly than the public chapter landing page. It labels the chapter as a technical, skill-first unit with an L00 setup lesson. It defines four lessons total, identifies nine core concepts across the chapter, and explains that the chapter's job is to build two skills first and then improve them through the lesson sequence.

Its success criteria also sharpen the chapter's scope. Students are expected to create working telephony and browser-audio skills from official documentation, explain SIP and native-SIP-versus-webhook tradeoffs, implement inbound and outbound Twilio calling, understand the Telnyx cost case, build browser capture with AudioWorklet, run Silero VAD in browser, and implement production patterns such as IVR, recording, and failover. The criteria make clear that this chapter is not only about channel access. It is about designing reusable guidance for channel access.

The assessment plan is also visible here even though a standalone quiz page was not exposed in the published navigation I could access. The lesson-plan page lists both formative checks during each lesson and a summative chapter quiz covering SIP choice, provider economics, AudioWorklet, client-side VAD, and recording consent. It also defines a practical assessment that requires inbound phone calls, browser audio capture, IVR flow, and recording with consent.

The dependency graph shows where the chapter sits in the larger part. It depends on earlier voice chapters for frameworks and direct APIs, and it prepares Chapter 115, where phone and browser channels are expected to compose into a fuller production voice agent.

## Major supporting logic
- Channel integration should be split into two skills because telephony and browser audio solve different protocol, latency, and infrastructure problems even when they serve the same user-facing goal.
- Telephony design starts with SIP and routing models, not with provider SDKs alone.
- Provider choice is operational, not cosmetic. Twilio, Telnyx, and native SIP routes imply different tradeoffs in price, reliability, and integration style.
- Browser voice requires secure capture, low-latency client processing, local VAD, and an explicit transport decision. It is not just microphone permission plus a socket.
- Production readiness adds three missing layers: conversational IVR, legally compliant recording behavior, and multi-provider failover.
- The chapter's pedagogical method is skill-first. Each lesson is supposed to improve one or both reusable skills rather than exist as isolated tutorial content.

## Chapter conclusion
The chapter concludes that real-time voice systems become durable products only when channel connectivity is turned into reusable operating knowledge. A builder should leave with two refined skills: one that can guide telephony architecture, provider selection, and phone-specific behavior, and another that can guide secure browser capture, low-latency processing, and browser transport. Production voice work then begins where the chapter ends: combining those channel skills into one service that survives regulation, outages, and real user traffic.

## Practical takeaways
- Separate phone and browser integration into distinct skills even if one product needs both.
- Learn SIP well enough to choose between native SIP paths and webhook-driven provider flows.
- Treat Twilio and Telnyx as different operating models, not just interchangeable APIs.
- Design phone prompts and confirmations for low-fidelity PSTN audio rather than reuse browser assumptions.
- Keep browser capture inside HTTPS, offload audio work to AudioWorklet, and push VAD into the client when feasible.
- Choose WebRTC or WebSocket from network and deployment constraints, not from fashion.
- For production telephony, add conversational IVR, compliance-aware recording, and multi-provider failover before calling the system complete.

## Source note
The linked landing page still renders the chapter as **Chapter 84: Phone & Browser Integration**, while the lesson pages and sidebar render it as **Chapter 114** under **Part 10**. The lesson sequence itself is consistent, so this summary follows the current published lesson order and treats the numbering difference as a site artifact.

## Coverage note
I did not find a separate published quiz or assessment page in the visible chapter navigation during this pass. The lesson-plan page does, however, reference a `04-chapter-quiz.md` assessment file and spells out both quiz topics and practical evaluation criteria.
