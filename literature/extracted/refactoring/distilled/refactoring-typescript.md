# Refactoring TypeScript — distilled

> **Source**: James Hickey, *Refactoring TypeScript: Keeping your code healthy*, Packt 2019 · extracted from `../Refactoring-TypeScript_Keeping-your-code-healthy.txt` · distilled 2026-07-09 (spec v2)
> **Contributes**: The smallest, most directly actionable pattern set in this directory: nine code smells, each paired with 1–4 concrete TypeScript before→after refactorings an agent can apply mechanically in a diff. Where `refactoring-fowler-beck` gives the exhaustive catalog and process discipline, this source gives the TS-idiomatic hot list — **Null Object**, **Special Case**, outcome-enums-over-deceptive-booleans, strategy-map-over-branch-chain, **gate classes**, **pipe classes**, context-specific classes over generic dumping grounds, and factory/builder object creation. Its unique rules are the *deceptive boolean* smell (a method returning `bool` or `obj|null` that callers immediately branch on) and the *gate class* pattern (reusable async precondition that throws a typed exception caught by middleware).

## Chapter map

- ch-1 — Introduction: what refactoring is; when to do it (Boy Scout Rule, repetition, feature friction)
- ch-2 — Null Checks Everywhere: how to eliminate null-check pyramids (Null Object, Special Case)
- ch-3 — Wordy Conditionals: how to tame long boolean expressions (named vars → domain methods → condition classes → pipes)
- ch-4 — Nested Conditionals: how to flatten if/else trees (guard clauses, fail fast, gate classes)
- ch-5 — Primitive Overuse: when a raw string/bool hides a domain concept (value objects, outcome enums, strategy map)
- ch-6 — Lengthy Method Signatures: what to do with parameter-heavy / optional-param methods (named wrappers, data objects, fluent builders)
- ch-7 — Methods That Never End: when a method is too long and how to cut it (screen rule, extract at seams, strategy pattern)
- ch-8 — Dumping Grounds: how to split generic god-classes (context-specific classes, CQRS, commands/queries)
- ch-9 — Messy Object Creation: how to centralize complex construction (factory functions, options objects, builder)
- ch-10 — Conclusion: scope limits of the book

## ch-1 — Introduction {#ch-1}

**Refactoring** = improving code without changing its behavior. If the "improvement" introduces bugs or changes behavior, it is not refactoring. Prefer **small targeted changes** over sweeping rewrites: large changes carry more risk and take longer to land; small ones keep the system shippable and feedback loops short.

**When to refactor** (three observable triggers):

1. **Boy Scout Rule** — leave any code you touch cleaner than you found it, whatever the reason you touched it.
2. **Repetitive work** — you are writing the *exact* same code that already exists elsewhere → consolidate into a shareable resource so a fix doesn't require editing 12 files.
3. **Difficulty adding features** — the existing code makes a new behavior disproportionately hard to add → refactor the code into a shape where the addition is easy, *then* add it.

Refactoring is continuous and habitual, not a project-plan line item (quotes Fowler: "Done well, it's a regular part of programming activity"). You shouldn't have to ask permission.

**Why TypeScript**: the type system turns a class of runtime production bugs (a function returning sometimes-boolean-sometimes-object; assigning a number to a string field) into compile-time/IDE errors. Design patterns are framed as refactoring tools — reach for them to fix a specific observed problem, never speculatively.

## ch-2 — Null Checks Everywhere {#ch-2}

**Smell**: Hoare's "billion-dollar mistake" metastasized — nested null-check pyramids repeated across the codebase; objects constructible in inconsistent states (`new Product(null, null, null)` — a Product with no id should be impossible).

```ts
// Before: every consumer defends itself
if (product != null) { if (product.id != null) { if (product.title != null) {
  title = product.title; } else { title = "N/A"; } } ... }
```

**Root-cause rule**: fix nulls at the producer (the method that returns them), not at every consumer. One producer-side fix deletes N consumer-side checks.

