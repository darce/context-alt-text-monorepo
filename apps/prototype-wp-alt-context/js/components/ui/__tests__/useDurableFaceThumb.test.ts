import { act, renderHook } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import type { BoundingBox } from '../../../admin/api/recognition/types/identity';
import { AVATAR_STATE, FACE_THUMB_MODE, type FaceThumbDisplay } from '../faceThumbDisplay';
import { cropKeyFor, useDurableFaceThumb, type UseDurableFaceThumbResult } from '../useDurableFaceThumb';

const BBOX: BoundingBox = { x: 10, y: 20, width: 40, height: 50 };
const BLOB_A = 'https://example.test/wp-json/acx/v1/recognition/face-thumbs/job-1/a';
const BLOB_B = 'https://example.test/wp-json/acx/v1/recognition/face-thumbs/job-1/b';
const ATTACH_A = 'https://example.test/uploads/a.jpg';
const ATTACH_B = 'https://example.test/uploads/b.jpg';

const hookWithPaintLog = (paints: FaceThumbDisplay[]) => {
  return (source: Parameters<typeof useDurableFaceThumb>[0]): UseDurableFaceThumbResult => {
    const hooked = useDurableFaceThumb(source);
    paints.push(hooked.display);
    return hooked;
  };
};

describe('useDurableFaceThumb [TEST-15] [REV1-05]', () => {
  it('reads a stale-key status as loading so a swap cannot inherit fallbackCrop or real [REV2-01]', () => {
    const paints: FaceThumbDisplay[] = [];
    const { result, rerender } = renderHook(hookWithPaintLog(paints), {
      initialProps: { thumbUrl: BLOB_A, attachmentUrl: ATTACH_A, bbox: BBOX },
    });

    act(() => {
      result.current.onBlobError();
    });
    expect(result.current.display.state).toBe(AVATAR_STATE.fallbackCrop);

    const beforeSwap = paints.length;
    rerender({ thumbUrl: BLOB_B, attachmentUrl: ATTACH_B, bbox: BBOX });
    const firstAfterSwap = paints[beforeSwap];

    expect(firstAfterSwap?.state).toBe(AVATAR_STATE.loading);
    expect(firstAfterSwap?.state).not.toBe(AVATAR_STATE.fallbackCrop);
    expect(firstAfterSwap?.state).not.toBe(AVATAR_STATE.real);
    expect(firstAfterSwap?.src).toBe(BLOB_B);
  });

  it('resets a prior blob error during render so the new dedicated url is not skipped', () => {
    const paints: FaceThumbDisplay[] = [];
    const { result, rerender } = renderHook(hookWithPaintLog(paints), {
      initialProps: { thumbUrl: BLOB_A, attachmentUrl: ATTACH_A, bbox: BBOX },
    });

    act(() => {
      result.current.onBlobError();
    });
    expect(result.current.display.mode).toBe(FACE_THUMB_MODE.crop);
    expect(result.current.display.state).toBe(AVATAR_STATE.fallbackCrop);

    const beforeSwap = paints.length;
    rerender({ thumbUrl: BLOB_B, attachmentUrl: ATTACH_A, bbox: BBOX });
    const firstAfterSwap = paints[beforeSwap];

    expect(firstAfterSwap?.mode).toBe(FACE_THUMB_MODE.avatar);
    expect(firstAfterSwap?.src).toBe(BLOB_B);
    expect(firstAfterSwap?.state).toBe(AVATAR_STATE.loading);
    expect(firstAfterSwap?.state).not.toBe(AVATAR_STATE.fallbackCrop);
  });

  it('resets a prior blob loaded bit during render so the new url is not claimed real', () => {
    const paints: FaceThumbDisplay[] = [];
    const { result, rerender } = renderHook(hookWithPaintLog(paints), {
      initialProps: { thumbUrl: BLOB_A, attachmentUrl: ATTACH_A, bbox: BBOX },
    });

    act(() => {
      result.current.onBlobLoad();
    });
    expect(result.current.display.state).toBe(AVATAR_STATE.real);
    expect(result.current.display.src).toBe(BLOB_A);

    const beforeSwap = paints.length;
    rerender({ thumbUrl: BLOB_B, attachmentUrl: ATTACH_A, bbox: BBOX });
    const firstAfterSwap = paints[beforeSwap];

    expect(firstAfterSwap?.src).toBe(BLOB_B);
    expect(firstAfterSwap?.state).toBe(AVATAR_STATE.loading);
    expect(firstAfterSwap?.state).not.toBe(AVATAR_STATE.real);
  });

  it('ignores a stale blob-error from the previous dedicated key', () => {
    const { result, rerender } = renderHook((source) => useDurableFaceThumb(source), {
      initialProps: { thumbUrl: BLOB_A, attachmentUrl: ATTACH_A, bbox: BBOX },
    });

    const staleError = result.current.onBlobError;
    rerender({ thumbUrl: BLOB_B, attachmentUrl: ATTACH_A, bbox: BBOX });

    act(() => {
      staleError();
    });

    expect(result.current.display.mode).toBe(FACE_THUMB_MODE.avatar);
    expect(result.current.display.src).toBe(BLOB_B);
    expect(result.current.display.isLoudError).toBe(false);
    expect(result.current.display.state).not.toBe(AVATAR_STATE.fallbackCrop);
  });

  it('ignores a stale crop-error after the crop source changes', () => {
    const { result, rerender } = renderHook((source) => useDurableFaceThumb(source), {
      initialProps: { attachmentUrl: ATTACH_A, bbox: BBOX },
    });

    const staleCropError = result.current.onCropError;
    rerender({ attachmentUrl: ATTACH_B, bbox: BBOX });

    act(() => {
      staleCropError();
    });

    expect(result.current.display.mode).toBe(FACE_THUMB_MODE.crop);
    expect(result.current.display.isLoudError).toBe(false);
    expect(result.current.display.crop?.mediaUrl).toBe(ATTACH_B);
  });

  it('folds the normalized bbox into cropKey [REV1-06]', () => {
    expect(cropKeyFor({ attachmentUrl: ATTACH_A, mediaUrl: ATTACH_B, bbox: BBOX })).toBe(
      `${ATTACH_A}|${ATTACH_B}|10,20,40,50`,
    );
    expect(cropKeyFor({ attachmentUrl: ATTACH_A, mediaUrl: ATTACH_B, bbox: { x: 1, y: 2, width: 3, height: 4 } })).toBe(
      `${ATTACH_A}|${ATTACH_B}|1,2,3,4`,
    );
    expect(cropKeyFor({ attachmentUrl: ATTACH_A })).toBe(`${ATTACH_A}||`);
  });

  it('resets crop error when only the bbox changes on the same attachment [REV1-06]', () => {
    const paints: FaceThumbDisplay[] = [];
    const { result, rerender } = renderHook(hookWithPaintLog(paints), {
      initialProps: { attachmentUrl: ATTACH_A, bbox: BBOX },
    });

    act(() => {
      result.current.onCropError();
    });
    expect(result.current.display.isLoudError).toBe(true);

    const nextBbox: BoundingBox = { x: 1, y: 2, width: 3, height: 4 };
    const beforeSwap = paints.length;
    rerender({ attachmentUrl: ATTACH_A, bbox: nextBbox });
    const firstAfterSwap = paints[beforeSwap];

    expect(firstAfterSwap?.isLoudError).toBe(false);
    expect(firstAfterSwap?.mode).toBe(FACE_THUMB_MODE.crop);
    expect(firstAfterSwap?.crop?.bbox).toEqual(nextBbox);
    expect(firstAfterSwap?.state).not.toBe(AVATAR_STATE.error);
  });
});
