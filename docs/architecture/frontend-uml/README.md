# Frontend Component Architecture Documentation

This directory contains architectural diagrams and patterns for the Context Alt Text frontend React application.

## 📋 Quick Reference

### Component Architecture Rules

- **Maximum 300 lines** per component file
- **Maximum 5 `useState`** hooks per component
- **Maximum 3 `useEffect`** hooks per component
- Extract sub-components when JSX exceeds 50 lines
- Extract custom hooks when logic is reused 2+ times

See [`../rules/instructions.md`](../rules/instructions.md) for complete enforcement guidelines.

## 📊 Diagram Files

### 1. **Component Architecture Patterns** ([`component-architecture-patterns.md`](./component-architecture-patterns.md))

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

## 🚀 Next Steps

1. **Immediate**: Enforce new limits in code review
2. **Short-term**: Refactor `RosterRoute.tsx` following the roadmap diagram
3. **Mid-term**: Add ESLint rules to catch violations automatically
4. **Long-term**: Establish component library with reusable primitives

---

**Last Updated**: October 17, 2025  
**Maintainer**: Architecture Team  
**Related**: [`instructions.md`](../rules/instructions.md), [`roadmap-v3.md`](../rules/roadmap-v3.md)
