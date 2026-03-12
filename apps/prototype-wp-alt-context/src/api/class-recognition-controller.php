<?php

declare(strict_types=1);

namespace AltContext\Api;

require_once __DIR__ . '/interface-recognition-route-controller.php';
require_once __DIR__ . '/class-abstract-recognition-proxy-controller.php';
require_once __DIR__ . '/class-analysis-jobs-controller.php';
require_once __DIR__ . '/class-clusters-controller.php';
require_once __DIR__ . '/class-cluster-mutations-controller.php';
require_once __DIR__ . '/class-conflict-controller.php';
require_once __DIR__ . '/class-media-identities-controller.php';
require_once __DIR__ . '/class-retention-controller.php';
require_once __DIR__ . '/class-sync-status-controller.php';
require_once __DIR__ . '/class-suggestions-controller.php';
require_once __DIR__ . '/../sovereign/class-cluster-facade.php';
require_once __DIR__ . '/../sovereign/sync/class-sync-pull-job-factory.php';

use AltContext\Sovereign\ClusterFacade;
use AltContext\Sovereign\Repositories\ClustersRepository;
use AltContext\Sovereign\Repositories\IdentityMembersRepository;
use AltContext\Sovereign\Repositories\SyncStateRepository;
use AltContext\Sovereign\Sync\SnapshotClient;
use AltContext\Sovereign\Sync\SyncPullJobFactory;
use WP_Error;
use WP_REST_Request;
use WP_REST_Response;
use Throwable;

use function do_action;

class RecognitionController {
	private AnalysisJobsController $analysisJobsController;
	private ClustersController $clustersController;
	private ClusterMutationsController $clusterMutationsController;
	private ConflictController $conflictController;
	private MediaIdentitiesController $mediaIdentitiesController;
	private RetentionController $retentionController;
	private SyncStatusController $syncStatusController;
	private SuggestionsController $suggestionsController;
	private ClusterFacade $clusterFacade;

	/**
	 * @param ?AnalysisJobsController     $analysis_jobs_controller     Optional for testing.
	 * @param ?ClustersController         $clusters_controller          Optional for testing.
	 * @param ?ClusterMutationsController $cluster_mutations_controller Optional for testing.
	 * @param ?ConflictController         $conflict_controller          Optional for testing.
	 * @param ?MediaIdentitiesController  $media_identities_controller  Optional for testing.
	 * @param ?RetentionController        $retention_controller         Optional for testing.
	 * @param ?SyncStatusController       $sync_status_controller       Optional for testing.
	 * @param ?SuggestionsController      $suggestions_controller       Optional for testing.
	 */
	public function __construct(
		?AnalysisJobsController $analysis_jobs_controller = null,
		?ClustersController $clusters_controller = null,
		?ClusterMutationsController $cluster_mutations_controller = null,
		?ConflictController $conflict_controller = null,
		?MediaIdentitiesController $media_identities_controller = null,
		?RetentionController $retention_controller = null,
		?SyncStatusController $sync_status_controller = null,
		?SuggestionsController $suggestions_controller = null
	) {
		$this->analysisJobsController = $analysis_jobs_controller ?? new AnalysisJobsController();
		$sync_pull_job = null;
		if ( null !== $clusters_controller ) {
			$this->clustersController = $clusters_controller;
		} else {
			try {
				$clusters_repository = new ClustersRepository();
				$members_repository  = new IdentityMembersRepository();
				$sync_repository     = new SyncStateRepository();
				$sync_pull_job_factory = new SyncPullJobFactory(
					$clusters_repository,
					$members_repository,
					$sync_repository,
					new SnapshotClient()
				);
				$sync_pull_job       = $sync_pull_job_factory->create();
				$this->clusterFacade = new ClusterFacade( $clusters_repository, $members_repository );
				$this->clustersController = new ClustersController( $clusters_repository, $members_repository, $sync_repository, $sync_pull_job, null, null, $this->clusterFacade, $sync_pull_job_factory );
				$this->clusterMutationsController = $cluster_mutations_controller ?? new ClusterMutationsController( $clusters_repository, $sync_repository, $members_repository );
				$this->retentionController = $retention_controller ?? new RetentionController( $sync_pull_job );
				$this->syncStatusController = $sync_status_controller ?? new SyncStatusController(
					$sync_repository,
					$sync_pull_job,
					$sync_pull_job_factory
				);
			} catch ( Throwable $throwable ) {
				do_action(
					'acx_recognition_composition_failed',
					array(
						'message' => $throwable->getMessage(),
						'controller' => __CLASS__,
					)
				);
				$this->clusterFacade = new ClusterFacade( new ClustersRepository(), new IdentityMembersRepository() );
				$this->clustersController = new ClustersController( null, null, null, null, null, null, $this->clusterFacade );
				$this->clusterMutationsController = $cluster_mutations_controller ?? new ClusterMutationsController();
				$this->retentionController = $retention_controller ?? new RetentionController();
			}
		}
		if ( null !== $cluster_mutations_controller ) {
			$this->clusterMutationsController = $cluster_mutations_controller;
		} elseif ( ! isset( $this->clusterMutationsController ) ) {
			$this->clusterMutationsController = new ClusterMutationsController(
				$this->clustersController->get_clusters_repository(),
				$this->clustersController->get_sync_state_repository(),
				new IdentityMembersRepository()
			);
		}
		$this->conflictController = $conflict_controller ?? new ConflictController();
		$this->mediaIdentitiesController = $media_identities_controller ?? new MediaIdentitiesController();
		if ( ! isset( $this->retentionController ) ) {
			$this->retentionController = $retention_controller ?? new RetentionController( $sync_pull_job ?? null );
		}
		if ( ! isset( $this->syncStatusController ) ) {
			$this->syncStatusController = $sync_status_controller ?? new SyncStatusController(
				null,
				$sync_pull_job ?? null
			);
		}
		$this->suggestionsController = $suggestions_controller ?? new SuggestionsController();
	}

	public function register_routes(): void {
		$this->analysisJobsController->register_routes();
		$this->clustersController->register_routes();
		$this->clusterMutationsController->register_routes();
		$this->conflictController->register_routes();
		$this->mediaIdentitiesController->register_routes();
		$this->retentionController->register_routes();
		$this->syncStatusController->register_routes();
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

	public function assign_outlier_to_cluster( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		return $this->clusterMutationsController->assign_outlier_to_cluster( $request );
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
