# Drilldown Summary — Chapter 14: Working with General Agents: Claude Code and Cowork

## Source
This summary covers Chapter 14 of *Agent Factory*: **Working with General Agents: Claude Code and Cowork**. It is based on the chapter page, the five section pages, and representative lesson pages consulted in sequence through the chapter navigation.

## One-paragraph summary
Chapter 14 argues that Claude Code and Claude Cowork are not ordinary chat interfaces but **general agents**: systems that can inspect real files, reason through a task, act on the environment, and iterate until they reach a result. The chapter first explains why filesystem access changes AI from passive suggestion into active execution, then moves through setup, context files, skills, subagents, MCP, hooks, plugins, and team workflows. It then shifts from the terminal to the desktop with Cowork, showing the same agent model applied to documents, folders, browsers, and office files. The chapter closes by turning these capabilities into decision rules and business framing: when to use Code versus Cowork, how skills become products, how the same concepts map across vendors, and how to think about general agents as a practical part of knowledge work and software work.

## Central claim
The chapter’s main claim is that the real shift is not “better AI chat,” but **agentic AI with access, context, and execution**. Once the model can see the working environment and act inside it, the bottleneck moves from model intelligence to product design, encoded expertise, and workflow structure.

## Chapter structure at a glance
- **Section A** establishes the core model: why Claude Code matters, how to install it, how to interact with it safely, and how to supply stable context.
- **Section B** explains extensibility: skills, subagents, MCP, and settings.
- **Section C** covers automation and scale: hooks, plugins, iterative loops, teams, worktrees, remote control, tasks, and channels.
- **Section D** translates the same agent model into the desktop through Cowork.
- **Section E** turns the chapter into a decision framework and business lens.

---

## Section A — Claude Code Essentials

### Section summary
Section A takes the reader from the origin of Claude Code to first practical use. Its purpose is to make the terminal-based agent concrete: install it, authenticate it, use it safely, reduce repeated explanation with `CLAUDE.md`, and start building the habits that make a general agent productive instead of chaotic.

### Lesson drilldown
1. **Claude Code Origin Story**  
   Filesystem access unlocked a capability that was already latent in the model: Claude stopped behaving like a remote adviser and started behaving like a partner that could inspect a codebase, run commands, test hypotheses, and iterate.

2. **Installing and Authenticating Claude Code**  
   The lesson covers the official setup path and frames installation as the point where the tool stops being theoretical and becomes part of real work.

3. **Free Claude Code Setup**  
   A lower-cost path is presented so the agent workflow can be learned without depending on the paid Anthropic subscription route.

4. **Hello Claude: Your First Conversation**  
   The reader learns the basic CLI interaction model, including first prompts, approvals, and the difference between observing Claude and letting it act.

5. **CLAUDE.md Context Files**  
   Persistent context files are introduced as project memory: a way to encode conventions, architecture notes, and expectations once instead of restating them every session.

6. **Practical Problem-Solving Exercises**  
   The exercises teach problem decomposition, specification writing, and verification as operational skills for working with an agent.

7. **Teach Claude Your Way of Working**  
   Custom instructions are used to align the agent with personal or team standards so the model fits the workflow instead of forcing a generic default.

### What Section A is really doing
It trains the reader to stop treating AI as a chat box and start treating it as an operator that needs boundaries, context, and feedback loops.

---

## Section B — Skills, Subagents & MCP

### Section summary
Section B explains how a general agent becomes useful in a specific domain without turning into a custom-built application. The main idea is simple: the agent stays general, while expertise and integrations are layered on top through skills, subagents, MCP servers, and configuration.

### Lesson drilldown
8. **The Concept Behind Skills**  
   Skills are presented as encoded expertise rather than new agents: reusable procedures, reasoning patterns, and domain knowledge packaged in a form Claude can load when needed.

9. **Building Your Own Skills**  
   The reader learns how to write skills so recurring patterns become explicit assets rather than prompts improvised from memory.

10. **Agent Skills Exercises**  
    Practice turns skill design into a concrete craft, from simple task templates to more complete skill suites.

