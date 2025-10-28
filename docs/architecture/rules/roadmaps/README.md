````markdown
# Frontend Component Architecture Documentation

This directory contains architectural diagrams and patterns for the Context Alt Text frontend React application.

**Last Updated:** October 28, 2025  
**Status:** Phase 10 complete, Face Clustering POC complete (716 tests passing)  
**Next:** Complete MVP alt-text generation pipeline, then RosterRoute refactoring

## 📋 Quick Reference

### Component Architecture Rules

- **Maximum 300 lines** per component file
- **Maximum 5 `useState`** hooks per component
- **Maximum 3 `useEffect`** hooks per component
- Extract sub-components when JSX exceeds 50 lines
- Extract custom hooks when logic is reused 2+ times

See [`../rules/instructions.md`](../rules/instructions.md) for complete enforcement guidelines.

## 🗺️ Architecture Overview

### Current State (October 2025)

**✅ Completed:**

- Dashboard: All 6 cards with tests, analytics, accessibility
- Workbench: Refactored hooks (224-333 lines), extracted utilities
- Utilities: HTTP, normalization, validation (716 tests passing)
- Contracts: TypeScript ↔ PHP alignment documented

**🚧 In Progress:**

- Alt-text generation UI and LLM integration
- REST endpoint implementation for live data
- Storybook documentation

**📍 Technical Debt:**

- RosterRoute: 2,543 lines (target for Phase 2 refactoring)

### Key Architectural Decisions

1. **React Query for Data**: All API calls use React Query with caching
2. **Extracted Utilities**: HTTP, normalization, validation shared across stack
3. **Contract Alignment**: TypeScript and PHP share validation/sanitization logic
4. **Analytics Instrumentation**: IntersectionObserver + custom events
5. **Feature Flags**: Trend visualization, workbench, MCP (post-MVP)

## 📊 Diagram Files

### 🎯 High-Level Architecture

#### **`architecture-roadmap.mmd`** (NEW - October 2025)

**Purpose:** Strategic view of current state, MVP completion path, and post-MVP enhancements

**Shows:**

- ✅ Current state: Dashboard complete, Workbench refactored, 716 tests
- 🎯 MVP blockers: Alt-text UI, REST endpoints, Storybook
- 🚀 Post-MVP: RosterRoute refactor, MCP integration, advanced features
- 📅 Timeline: Q4 2025 (MVP) → Q1 2026 (enhancements) → Q2 2026 (advanced)

**When to use:** Planning next phase, communicating roadmap, prioritizing work

---

#### **`admin-spa-modules-v2.mmd`** (UPDATED - October 2025)

**Purpose:** Complete module map showing all routes, components, hooks, and data flow

**Shows:**

- Routes: Dashboard, Workbench, Roster
- Components: 6 dashboard cards, workbench panels, roster UI
- Hooks: useCoverageMetrics, useRecognitionJob, useWorkbenchMedia, useRoster
- Data layer: React Query, REST API endpoints, backend services
- Utilities: HTTP, normalization, validation, notices, analytics

**When to use:** Understanding system architecture, onboarding new developers, planning integrations

**Replaces:** `admin-spa-modules.mmd` (kept for historical reference)

---

### 🔄 Workflow Diagrams

#### **`sequence-complete-workflow.mmd`** (NEW - October 2025)

**Purpose:** End-to-end sequence diagram for recognition workflow

**Phases:**

1. Media selection & recognition trigger (Workbench → API → Backend)
2. Status polling (useRecognitionPoll with 2s intervals)
3. Observation review (Roster Manager → create/assign/dismiss)
4. Alt-text generation (future: LLM integration)

**When to use:** Understanding recognition flow, debugging issues, planning alt-text integration

---

#### **`face-clustering-components.mmd`** (NEW - October 2025)

**Purpose:** Face clustering frontend architecture showing components, hooks, and data flow

**Shows:**

- Components: UnknownPeoplePanel, ClusterCard, ClusterDetailView, ClusterConfirmationModal, FaceScanActions
- Hooks: useUnknownClusters, useClusterDetail, useClusterSuggestions, useFaceScan
- API Client: clusterApi with REST endpoints
- Types: ClusterSummary, ClusterDetail, UnknownFace, ClusterSuggestion, BBox
- Data flow: React Query → REST API → ClusteringService

**When to use:** Working on face clustering UI, understanding clustering workflow, debugging cluster operations

---

#### **`workbench-flow-v2.mmd`** (UPDATED - October 2025)

**Purpose:** Detailed workbench architecture showing refactored hooks and data flow

**Shows:**

