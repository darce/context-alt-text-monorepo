import type { UseMutationResult, UseQueryResult } from '@tanstack/react-query';
import { vi } from 'vitest';

type QueryOverrides<TData, TError> = Partial<UseQueryResult<TData, TError>>;
type MutationOverrides<TData, TError, TVariables, TContext> = Partial<
  UseMutationResult<TData, TError, TVariables, TContext>
>;

type QueryStatus = 'pending' | 'error' | 'success';
type MutationStatus = 'idle' | 'pending' | 'error' | 'success';

const resolveQueryStatus = <TData, TError>(overrides: QueryOverrides<TData, TError>): QueryStatus => {
  if (overrides.status) {
    return overrides.status;
  }
  if (overrides.isError) {
    return 'error';
  }
  if (overrides.isSuccess || overrides.data !== undefined) {
    return 'success';
  }
  return 'pending';
};

const resolveMutationStatus = <TData, TError, TVariables, TContext>(
  overrides: MutationOverrides<TData, TError, TVariables, TContext>,
): MutationStatus => {
  if (overrides.status) {
    return overrides.status;
  }
  if (overrides.isError) {
    return 'error';
  }
  if (overrides.isSuccess) {
    return 'success';
  }
  if (overrides.isPending) {
    return 'pending';
  }
  return 'idle';
};

export const createMockQuery = <TData, TError = Error>(
  overrides: QueryOverrides<TData, TError> = {},
): UseQueryResult<TData, TError> => {
  const status = resolveQueryStatus(overrides);

  const base = {
    data: overrides.data,
    dataUpdatedAt: 0,
    error: overrides.error ?? null,
    errorUpdatedAt: 0,
    failureCount: 0,
    failureReason: null,
    errorUpdateCount: 0,
    isError: status === 'error',
    isFetched: status !== 'pending',
    isFetchedAfterMount: status !== 'pending',
    isFetching: false,
    isLoading: status === 'pending',
    isPending: status === 'pending',
    isLoadingError: status === 'error' && overrides.data === undefined,
    isInitialLoading: status === 'pending',
    isPaused: false,
    isPlaceholderData: false,
    isRefetchError: status === 'error' && overrides.data !== undefined,
    isRefetching: false,
    isStale: true,
    isSuccess: status === 'success',
    isEnabled: true,
    refetch: vi.fn(),
    status,
    fetchStatus: 'idle',
    promise: Promise.resolve(overrides.data as TData),
  } as UseQueryResult<TData, TError>;

  return { ...base, ...overrides } as UseQueryResult<TData, TError>;
};

export const createMockMutation = <TData, TError = Error, TVariables = void, TContext = unknown>(
  overrides: MutationOverrides<TData, TError, TVariables, TContext> = {},
): UseMutationResult<TData, TError, TVariables, TContext> => {
  const status = resolveMutationStatus(overrides);

  const base = {
    data: overrides.data,
    error: overrides.error ?? null,
    failureCount: 0,
    failureReason: null,
    isPaused: false,
    status,
    variables: overrides.variables,
    submittedAt: 0,
    context: overrides.context,
    isError: status === 'error',
    isIdle: status === 'idle',
    isPending: status === 'pending',
    isSuccess: status === 'success',
    mutate: vi.fn(),
    mutateAsync: vi.fn(() => Promise.resolve(overrides.data as TData)),
    reset: vi.fn(),
  } as UseMutationResult<TData, TError, TVariables, TContext>;

  return { ...base, ...overrides } as UseMutationResult<TData, TError, TVariables, TContext>;
};
