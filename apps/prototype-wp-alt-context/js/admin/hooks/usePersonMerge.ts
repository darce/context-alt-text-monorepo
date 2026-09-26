import { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { previewPersonMerge, commitPersonMerge, undoPersonMerge } from '../api/personMergeApi';
import { queryKeys } from '../api/queryKeys';

export const PERSON_MERGE_UNDO_TOKEN_TTL_MS = 24 * 60 * 60 * 1000;
const UNDO_TOKEN_STORAGE_PREFIX = 'acx:person-merge-undo:';

interface StoredUndoToken {
  token: string;
  expiresAt: number;
}

const undoTokenStorageKey = (scope: string): string => `${UNDO_TOKEN_STORAGE_PREFIX}${encodeURIComponent(scope)}`;

const browserStorage = (): Storage | null => {
  if (typeof window === 'undefined') return null;
  try {
    return window.localStorage;
  } catch {
    return null;
  }
};

export const readPersonMergeUndoToken = (scope: string, now = Date.now()): StoredUndoToken | null => {
  const storage = browserStorage();
  if (!storage) return null;
  const key = undoTokenStorageKey(scope);
  try {
    const raw = storage.getItem(key);
    if (raw === null) return null;
    const stored: unknown = JSON.parse(raw);
    if (
      typeof stored !== 'object' || stored === null ||
      !('token' in stored) || typeof stored.token !== 'string' || stored.token.length === 0 ||
      !('expiresAt' in stored) || typeof stored.expiresAt !== 'number' || !Number.isFinite(stored.expiresAt)
    ) {
      storage.removeItem(key);
      return null;
    }
    if (stored.expiresAt <= now) {
      storage.removeItem(key);
      return null;
    }
    return { token: stored.token, expiresAt: stored.expiresAt };
  } catch {
    return null;
  }
};

const persistPersonMergeUndoToken = (scope: string, token: string): StoredUndoToken | null => {
  const storage = browserStorage();
  const stored = { token, expiresAt: Date.now() + PERSON_MERGE_UNDO_TOKEN_TTL_MS };
  if (storage) {
    try {
      storage.setItem(undoTokenStorageKey(scope), JSON.stringify(stored));
    } catch {
      // The in-memory token still supports undo when browser storage is unavailable.
    }
  }
  return stored;
};

export const clearPersonMergeUndoToken = (scope: string): void => {
  const storage = browserStorage();
  if (!storage) return;
  try {
    storage.removeItem(undoTokenStorageKey(scope));
  } catch {
    // Keep the in-memory token usable if browser storage is unavailable.
  }
};

export const usePersonMerge = (undoTokenScope = 'default') => {
  const client = useQueryClient();
  const [storedUndoToken, setStoredUndoToken] = useState(() => readPersonMergeUndoToken(undoTokenScope));
  const invalidate = () => {
    void client.invalidateQueries({ queryKey: queryKeys.roster.all });
    void client.invalidateQueries({ queryKey: queryKeys.clusters.all });
    // IDCHIP-1-MUI-R-02: merge rebinds clusters to another person, so media
    // identity projections keyed off the old person must refetch too.
    void client.invalidateQueries({ queryKey: queryKeys.media.identities() });
  };
  const preview = useMutation({ mutationFn: previewPersonMerge });
  const commit = useMutation({ mutationFn: commitPersonMerge, onSuccess: (result) => {
    setStoredUndoToken(persistPersonMergeUndoToken(undoTokenScope, result.undo_token));
    invalidate();
  } });
  const undo = useMutation({
    mutationFn: undoPersonMerge,
    onSuccess: () => {
      clearPersonMergeUndoToken(undoTokenScope);
      invalidate();
    },
  });
  return {
    preview,
    commit,
    undo,
    undoToken: storedUndoToken?.token ?? null,
    undoExpiresAt: storedUndoToken?.expiresAt ?? null,
  };
};
