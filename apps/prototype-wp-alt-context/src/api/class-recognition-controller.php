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
	private ?AnalysisJobsController $analysisJobsController = null;
	private ?ClustersController $clustersController = null;
	private ?ClusterMutationsController $clusterMutationsController = null;
	private ?ConflictController $conflictController = null;
	private ?MediaIdentitiesController $mediaIdentitiesController = null;
	private ?RetentionController $retentionController = null;
	private ?SyncStatusController $syncStatusController = null;
	private ?SuggestionsController $suggestionsController = null;
	private ?ClusterFacade $clusterFacade = null;

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
		$this->analysisJobsController = $analysis_jobs_controller;
		$this->clustersController = $clusters_controller;
		$this->clusterMutationsController = $cluster_mutations_controller;
		$this->conflictController = $conflict_controller;
		$this->mediaIdentitiesController = $media_identities_controller;
		$this->retentionController = $retention_controller;
		$this->syncStatusController = $sync_status_controller;
		$this->suggestionsController = $suggestions_controller;
	}

	public function register_routes(): void {
		$this->register_routes_for(
			static fn ( self $controller ): RecognitionRouteControllerInterface => $controller->getAnalysisJobsController()
		);
		$this->register_routes_for(
			static fn ( self $controller ): RecognitionRouteControllerInterface => $controller->getClustersController()
		);
		$this->register_routes_for(
			static fn ( self $controller ): RecognitionRouteControllerInterface => $controller->getClusterMutationsController()
		);
		$this->register_routes_for(
			static fn ( self $controller ): RecognitionRouteControllerInterface => $controller->getConflictController()
		);
		$this->register_routes_for(
			static fn ( self $controller ): RecognitionRouteControllerInterface => $controller->getMediaIdentitiesController()
		);
		$this->register_routes_for(
			static fn ( self $controller ): RecognitionRouteControllerInterface => $controller->getRetentionController()
		);
		$this->register_routes_for(
			static fn ( self $controller ): RecognitionRouteControllerInterface => $controller->getSyncStatusController()
		);
		$this->register_routes_for(
			static fn ( self $controller ): RecognitionRouteControllerInterface => $controller->getSuggestionsController()
		);
	}

	public function can_manage_recognition(): bool {
		return $this->getAnalysisJobsController()->can_manage_recognition();
	}

	public function analyze_media( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		return $this->getAnalysisJobsController()->analyze_media( $request );
	}

	public function get_job_status( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		return $this->getAnalysisJobsController()->get_job_status( $request );
	}

	public function stream_job_progress( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		return $this->getAnalysisJobsController()->stream_job_progress( $request );
	}

	public function cancel_job( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		return $this->getAnalysisJobsController()->cancel_job( $request );
	}

	public function validate_media_ids( $value, WP_REST_Request $request, string $param ): bool|WP_Error {
		return $this->getAnalysisJobsController()->validate_media_ids( $value, $request, $param );
	}

	public function cluster_media( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		return $this->getClusterMutationsController()->cluster_media( $request );
	}

	public function list_clusters( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		return $this->getClustersController()->list_clusters( $request );
	}

	public function list_top_unlabeled_clusters( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		return $this->getClustersController()->list_top_unlabeled_clusters( $request );
	}

	public function list_cluster_labels( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		return $this->getClustersController()->list_cluster_labels( $request );
	}

	public function get_cluster_detail( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		return $this->getClustersController()->get_cluster_detail( $request );
	}

	public function get_cluster_members( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		return $this->getClustersController()->get_cluster_members( $request );
	}

	public function update_cluster_label( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		return $this->getClusterMutationsController()->update_cluster_label( $request );
	}

	public function reassign_cluster_identity( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		return $this->getClusterMutationsController()->reassign_cluster_identity( $request );
	}

	public function dismiss_cluster( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		return $this->getClusterMutationsController()->dismiss_cluster( $request );
	}

	public function undismiss_cluster( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		return $this->getClusterMutationsController()->undismiss_cluster( $request );
	}

	public function merge_cluster( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		return $this->getClusterMutationsController()->merge_cluster( $request );
	}

	public function split_cluster( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		return $this->getClusterMutationsController()->split_cluster( $request );
	}

	public function create_cluster_for_identity( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		return $this->getClusterMutationsController()->create_cluster_for_identity( $request );
	}

	public function revert_merge_cluster( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		return $this->getClusterMutationsController()->revert_merge_cluster( $request );
	}

	public function assign_outlier_to_cluster( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		return $this->getClusterMutationsController()->assign_outlier_to_cluster( $request );
	}

	public function get_media_identities( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		return $this->getMediaIdentitiesController()->get_media_identities( $request );
	}

	public function get_identity_suggestions( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		return $this->getSuggestionsController()->get_identity_suggestions( $request );
	}

	public function get_pending_suggestions( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		return $this->getSuggestionsController()->get_pending_suggestions( $request );
	}

	public function get_pending_merge_suggestions( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		return $this->getSuggestionsController()->get_pending_merge_suggestions( $request );
	}

	public function accept_suggestion( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		return $this->getSuggestionsController()->accept_suggestion( $request );
	}

	public function accept_merge_suggestion( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		return $this->getSuggestionsController()->accept_merge_suggestion( $request );
	}

	public function reject_suggestion( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		return $this->getSuggestionsController()->reject_suggestion( $request );
	}

	public function reject_merge_suggestion( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		return $this->getSuggestionsController()->reject_merge_suggestion( $request );
	}

	private function register_routes_for( callable $resolver ): void {
		try {
			$controller = $resolver( $this );
			$controller->register_routes();
		} catch ( Throwable $throwable ) {
			do_action(
				'acx_recognition_composition_failed',
				array(
					'message'    => $throwable->getMessage(),
					'controller' => __CLASS__,
				)
			);
		}
	}

	private function getAnalysisJobsController(): AnalysisJobsController {
		if ( null === $this->analysisJobsController ) {
			$this->analysisJobsController = new AnalysisJobsController();
		}

		return $this->analysisJobsController;
	}

	private function getClustersController(): ClustersController {
		$this->ensureProjectionControllers();
		return $this->clustersController;
	}

	private function getClusterMutationsController(): ClusterMutationsController {
		$this->ensureProjectionControllers();
		return $this->clusterMutationsController;
	}

	private function getConflictController(): ConflictController {
		if ( null === $this->conflictController ) {
			$this->conflictController = new ConflictController();
		}

		return $this->conflictController;
	}

	private function getMediaIdentitiesController(): MediaIdentitiesController {
		if ( null === $this->mediaIdentitiesController ) {
			$this->mediaIdentitiesController = new MediaIdentitiesController();
		}

		return $this->mediaIdentitiesController;
	}

	private function getRetentionController(): RetentionController {
		$this->ensureProjectionControllers();
		return $this->retentionController;
	}

	private function getSyncStatusController(): SyncStatusController {
		$this->ensureProjectionControllers();
		return $this->syncStatusController;
	}

	private function getSuggestionsController(): SuggestionsController {
		if ( null === $this->suggestionsController ) {
			$this->suggestionsController = new SuggestionsController();
		}

		return $this->suggestionsController;
	}

	private function ensureProjectionControllers(): void {
		if (
			null !== $this->clustersController
			&& null !== $this->clusterMutationsController
			&& null !== $this->retentionController
			&& null !== $this->syncStatusController
		) {
			return;
		}

		$sync_pull_job = null;
		if ( null !== $this->clustersController ) {
			if ( null === $this->clusterMutationsController ) {
				$this->clusterMutationsController = new ClusterMutationsController(
					$this->clustersController->get_clusters_repository(),
					$this->clustersController->get_sync_state_repository(),
					new IdentityMembersRepository()
				);
			}
			if ( null === $this->retentionController ) {
				$this->retentionController = new RetentionController();
			}
			if ( null === $this->syncStatusController ) {
				$this->syncStatusController = new SyncStatusController();
			}
			return;
		}

		try {
			$clusters_repository   = new ClustersRepository();
			$members_repository    = new IdentityMembersRepository();
			$sync_repository       = new SyncStateRepository();
			$sync_pull_job_factory = new SyncPullJobFactory(
				$clusters_repository,
				$members_repository,
				$sync_repository,
				new SnapshotClient()
			);
			$sync_pull_job         = $sync_pull_job_factory->create();
			$this->clusterFacade   = new ClusterFacade( $clusters_repository, $members_repository );
			$this->clustersController = new ClustersController(
				$clusters_repository,
				$members_repository,
				$sync_repository,
				$sync_pull_job,
				null,
				null,
				$this->clusterFacade,
				$sync_pull_job_factory
			);
			if ( null === $this->clusterMutationsController ) {
				$this->clusterMutationsController = new ClusterMutationsController(
					$clusters_repository,
					$sync_repository,
					$members_repository
				);
			}
			if ( null === $this->retentionController ) {
				$this->retentionController = new RetentionController( $sync_pull_job );
			}
			if ( null === $this->syncStatusController ) {
				$this->syncStatusController = new SyncStatusController(
					$sync_repository,
					$sync_pull_job,
					$sync_pull_job_factory
				);
			}
		} catch ( Throwable $throwable ) {
			do_action(
				'acx_recognition_composition_failed',
				array(
					'message'    => $throwable->getMessage(),
					'controller' => __CLASS__,
				)
			);
			if ( null === $this->clusterFacade ) {
				$this->clusterFacade = new ClusterFacade( new ClustersRepository(), new IdentityMembersRepository() );
			}
			if ( null === $this->clustersController ) {
				$this->clustersController = new ClustersController( null, null, null, null, null, null, $this->clusterFacade );
			}
			if ( null === $this->clusterMutationsController ) {
				$this->clusterMutationsController = new ClusterMutationsController();
			}
			if ( null === $this->retentionController ) {
				$this->retentionController = new RetentionController( $sync_pull_job );
			}
			if ( null === $this->syncStatusController ) {
				$this->syncStatusController = new SyncStatusController( null, $sync_pull_job );
			}
		}
	}
}
