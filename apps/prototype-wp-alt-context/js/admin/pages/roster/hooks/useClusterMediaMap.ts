import { useEffect, useState } from 'react';

import type { ClusterSummary } from '../../../api/recognitionApi';
import { fetchMediaMeta, type MediaMeta } from '../utils/mediaMeta';

export type MediaMap = Record<number, MediaMeta>;

export const useClusterMediaMap = (clusters: ClusterSummary[]): MediaMap => {
	const [mediaMap, setMediaMap] = useState<MediaMap>({});

	useEffect(() => {
		const mediaIds = new Set<number>();
		clusters.forEach((cluster) => {
			cluster.sample_faces.forEach((face: ClusterSummary['sample_faces'][number]) => mediaIds.add(face.media_id));
			if (cluster.representative_face.media_id) {
				mediaIds.add(cluster.representative_face.media_id);
			}
		});

		const missing = Array.from(mediaIds).filter((id) => !(id in mediaMap));
		if (missing.length === 0) {
			return;
		}

		let cancelled = false;
		(async () => {
			const entries = await Promise.all(
				missing.map(async (id) => {
					const meta = await fetchMediaMeta(id);
					return [id, meta] as const;
				})
			);
			if (cancelled) {
				return;
			}
			setMediaMap((prev) => {
				const next = { ...prev };
				entries.forEach(([id, meta]) => {
					next[id] = meta;
				});
				return next;
			});
		})();

		return () => {
			cancelled = true;
		};
	}, [clusters, mediaMap]);

	return mediaMap;
};
