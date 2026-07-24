/**
 * Bounded, TTL'd retired→survivor map for open-target rebind (E21-5 §11 / PR-34).
 *
 * Context DI (no module singleton) so tests can wrap a fresh provider.
 * Cap ~50 entries, TTL ~60s, evict oldest on overflow or expiry.
 */

import React, { createContext, useCallback, useContext, useMemo, useRef, useState } from 'react';

const DEFAULT_CAP = 50;
const DEFAULT_TTL_MS = 60_000;

export interface MergeSurvivorEntry {
  survivorId: string;
  at: number;
}

export interface MergeSurvivorApi {
  recordMergeSurvivor: (retiredId: string, survivorId: string) => void;
  resolveSurvivor: (retiredId: string) => string | null;
}

const MergeSurvivorContext = createContext<MergeSurvivorApi | null>(null);

export interface MergeSurvivorProviderProps {
  children: React.ReactNode;
  /** Max map entries (default 50). */
  cap?: number;
  /** Entry TTL in ms (default 60_000). */
  ttlMs?: number;
  /** Injectable clock for tests. */
  now?: () => number;
}

export const MergeSurvivorProvider: React.FC<MergeSurvivorProviderProps> = ({
  children,
  cap = DEFAULT_CAP,
  ttlMs = DEFAULT_TTL_MS,
  now = () => Date.now(),
}) => {
  // Insertion-ordered Map: oldest at iteration start; re-set moves to end.
  const mapRef = useRef<Map<string, MergeSurvivorEntry>>(new Map());
  // E215-BR-01: bump on record so lifecycle consumers re-render and re-check
  // resolveSurvivor after a late record-after-404 (map alone is ref-backed).
  const [revision, setRevision] = useState(0);

  const pruneExpired = useCallback(() => {
    const t = now();
    for (const [id, entry] of mapRef.current) {
      if (t - entry.at > ttlMs) {
        mapRef.current.delete(id);
      } else {
        // Map is insertion-ordered and we only append at the end — once we
        // hit a non-expired entry, later ones are newer.
        break;
      }
    }
  }, [now, ttlMs]);

  const recordMergeSurvivor = useCallback(
    (retiredId: string, survivorId: string) => {
      if (!retiredId || !survivorId || retiredId === survivorId) {
        return;
      }
      pruneExpired();
      // Re-set so this entry is newest (Map preserves insertion order).
      mapRef.current.delete(retiredId);
      mapRef.current.set(retiredId, { survivorId, at: now() });
      while (mapRef.current.size > cap) {
        const oldest = mapRef.current.keys().next().value;
        if (oldest === undefined) {
          break;
        }
        mapRef.current.delete(oldest);
      }
      setRevision((n) => n + 1);
    },
    [cap, now, pruneExpired],
  );

  const resolveSurvivor = useCallback(
    (retiredId: string): string | null => {
      if (!retiredId) {
        return null;
      }
      pruneExpired();
      const entry = mapRef.current.get(retiredId);
      if (!entry) {
        return null;
      }
      if (now() - entry.at > ttlMs) {
        mapRef.current.delete(retiredId);
        return null;
      }
      return entry.survivorId;
    },
    [now, pruneExpired, ttlMs],
  );

  const value = useMemo<MergeSurvivorApi>(
    () => ({ recordMergeSurvivor, resolveSurvivor }),
    // revision forces a new context value so consumers re-render after record.
    // eslint-disable-next-line react-hooks/exhaustive-deps -- revision is the notify signal
    [recordMergeSurvivor, resolveSurvivor, revision],
  );

  return <MergeSurvivorContext.Provider value={value}>{children}</MergeSurvivorContext.Provider>;
};

export const useMergeSurvivors = (): MergeSurvivorApi => {
  const ctx = useContext(MergeSurvivorContext);
  if (!ctx) {
    throw new Error('useMergeSurvivors must be used within a MergeSurvivorProvider');
  }
  return ctx;
};

/** Mutations that may run outside the workbench tree — no-op when unmounted. */
export const useOptionalMergeSurvivors = (): MergeSurvivorApi | null => useContext(MergeSurvivorContext);
