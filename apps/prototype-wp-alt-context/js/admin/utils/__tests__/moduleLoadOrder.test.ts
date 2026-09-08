/**
 * FEBT2-LA-NEW-01 / FEBT2-LC-NEW-03 — runtime load-order guard.
 *
 * `api/config -> utils/logger -> utils/appError -> utils/http -> api/config` was a
 * load-time ESM cycle. Whichever module the graph was entered from evaluated last,
 * so a top-level `class NonceRefreshError extends NonceRefreshFailedError` saw its
 * base binding still in the temporal dead zone and threw
 * `TypeError: Class extends value undefined is not a constructor or null` — at
 * *collection* time, taking down every suite that transitively imported `http.ts`.
 * `tsc --noEmit` passed the whole time: the type graph is order-free, the
 * evaluation graph is not.
 *
 * Canon applied:
 *  - ARCH-13 (lexicons/engineering.md:563) — a property enforced only by discipline
 *    is eventually violated. "Do not add a cross-module `extends`" is discipline;
 *    this file is the structure. It fails closed: an emptied module table, a member
 *    that stops exporting a declared constructor, or a base that is not extendable
 *    at runtime are all red, not silently green.
 *  - RLSE-05 (lexicons/engineering.md:696) — the original failure surfaced as an
 *    unrelated whole-file collection error, i.e. the silent-failure shape: the real
 *    defect (one bad `extends`) was invisible behind hundreds of "cannot collect"
 *    lines. Every module here is loaded through a *dynamic* import so a regression
 *    lands as a named, attributable test failure instead of a collection crash.
 *  - REF-01 (lexicons/engineering.md:320) — no boolean/`null` verdicts. Each probe
 *    reports the module and export it was checking, so the failure names its bearer.
 *
 * Deliberately NOT co-located with `httpModuleGraph.test.ts`: that file imports the
 * former cycle members statically at the top (its own, separate regression witness),
 * which means a reintroduced cycle kills it during collection. This file holds no
 * static import of any cycle member, so it can *observe* the failure and report which
 * entry order produced it.
 */
import { afterEach, describe, expect, it, vi } from 'vitest';

type Namespace = Record<string, unknown>;

interface CycleMember {
  /** Human-readable id used in every failure message. */
  readonly name: string;
  /** Dynamic loader — a literal specifier so Vite can resolve it statically. */
  readonly load: () => Promise<Namespace>;
  /**
   * Exports that must be real, extendable constructors after this module is
   * evaluated. A cross-module `extends` whose base is still in its TDZ produces
   * `undefined` here, which is exactly what the original defect looked like.
   */
  readonly constructors: readonly string[];
}

/** Class exports of the error vocabulary; `utils/http` republishes all of them. */
const BOUNDARY_CLASSES = [
  'BoundaryError',
  'HTTPError',
  'ResponseParseError',
  'AuthExpiredError',
  'AbortedRequestError',
  'RequestTimeoutError',
  'TransportError',
  'UnknownBoundaryError',
  'NonceRefreshFailedError',
  'NonceRefreshError',
] as const;

/**
 * The four former cycle members plus `utils/errorTaxonomy`, the leaf the shared
 * vocabulary was extracted into to cut the back-edge.
 *
 * ORDER OF THIS TABLE IS PART OF THE TEST. Each entry is used, in turn, as the
 * FIRST module evaluated in a fresh registry. Importing only in the order that
 * happens to work proves nothing — the original bug reproduced only when the graph
 * was entered from `api/config`.
 */
const CYCLE_MEMBERS: readonly CycleMember[] = [
  { name: 'utils/http', load: () => import('../http'), constructors: BOUNDARY_CLASSES },
  { name: 'utils/appError', load: () => import('../appError'), constructors: [] },
  { name: 'utils/logger', load: () => import('../logger'), constructors: [] },
  { name: 'api/config', load: () => import('../../api/config'), constructors: ['NonceRefreshFailedError'] },
  { name: 'utils/errorTaxonomy', load: () => import('../errorTaxonomy'), constructors: BOUNDARY_CLASSES },
];

