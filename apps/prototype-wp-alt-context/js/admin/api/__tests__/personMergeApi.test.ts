import { describe, expect, it, vi, beforeEach } from 'vitest';
import { fetchRequiredApi } from '../../utils/http';
import {
  MalformedPersonMergeResponseError,
  previewPersonMerge,
  commitPersonMerge,
  undoPersonMerge,
} from '../personMergeApi';

vi.mock('../../utils/http', async importOriginal => ({
  ...await importOriginal<typeof import('../../utils/http')>(),
  fetchRequiredApi: vi.fn(),
}));
vi.mock('../config', () => ({
  getConfig: () => ({ nonce: 'nonce' }),
  getEndpoint: () => '/wp-json/acx/v1/roster/persons',
}));

const preview = { survivor: { id: 1, name: 'Alice', cluster_count: 3 }, loser: { id: 2, name: 'Ally', cluster_count: 2 }, tags: ['friend'], conflicts: [] };
const mergeResult = { survivor_id: 1, merged_cluster_ids: ['c'], undo_token: 'token' };
const undoResult = { restored_person_id: 2, restored_cluster_ids: ['c'] };

beforeEach(() => {
  vi.clearAllMocks();
});

describe('personMergeApi boundary validation (IDCHIP-1-MUI-R-03)', () => {
  it('returns a well-formed preview response unchanged', async () => {
    vi.mocked(fetchRequiredApi).mockResolvedValue(preview);
    await expect(previewPersonMerge({ survivor_id: 1, loser_id: 2 })).resolves.toEqual(preview);
  });

  it('rejects a preview response with a missing person field', async () => {
    vi.mocked(fetchRequiredApi).mockResolvedValue({ ...preview, survivor: { id: 1, name: 'Alice' } });
    await expect(previewPersonMerge({ survivor_id: 1, loser_id: 2 })).rejects.toThrow(MalformedPersonMergeResponseError);
  });

  it('rejects a preview response where conflicts is not an array', async () => {
    vi.mocked(fetchRequiredApi).mockResolvedValue({ ...preview, conflicts: 'none' });
    await expect(previewPersonMerge({ survivor_id: 1, loser_id: 2 })).rejects.toThrow(MalformedPersonMergeResponseError);
  });

  it('rejects a preview response where tags contains a non-string', async () => {
    vi.mocked(fetchRequiredApi).mockResolvedValue({ ...preview, tags: ['ok', 5] });
    await expect(previewPersonMerge({ survivor_id: 1, loser_id: 2 })).rejects.toThrow(MalformedPersonMergeResponseError);
  });

  it('returns a well-formed merge response unchanged', async () => {
    vi.mocked(fetchRequiredApi).mockResolvedValue(mergeResult);
    await expect(commitPersonMerge({ survivor_id: 1, loser_id: 2 })).resolves.toEqual(mergeResult);
  });

  it('rejects a merge response with an empty undo_token', async () => {
    vi.mocked(fetchRequiredApi).mockResolvedValue({ ...mergeResult, undo_token: '' });
    await expect(commitPersonMerge({ survivor_id: 1, loser_id: 2 })).rejects.toThrow(MalformedPersonMergeResponseError);
  });

  it('rejects a merge response with a non-string undo_token', async () => {
    vi.mocked(fetchRequiredApi).mockResolvedValue({ ...mergeResult, undo_token: 42 });
    await expect(commitPersonMerge({ survivor_id: 1, loser_id: 2 })).rejects.toThrow(MalformedPersonMergeResponseError);
  });

  it('rejects a merge response whose merged_cluster_ids is not a string array', async () => {
    vi.mocked(fetchRequiredApi).mockResolvedValue({ ...mergeResult, merged_cluster_ids: [1, 2] });
    await expect(commitPersonMerge({ survivor_id: 1, loser_id: 2 })).rejects.toThrow(MalformedPersonMergeResponseError);
  });

  it('returns a well-formed undo response unchanged', async () => {
    vi.mocked(fetchRequiredApi).mockResolvedValue(undoResult);
    await expect(undoPersonMerge('token')).resolves.toEqual(undoResult);
  });

  it('rejects an undo response missing restored_person_id', async () => {
    vi.mocked(fetchRequiredApi).mockResolvedValue({ restored_cluster_ids: ['c'] });
    await expect(undoPersonMerge('token')).rejects.toThrow(MalformedPersonMergeResponseError);
  });

  it('rejects a response that is not an object', async () => {
    vi.mocked(fetchRequiredApi).mockResolvedValue('nope');
    await expect(previewPersonMerge({ survivor_id: 1, loser_id: 2 })).rejects.toThrow(MalformedPersonMergeResponseError);
  });
});