**Aside — `strictNullChecks`**: TypeScript's non-nullable types flag helps, but (a) legacy codebases can't flip it cheaply, (b) flipping it without tests can itself cause runtime regressions, (c) the patterns below work in any language.

### Null Object Pattern — collections

Never return a null array. At the fetch boundary, substitute empties:

```ts
const legalCases = legalCasesFromAPI || [];            // whole collection
for (const c of legalCases) c.documents = c.documents || [];  // nested arrays
```

In strictly-typed languages without array-literal coercion: `EmptyArray.create<T>()` returning `new Array<T>()`.

### Null Object Pattern — objects

Replace a nullable reference with an interface + a do-nothing implementation:

```ts
interface IBoss { fight(player: Player); isDead(): boolean; }
class NullBoss implements IBoss {
  fight(player: Player) { /* player always wins */ }
  isDead() { return true; }
}
// After: no consumer null checks, ever
currentLevel.boss.fight(player);
```

### Special Case Pattern

Null Object "taken a step further": when the object has *multiple* alternate states, not just absent/present. Background order processor must handle pending / payment-rejected / fraudulent-account orders — instead of a status enum branched on at every call site (`if (order.status === OrderStatus.Pending) ... else if ...`), give each state its own class behind one interface:

```ts
class PendingOrder implements IOrder          { placeOrder() { /* API call */ } }
class PaymentRejectedOrder implements IOrder  { placeOrder() { /* retry payment */ } }
class OrderOnFraudulentAccount implements IOrder { placeOrder() { /* notify fraud dept */ } }

const orders: IOrder[] = await getOrders();
for (const order of orders) order.placeOrder();   // no status switch anywhere
```

Rename `placeOrder` → `tryPlaceOrder` for semantic honesty. **Trigger**: status-enum branch chains repeated at call sites → move the per-status behavior into per-status classes.

## ch-3 — Wordy Conditionals {#ch-3}

**Smell**: long boolean expressions inline in `if` — hard to read, impossible to test directly, and duplicated (the "fixed" bug reappears next week in the copy-pasted twin).

```ts
if (user.role === "admin" && user.active
    && user.permissions.some(p => p === "edit")) { ... }
```

Four escalating fixes — start with the cheapest; escalate only when the code warrants it:

**1. Extract named variables.** Each sub-condition gets a name; combine into one intent-revealing variable. **Guideline: an `if` statement should test one variable**; multiple checks → combine into a named boolean first.

```ts
const isAdmin = user.role === "admin";
const userIsActive = user.active;
const userCanEdit = user.permissions.some(p => p === "edit");
const activeAdminCanEdit = isAdmin && userIsActive && userCanEdit;
if (activeAdminCanEdit) { ... }
```

**2. Extract methods onto the domain object.** The checks are all *about the user* → the user owns them: `user.isAdmin() && user.isActive() && user.canEdit()`. Now the logic is shareable and independently testable.

**3. Extract condition classes (SRP).** When the domain class accumulates dozens of check-methods (`isActiveAdmin`, `isActiveAdminThatCanEdit`, …), extract each condition into its own single-responsibility class:

```ts
class UserIsActiveAdmin {
  constructor(private _user: User) {}
  invoke(): boolean { return this._user.isAdmin() && this._user.isActive(); }
}
```

**4. Pipe Classes.** Many small condition classes to combine? A class name like `CheckOneCheckTwo…CheckEight` is the tell. Keep each class checking one or two things behind a common interface and pipe them:

```ts
interface IPipeableCondition { check(): boolean; }
const conditions: IPipeableCondition[] = [
  new UserIsActiveAdmin(user), new UserCanEdit(user), new UserIsNotBlacklisted(user)];
const valid = conditions.every(p => p.check());
```

If the same pipe is used in several places, wrap it in a `ConditionsPipe` class holding the array. Hickey's own caveat: pipes are "not the go-to" — use only when condition count and reuse warrant it.

## ch-4 — Nested Conditionals {#ch-4}

**Smell**: if/else trees and deep indentation (his real-world worst: a 5,000-line function that was one giant switch of nested ifs). Symptom in code: a null-initialized mutable `result` variable assigned in different branches and returned at the end.

