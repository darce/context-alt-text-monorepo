import { useCallback, useEffect, useState } from 'react';

import { resolveVisibleFaceId } from '../personFaces';

export const useRosterFaceCursor = (
  visibleIds: readonly string[],
  requestedId: string | null,
): {
  selectedId: string | null;
  select: (faceId: string) => void;
  retainVisible: (nextVisibleIds: readonly string[]) => void;
} => {
  const [selectedId, setSelectedId] = useState<string | null>(() =>
    resolveVisibleFaceId(visibleIds, requestedId, null),
  );

  const retainVisible = useCallback(
    (nextVisibleIds: readonly string[]) => {
      setSelectedId((prev) => {
        const next = resolveVisibleFaceId(nextVisibleIds, requestedId, prev);
        return next === prev ? prev : next;
      });
    },
    [requestedId],
  );

  const select = useCallback((faceId: string) => {
    setSelectedId(faceId);
  }, []);

  useEffect(() => {
    retainVisible(visibleIds);
  }, [retainVisible, visibleIds]);

  return {
    selectedId: resolveVisibleFaceId(visibleIds, requestedId, selectedId),
    select,
    retainVisible,
  };
};