- UI Layer: WorkbenchApp, MediaList, SelectionToolbar, RecognitionActions
- Hook Layer: useWorkbenchMedia (224 lines), useRecognitionJob (333 lines split into submit + poll)
- Utility Layer: HTTP utils, normalization, validation
- Backend: WordPress REST API → Recognition Service → Observations

**When to use:** Working on workbench features, understanding hook composition

**Replaces:** `workbench-flow.mmd` (kept for historical reference)

---

### 📊 Component Details

#### **`dashboard-coverage-detail-v2.mmd`** (UPDATED - October 2025)

**Purpose:** Deep dive into CoverageCard implementation

**Shows:**

- Component structure: CoverageCard → CoverageDonut + CoverageTrend
- React Query integration: useCoverageMetrics hook with 60s stale time
- Analytics: IntersectionObserver tracking, event emission
- Feature flags: coverageTrend gating
- API flow: WordPress REST → DashboardMetricsService → coverage calculation

**When to use:** Understanding dashboard patterns, implementing new cards

**Replaces:** `dashboard-coverage-detail.mmd` (kept for historical reference)

---

### � Pattern Documentation

#### **`component-architecture-patterns.md`**

**Purpose**: Comprehensive guide showing ideal component structures vs problematic patterns

**Contents**:

- ❌ Problem: God Components (2,543-line monsters)
- ✅ Solution: Layered architecture (Route → Feature → UI)
- 📐 Hook extraction patterns
- 🎨 Component composition strategies
- 🔄 State management best practices

**When to use**: Reference when designing new features or refactoring existing components

---

### 2. **Ideal Component Structure** ([`ideal-component-structure.mmd`](./ideal-component-structure.mmd))

**Purpose**: Visual Mermaid diagram showing the ideal layered component architecture

**Contents**:

- Route layer (orchestration, <400 lines)
- Feature layer (business logic, <300 lines)
- UI layer (presentation, <200 lines)
- Hook layer (state management)
- Utility layer (pure functions)

**When to use**: As a reference when planning component hierarchies for new features

---

### 3. **RosterRoute Refactoring Roadmap** ([`roster-route-refactoring-roadmap.mmd`](./roster-route-refactoring-roadmap.mmd))

**Purpose**: Concrete refactoring plan for breaking down the 2,543-line `RosterRoute.tsx`

**Current State**:

- ❌ 2,543 lines
- ❌ 14+ `useState` hooks
- ❌ 6+ `useEffect` hooks
- ❌ 4+ embedded components

**Target State**:

- ✅ 8-10 separate components
- ✅ 3-4 custom hooks
- ✅ Clear separation of concerns
- ✅ ~200-400 lines per file

**When to use**: As a blueprint for refactoring `RosterRoute.tsx` or similar god components

---

### 4. **Anti-Patterns vs Ideal Patterns** ([`anti-patterns-vs-ideal.mmd`](./anti-patterns-vs-ideal.mmd))

**Purpose**: Side-by-side comparison of common React anti-patterns and their solutions

**Covers**:

1. ❌ Mirroring props in state → ✅ Use props directly or controlled/uncontrolled pattern
2. ❌ Storing derived values → ✅ Compute during render with `useMemo`
3. ❌ Chaining state updates → ✅ Handle in single event handler
4. ❌ Prop drilling → ✅ Component composition or context

**When to use**: During code review or when debugging unnecessary re-renders

---

## 🎯 Current Architecture Status

### ✅ Well-Structured Components (Following Guidelines)

| Component              | Lines | useState | useEffect | Status        |
| ---------------------- | ----- | -------- | --------- | ------------- |
| `useWorkbenchMedia.ts` | 224   | 0        | 1         | ✅ Excellent  |
| `useRecognitionJob.ts` | 333   | 5        | 3         | ✅ Good       |
| `useRoster.ts`         | 450   | 5        | 2         | ✅ Good       |
| `WorkbenchApp.tsx`     | 274   | ~3       | ~2        | ✅ Acceptable |

### ❌ Components Needing Refactoring

| Component         | Lines | useState | useEffect | Severity    | Priority |
| ----------------- | ----- | -------- | --------- | ----------- | -------- |
| `RosterRoute.tsx` | 2,543 | 14+      | 6+        | 🔴 Critical | P0       |
| `App.tsx`         | 563   | 8+       | 5+        | 🟠 High     | P1       |

## 🛠️ Refactoring Workflow

### Step 1: Identify Violations

```bash
# Count lines
wc -l js/components/**/*.tsx

# Count hooks (rough)
grep -c "useState\|useEffect" js/components/**/*.tsx
```

### Step 2: Plan Component Extraction