### Guard Clauses (fail fast)

Two principles: (1) **return from the method at the earliest possible moment**; (2) **test for failure, not success**. Nested conditionals do the opposite.

```ts
// Before: 4 levels deep, mutable result      // After: flat guard clauses
let result = null;                            if (order.wasCancelled()) return;
if (!order.wasCancelled()) { ... }            if (order.wasPaid()) return order.sendToShipping();
return result;                                if (order.isFraudulent()) return order.sendToFraudDept();
                                              return order.tryAgainLater();
```

Flat code is easier to read *and to extend* — ch-5's login example shows new rules dropping in as one guard line each.

### Gate Classes

Hickey's own coinage. A **gate** is an `if` with no `else` that only lets the rest of the function run when the condition passes. When gates (a) have external/async dependencies (repositories) and (b) are needed in multiple places, extract each into a class that **throws a typed exception on failure**:

```ts
class AccountIsVerifiedGate {
  constructor(private _accountRepo: AccountRepo) {}
  async invoke(account: UserAccount) {
    const ok = await this._accountRepo.accountIsVerified(account);
    if (!ok) throw "Gate exception";   // use a dedicated exception type in practice
  }
}
// Usage — zero nesting:
await accountIsVerifiedGate.invoke(userAccount);
await userCanPlaceOrderGate.invoke(user);
await orderRepo.placeOrder(order);
```

A global error handler / web middleware catches the gate exception type and maps it to a response (401/403) automatically — failure handling is centralized once. Hickey flags this as **not an entry-level pattern**: use it when the same precondition guards multiple entry points, not for one-off checks.

## ch-5 — Primitive Overuse {#ch-5}

**Smell**: raw strings/numbers/booleans carry an implicit business concept — email-parsing regexes inline, `firstname + " " + lastname` with null-coalescing scattered around. Consequences: logic unshareable (so duplicated), concept implicit (exists only in a lucky variable name), validation optional.

### Value Objects

Encapsulate the primitive plus all its logic in a class. Canonical example — email routing:

```ts
class EmailAddress {
  private _value: string; private _domain: string; private _userName: string;
  constructor(value: string) {
    if (this.isExternal(value)) throw "Cannot email externally.";  // validate HERE
    this._domain = value.replace(/.*@/, "");
    this._userName = value.replace(this._domain, "");
    this._value = value;
  }
  isExternal(): boolean { return this._domain !== "internal-company.com"; }
  isInfoUser(): boolean { return this._userName === "info"; }
  value(): string { return this._value; }
}
```

Rules for a **true value object**: (1) **immutable** — no setters, private fields, expose only the read methods outsiders need; (2) **validates in its constructor and throws** — it can never exist in an invalid state, so no downstream code can misuse it; (3) all logic for the concept lives in this one place. Call sites collapse: `if (emailAddress.isInfoUser()) mailer.sendToCustomerServiceTeam(emailAddress.value(), message);`

### Deceptive Booleans → outcome enums

The most common primitive-overuse case Hickey sees. **Smell**: a method returns `boolean` (or `User | null`, or an object whose boolean properties are checked immediately) and every caller branches on it. Each new business rule (inactive user, existing session, locked out, first login) piles on nested checks or bloats the `User` class with auth-only flags — the class becomes a dumping ground for data no other feature needs.

**Fix**: rename to `try…` and return an enum naming *every* possible outcome:

```ts
enum AuthenticationResult {
  InvalidCredentials, UserIsNotActive, HasExistingSession,
  IsLockedOut, IsFirstLogin, Successful
}
const result = await tryAuthenticateUser(username, password);
if (result === AuthenticationResult.InvalidCredentials)
  returnErrorOnLoginPage("Credentials are not valid.");
// ... one flat guard per outcome
```

One return value, no nulls, no host-class pollution, all outcomes discoverable from the type.

### Strategy Pattern over the enum branch chain

When outcome branches multiply, replace the guard chain with an enum-indexed handler map — "whenever I use the enum refactoring, I automatically know the strategy pattern might help me more":

