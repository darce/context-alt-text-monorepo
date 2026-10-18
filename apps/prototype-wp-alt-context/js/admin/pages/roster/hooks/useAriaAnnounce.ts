import { useCallback, useState } from 'react';

interface AriaAnnounceState {
  message: string | null;
  seq: number;
}

export interface UseAriaAnnounceResult extends AriaAnnounceState {
  announce: (message: string) => void;
}

export const useAriaAnnounce = (): UseAriaAnnounceResult => {
  const [state, setState] = useState<AriaAnnounceState>({ message: null, seq: 0 });
  const announce = useCallback((message: string) => {
    setState((prev) => ({ message, seq: prev.seq + 1 }));
  }, []);
  return { message: state.message, seq: state.seq, announce };
};
