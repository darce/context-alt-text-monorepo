import { useEffect, useRef, useState } from 'react';
import { useMutation, type MutateOptions } from '@tanstack/react-query';

import {
  describeMedia,
  DESCRIBE_OPERATION_ERROR_CODE,
  resolveDescribeErrorCode,
  resolveDescribeErrorDataField,
  resolveDescribeErrorDetailNumberField,
  type DescribeMediaWriteOptions,
  type DescribeOperationTiming,
  type VisualFactsResponse,
} from '../api/describeApi';
import { clampRetryAfterMs } from '../utils/retryAfter';

export type DescribeMediaMutationInput =
  | number
  | ({
      mediaId: number;
    } & DescribeMediaWriteOptions);

export type DescribeWarmingState = {
  operationId: string | null;
  warmupEtaSeconds: number | null;
};

/** Wait when a starting 503 has no warmup_eta_seconds and no parsed Retry-After. */
const SUGGEST_WARMING_FALLBACK_MS = 5_000;

/**
 * Hard Suggest warming retry ceiling so a bad payload cannot wait forever.
 * The per-attempt window is startup_budget_seconds plus one retry gap,
 * never above this bound.
 */
export const SUGGEST_WARMING_HARD_CEILING_MS = 900_000;

/**
 * Total Suggest warming wait: the server's startup budget plus one retry gap,
 * clamped to SUGGEST_WARMING_HARD_CEILING_MS. Absent or invalid budget waits
 * only the retry gap (do not invent a client constant).
 */
export const suggestWarmingCeilingMs = (startupBudgetSeconds: number | null, retryGapMs: number): number => {
  const boundedRetryGapMs =
    Number.isFinite(retryGapMs) && retryGapMs > 0
      ? Math.min(retryGapMs, SUGGEST_WARMING_HARD_CEILING_MS)
      : SUGGEST_WARMING_FALLBACK_MS;
  if (startupBudgetSeconds === null || !Number.isFinite(startupBudgetSeconds) || !(startupBudgetSeconds > 0)) {
    return boundedRetryGapMs;
  }
  const budgetMs = startupBudgetSeconds * 1000;
  if (!Number.isFinite(budgetMs)) {
    return boundedRetryGapMs;
  }
  const ceilingMs = budgetMs + boundedRetryGapMs;
  if (!Number.isFinite(ceilingMs)) {
    return SUGGEST_WARMING_HARD_CEILING_MS;
  }
  return Math.min(ceilingMs, SUGGEST_WARMING_HARD_CEILING_MS);
};

type DescribeMutateOptions = MutateOptions<VisualFactsResponse, Error, DescribeMediaMutationInput>;

const mediaIdOf = (input: DescribeMediaMutationInput): number => (typeof input === 'number' ? input : input.mediaId);

const writeOptionsOf = (input: DescribeMediaMutationInput): DescribeMediaWriteOptions =>
  typeof input === 'number' ? {} : { writeAlt: input.writeAlt, force: input.force ?? false };

const isMismatchOrExpired = (code: string | null): boolean =>
  code === DESCRIBE_OPERATION_ERROR_CODE.MISMATCH || code === DESCRIBE_OPERATION_ERROR_CODE.EXPIRED;

const startupBudgetSecondsFromError = (error: unknown): number | null => {
  const value = resolveDescribeErrorDetailNumberField(error, 'startup_budget_seconds');
  if (value === null || !(value > 0)) {
    return null;
  }
  return value;
};

const retryAfterSecondsFromError = (error: unknown): number | undefined => {
  if (typeof error !== 'object' || error === null || !('retryAfterSeconds' in error)) {
    return undefined;
  }
  const value = error.retryAfterSeconds;
  if (typeof value !== 'number' || !Number.isFinite(value) || value < 0) {
    return undefined;
  }
  return value;
};

const warmingRetryDelayMs = (error: unknown, warmupEtaSeconds: number | null): number => {
  const waitSeconds = warmupEtaSeconds ?? retryAfterSecondsFromError(error);
  return clampRetryAfterMs(waitSeconds ?? undefined, SUGGEST_WARMING_FALLBACK_MS);
};

const describeWithLease = (
  input: DescribeMediaMutationInput,
  operationId: string | null,
): Promise<VisualFactsResponse> => {
  const mediaId = mediaIdOf(input);
  if (typeof input === 'number' && operationId === null) {
    return describeMedia(mediaId);
  }
  return describeMedia(mediaId, {
    ...writeOptionsOf(input),
    ...(operationId !== null ? { operationId } : {}),
  });
};

/**
 * Describe a single attachment through the WP proxy (E19-1 S12). One-shot
 * mutation: callers `mutate(mediaId)` or `mutate({ mediaId, writeAlt })`.
 * GPUFLOW-1 lease: starting errors store operation_id for retry(); mismatch
 * and expired drop the id and retry once without it. Auto-retry honours the
 * warmup ETA (else Retry-After, else 5 s) until the server startup budget
 * plus one retry gap, hard-capped at 900 s.
 */