```ts
const strategies: any = [];
strategies[AuthenticationResult.InvalidCredentials] = () => returnErrorOnLoginPage("...");
strategies[AuthenticationResult.Successful]        = () => redirectToUserDashboard();
strategies[result]();
```

Adding an outcome = one enum member + one map entry; no existing lines touched.

## ch-6 — Lengthy Method Signatures {#ch-6}

**Smell**: the **optional-parameter slippery slope**. `getUsers()` grows a `includeInactive = false` flag, then `filterText`, `orderByName`, `forHireDate`… Each optional param multiplies the method's behaviors *combinatorially*, and the signature can't tell you which combinations are valid. Even many *required* params signal an SRP violation.

**Diagnostic question**: *are the parameters just data the method needs, or do they tell the method to alter its behavior?* Behavior-switching params → refactor.

**Failure criterion**: "If you have to open up the source code of a method to understand how to use it, then that method has failed to give you a clear, understandable, and usable abstraction."

### Behavior-switching params → private core + semantic wrappers

1. Make the flag-ridden method `private`. 2. Expose one public method per real behavior, named for it:

```ts
private getUsers(includeInactive = false, filterText: string = null,
                 orderByName = false, forHireDate: Date = null): User[] { ... }
public getActiveUsers(): User[]                     { return this.getUsers(false); }
public getInactiveUsers(): User[]                   { return this.getUsers(true); }
public getActiveUsersByName(filter: string): User[] { return this.getUsers(false, filter); }
public getActiveUsersForHireDate(d: Date): User[]   { return this.getUsers(false, null, false, d); }
```

Callers pick a name, not a flag combination. (Fluent alternative for query-heavy code: `new UserQueryBuilder().whereLike("Username", filter).orderBy("Username").execute()` — but prefer an existing ORM/query library over building one.)

### Data params → Extract Data Object

When the params are pure data (`saveUserDetails(id, employeeId, firstName, lastName, email, phone, fax)`), group them into a purpose-named class — `UserForStorage`, not a generic `User` — and pass one object: `await saveUserDetails(user)`. Logically distinct groups become separate objects: `saveUserDetails(user, contactInformation)`.

## ch-7 — Methods That Never End {#ch-7}

**Smell**: a method too long to hold in your head. Rejects line-count metrics ("no longer than 10 lines" is unhelpful); his **screen rule**: *if the method is taller than your monitor, it's too long*. Real-world pathology: 5,000-line methods; files an IDE couldn't load.

**Reframe**: methods are not primarily for code reuse — **their main purpose is to abstract a chunk of code and give it an understandable label**. A section comment (`// This section checks if a user is allowed…`) is a method name waiting to be extracted.

### Extract methods at the comment seams

Annotate the natural sections, then turn each into a named method. The order-processing monster collapses to:

```ts
const userAllowed = await this.sessionUserCanModifyOrder();
if (!userAllowed) return new ValidationMessage("User not allowed.");
return this.retry(3, () => this.processOrder(orderId));   // retry loop → higher-order fn

public async processOrder(orderId: string) {
  const order = await this.getOrderById(orderId);
  order.isActive() ? this.processActiveOrder(order) : this.tryArchivingOrder(order);
  return await this.tryUpdateOrder(order);
}
```

Multiple *levels* of extraction are normal and expected — keep going until every method fits on screen. Note the retry-while-loop became a reusable `retry(n, fn)` higher-order function.

### Strategy pattern for lengthy conditional bodies

The other long-method cause: an `if/else if` chain where each branch holds a page of logic. "The classic refactoring… is the strategy pattern" — with a numeric-backed enum, an indexed handler table:

```ts
enum OrderStatus { Pending = 0, Shipped = 1, Cancelled = 2, Returned = 3 }
const strategies: Function[] = [];
strategies[OrderStatus.Pending]   = this.processPendingOrder;
strategies[OrderStatus.Shipped]   = this.processShippedOrder;
strategies[OrderStatus.Cancelled] = this.processCancelledOrder;
strategies[OrderStatus.Returned]  = this.processReturnedOrder;
strategies[order.getStatus()]();
```

