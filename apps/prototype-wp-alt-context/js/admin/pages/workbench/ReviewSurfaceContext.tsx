import React, { createContext, useContext, useMemo, useState } from 'react';

/**
 * Review-surface accent signal (§7/BR-83). Kept OUT of WorkbenchMediaContext on
 * purpose — it is not media data, and folding it in would break that context's
 * group-cohesion memos (sr-008).
 */
export interface ReviewSurfaceContextValue {
  cardPrimaryPresent: boolean;
  setCardPrimaryPresent: (present: boolean) => void;
}

const ReviewSurfaceContext = createContext<ReviewSurfaceContextValue | null>(null);

export const ReviewSurfaceProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [cardPrimaryPresent, setCardPrimaryPresent] = useState(false);

  const value = useMemo<ReviewSurfaceContextValue>(
    () => ({ cardPrimaryPresent, setCardPrimaryPresent }),
    [cardPrimaryPresent],
  );

  return <ReviewSurfaceContext.Provider value={value}>{children}</ReviewSurfaceContext.Provider>;
};

export const useReviewSurface = (): ReviewSurfaceContextValue => {
  const context = useContext(ReviewSurfaceContext);
  if (!context) {
    throw new Error('useReviewSurface must be used within a ReviewSurfaceProvider');
  }
  return context;
};