1. Identify distinct responsibilities (data fetching, forms, modals, tables)
2. Look for reusable UI patterns (repeated JSX blocks)
3. Find complex state that can be extracted to custom hooks
4. Spot unnecessary `useEffect` that can be replaced with derived state

### Step 3: Extract in Order (from [`component-architecture-patterns.md`](./component-architecture-patterns.md))

1. **Extract data fetching** → Custom hooks or React Query
2. **Extract sub-components** → Split large JSX blocks
3. **Consolidate state** → `useReducer` or custom hooks
4. **Eliminate unnecessary effects** → Derived state
5. **Extract business logic** → Utility functions
6. **Split by responsibility** → Smart vs dumb components

### Step 4: Verify Improvements

```bash
# Run tests after each extraction
npm test

# Check line counts
wc -l js/components/roster/*.tsx

# Verify hooks usage
grep -n "useState\|useEffect" js/components/roster/RosterRoute.tsx
```

## 📚 Additional Resources

### React Best Practices

- [React Hooks Best Practices](https://react.dev/reference/react)
- [Thinking in React](https://react.dev/learn/thinking-in-react)
- [Extracting State Logic into a Reducer](https://react.dev/learn/extracting-state-logic-into-a-reducer)

### Component Patterns

- [Composition vs Inheritance](https://react.dev/learn/choosing-the-state-structure#avoid-duplication-in-state)
- [When to use `useMemo`](https://react.dev/reference/react/useMemo#should-you-add-usememo-everywhere)
- [You Might Not Need an Effect](https://react.dev/learn/you-might-not-need-an-effect)

### Code Quality Tools

- ESLint: [`eslint-plugin-react-hooks`](https://www.npmjs.com/package/eslint-plugin-react-hooks)
- TypeScript: `strict: true` in tsconfig.json
- Prettier: Consistent formatting (already configured)

## 🎓 Learning from Examples

### Good Example: `useWorkbenchMedia.ts` (224 lines)

**Why it's good**:

- Single responsibility (media data fetching)
- Minimal state (relies on React Query)
- One focused `useEffect` (polling)
- Clear separation of concerns
- Easy to test

### Bad Example: `RosterRoute.tsx` (2,543 lines)

**Why it's bad**:

- Multiple responsibilities (routing, data, forms, modals, tables)
- Excessive state (14+ `useState`)
- Too many effects (6+ `useEffect`)
- Embedded components (4+)
- Hard to test, hard to maintain

**Lesson**: When a component does too much, split it. Each component should have **one primary responsibility**.

---

## � Test Coverage (October 2025)

### Frontend (Vitest)

- **Total:** 362 tests passing ✅
- **Hooks:** useRecognitionJob (44 tests), primitives (78 tests), http (44 tests)
- **Components:** Dashboard cards fully tested with accessibility + analytics
- **Coverage:** ~80% (target achieved)

### PHP (PHPUnit)

- **Total:** 354 tests passing ✅
- **Helpers:** SanitizationHelpers (151 tests), ValidationHelpers (40 tests)
- **Services:** DashboardMetricsService, WorkbenchMediaResolver
- **Coverage:** ~85% (target achieved)

### Contract Alignment

- **TypeScript ↔ PHP:** Documented in `docs/architecture/contracts/`
- **JSON Schemas:** 5 schemas for cross-stack types (Draft 07)
- **Test coverage:** 100% for shared utilities

---

## 🚀 Next Steps

### Immediate (MVP Completion - Q4 2025)

1. **Alt-text generation UI**: Draft approval surface, LLM integration
2. **REST endpoints**: Live data for dashboard cards
3. **Storybook**: Documentation for all components
4. **Workbench**: Bulk operations, progress tracking

### Short-term (Post-MVP - Q1 2026)

1. **RosterRoute refactor**: Split into 8-10 components following roadmap
2. **MCP integration**: Enable Abilities layer for agent access
3. **Advanced metrics**: Historical trends, analytics dashboards

### Mid-term (Q2 2026)

1. **Keyboard shortcuts**: System-wide shortcut map with helper overlay
2. **Batch operations**: Queue manager for background processing
3. **Performance**: Optimize rendering, lazy loading, code splitting

### Long-term

1. **Component library**: Establish reusable primitive components
2. **ESLint rules**: Catch architecture violations automatically
3. **Multi-tenant**: Support for multiple recognition backends

---

**Last Updated**: October 18, 2025  
**Maintainer**: Architecture Team  
**Related**: [`instructions.md`](../rules/instructions.md), [`roadmap-v3.md`](../rules/roadmap-v3.md)

```

```
````