Each branch body becomes a named method; the dispatch is one line; new statuses don't touch existing code.

## ch-8 — Dumping Grounds {#ch-8}

**Smell**: generic classes — `User`, `Customer`, `Order` — reused across unrelated features (billing, shipping, profile, auth). Because they're generic, they become **dumping grounds** for code nobody knows where else to put. Most "OOP" codebases use objects as "glorified variables" (data holders filled by an HTTP/DB layer), not Alan Kay's message-passing bundles.

**Coupling consequence**: change `User` for billing and you might break shipping — probability > 0%, so you must re-test everything, which breeds *fear of changing code*. Goal: **orthogonal** code — changing one place can't affect unrelated places.

**Warning-sign heuristic**: a class name should answer at least two of: (1) *subject* (user, order), (2) *context* (shipping, auth, dashboard), (3) *action performed on the subject*. `User` answers one → alarm. `UserForAuthentication`, `PaymentsCustomer` → fine.

### Context-specific classes

Split the god-`User` into one class per consuming context, each carrying only the data+methods that context uses:

```ts
class UserProfileUser      { id; firstName; lastName; homeAddress; getFullName() {...} }
class ShippingUser         { id; homeAddress; }
class UserForAuthentication{ id; jwtToken; decodeJwtToken() {...} }
class PaymentUser          { id; creditCardNo; }
```

**Duplicated data across contexts is fine.** `homeAddress` appears in both profile and shipping — same raw data, *different business concepts* (UI editing vs. delivery destination; billing address may legitimately differ from shipping address). "It's better to duplicate code and/or data if they are within different contexts" — DRY dogma is what created the dumping ground. ↔ tension with naive DRY readings of `refactoring-fowler-beck` (duplication smell): Hickey scopes DRY to *same business concept*, not same-looking data.

### CQRS — split reads from writes

**CQRS** (Command Query Responsibility Segregation), at the basic level used here: never let one class serve both write scenarios (mutations enforcing business rules, e.g. `changeCreditCard` validating the number) and read scenarios (display logic, e.g. `displayName()`). Split `PaymentUser` → `PaymentUserForWrite` (id, creditCardNo, `changeCreditCard`) + `PaymentUserForDisplay` (id, names, `displayName`).

### Commands and Queries

Take it further — one class per business scenario, each read-only or write-only:

- **Command** — changes the system, returns no display data: `UpdateUserCreditCardInfoCommand.handle(newNumber)` (validates, mutates). No one touches this class except when working on exactly this use case.
- **Query** — returns data for a decision/display, changes nothing: `UserProfileQuery.handle(forUserId): Promise<UserProfileView>` returning a dedicated **view model** class (`UserProfileView` — plain fields, no behavior).

