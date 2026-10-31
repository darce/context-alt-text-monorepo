import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import Ajv from 'ajv';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { fetchTopUnlabeledClusters } from '../clusterApiQueries';
import { fetchRequiredApi } from '../../../utils/http';

vi.mock('../../../utils/http', () => ({
  fetchRequiredApi: vi.fn(),
  stripTrailingSlash: (s: string) => s.replace(/\/$/, ''),
}));
vi.mock('../../config', () => ({ getEndpoint: () => '/recognition/clusters', getConfig: () => ({ nonce: 'test' }) }));
const local = {
  id: 'group',
  tenant_id: 'tenant',
  label: null,
  label_state: 'unlabeled',
  is_labeled: false,
  is_auto_label: false,
  identity_count: 8,
  user_confirmed: false,
  photo_count: 2,
  representatives: [{ id: 'face', media_id: 12, is_pinned: false }],
};
const response = {
  clusters: [local],
  limit: 20,
  total: 1,
  truncated: false,
  data_source: 'local_projection',
  singleton_count: 0,
  has_clusters: true,
  repair_pending: false,
};
beforeEach(() => {
  vi.stubGlobal('window', { location: { origin: 'https://example.test' } });
  vi.mocked(fetchRequiredApi).mockResolvedValue(response);
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.resetAllMocks();
});
it('keeps photo and face counts separate and accepts unavailable older aggregates', async () => {
  const page = await fetchTopUnlabeledClusters('tenant', 20, undefined, { min_photos: 2, offset: 20 });
  const url = new URL(vi.mocked(fetchRequiredApi).mock.calls[0][0]);
  expect(url.pathname).toBe('/recognition/clusters/top-unlabeled');
  expect(url.searchParams.get('min_photos')).toBe('2');
  expect(url.searchParams.get('offset')).toBe('20');
  expect(page.clusters[0].identity_count).toBe(8);
  expect(page.clusters[0].photo_count).toBe(2);
  const older: Partial<typeof local> = { ...local };
  delete older.photo_count;
  vi.mocked(fetchRequiredApi).mockResolvedValue({ ...response, clusters: [older] });
  expect((await fetchTopUnlabeledClusters('tenant', 20)).clusters[0]).not.toHaveProperty('photo_count');
});
it.each([-1, 1.5, '2', false])(
  'rejects malformed photo counts (%s) instead of substituting faces',
  async (photo_count) => {
    vi.mocked(fetchRequiredApi).mockResolvedValue({ ...response, clusters: [{ ...local, photo_count }] });
    await expect(fetchTopUnlabeledClusters('tenant', 20)).rejects.toThrow('photo_count');
  },
);
it('limits null totals to opt-in filtering and preserves remote representative provenance', async () => {
  const remote = { ...local, representatives: [{ id: 'face', media_id: '12', bbox: null, is_user_selected: true }] };
  vi.mocked(fetchRequiredApi).mockResolvedValue({
    ...response,
    clusters: [remote],
    data_source: 'backend_proxy',
    total: null,
    truncated: true,
  });
  const page = await fetchTopUnlabeledClusters('tenant', 20, undefined, { min_photos: 2 });
  expect(page.total).toBeNull();
  expect(page.truncated).toBe(true);
  expect(page.clusters[0].representatives[0].is_pinned).toBe(true);
  await expect(fetchTopUnlabeledClusters('tenant', 20)).rejects.toThrow('total');
});
it('the opt-in schema accepts actual local/proxy row shapes and rejects invalid counts', () => {
  const schema = JSON.parse(
    readFileSync(
      resolve(process.cwd(), '../../packages/shared-contracts/schemas/recognition-cluster-list-response.schema.json'),
      'utf8',
    ),
  ) as object;
  const ajv = new Ajv({ allErrors: true });
  ajv.addSchema(schema, 'review');
  const validate = ajv.compile({ $ref: 'review#/definitions/reviewPhotoFilteredResponse' });
  expect(validate(response)).toBe(true);
  expect(
    validate({
      ...response,
      total: null,
      data_source: 'backend_proxy',
      clusters: [{ ...local, representatives: [{ id: 'face', media_id: '12', bbox: null, is_user_selected: false }] }],
    }),
  ).toBe(true);
  expect(validate({ ...response, clusters: [{ ...local, photo_count: -1 }] })).toBe(false);
});
