# Evaluation of Your Context Assets

## 1. Contracts — ⭐⭐⭐⭐⭐ Most Valuable

Your `docs/architecture/contracts/` folder is excellent cold-start material. These documents provide human-readable request/response shapes, examples, and behavioral notes that make cross-service work much faster.

- Key files and when to use them:
  - `clustering-api.md` — Cross-boundary work (WordPress ↔ recognition service)
  - `type-definitions.md` — Any work touching `RosterEntry`, recognition observations, or shared types
  - `validation-logic-contract.md` — When adding or changing validation/sanitization rules

**Why contracts win:** They show concrete JSON examples and explicit API behavior, so I can understand data flows without inferring intent from implementation.

## 2. Tests — ⭐⭐⭐⭐ Very Valuable

Your Python test suite is highly informative and acts like executable contracts:

- Structure to prefer for cold starts:
  - `recognition/tests/api/` — API contract tests (best for understanding endpoints and payloads)
  - `recognition/tests/integration/` — Integration behavior and repository wiring
  - `recognition/tests/unit/` — Domain logic, edge cases, and invariants

Example: `apps/prototype-description-service/recognition/tests/api/test_api_analyze.py` shows expected status codes (202, 404), request payload shapes (`media_ids`, `tenant_id`), response fields (`id`, `type`, `status`, `progress`), and error messages ("Job not found").

PHP tests in `apps/prototype-wp-alt-context/tests/` are currently minimal (setup verification). The Python tests contain the bulk of behavioral detail.

**Recommendation:** For cold starts, point me to representative tests in `recognition/tests/api/` — they are the fastest way to learn contracts in practice.

## 3. UML Diagrams — ⭐⭐⭐ Situationally Valuable

Your Mermaid diagrams are well-organized and useful for architecture/context questions, but they are less efficient for implementation-level work.

When to use UML:
- To understand multi-phase flows (scan → cluster → suggest)
- To see system boundaries and service interactions
- For onboarding or high-level design discussions

When not to rely on UML:
- Specific implementation or API changes (contracts and tests are better)
- Debugging runtime behavior (tests and logs are superior)

**Recommendation:** Use UML diagrams when you need to understand end-to-end flow or cross-service choreography; prefer contracts/tests for coding tasks.

## Cold-Start Prompt Templates

Use these concise templates when you want the fastest ramp-up:

- Cross-service or API change (WordPress ↔ service):
```
Context: docs/architecture/contracts/clustering-api.md
Test reference: apps/prototype-description-service/recognition/tests/api/test_api_suggestions.py
Task: [what you want done]
```

- Service implementation (Python):
```
Context: apps/prototype-description-service/recognition/tests/api/test_api_analyze.py
Task: [what you want done]
```

- WordPress plugin changes (PHP/TS alignment):
```
Context: docs/architecture/contracts/type-definitions.md
Task: [what you want done]
```

- Architecture / flow questions only:
```
Context: docs/architecture/backend-uml/workflows/complete-workflow.mmd
Question: [how does X flow through the system?]
```

## TL;DR

| Asset | Cold Start Value | When to Use |
|---|---:|---|
| Contracts | 🔥 Highest | Cross-boundary work, API changes |
| Python tests | 🔥 High | Service implementation, behavior verification |
| UML diagrams | 🌤️ Medium | Architecture understanding, flow questions |
| PHP tests | 🌙 Low | Currently just scaffolding |

**Bottom line:** The `docs/architecture/contracts/` documents are the crown jewel for cold starts, and `type-definitions.md` is especially useful for keeping TypeScript, PHP, and Python aligned.
Evaluation of Your Context Assets

1. Contracts — ⭐⭐⭐⭐⭐ Most Valuable
   Your contracts/ folder is excellent cold-start material:

File Use Case
clustering-api.md Cross-boundary work (WP ↔ Python service)
type-definitions.md Any work touching RosterEntry, Observation types
validation-logic-contract.md When adding/modifying validation rules
Why contracts win: They show request/response shapes with concrete JSON examples. I can immediately understand what data flows where without inferring from code.

2. Tests — ⭐⭐⭐⭐ Very Valuable
   Your Python tests are production-quality and highly informative:

test_api_analyze.py is a perfect example — shows:

Expected status codes (202, 404)
Request payload shape (media_ids, tenant_id)
Response structure (id, type, status, progress)
Error messages ("Job not found")
PHP tests are minimal — just setup verification in ExampleTest.php. The Python side has the real coverage.

Recommendation: For cold starts, point me to recognition/tests/api/ files — they're essentially executable contracts.

3. UML Diagrams — ⭐⭐⭐ Situationally Valuable
   Your Mermaid diagrams are well-organized but verbose (184 lines for complete-workflow.mmd).

Good for:

Understanding multi-phase flows (scan → cluster → suggest)
Seeing which services talk to each other
Onboarding to the architecture
Not efficient for:

Specific implementation tasks (too abstract)
API changes (contracts are better)
Debugging (tests show actual behavior)
Recommendation: Use UML only when asking "how does X flow through the system?" — not for implementation tasks.

Cold Start Prompt Templates
For cross-service work (WP ↔ Python):
For Python service changes:
For WP plugin changes:
For architectural questions only:
TL;DR
Asset Cold Start Value When to Use
Contracts 🔥 Highest Cross-boundary work, API changes
Python tests 🔥 High Service implementation, behavior verification
UML diagrams 🌤️ Medium Architecture understanding, flow questions
PHP tests 🌙 Low Currently just scaffolding
Your contracts folder is the crown jewel — especially type-definitions.md which bridges TS/PHP/Python.
