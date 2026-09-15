import { useRef, useState } from 'react';
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

export type DescribeMediaMutationInput =
  | number
  | ({
      mediaId: number;
    } & DescribeMediaWriteOptions);

export type DescribeWarmingState = {
  operationId: string | null;
  warmupEtaSeconds: number | null;
};

const mediaIdOf = (input: DescribeMediaMutationInput): number =>
  typeof input === 'number' ? input : input.mediaId;

const writeOptionsOf = (input: DescribeMediaMutationInput): DescribeMediaWriteOptions =>
  typeof input === 'number' ? {} : { writeAlt: input.writeAlt, force: input.force ?? false };

const isMismatchOrExpired = (code: string | null): boolean =>
  code === DESCRIBE_OPERATION_ERROR_CODE.MISMATCH || code === DESCRIBE_OPERATION_ERROR_CODE.EXPIRED;

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
 * and expired drop the id and retry once without it.
 */
export const useDescribeMedia = () => {
  const lastInputRef = useRef<DescribeMediaMutationInput | null>(null);
  const leaseOperationIdRef = useRef<string | null>(null);
  const mismatchRetriedRef = useRef(false);
  const [warming, setWarming] = useState<DescribeWarmingState | null>(null);
  const [timing, setTiming] = useState<DescribeOperationTiming | null>(null);

  const clearLease = (): void => {
    leaseOperationIdRef.current = null;
    mismatchRetriedRef.current = false;
    setWarming(null);
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
        setWarming({ operationId, warmupEtaSeconds });
        setTiming(null);
        return;
      }
      clearLease();
      setTiming(null);
    },
  });

  const retry = (
    options?: MutateOptions<VisualFactsResponse, Error, DescribeMediaMutationInput>,
  ): void => {
    const lastInput = lastInputRef.current;
    if (lastInput === null) {
      return;
    }
    mutation.mutate(lastInput, options);
  };

  const reset = (): void => {
    lastInputRef.current = null;
    clearLease();
    setTiming(null);
    mutation.reset();
  };

  return { ...mutation, reset, retry, warming, timing };
};
