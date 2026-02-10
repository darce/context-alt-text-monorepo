import { useCallback, useMemo, useState } from 'react';

import type { WorkbenchMediaItem } from './useWorkbenchMedia';

export const useMediaSelectionState = () => {
  const [selection, setSelection] = useState<Record<string, boolean>>({});
  const [selectedDetails, setSelectedDetails] = useState<Record<string, WorkbenchMediaItem>>({});

  const selectedMedia = useMemo(
    () =>
      Object.entries(selection)
        .filter(([, isChecked]) => isChecked)
        .map(([key]) => selectedDetails[key])
        .filter((item): item is WorkbenchMediaItem => Boolean(item)),
    [selection, selectedDetails],
  );

  const toggleRow = useCallback((item: WorkbenchMediaItem, checked: boolean) => {
    const key = item.id.toString();
    setSelection((prev) => {
      const next = { ...prev };
      if (checked) {
        next[key] = true;
      } else {
        delete next[key];
      }
      return next;
    });

    setSelectedDetails((prev) => {
      const next = { ...prev };
      if (checked) {
        next[key] = item;
      } else {
        delete next[key];
      }
      return next;
    });
  }, []);

  const toggleAll = useCallback((items: WorkbenchMediaItem[], checked: boolean) => {
    setSelection((prev) => {
      const next = { ...prev };
      items.forEach((item) => {
        const key = item.id.toString();
        if (checked) {
          next[key] = true;
        } else {
          delete next[key];
        }
      });
      return next;
    });

    setSelectedDetails((prev) => {
      const next = { ...prev };
      items.forEach((item) => {
        const key = item.id.toString();
        if (checked) {
          next[key] = item;
        } else {
          delete next[key];
        }
      });
      return next;
    });
  }, []);

  const isPageFullySelected = useCallback(
    (items: WorkbenchMediaItem[]) => items.length > 0 && items.every((item) => selection[item.id.toString()] === true),
    [selection],
  );

  return {
    selection,
    selectedMedia,
    toggleRow,
    toggleAll,
    isPageFullySelected,
  } as const;
};
