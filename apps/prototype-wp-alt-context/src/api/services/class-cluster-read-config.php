<?php

declare(strict_types=1);

namespace AltContext\Api\Services;

/**
 * Immutable string configuration for the cluster read path: the bootstrap-sync
 * hook name plus the data-source and projection-status vocabulary. Grouped into
 * one value object so ClusterReadDependencies stays within the parameter-count
 * guideline (sr-008); the canonical values live on ClustersController.
 */
final class ClusterReadConfig {
	public string $bootstrap_sync_hook;
	public string $data_source_backend_proxy;
	public string $data_source_local_projection;
	public string $data_source_unavailable;
	public string $projection_status_bootstrapping;
	public string $projection_status_available;

	public function __construct(
		string $bootstrap_sync_hook,
		string $data_source_backend_proxy,
		string $data_source_local_projection,
		string $data_source_unavailable,
		string $projection_status_bootstrapping,
		string $projection_status_available
	) {
		$this->bootstrap_sync_hook = $bootstrap_sync_hook;
		$this->data_source_backend_proxy = $data_source_backend_proxy;
		$this->data_source_local_projection = $data_source_local_projection;
		$this->data_source_unavailable = $data_source_unavailable;
		$this->projection_status_bootstrapping = $projection_status_bootstrapping;
		$this->projection_status_available = $projection_status_available;
	}
}
