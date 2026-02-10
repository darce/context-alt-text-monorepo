<?php

declare(strict_types=1);

namespace AltContext\Api;

require_once __DIR__ . '/interface-recognition-route-controller.php';
require_once __DIR__ . '/class-abstract-recognition-proxy-controller.php';
require_once __DIR__ . '/class-analysis-jobs-controller.php';
require_once __DIR__ . '/class-clusters-controller.php';
require_once __DIR__ . '/class-cluster-mutations-controller.php';
require_once __DIR__ . '/class-media-identities-controller.php';
require_once __DIR__ . '/class-suggestions-controller.php';

use WP_Error;
use WP_REST_Request;
use WP_REST_Response;

class RecognitionController {
	private AnalysisJobsController $analysisJobsController;
	private ClustersController $clustersController;
	private ClusterMutationsController $clusterMutationsController;
	private MediaIdentitiesController $mediaIdentitiesController;
	private SuggestionsController $suggestionsController;

	public function __construct() {
		$this->analysisJobsController = new AnalysisJobsController();
		$this->clustersController = new ClustersController();
		$this->clusterMutationsController = new ClusterMutationsController();
		$this->mediaIdentitiesController = new MediaIdentitiesController();
		$this->suggestionsController = new SuggestionsController();
	}

	public function register_routes(): void {
		$this->analysisJobsController->register_routes();
		$this->clustersController->register_routes();
		$this->clusterMutationsController->register_routes();
		$this->mediaIdentitiesController->register_routes();
		$this->suggestionsController->register_routes();
	}

	public function can_manage_recognition(): bool {
		return $this->analysisJobsController->can_manage_recognition();
	}

	public function analyze_media( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		return $this->analysisJobsController->analyze_media( $request );
	}

	public function get_job_status( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		return $this->analysisJobsController->get_job_status( $request );
	}

	public function stream_job_progress( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		return $this->analysisJobsController->stream_job_progress( $request );
	}

	public function cancel_job( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		return $this->analysisJobsController->cancel_job( $request );
	}

	public function validate_media_ids( $value, WP_REST_Request $request, string $param ): bool|WP_Error {
		return $this->analysisJobsController->validate_media_ids( $value, $request, $param );
	}

	public function cluster_media( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		return $this->clusterMutationsController->cluster_media( $request );
	}

	public function list_clusters( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		return $this->clustersController->list_clusters( $request );
	}

	public function list_top_unlabeled_clusters( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		return $this->clustersController->list_top_unlabeled_clusters( $request );
	}

	public function list_cluster_labels( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		return $this->clustersController->list_cluster_labels( $request );
	}

	public function get_cluster_detail( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		return $this->clustersController->get_cluster_detail( $request );
	}

	public function get_cluster_members( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		return $this->clustersController->get_cluster_members( $request );
	}

	public function update_cluster_label( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		return $this->clusterMutationsController->update_cluster_label( $request );
	}

	public function reassign_cluster_identity( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		return $this->clusterMutationsController->reassign_cluster_identity( $request );
	}

	public function dismiss_cluster( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		return $this->clusterMutationsController->dismiss_cluster( $request );
	}

	public function undismiss_cluster( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		return $this->clusterMutationsController->undismiss_cluster( $request );
	}

	public function merge_cluster( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		return $this->clusterMutationsController->merge_cluster( $request );
	}

	public function split_cluster( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		return $this->clusterMutationsController->split_cluster( $request );
	}

	public function create_cluster_for_identity( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		return $this->clusterMutationsController->create_cluster_for_identity( $request );
	}

	public function revert_merge_cluster( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		return $this->clusterMutationsController->revert_merge_cluster( $request );
	}

	public function get_media_identities( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		return $this->mediaIdentitiesController->get_media_identities( $request );
	}

	public function get_identity_suggestions( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		return $this->suggestionsController->get_identity_suggestions( $request );
	}

	public function get_pending_suggestions( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		return $this->suggestionsController->get_pending_suggestions( $request );
	}

	public function get_pending_merge_suggestions( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		return $this->suggestionsController->get_pending_merge_suggestions( $request );
	}

	public function accept_suggestion( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		return $this->suggestionsController->accept_suggestion( $request );
	}

	public function accept_merge_suggestion( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		return $this->suggestionsController->accept_merge_suggestion( $request );
	}

	public function reject_suggestion( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		return $this->suggestionsController->reject_suggestion( $request );
	}

	public function reject_merge_suggestion( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		return $this->suggestionsController->reject_merge_suggestion( $request );
	}
}