/**
 * Fail-closed floor. If someone trims `CYCLE_MEMBERS` — or a rename silently drops
 * an entry — the suite must go red rather than quietly iterate over less.
 */
const REQUIRED_MEMBERS = [
  'utils/http',
  'utils/appError',
  'utils/logger',
  'api/config',
  'utils/errorTaxonomy',
] as const;

/**
 * A binding is only a usable base class if it is a function with a prototype AND
 * survives an actual `extends`. Checking `typeof x === 'function'` alone would pass
 * for an arrow function and would not reproduce the failing operation.
 */
const assertExtendableConstructor = (namespace: Namespace, exportName: string, where: string): void => {
  const value = namespace[exportName];
  expect(typeof value, `${where}: export "${exportName}" is ${String(value)}, not a constructor`).toBe(
    'function',
  );
  const ctor = value as new (...args: never[]) => object;
  expect(typeof ctor.prototype, `${where}: "${exportName}" has no prototype object`).toBe('object');
  expect(Object.getPrototypeOf(ctor), `${where}: "${exportName}" has a null prototype chain`).not.toBe(
    null,
  );
  expect(() => {
    class Probe extends ctor {}
    return Probe;
  }, `${where}: "${exportName}" is not extendable at runtime`).not.toThrow();
};

/**
 * Evaluate the whole graph with `entry` first, then assert every declared
 * constructor across every member is real. The assertions are global on purpose:
 * a bad `extends` anywhere in the graph is attributable to the entry order that
 * exposed it.
 */
const loadGraphEnteredFrom = async (entry: CycleMember): Promise<void> => {
  vi.resetModules();

  const loaded = new Map<string, Namespace>();
  loaded.set(entry.name, await entry.load());
  for (const member of CYCLE_MEMBERS) {
    if (!loaded.has(member.name)) {
      loaded.set(member.name, await member.load());
    }
  }

  let checked = 0;
  for (const member of CYCLE_MEMBERS) {
    const namespace = loaded.get(member.name);
    // Fail closed rather than assert-and-continue: a member the loader silently
    // skipped is a hole in the check, not a soft warning (RLSE-05).
    if (namespace === undefined) {
      throw new Error(`entering from ${entry.name}: ${member.name} produced no namespace`);
    }
    for (const exportName of member.constructors) {
      assertExtendableConstructor(namespace, exportName, `${member.name} (entry: ${entry.name})`);
      checked += 1;
    }
  }

  // Fail-closed: a table whose `constructors` were all emptied would otherwise
  // "pass" while asserting nothing at all.
  expect(checked, `entering from ${entry.name}: no constructor was actually checked`).toBeGreaterThan(0);
};

describe('error-taxonomy module load order [FEBT2-LA-NEW-01]', () => {
  afterEach(() => {
    vi.resetModules();
    delete window.AltContextAdmin;
  });

  it('covers every former cycle member [fail-closed table]', () => {
    const names = CYCLE_MEMBERS.map((member) => member.name);
    expect(new Set(names).size, 'CYCLE_MEMBERS contains duplicate entries').toBe(names.length);
    for (const required of REQUIRED_MEMBERS) {
      expect(names, `CYCLE_MEMBERS no longer covers ${required}`).toContain(required);
    }
    const declared = CYCLE_MEMBERS.reduce((total, member) => total + member.constructors.length, 0);
    expect(declared, 'no module declares a constructor to check').toBeGreaterThan(0);
  });

  it.each(CYCLE_MEMBERS.map((member) => [member.name, member] as const))(
    'entering the graph from %s first yields real constructors [FEBT2-LC-NEW-03]',
    async (_name, member) => {
      await loadGraphEnteredFrom(member);
    },
  );

  it('every entry order agrees on class identity [no duplicate evaluation]', async () => {
    vi.resetModules();
    const viaHttp = (await import('../http')) as Namespace;
    const viaTaxonomy = (await import('../errorTaxonomy')) as Namespace;
    for (const exportName of BOUNDARY_CLASSES) {
      expect(viaHttp[exportName], `utils/http republished a different "${exportName}"`).toBe(
        viaTaxonomy[exportName],
      );
    }
  });
});
