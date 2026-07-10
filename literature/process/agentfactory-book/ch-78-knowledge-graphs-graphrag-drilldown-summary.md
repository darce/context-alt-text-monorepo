# Chapter 78 — Knowledge Graphs & GraphRAG — Drilldown Summary

## Source Record
- **Source type:** Chapter overview page
- **Title:** Chapter 78: Knowledge Graphs & GraphRAG
- **Program location:** Part 6: Building Agent Factories → Phase 3: Data & Memory
- **Publisher:** Agent Factory / Panaversity
- **URL:** https://agentfactory.panaversity.org/docs/Building-Agent-Factories/knowledge-graphs-graphrag
- **Status:** Under development

## Main Idea
This chapter introduces knowledge graphs and GraphRAG as a way to give AI agents structured relational memory, especially for problems where linked entities, dependencies, and multi-hop reasoning matter more than plain similarity search.

## Chapter-Level Summary
The chapter frames knowledge graphs as a complement to vector retrieval, not a replacement for it. Its core claim is that some agent tasks depend on explicit relationships between entities, and those tasks are better served by graph traversal than by nearest-neighbor search alone.

The page defines the chapter around six learning goals. First, it establishes graph basics: nodes, edges, properties, and graph schemas. Second, it points to graph databases, with Neo4j named as the production option and lighter alternatives acknowledged for smaller agent systems. Third, it introduces GraphRAG as an architecture that combines graph traversal with LLM reasoning. Fourth, it adds entity extraction as the path from unstructured text to graph structure. Fifth, it identifies multi-hop reasoning as the practical payoff: answering queries that require following chains of relationships rather than retrieving isolated passages. Sixth, it places the whole chapter inside a hybrid retrieval strategy, where the real design question is when to use vectors, graphs, or both together.

The prerequisites clarify how the chapter fits into the broader curriculum. It assumes prior knowledge of vector retrieval from Chapter 73, data modeling from Chapter 74, and the agent SDK foundations from Chapters 62 through 65. That prerequisite stack implies that GraphRAG is treated as an advanced data-and-memory technique built on top of existing agent, database, and retrieval patterns.

The chapter also gives a running example: extending the Task API with graph capabilities. The examples focus on task dependencies, project hierarchies, team structures, and multi-hop operational questions such as identifying all tasks blocking a release. That is the clearest signal of the chapter’s intended use case. The graph is not presented as abstract theory; it is a way to model operational relationships that ordinary document retrieval can miss or flatten.

Because the page is marked as under development, it does not yet expose the lesson-by-lesson build sequence present in the more complete chapters. What exists now is the chapter contract: why graphs matter, what technical pieces the reader is expected to learn, and what kind of agent problem the chapter will eventually solve.

## Drilldown by On-Page Section

### What You’ll Learn
The chapter is scoped around graph modeling, graph databases, GraphRAG architecture, entity extraction, multi-hop reasoning, and hybrid retrieval decisions. The important design claim is that graph-based systems are justified when the agent must reason over explicit relationships instead of retrieving semantically similar text fragments.

### Prerequisites
The prerequisite list places this material after vector RAG, relational modeling, and core agent SDK work. That ordering suggests the chapter assumes the reader already knows how to build an agent and persist data, and is now learning when relational structure should become first-class memory.

### Key Technologies
The page names Neo4j, LangChain GraphRAG, NetworkX, and entity extraction workflows. The stack spans production graph storage, graph-aware retrieval, lightweight in-memory graph operations, and automated graph construction from text.

### Running Example
The Task API example translates graph concepts into concrete agent behavior: dependencies become edges, projects and teams become structured subgraphs, and user queries become traversal problems. The example matters because it ties GraphRAG to workflow software rather than generic knowledge-base demos.

## Compressed Takeaway
Chapter 78 positions knowledge graphs and GraphRAG as the next step after vector RAG and relational storage for agents that need explicit relational reasoning. Its current page does not yet teach the implementation sequence, but it clearly defines the target outcome: build agents that can extract entities, represent them as connected structures, and answer multi-hop questions by combining traversal with LLM reasoning.

## Structural Note
This source is currently a chapter overview page, not a completed multi-lesson chapter. The page explicitly states that the chapter is under development and that future lessons will cover the path from graph fundamentals to production GraphRAG implementation.