export const useDescribeMedia = () => {
  const lastInputRef = useRef<DescribeMediaMutationInput | null>(null);
  const lastMutateOptionsRef = useRef<DescribeMutateOptions | undefined>(undefined);
  const leaseOperationIdRef = useRef<string | null>(null);
  const mismatchRetriedRef = useRef(false);
  const warmingStartedAtRef = useRef<number | null>(null);
  const warmingCeilingMsRef = useRef(SUGGEST_WARMING_HARD_CEILING_MS);
  const warmingRetryDelayMsRef = useRef(SUGGEST_WARMING_FALLBACK_MS);
  const mutateForRetryRef = useRef<() => void>(() => undefined);
  const enterWarmingTimeoutRef = useRef<() => void>(() => undefined);
  const [warming, setWarming] = useState<DescribeWarmingState | null>(null);
  const [warmingTimedOut, setWarmingTimedOut] = useState(false);
  const [timing, setTiming] = useState<DescribeOperationTiming | null>(null);

  const clearLease = (): void => {
    leaseOperationIdRef.current = null;
    mismatchRetriedRef.current = false;
    warmingStartedAtRef.current = null;
    warmingCeilingMsRef.current = SUGGEST_WARMING_HARD_CEILING_MS;
    setWarming(null);
    setWarmingTimedOut(false);
  };

  const mutation = useMutation<VisualFactsResponse, Error, DescribeMediaMutationInput>({
    mutationFn: async (input: DescribeMediaMutationInput) => {
      lastInputRef.current = input;
      try {
        return await describeWithLease(input, leaseOperationIdRef.current);
      } catch (error) {
        const code = resolveDescribeErrorCode(error);
        if (isMismatchOrExpired(code) && !mismatchRetriedRef.current) {
          leaseOperationIdRef.current = null;
          mismatchRetriedRef.current = true;
          return await describeWithLease(input, null);
        }
        throw error;
      }
    },
    onSuccess: (response) => {
      clearLease();
      setTiming(response.timing ?? null);
    },
    onError: (error) => {
      const code = resolveDescribeErrorCode(error);
      if (code === DESCRIBE_OPERATION_ERROR_CODE.STARTING) {
        const operationId = resolveDescribeErrorDataField(error, 'operation_id');
        const warmupEtaSeconds = resolveDescribeErrorDetailNumberField(error, 'warmup_eta_seconds');
        leaseOperationIdRef.current = operationId;
        mismatchRetriedRef.current = false;
        warmingRetryDelayMsRef.current = warmingRetryDelayMs(error, warmupEtaSeconds);
        if (warmingStartedAtRef.current === null) {
          warmingStartedAtRef.current = Date.now();
          warmingCeilingMsRef.current = suggestWarmingCeilingMs(
            startupBudgetSecondsFromError(error),
            warmingRetryDelayMsRef.current,
          );
        }
        if (Date.now() - warmingStartedAtRef.current >= warmingCeilingMsRef.current) {
          leaseOperationIdRef.current = null;
          mismatchRetriedRef.current = false;
          warmingStartedAtRef.current = null;
          warmingCeilingMsRef.current = SUGGEST_WARMING_HARD_CEILING_MS;
          setWarming(null);
          setWarmingTimedOut(true);
          setTiming(null);
          return;
        }
        setWarmingTimedOut(false);
        setWarming({ operationId, warmupEtaSeconds });
        setTiming(null);
        return;
      }
      clearLease();
      setTiming(null);
    },
  });

  mutateForRetryRef.current = (): void => {
    const lastInput = lastInputRef.current;
    if (lastInput === null) {
      return;
    }
    mutation.mutate(lastInput, lastMutateOptionsRef.current);
  };

  enterWarmingTimeoutRef.current = (): void => {
    leaseOperationIdRef.current = null;
    mismatchRetriedRef.current = false;
    warmingStartedAtRef.current = null;
    warmingCeilingMsRef.current = SUGGEST_WARMING_HARD_CEILING_MS;
    setWarming(null);
    setWarmingTimedOut(true);
  };

  useEffect(() => {
    if (warming === null || mutation.isPending) {
      return undefined;
    }
    const startedAt = warmingStartedAtRef.current;
    if (startedAt === null) {
      return undefined;
    }
    const remaining = warmingCeilingMsRef.current - (Date.now() - startedAt);
    if (remaining <= 0) {
      enterWarmingTimeoutRef.current();
      return undefined;
    }
    const waitMs = Math.min(warmingRetryDelayMsRef.current, remaining);
    const timer = setTimeout(() => {
      if (Date.now() - startedAt >= warmingCeilingMsRef.current) {
        enterWarmingTimeoutRef.current();
        return;
      }
      mutateForRetryRef.current();
    }, waitMs);
    return () => {
      clearTimeout(timer);
    };
  }, [warming, mutation.isPending]);

  const mutate = (input: DescribeMediaMutationInput, options?: DescribeMutateOptions): void => {
    leaseOperationIdRef.current = null;
    warmingStartedAtRef.current = null;
    lastMutateOptionsRef.current = options;
    mutation.mutate(input, options);
  };

  const retry = (options?: DescribeMutateOptions): void => {
    const lastInput = lastInputRef.current;
    if (lastInput === null) {
      return;
    }
    if (options !== undefined) {
      lastMutateOptionsRef.current = options;
    }
    mutation.mutate(lastInput, options ?? lastMutateOptionsRef.current);
  };

  const reset = (): void => {
    lastInputRef.current = null;
    lastMutateOptionsRef.current = undefined;
    clearLease();
    setTiming(null);
    mutation.reset();
  };

  return { ...mutation, mutate, reset, retry, warming, warmingTimedOut, timing };
};