11. **Subagents and Orchestration**  
    Complex tasks can be split across specialized helpers, with Claude delegating parts of the work when the structure of the problem makes that sensible.

12. **MCP Integration**  
    Model Context Protocol is introduced as the safe bridge between Claude and outside systems, giving the agent controlled access to tools and data beyond the local environment.

13. **Compiling MCP to Skills**  
    The chapter argues that raw MCP access is often too expensive or too broad; packaging the useful pattern as a skill cuts token use and sharpens behavior.

14. **Settings Hierarchy**  
    Configuration precedence matters once multiple layers of behavior exist, so this lesson explains how rules interact across user, project, and system scope.

### What Section B is really doing
It separates **agent intelligence** from **domain specialization**. The agent remains general; the specialization lives in files, protocols, and orchestration patterns that can be reused, shared, and sold.

---

## Section C — Extensibility & Teams

### Section summary
Section C moves from single-agent usage to operational systems. It covers automatic behaviors, reusable extensions, iterative repair loops, multi-agent coordination, isolated workspaces, remote sessions, scheduling, and event-driven reactions. This is where Claude Code stops looking like a clever terminal helper and starts looking like a platform.

### Lesson drilldown
15. **Hooks: Event-Driven Automation**  
    Hooks turn desired behavior into guaranteed behavior by running code when events occur, such as before or after tool use, on prompt submission, or at session boundaries.

16. **Plugins: Discover and Install**  
    Plugins bundle useful capabilities into portable workflow packages so extension stops being ad hoc.

17. **Ralph Wiggum Loop: Autonomous Iteration Workflows**  
    Claude can be given a target condition and allowed to keep iterating until the condition is met, which makes error correction and repetitive cleanup much more practical.

18. **The Creator’s Workflow: Claude Code Best Practices**  
    This lesson distills a working style for using Claude Code well rather than merely using it often.

19. **Plugins Exercises**  
    Exercises reinforce how to discover, install, test, and work with extensions in practice.

20. **Agent Teams: Coordinating Multiple Claude Sessions**  
    The chapter expands from one agent to several, each handling part of a larger task under explicit coordination.

21. **Agent Teams Exercises**  
    Practice focuses on dividing work cleanly, preserving quality, and preventing multi-agent sprawl.

22. **Worktrees: Parallel Agent Isolation**  
    Git worktrees give each agent an isolated surface for experimentation so parallel work does not collapse into conflict.

23. **Remote Control: Sessions Without Boundaries**  
    Sessions can be reached and managed from elsewhere, which extends the working model beyond the machine sitting in front of the user.

24. **Scheduled Tasks: The Loop Skill and Cron Tools**  
    The agent is made recurring: it can check, remind, or re-run work on a schedule.

25. **Channels: Event-Driven Automation**  
    Instead of polling for changes, agents can react to commits, file events, or outside triggers as they happen.

### What Section C is really doing
It shows how a general agent becomes part of a wider operating model: automated, composable, parallel, and reactive.

---

## Section D — Claude Cowork

### Section summary
Section D brings the same general-agent model into a desktop interface for non-terminal users. The point is not to make Claude “friendlier”; it is to remove the terminal as a barrier while preserving the core advantages of the agent model: direct file access, persistent context, document-native work, and autonomous execution.

### Lesson drilldown
26. **From Terminal to Desktop: The Cowork Story**  
    Cowork is introduced as the desktop expression of the same agent architecture, aimed at researchers, analysts, writers, managers, and other knowledge workers.

27. **Getting Started with Cowork**  
    The reader learns the basic setup, permissions, and operating model for the desktop agent.

28. **Cowork in Action: Practical Workflows**  
    Concrete workflows show how Cowork handles organization, document work, and cross-file tasks that would be tedious through chat alone.

29. **Browser Integration: Claude in Chrome**  
    The desktop agent extends into the browser, making web-based tasks part of the same working surface.

30. **Plugins and Connectors: Extending Cowork’s Reach**  
    Connectors and packaged workflows expand Cowork into systems like productivity suites and workplace tools.