**A word of caution** (author's own): CQRS/commands/queries is *not* a refactoring you always apply — it depends on project complexity. The context-splitting of the first half is the broadly applicable part.

## ch-9 — Messy Object Creation {#ch-9}

**Smell**: multi-step construction (`new Airplane()` + eight property assignments) copy-pasted at call sites; callers reaching into objects to set internals. No central place to fix a construction bug; hard to test.

### Factory Functions

Encapsulate construction in a named, parameterized function:

```ts
const createPassengerPlane = (numberOfSeats: number): Airplane => {
  const plane = new Airplane();
  plane.type = PlaneType.Passenger;
  plane.engine = new PassengerPlaneEngine();
  plane.hasFirstClass = true; plane.hasBathroom = false;
  plane.numberOfSeats = numberOfSeats;
  return plane;
};
const plane1 = createPassengerPlane(100);
```

TS: prefer module-level exported functions. Java/C# (no free functions): static methods on an `AirplaneFactory` class.

### Options object + preset factories + Builder

When the factory itself needs many params, combine ch-6's data-object extraction: `createPlane(options: PlaneCreationOptions)`. That moves the noise into building the options — so add **preset factory functions** for common configurations (`fullyLoadedPassengerOptions()`, `bareBonesPassengerOptions()`), then make the options object **fluent** (each `with…` setter returns `this`) — the **Builder Pattern**, done as plain functions rather than Java-style builder class hierarchies:

```ts
class PlaneCreationOptions {
  withSeats(n: number) { this.numberOfSeats = n; return this; }
  // ...other with* methods
}
const plane1 = createPlane(fullyLoadedPassengerOptions());
const plane2 = createPlane(bareBonesPassengerOptions().withSeats(50));
```

Readable at the call site, one central place per configuration to fix bugs, trivially testable (build options, assert fields).

## ch-10 — Conclusion {#ch-10}

Explicitly a starter set: many smells and techniques are out of scope. Code health is one axis among architecture, business process, and product concerns. Improvement path = practice on the code you're already working in.

## Decision rules (summary)

| Trigger (observable in code/diff/plan) | Rule | Rationale | Src |
|---|---|---|---|
| Writing the exact same code that already exists elsewhere | Consolidate into a shared resource before proceeding | One bug fix shouldn't require editing N files | ch-1 |
| New feature is disproportionately hard to add | Refactor the surrounding code into shape first, then add the feature | Code inflexibility, not the feature, is the obstacle | ch-1 |
| Planned refactor is a sweeping rewrite | Split into small targeted changes | Large changes = more risk, longer un-shippable state | ch-1 |
| Constructor accepts nulls for fields the domain requires (`new Product(null,…)`) | Make invalid states unconstructible (validate/require in ctor) | Objects in inconsistent states force downstream null checks | ch-2 |
| Function can return a null array/collection | Return `[]` (Null Object) at the producer | Producer-side fix deletes every consumer-side null check | ch-2 |
| Same null check on the same object repeated at ≥2 call sites | Introduce a Null Object implementation of a shared interface | Consumers call methods unconditionally | ch-2 |
| Status-enum `if/else if` chain repeated at call sites, branches do per-state work | Special Case Pattern: one class per state behind one interface | Each state owns its logic; call sites lose the switch | ch-2 |
| `if` tests >1 variable / long `&&` chain inline | Extract named booleans; combine into one intent-named variable | An `if` should reference one condition | ch-3 |
| Extracted conditions are all about one domain object | Move them onto that object as methods | Shareable, testable, self-documenting | ch-3 |
| Domain class accumulating many boolean check-methods | Extract each condition into its own class (SRP) | Keeps the domain class small; conditions composable | ch-3 |
| >3–4 independent condition objects combined in several places | Pipe classes: `IPipeableCondition[]` + `every(c => c.check())` | Composition at runtime instead of a mega-class | ch-3 |
| Nested if/else with mutable null-initialized `result` returned at end | Guard clauses: earliest return, test for failure not success | Flat code is readable and extends one line at a time | ch-4 |
| Same async precondition (repo/API check) guards multiple entry points | Gate class: `invoke()` throws typed exception; middleware maps to response | Centralizes both the check and its failure handling | ch-4 |
| Regex/string surgery on the same primitive in multiple places | Value object encapsulating the primitive + its logic | Implicit business concept made explicit and shareable | ch-5 |
| Value-object-like class mutable or constructible invalid | No setters; validate in constructor and throw | An object that can't be invalid needs no downstream defense | ch-5 |
| Method returns `boolean` or `T \| null` and caller immediately branches | Rename `try…`, return an outcome enum covering all results | Deceptive boolean: outcomes multiply; enum names them all | ch-5 |
| Guard chain over an outcome enum keeps growing | Strategy map keyed by enum → handler | New outcome = one entry, zero edits to existing lines | ch-5 |
| Diff adds an optional param that changes what a method *does* | Stop: make core private, expose named public wrappers per behavior | Optional params multiply behaviors combinatorially | ch-6 |
| Caller must read a method's body to know how to call it | The abstraction has failed — redesign the signature | Signatures are the contract, not the source | ch-6 |
| Method takes many pure-data params | Extract a purpose-named data object (`UserForStorage`) | One argument; groups documented by the type | ch-6 |
| Method taller than one screen | Extract methods at natural seams until each fits on screen | Methods exist to label/abstract, not just to reuse | ch-7 |
| Section comment inside a method body | That comment is the name of a method to extract | Comments marking sections = seams | ch-7 |
| `if/else if` chain with a page of logic per branch | Strategy: extract each branch to a method, dispatch via enum-keyed map | Dispatch shrinks to one line; branches independently readable | ch-7 |
| Class named bare subject (`User`, `Order`) used by unrelated features | Split into per-context classes (subject + context in the name) | Generic classes become dumping grounds and couple features | ch-8 |
| Reviewer flags duplicated fields across context classes | Accept it when contexts differ — same data ≠ same concept | De-duplicating across contexts re-couples features | ch-8 |
| One class holds both mutation-with-rules methods and display methods | Split write model from read model (CQRS); escalate to Command/Query classes per scenario if complex | Read and write concerns evolve independently | ch-8 |
| Multi-step object construction copy-pasted at call sites | Factory function (module-level in TS) | One central place to build and to fix | ch-9 |
| Factory/constructor itself needs many params | Options data object + preset factories + fluent `with…` builders | Call-site readability; presets testable in isolation | ch-9 |

## Anti-patterns

- **Null-check pyramid** — detection: ≥2 nesting levels of `!= null` on one object graph; `"N/A"`-style defaults assigned in multiple else-branches. Fix at the producer (ch-2).
- **Constructible-invalid object** — detection: constructor params can be null/omitted for domain-required fields; public settable fields on a domain concept (ch-2, ch-5).
- **Verbose conditional** — detection: `if` with ≥3 `&&`/`||` terms inline; same boolean expression copy-pasted in >1 file (ch-3).
- **Mega-condition class** — detection: class name concatenating checks (`UserIsActiveAdminAndCanEdit`, `CheckOneCheckTwo…`) (ch-3).
- **Arrow anti-pattern / nested conditionals** — detection: mutable `result` initialized to null and assigned in branches; success-path tested before failure paths (ch-4).
- **Deceptive boolean** — detection: `Promise<boolean>` or `T | null` return from a `verbUser()`-style method, with an immediate `if` on the result at every call site; boolean flags added to a domain class that only one feature reads (ch-5).
- **Optional-parameter slippery slope** — detection: diff adds a defaulted param to an existing public method; signature with ≥2 behavior-flags (ch-6).
- **Comment-sectioned method** — detection: block comments delimiting phases inside one method body; method exceeds one screen (ch-7).
- **Dumping ground / god class** — detection: bare-subject class name imported by ≥3 unrelated feature folders; fields used by disjoint features (jwtToken next to creditCardNo) (ch-8).
- **Mixed read/write model** — detection: `display…()`/formatting methods and rule-enforcing mutators on the same class (ch-8).
- **Copy-paste construction** — detection: `new X()` followed by ≥3 property assignments, appearing at >1 call site (ch-9).

## Applicability & exemptions

- **This is a refactoring-patterns source, NOT a concurrency source.** It says nothing about async correctness, ordering, races, or resilience — `await` appears only incidentally in examples. For concurrency cite `using-asyncio-in-python`; for resilience cite `release-it`.
- **Scope**: application-level TypeScript (web apps, APIs, background jobs) in an OO-leaning style. Hickey is explicitly paradigm-agnostic (TS "embraces both" OOP and FP) — in a functional codebase, condition classes/gate classes translate to predicate functions and composition; don't force class-shaped fixes there.
- **Beginner-oriented breadth, not a catalog**: nine smells only; for mechanics (safe steps, test-first discipline) and the full catalog defer to `refactoring-fowler-beck`. Hickey's own book says techniques here are "just the beginning."
- **Escalation ladders are ordered** — extract-variable before condition classes before pipes; guard clauses before gate classes; enum before strategy map; factory before builder. Firing the heavyweight pattern on first contact is over-application; Hickey flags pipes as "not the go-to" and gates as "not an entry-level pattern."
- **CQRS / Commands+Queries is explicitly optional** ("this isn't refactoring that you necessarily ought to always implement") — apply only when a class demonstrably accumulates both rule-heavy writes and display reads.
- **Duplicate-data license is scoped**: duplication is acceptable *across different business contexts* only. Identical logic within one context is still the ch-1 repetition trigger — consolidate it.
- **TS-strictness caveats (2019-era code)**: the strategy-map examples use `const strategies: any = []` and numeric-enum array indexing, and gates `throw` a string — under modern `strict` TS, prefer `Record<Enum, () => T>` (exhaustiveness-checked) and `Error` subclasses. The *pattern* stands; the literal snippets predate current lint norms. Book also predates optional chaining (`?.`)/nullish coalescing being idiomatic — those shrink null-check pyramids but don't replace Null Object (callers still branch); the producer-side rule still applies.
- **Non-nullable types**: `strictNullChecks` removes much of ch-2's motivation in greenfield TS; the Null Object/Special Case patterns remain valuable for representing *absent-with-behavior* and multi-state domains, and for languages/configs without the flag.
- **Screen rule is a heuristic**, monitor-dependent by construction — treat as a review prompt, not a lint threshold.

## Candidate lexicon rows

| method returns `boolean` or `T \| null` and every caller immediately branches on it | **No deceptive booleans** — return an outcome enum (`try…` naming) so all results are explicit and callers can't half-handle them | Does the caller's first act on this return value decide between success/failure paths? | should | write | src: refactoring-typescript ch-5 |
| function may return a null array/collection | **Null Object at the producer** — return `[]`/empty collection from the source so no consumer ever null-checks | Can any code path hand callers `null` where a collection is expected? | should | write | src: refactoring-typescript ch-2 |
| status-enum `if/else` chain with per-state behavior repeated at call sites | **Special Case classes** — one class per state behind a shared interface; call sites lose the switch | Is the same status switch appearing at more than one call site? | judgment | review | src: refactoring-typescript ch-2 |
| `if` statement tests ≥3 boolean terms inline | **One condition per if** — extract named booleans (or domain methods) and test a single intent-named variable | Could this expression be read aloud as one business statement? | should | write | src: refactoring-typescript ch-3 |
| nested if/else assigning a null-initialized mutable `result` | **Guard clauses / fail fast** — return earliest, test failure not success, flatten the tree | Can each branch become an early return? | should | write | src: refactoring-typescript ch-4 |
| enum-keyed `if/else` or `switch` chain that grows with each new case | **Strategy map over branch chain** — enum-indexed handler map; new case = one entry, no edits to existing lines | Will the next requirement add another branch here? | judgment | write | src: refactoring-typescript ch-5 |
| diff adds an optional/defaulted param that changes a public method's behavior | **No behavior-flag params** — make the core private and expose one named public method per behavior | Does this parameter select *what the method does* rather than supply data? | should | review | src: refactoring-typescript ch-6 |
| primitive (string/number) undergoing the same parsing/validation in >1 place | **Value object** — immutable class, validates in constructor, owns all logic for the concept | Is there a business concept hiding in this variable's name? | judgment | write | src: refactoring-typescript ch-5 |
| method body longer than one screen or containing section comments | **Extract at the seams** — each commented section becomes a named method; recurse until all fit on screen | What would each section be called if it had to have a name? | should | review | src: refactoring-typescript ch-7 |
| class named by bare subject (`User`, `Order`) imported by unrelated features | **Context-specific classes** — split per consuming context (subject+context name); duplicate fields across contexts are acceptable | Can the class name answer both "what subject?" and "which context?" | judgment | plan | src: refactoring-typescript ch-8 |
| `new X()` followed by several property assignments, copy-pasted at call sites | **Factory function** — centralize construction in a named module-level function; escalate to options object + fluent builder for many params | Is there exactly one place to fix a construction bug? | should | write | src: refactoring-typescript ch-9 |
| same async precondition check guarding multiple entry points | **Gate class** — extract the check to a class that throws a typed exception; map it to a response once in middleware | Is this precondition's failure handling duplicated per call site? | judgment | plan | src: refactoring-typescript ch-4 |
