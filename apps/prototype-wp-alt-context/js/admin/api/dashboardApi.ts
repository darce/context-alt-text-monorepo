import { fetchRequiredApi } from '../utils/http';
import { getEndpoint, getConfig } from './config';

export interface DashboardStats {
  people_count: number;
  assigned_clusters_count: number;
  pending_clusters_count: number;
  media_with_faces_count: number;
  unassigned_persons_count: number;
}

export const fetchDashboardStats = async (): Promise<DashboardStats> => {
  const endpoint = getEndpoint('dashboardStats');
  return fetchRequiredApi<DashboardStats>(endpoint, {
    method: 'GET',
    restNonce: getConfig().nonce,
  });
};
