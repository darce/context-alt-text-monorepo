import React from 'react';

interface ReviewPhotoFilter {
  minimumPhotos: number | undefined;
  offset: number;
  setMinimumPhotos: (minimum: number | undefined) => void;
  setOffset: (offset: number) => void;
  drafts?: ReadonlyMap<string, string>;
  setDraft?: (key: string, value: string) => void;
}

const Context = React.createContext<ReviewPhotoFilter>({
  minimumPhotos: undefined,
  offset: 0,
  setMinimumPhotos: () => undefined,
  setOffset: () => undefined,
});

/** Session-owned view state. Does not clear selections, naming drafts or policy. */
export const ReviewPhotoFilterProvider = ({ children }: React.PropsWithChildren): React.JSX.Element => {
  const [scope, setScope] = React.useState<{ minimumPhotos: number | undefined; offset: number }>({
    minimumPhotos: undefined,
    offset: 0,
  });
  const [drafts, setDrafts] = React.useState<ReadonlyMap<string, string>>(() => new Map());
  const value = React.useMemo(
    () => ({
      ...scope,
      drafts,
      setDraft: (key: string, value: string) => setDrafts((previous) => new Map(previous).set(key, value)),
      setMinimumPhotos: (minimumPhotos: number | undefined) => setScope({ minimumPhotos, offset: 0 }),
      setOffset: (offset: number) => setScope((previous) => ({ ...previous, offset })),
    }),
    [scope, drafts],
  );
  return <Context.Provider value={value}>{children}</Context.Provider>;
};

export const useReviewPhotoFilter = (): ReviewPhotoFilter => React.useContext(Context);

/** Keep the existing global findings summary independent of this view filter. */
export const UnfilteredReviewSummary = ({ children }: React.PropsWithChildren): React.JSX.Element => (
  <Context.Provider
    value={{ minimumPhotos: undefined, offset: 0, setMinimumPhotos: () => undefined, setOffset: () => undefined }}
  >
    {children}
  </Context.Provider>
);

/** Human drafts survive filtered/page removal; isolated consumers keep local state. */
export const useReviewNameDraft = (key: string, initialValue = ''): [string, (value: string) => void] => {
  const context = React.useContext(Context);
  const [local, setLocal] = React.useState<ReadonlyMap<string, string>>(() => new Map());
  if (context.drafts && context.setDraft) {
    return [context.drafts.get(key) ?? initialValue, (value) => context.setDraft?.(key, value)];
  }
  return [local.get(key) ?? initialValue, (value) => setLocal((previous) => new Map(previous).set(key, value))];
};
