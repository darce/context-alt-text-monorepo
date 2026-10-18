# Chapter 72 Drilldown: Apps SDK - Building Interactive ChatGPT Apps

Source chapter: <https://agentfactory.panaversity.org/docs/Building-Agent-Factories/openai-apps-sdk>

Drafting constraints used for this summary:
- `/mnt/data/agent-summary-template-from-bauer-ramazani.md`
- `/mnt/data/ai-writing-tropes-squashed-augmented.md`

## Source record

- Chapter title: Chapter 72: Apps SDK - Building Interactive ChatGPT Apps
- Course: Agent Factory
- Section: Part 6, Building Agent Factories
- Chapter URL: <https://agentfactory.panaversity.org/docs/Building-Agent-Factories/openai-apps-sdk>
- Lesson pages traversed from the live chapter navigation:
  - Build Your Apps SDK Skill
  - Apps SDK Architecture
  - Your First Widget
  - Adding a Refresh Button
  - Displaying Tasks
  - Task Actions with `callTool`
  - State Persistence and Display Modes
  - React & Apps SDK UI
  - Complete TaskManager Capstone
  - Chapter Quiz

## Chapter thesis

This chapter explains how to turn an MCP-backed agent into a ChatGPT app with an interactive UI. Its main claim is practical: the Apps SDK gives agent builders a distribution channel inside ChatGPT itself, then adds the widget runtime, communication APIs, and UI conventions needed to turn server-side tools into a usable product. The chapter teaches the material by building one TaskManager app in stages rather than presenting isolated concepts.

## What the chapter is trying to teach

The overview page frames the Apps SDK as the visual layer that sits on top of earlier work with the Agents SDK and MCP servers. It distinguishes backend intelligence from frontend interaction, then sets the scope for the chapter: three-layer architecture, FastMCP-based widget delivery, widget interactivity through `window.openai`, response design with `structuredContent` and `_meta`, widget state persistence, display modes, and a TaskManager capstone that brings those pieces together.

The overview also makes the chapter progression explicit. Each lesson adds one capability to the same app, starting with a simple widget, then adding refresh behavior, task display, task actions, state persistence, alternate display modes, a React rewrite, and production hardening. That progression is the spine of the chapter rather than a side note.