31. **Safety, Limitations, and What’s Coming**  
    The chapter makes the boundaries explicit: where the system is strong, where it should be constrained, and where future capability is expected to land.

32. **Built-in Skills: Documents, Spreadsheets, Presentations**  
    Native support for formats such as Word, Excel, PowerPoint, and PDF moves the agent from text-only assistance into real office work.

33. **Dispatch**  
    Tasks can be assigned to Cowork from other devices, which starts to decouple request from execution context.

34. **Computer Use**  
    Claude can interact with the visible desktop by clicking, typing, and navigating interfaces when direct integration is not available.

35. **Projects and Scheduling**  
    Persistent project organization and time-based execution make Cowork useful across sessions instead of only within them.

36. **Custom Visuals**  
    Cowork can generate diagrams, charts, and other visuals on demand, turning the agent into a presentation and analysis partner as well as a document operator.

### What Section D is really doing
It repositions agentic AI from a developer-only terminal tool to a broader desktop worker that can operate on common business artifacts.

---

## Section E — Strategy & Assessment

### Section summary
Section E turns the chapter from tool training into judgment. The section’s role is to help the reader choose the right interface, recognize where value comes from, and connect the chapter’s patterns to business outcomes and the broader vendor landscape.

### Lesson drilldown
37. **Code vs. Cowork: A Decision Framework**  
   The main rule is straightforward: use Claude Code for code-centric tasks and Cowork for document-centric tasks, then refine that choice by artifact type, goal, and user comfort.

38. **From Skills to Business: Monetizing Agent Expertise**  
   Skills are treated as packaged intellectual property: reusable expertise that can become an internal advantage or an external product.

39. **The Cross-Vendor Landscape: Your Skills Are Portable**  
   The chapter maps Claude-oriented ideas to similar concepts across other vendors, making the case that the underlying patterns outlast a specific platform.

40. **Business Strategy with AI: 10 MBA Frameworks in Your Terminal**  
   General agents are applied to structured business analysis, showing that the same workflow model can be used for strategy work, not only engineering or file manipulation.

41. **Chapter 14 Quiz**  
   The chapter ends with assessment, making the material testable rather than leaving it as a loose collection of demos.

### What Section E is really doing
It converts the chapter from product orientation into operational and commercial judgment: what to use, when to use it, and why the skill layer matters economically.

---

## Major ideas that carry the chapter

### 1. Filesystem access changes the category of the tool
The chapter returns to this point again and again. A model that can inspect real files, run commands, and see the results of its own actions is no longer limited to suggestion. It can pursue a goal.

### 2. The agent stays general; specialization is layered on top
Skills, plugins, subagents, MCP, and settings do not replace the base agent. They narrow, guide, and extend it.

### 3. Context is infrastructure, not decoration
`CLAUDE.md`, hooks, settings, projects, and persistent workspaces all solve the same problem: the agent performs better when expectations and domain knowledge are encoded once and reused.

### 4. Verification matters more than eloquence
The chapter consistently prefers workflows with observable feedback: read the files, run the tests, compare the output, iterate.

### 5. The same model applies beyond software
Cowork extends the logic of Claude Code into document work, research, organization, browser tasks, and office formats.

### 6. Skills are the economic layer
The text frames skills as the point where know-how becomes durable. A prompt is ephemeral; a skill is reusable expertise.

---

## Practical reading of the chapter
If the chapter is reduced to a working sequence, it says:
1. Give the model access to the real environment.
2. Add stable context so it understands the workspace.
3. Encode repeated expertise as skills.
4. Add integrations only where they sharpen execution.
5. Use hooks, schedules, and teams when the workflow needs automation or scale.
6. Choose Code or Cowork based on the primary artifact and user context.
7. Treat durable skills as business assets, not as throwaway prompts.

## Short conclusion
Chapter 14 is less about two Anthropic products than about a pattern for working with general agents. Claude Code and Claude Cowork are the two interfaces, but the deeper lesson is that once an AI can access the work surface, keep context, and act under verification, it becomes a usable operator. The remaining work is organizational: deciding what knowledge to encode, what access to grant, what loops to automate, and what expertise is valuable enough to turn into a repeatable system.
