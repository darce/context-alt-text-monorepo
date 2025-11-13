import React from 'react';
import { __, _n, sprintf } from '@wordpress/i18n';

import type { ClusterSummary } from '../../api/recognitionApi';
import type { RosterEntry } from '../../api/rosterApi';
import type { MediaMap } from './hooks/useClusterMediaMap';
import { FaceThumbnail } from './FaceThumbnail';

type Props = {
	cluster: ClusterSummary | null;
	mediaMap: MediaMap;
	onClose: () => void;
	onRescanCluster: (cluster: ClusterSummary) => void;
	isRescanning: boolean;
	onCommitCluster: (cluster: ClusterSummary, assignment: { rosterEntryId?: number; newEntryName?: string }) => void;
	isCommitting: boolean;
	rosterEntries: RosterEntry[];
	statusMessage?: string | null;
	errorMessage?: string | null;
	onFaceDragStart: (clusterId: string, faceId: string) => void;
	onFaceDragEnd: () => void;
	onDropTargetChange: (target: string | 'discard' | null) => void;
	onDropFace: (clusterId: string | null) => void;
	dropTarget: string | 'discard' | null;
	isDragging: boolean;
	onDiscardDrop: () => void;
};

export const ClusterDrawerPanel = ({
	cluster,
	mediaMap,
	onClose,
	onRescanCluster,
	isRescanning,
	onCommitCluster,
	isCommitting,
	rosterEntries,
	statusMessage,
	errorMessage,
	onFaceDragStart,
	onFaceDragEnd,
	onDropTargetChange,
	onDropFace,
	dropTarget,
	isDragging,
	onDiscardDrop,
}: Props): React.JSX.Element | null => {
	const [selectedEntryId, setSelectedEntryId] = React.useState('');
	const [newEntryName, setNewEntryName] = React.useState('');

	React.useEffect(() => {
		setSelectedEntryId('');
		setNewEntryName('');
	}, [cluster?.id]);

	if (!cluster) {
		return null;
	}

	const isCreatingEntry = selectedEntryId === 'create';
	const canCommit = (isCreatingEntry && newEntryName.trim().length > 0) || (!isCreatingEntry && selectedEntryId !== '');

	const handleCommit = () => {
		if (!canCommit) {
			return;
		}

		const assignment = isCreatingEntry
			? { newEntryName: newEntryName.trim() }
			: { rosterEntryId: Number.parseInt(selectedEntryId, 10) };

		onCommitCluster(cluster, assignment);
	};

	return (
		<>
			<div className="acx-cluster-drawer__backdrop" onClick={onClose} />
			<aside className="acx-cluster-drawer" aria-live="polite">
				<header className="acx-cluster-drawer__header">
					<div>
						<p className="acx-cluster-drawer__label">{__('Cluster', 'alt-context')}</p>
						<h3>{cluster.label || cluster.id}</h3>
						<p>{sprintf(_n('%d face', '%d faces', cluster.face_count, 'alt-context'), cluster.face_count)}</p>
					</div>
					<button type="button" className="acx-link-button" onClick={onClose}>
						{__('Close', 'alt-context')}
					</button>
				</header>

				<div className="acx-cluster-drawer__faces">
					{cluster.sample_faces.length === 0 ? (
						<p>{__('No faces found for this cluster.', 'alt-context')}</p>
					) : (
						cluster.sample_faces.map((face) => (
							<figure
								key={face.id}
								className="acx-cluster-drawer__face"
								draggable
								aria-label={sprintf(__('Move face from media %d', 'alt-context'), face.media_id)}
								onDragStart={(event) => {
									event.dataTransfer?.setData('text/plain', face.id);
									event.dataTransfer?.setDragImage(event.currentTarget, 0, 0);
									onFaceDragStart(cluster.id, face.id);
								}}
								onDragEnd={onFaceDragEnd}
							>
								<a
									href={`${window.location.origin}/wp-admin/post.php?post=${face.media_id}&action=edit`}
									target="_blank"
									rel="noopener noreferrer"
								>
									<FaceThumbnail face={face} mediaMeta={mediaMap[face.media_id]} size={128} />
								</a>
								<figcaption>
									{sprintf(__('Similarity: %s', 'alt-context'), face.similarity.toFixed(2))}
									<br />
									{sprintf(__('Media %d', 'alt-context'), face.media_id)}
								</figcaption>
							</figure>
						))
					)}
				</div>

				<div className="acx-cluster-drawer__dropzone-wrapper">
					<div
						className={`acx-cluster-drawer__dropzone${dropTarget === 'discard' ? ' is-drop-target' : ''}`}
						onDragOver={(event) => {
						if (!isDragging) {
							return;
						}
						event.preventDefault();
						onDropTargetChange('discard');
					}}
						onDragLeave={() => {
						if (dropTarget === 'discard') {
							onDropTargetChange(null);
						}
					}}
						onDrop={(event) => {
						if (!isDragging) {
							return;
						}
						event.preventDefault();
						onDropTargetChange(null);
						onDiscardDrop();
					}}
					>
						{__('Drop faces here to remove them from this cluster.', 'alt-context')}
					</div>
				</div>

				<div className="acx-cluster-drawer__actions">
					<button
						type="button"
						className="acx-apply-panel__scan"
						onClick={() => onRescanCluster(cluster)}
						disabled={isRescanning || cluster.sample_faces.length === 0}
					>
						{isRescanning
							? __('Rescanning…', 'alt-context')
							: __('Rescan with sensitive settings', 'alt-context')}
					</button>
				</div>

				<div className="acx-cluster-drawer__assignment">
					<label htmlFor="acx-roster-entry-select">{__('Commit to roster entry', 'alt-context')}</label>
					<select
						id="acx-roster-entry-select"
						value={selectedEntryId}
						onChange={(event) => setSelectedEntryId(event.target.value)}
						className="acx-cluster-drawer__select"
					>
						<option value="">{__('Select an entry', 'alt-context')}</option>
						{rosterEntries.map((entry) => (
							<option key={entry.id} value={entry.id.toString()}>
								{entry.name}
							</option>
						))}
						<option value="create">{__('Create new entry…', 'alt-context')}</option>
					</select>

					{selectedEntryId === 'create' && (
						<input
							type="text"
							className="acx-cluster-drawer__input"
							value={newEntryName}
							onChange={(event) => setNewEntryName(event.target.value)}
							placeholder={__('New roster entry name', 'alt-context')}
						/>
					)}

					<button type="button" className="acx-link-button" onClick={handleCommit} disabled={!canCommit || isCommitting}>
						{isCommitting ? __('Committing…', 'alt-context') : __('Commit to roster entry', 'alt-context')}
					</button>
				</div>

				{statusMessage && <p className="acx-cluster-drawer__status">{statusMessage}</p>}
				{errorMessage && <p className="acx-cluster-drawer__status acx-cluster-drawer__status--error">{errorMessage}</p>}
			</aside>
		</>
	);
};
