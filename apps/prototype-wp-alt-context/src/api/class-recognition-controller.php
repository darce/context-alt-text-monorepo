<?php

declare(strict_types=1);

namespace AltContext\Api;

require_once __DIR__ . '/interface-recognition-route-controller.php';
require_once __DIR__ . '/class-abstract-recognition-proxy-controller.php';
require_once __DIR__ . '/class-analysis-jobs-controller.php';
require_once __DIR__ . '/class-clusters-controller.php';
require_once __DIR__ . '/class-suggestions-controller.php';

use BadMethodCallException;

use function method_exists;
use function sanitize_key;
use function sprintf;

class RecognitionController {
	private AnalysisJobsController $analysisJobsController;
	private ClustersController $clustersController;
	private SuggestionsController $suggestionsController;

	public function __construct() {
		$this->analysisJobsController = new AnalysisJobsController();
		$this->clustersController     = new ClustersController();
		$this->suggestionsController  = new SuggestionsController();
	}

	public function register_routes(): void {
		$this->analysisJobsController->register_routes();
		$this->clustersController->register_routes();
		$this->suggestionsController->register_routes();
	}

	public function can_manage_recognition(): bool {
		return $this->analysisJobsController->can_manage_recognition();
	}

	/**
	 * Temporary compatibility layer while routes/callback ownership is split
	 * across domain controllers.
	 *
	 * @param string $name Method name.
	 * @param array<int,mixed> $arguments Method arguments.
	 * @throws BadMethodCallException
	 */
	public function __call( string $name, array $arguments ): mixed {
		foreach ( $this->get_controllers() as $controller ) {
			if ( method_exists( $controller, $name ) ) {
				return $controller->{$name}( ...$arguments );
			}
		}

		throw new BadMethodCallException( sprintf( 'Unknown recognition controller method: %s', sanitize_key( $name ) ) );
	}

	/**
	 * @return array<int,AbstractRecognitionProxyController>
	 */
	private function get_controllers(): array {
		return array(
			$this->analysisJobsController,
			$this->clustersController,
			$this->suggestionsController,
		);
	}
}