Source: [Chapter overview](https://agentfactory.panaversity.org/docs/Building-Agent-Factories/openai-apps-sdk)

## Drilldown by page

### 0. Build Your Apps SDK Skill

This setup page tells the reader to begin by generating a reusable Claude skill for the OpenAI Apps SDK from official documentation, using the Panaversity skills lab. Pedagogically, it pushes the learner to start with a local tool that can answer implementation questions and produce templates during the rest of the chapter. The page is short, but it sets the pattern used elsewhere in the curriculum: own a domain skill first, then learn the mechanics in detail.

Operationally, the page has two steps. First, fetch the `claude-code-skills-lab` repository and open it in Claude. Second, use the skill-creator flow to generate a new Apps SDK skill grounded in official OpenAI documentation. The point is not the repo itself; the point is that the learner enters the chapter with an assistant specialized for this API.

Source: [Build Your Apps SDK Skill](https://agentfactory.panaversity.org/docs/Building-Agent-Factories/openai-apps-sdk/build-your-apps-sdk-skill)

### 1. Apps SDK Architecture

This lesson introduces the reason the Apps SDK exists: distribution. The text argues that a capable agent is not enough if users cannot discover and run it. The Apps SDK solves that problem by placing the application inside ChatGPT and, according to the lesson, exposing it through the ChatGPT App Directory. The overview page also ties that distribution argument to usage claims about ChatGPT adoption and business usage, which the chapter uses to justify why this surface matters.

The lesson's technical core is the three-layer model:
- ChatGPT UI
- widget iframe
- MCP server

The learner is expected to understand what runs in each layer, who controls it, how data moves between adjacent layers, and why the separation exists. The architecture page also contrasts Apps SDK behavior with standard MCP tools and points to the three differentiators that matter in practice: special widget rendering, dual response channels, and bidirectional communication between the widget and the backend through ChatGPT.

At the end of the lesson, the memory target is simple and concrete: memorize the three layers and their responsibilities. That is the chapter's mental model.

Sources:
- [Apps SDK Architecture](https://agentfactory.panaversity.org/docs/Building-Agent-Factories/openai-apps-sdk/apps-sdk-architecture)
- [Chapter overview](https://agentfactory.panaversity.org/docs/Building-Agent-Factories/openai-apps-sdk)

### 2. Your First Widget

The second lesson moves from architecture to a minimal working app. The stated goal is to get a widget to render in ChatGPT in roughly 45 minutes, using a compact example that displays a styled greeting. The chapter does not try to explain the entire API at once. It picks the smallest example that proves the mechanism works.

The page identifies three requirements for turning a FastMCP tool into a widget:
- the MIME type must be `text/html+skybridge`
- the tool response must attach widget HTML under `_meta["openai.com/widget"]`
- the HTML must be wrapped as an embedded resource

The lesson also introduces a practical development setup with `uvicorn` for the local server and `ngrok` for HTTPS tunneling into ChatGPT. The page is explicit that free ngrok URLs change on restart, so re-registration is part of the normal dev loop.

What the learner should take away is narrow but decisive: a ChatGPT app widget is not just an HTML response. It is an MCP tool response with a very specific MIME type, metadata attachment point, and resource wrapper.

Source: [Your First Widget](https://agentfactory.panaversity.org/docs/Building-Agent-Factories/openai-apps-sdk/first-chatgpt-app)

### 3. Adding a Refresh Button

This lesson introduces interactivity through `window.openai.sendFollowUpMessage`. The widget is still simple, but it now contains a button that can trigger another conversation turn. That move matters because it separates static widget rendering from widget-driven conversation flow.

The page treats `sendFollowUpMessage` as the pattern for actions that should go back through the conversation and the model. The example is a refresh button, but the lesson says the same mechanism will later support TaskManager actions such as adding tasks or re-rendering views. In code terms, the widget calls `window.openai?.sendFollowUpMessage?.({ prompt: "Refresh the greeting" })`.

The main conceptual distinction is this: some widget actions should create a visible conversational step, and this API is for that class of action.

Source: [Adding a Refresh Button](https://agentfactory.panaversity.org/docs/Building-Agent-Factories/openai-apps-sdk/widget-interactivity)

### 4. Displaying Tasks

Lesson 4 swaps the greeting for the first real TaskManager view. The UI now renders a list of tasks backed by in-memory server data. The page introduces the chapter's most important response-design rule: the model and the widget do not need the same payload.

The chapter uses `structuredContent` for the compact, model-visible summary and `_meta` for the full widget-visible data. The widget reads these through two different `window.openai` properties:
- `toolOutput` for `structuredContent`
- `toolResponseMetadata` for `_meta`

The reason is cost and behavior control. If the model sees the full task list, it may narrate or summarize all of it. If the model sees a concise summary while the widget receives the full task data, the UI stays rich and the assistant stays brief. This is one of the chapter's stronger design choices because it links payload structure to both token efficiency and user experience.

Source: [Displaying Tasks](https://agentfactory.panaversity.org/docs/Building-Agent-Factories/openai-apps-sdk/response-payload-design)

### 5. Task Actions with `callTool`

This lesson introduces direct widget-to-server actions. The motivating problem is plain: a task list without working actions is just a report. The solution is `window.openai.callTool`, used here for completing and deleting tasks.

The page contrasts `callTool` with `sendFollowUpMessage`. `sendFollowUpMessage` routes through the conversation, so the model sees the turn. `callTool` invokes the backend tool directly, without requiring a conversational turn. The chapter presents a standard interaction loop for data-changing UI actions:
- call the backend tool with `callTool`
- refresh the display with `sendFollowUpMessage`

The lesson also introduces a security gate. Tools must be explicitly marked with `"openai/widgetAccessible": True` in their annotations before a widget can call them. The page frames this as a deliberate opt-in security control rather than a convenience flag.

Source: [Task Actions with callTool](https://agentfactory.panaversity.org/docs/Building-Agent-Factories/openai-apps-sdk/state-display-modes)

### 6. State Persistence and Display Modes

Lesson 6 addresses the first real UI-state failure mode. When the widget reloads after a tool call, client-side state disappears unless it has been saved somewhere durable. The example is bulk selection: if the user selects several tasks and performs an operation, the next reload wipes those selections.

The chapter's answer is widget-local persistence through `window.openai.widgetState` and `window.openai.setWidgetState(state)`. This state survives widget reloads inside the same conversation. The page uses that mechanism to preserve selected task IDs and then extends the lesson into display modes.

Display modes control where the widget appears, including inline mode and fullscreen. The fullscreen example is implemented through metadata, using `"openai.com/widgetDisplayMode": "fullscreen"` in the tool response. This lesson is where the chapter stops being only about data flow and starts dealing with interaction continuity and layout control.

Source: [State Persistence and Display Modes](https://agentfactory.panaversity.org/docs/Building-Agent-Factories/openai-apps-sdk/taskmanager-widget)

### 7. React & Apps SDK UI

This lesson rebuilds the widget with React and OpenAI's UI package. The chapter's argument is conventional but sensible: vanilla JavaScript is enough for small widgets, but UI complexity eventually makes manual DOM manipulation, ad hoc state, and event wiring expensive to maintain.

The page introduces `@openai/apps-sdk-ui` and positions it as the production path. The practical benefits it lists are concrete:
- design tokens aligned with ChatGPT
- prebuilt components such as buttons, badges, and links
- Tailwind integration
- accessible components built on Radix primitives

The lesson also defines a split project layout with a Python server directory and a separate web directory containing TypeScript, styles, hooks, and bundled widget output. The technical shift here is not just React for its own sake. It is React plus a platform-specific component library that reduces UI mismatch with ChatGPT.

Source: [React & Apps SDK UI](https://agentfactory.panaversity.org/docs/Building-Agent-Factories/openai-apps-sdk/react-apps-sdk-ui)

### 8. Complete TaskManager Capstone

The capstone consolidates the chapter into a single production-oriented view. The page recaps the sequence clearly: start with a simple widget, add conversation-triggered refresh, separate model-visible and widget-visible payloads, add direct tool actions, persist widget state, and then adopt the React-based UI path.

The final section matters because it names the gap between demo and deployment. The page lists the production replacements for the development stack:
- ngrok becomes a permanent HTTPS domain
- in-memory task storage becomes a database
- no authentication becomes OAuth 2.1
- single-user assumptions become multi-tenant design
- ad hoc local execution becomes container deployment

The capstone also includes debugging guidance, such as re-registering the app when widget caching interferes with development and using optional chaining on `window.openai` calls to avoid crashes when the runtime object is absent.

The chapter's real closing point is that a ChatGPT app is a full application surface, not just a decorated tool call. Once deployment, auth, tenancy, persistence, and UI packaging enter the picture, the work looks like product engineering rather than a tutorial toy.

Source: [Complete TaskManager Capstone](https://agentfactory.panaversity.org/docs/Building-Agent-Factories/openai-apps-sdk/taskmanager-capstone)

### 9. Chapter Quiz

The quiz page states that the assessment draws 15 to 20 questions from a pool of 50 and sets the passing score at 80 percent. The sample question shown on the live page reinforces the production message from the capstone by asking what should replace in-memory storage in deployment. In other words, the assessment checks both API mechanics and the chapter's deployment judgment.

Source: [Chapter Quiz](https://agentfactory.panaversity.org/docs/Building-Agent-Factories/openai-apps-sdk/quiz)

## Core patterns the chapter wants the reader to retain

### 1. Separate architecture by responsibility

The chapter insists on a three-part mental model:
- ChatGPT hosts the experience
- the widget owns the visual layer and local UI behavior
- the MCP server owns backend logic and data operations

That separation clarifies who owns which failure mode. Rendering issues usually belong to widget packaging or metadata. Action failures often belong to tool exposure or server behavior. Conversation refresh behavior belongs to the `window.openai` bridge.

### 2. Separate payloads by audience

`structuredContent` is for the model. `_meta` is for the widget. This division keeps model-visible output short and purposeful while still allowing the widget to render detailed state.

### 3. Separate action types by user experience

The chapter uses two action channels for two different interaction styles:
- `sendFollowUpMessage` when the interaction should create or route through a conversation turn
- `callTool` when the interaction should update state directly and return quickly

### 4. Persist UI state explicitly

Server state and widget state are different. The chapter treats that difference as a practical engineering constraint rather than a theory point. If UI continuity matters, save the widget state explicitly.

### 5. Treat the capstone as an app, not a demo

The closing lesson is a reminder that production requirements are not ornamental. Authentication, database storage, multi-tenancy, stable hosting, and deployment packaging are the parts that make the system usable outside a tutorial.

## Operational inventory

Key APIs and metadata introduced across the chapter:
- `text/html+skybridge`
- `_meta["openai.com/widget"]`
- `window.openai.sendFollowUpMessage(...)`
- `window.openai.callTool(...)`
- `"openai/widgetAccessible": True`
- `window.openai.widgetState`
- `window.openai.setWidgetState(...)`
- `_meta["openai.com/widgetDisplayMode"]`
- `@openai/apps-sdk-ui`

## Compressed takeaway

This chapter teaches one thing well: how to move from a backend agent to a ChatGPT-native application surface. It starts with a distribution argument, translates that into a three-layer architecture, and then builds the minimum UI, data, state, and action patterns needed for an interactive app. The TaskManager example is simple, but the method is transferable. Any future ChatGPT app built on MCP tools will need the same decisions about rendering, communication, payload design, widget permissions, state persistence, and production deployment.

## Full source list

- [Chapter 72 overview](https://agentfactory.panaversity.org/docs/Building-Agent-Factories/openai-apps-sdk)
- [Build Your Apps SDK Skill](https://agentfactory.panaversity.org/docs/Building-Agent-Factories/openai-apps-sdk/build-your-apps-sdk-skill)
- [Apps SDK Architecture](https://agentfactory.panaversity.org/docs/Building-Agent-Factories/openai-apps-sdk/apps-sdk-architecture)
- [Your First Widget](https://agentfactory.panaversity.org/docs/Building-Agent-Factories/openai-apps-sdk/first-chatgpt-app)
- [Adding a Refresh Button](https://agentfactory.panaversity.org/docs/Building-Agent-Factories/openai-apps-sdk/widget-interactivity)
- [Displaying Tasks](https://agentfactory.panaversity.org/docs/Building-Agent-Factories/openai-apps-sdk/response-payload-design)
- [Task Actions with callTool](https://agentfactory.panaversity.org/docs/Building-Agent-Factories/openai-apps-sdk/state-display-modes)
- [State Persistence and Display Modes](https://agentfactory.panaversity.org/docs/Building-Agent-Factories/openai-apps-sdk/taskmanager-widget)
- [React & Apps SDK UI](https://agentfactory.panaversity.org/docs/Building-Agent-Factories/openai-apps-sdk/react-apps-sdk-ui)
- [Complete TaskManager Capstone](https://agentfactory.panaversity.org/docs/Building-Agent-Factories/openai-apps-sdk/taskmanager-capstone)
- [Chapter Quiz](https://agentfactory.panaversity.org/docs/Building-Agent-Factories/openai-apps-sdk/quiz)
