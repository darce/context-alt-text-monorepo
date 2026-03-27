# Phase 2 / Chapter 47 drilldown summary: Specify with Types

## Source record

- Source type: curriculum phase overview and part overview
- Title: Phase 2 — Specify with Types
- Venue: Agent Factory
- URLs:
  - https://agentfactory.panaversity.org/docs/Programming-in-the-AI-Era/specify-with-types
  - https://agentfactory.panaversity.org/docs/Programming-in-the-AI-Era

## Scope note

The provided URL is a phase landing page, not a long chapter lesson page. The landing page labels this material as Chapters 34, 35, 36, and 37. The broader Part 4 overview maps the same phase to Chapters 47, 48, 49, and 50. This summary keeps that discrepancy visible instead of normalizing it away.

## Main idea

In "Phase 2 — Specify with Types," the course explains that AI-generated code improves only when the human specification is precise, and it presents Python's type system as the language for stating intent before any implementation is generated.

## Drilldown

The phase defines the learner's role as "Specifier": the person who can tell AI exactly what to build. Its central claim is simple. Ambiguity at the specification stage produces weak AI output, so the human must describe data and behavior precisely before generation begins.

The landing page organizes the phase around four focus areas. The first is primitive types and expressions, presented as the basic vocabulary of typed specifications. The second is collections: lists, dictionaries, tuples, and sets, which extend that vocabulary from single values to structured groups of values. The third is data modeling with dataclasses and Pydantic, where the course moves from loose data containers to explicit domain structure. The fourth is functions as contracts, where function signatures stop being just syntax and become a specification of accepted inputs and expected outputs.

Read against the broader Part 4 overview, the phase sits inside the course's Test-Driven Generation method. Part 4 argues that the human role is no longer to type most of the implementation by hand, but to define intent, state correctness criteria, and verify results. Within that larger workflow, Phase 2 handles the first of those responsibilities: giving AI a typed description of the shapes, constraints, and interfaces the code must follow.

The Part 4 overview also shows why this phase comes after the workbench phase and before the tests phase. The course wants the learner to read code first, then describe data precisely, then write tests that define correctness. Types therefore bridge basic code literacy and full specification. They are not treated as decorative annotations. They are treated as a way to reduce guesswork before generation.

The project layer reinforces the same point. In the SmartNotes build that runs through Part 4, Phase 2 adds the data structures for notes, tags, and collections. The goal is not to practice syntax in isolation. It is to specify the shape of a real domain clearly enough that AI can generate the right structures for an evolving application.

The phase ends with a concrete outcome. By the end, the learner should be able to write a type-annotated specification that tells AI what to build without leaving key decisions implicit. In the logic of the course, that is the threshold between prompting for plausible code and directing code generation with intent.

## Condensed takeaway

This phase teaches that types are not a secondary polish step. They are the first serious specification tool in the book's programming workflow. Primitive values, collections, data models, and function signatures together form the vocabulary the human uses to constrain AI before code generation starts.
