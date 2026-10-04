<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Api\Services\DescriptionBudgetService;
use AltContext\Api\Services\DescribeMediaService;
use AltContext\Api\DescribeHostInterface;
use AltContext\Tests\TestCase;
use WP_Error;
use WP_REST_Request;
use WP_REST_Response;

/**
 * Regression coverage for operation-level description budget accounting.
 *
 * @covers \AltContext\Api\Services\DescriptionBudgetService
 * @covers \AltContext\Sovereign\Repositories\DescriptionUsageRepository
 */
class AdvfixDescriptionBudgetOperationTest extends TestCase
{
	protected function setUp(): void {
		parent::setUp();
		$GLOBALS['wpdb']->mockVar = '1';
	}

	public function testDescribeRetryWithSameOperationIdWritesOneUsageRow(): void {
		$this->setOption( 'acx_description_budget_max_attempts', 1 );
		$temp_path = tempnam( sys_get_temp_dir(), 'advfix-wpbudget-' );
		$this->assertNotFalse( $temp_path );
		file_put_contents( $temp_path, "\xff\xd8\xff\xe0test-image" );
		$GLOBALS['__ac_attached_file'][42] = $temp_path;
		$operation_id = 'retry-operation-42';
		$host         = new AdvfixDescriptionBudgetTestHost();
		$service      = new DescribeMediaService( $host );

		try {
			$first = new AdvfixDescriptionBudgetTestRequest( array( 'operation_id' => $operation_id ) );
			$first->set_param( 'media_id', 42 );
			$retry = new AdvfixDescriptionBudgetTestRequest( array( 'operation_id' => $operation_id ) );
			$retry->set_param( 'media_id', 42 );

			$this->assertInstanceOf( WP_REST_Response::class, $service->describe_media( $first ) );
			$this->assertInstanceOf( WP_REST_Response::class, $service->describe_media( $retry ) );
			$this->assertSame( 2, $host->dispatches );
			$this->assertSame( $operation_id, $host->last_body['operation_id'] );
			$usage_rows = ( new \AltContext\Sovereign\Repositories\DescriptionUsageRepository() )->all();
			$this->assertCount( 1, $usage_rows );
			$this->assertSame( $operation_id, $usage_rows[0]['operation_id'] );
			$this->assertTrue( $usage_rows[0]['cached'] );
		} finally {
			@unlink( $temp_path );
		}
	}

	public function testSameOperationIdUsesOneReservationAndOneUsageDebit(): void {
		$this->setOption( 'acx_description_budget_max_attempts', 1 );
		$service       = new DescriptionBudgetService();
		$operation_id  = 'retry-operation-42';

		$first = $service->reserve_attempt( $operation_id );
		$this->assertTrue( $first['allowed'] );
		$retry = $service->reserve_attempt( $operation_id );
		$this->assertTrue( $retry['allowed'] );
		$this->assertSame( $first['reservation_id'], $retry['reservation_id'] );
		$this->assertTrue( $service->mark_attempt_dispatched( $first['reservation_id'] ) );

		$this->recordSuccess( $service, $operation_id, $first['reservation_id'] );
		$settled_retry = $service->reserve_attempt( $operation_id );
		$this->assertTrue( $settled_retry['allowed'] );
		$this->assertNull( $settled_retry['reservation_id'] );
		$this->recordSuccess( $service, $operation_id, null );

		$usage_rows = ( new \AltContext\Sovereign\Repositories\DescriptionUsageRepository() )->all();
		$this->assertCount( 1, $usage_rows );
		$this->assertSame( $operation_id, $usage_rows[0]['operation_id'] );
		$this->assertSame( 1, $service->usage_summary()['attempts'] );
	}

	public function testExpiredDispatchedReservationStillConsumesLifetimeBudget(): void {
		$this->setOption( 'acx_description_budget_max_attempts', 1 );
		$service      = new DescriptionBudgetService();
		$operation_id = 'dispatched-operation-42';
		$reservation  = $service->reserve_attempt( $operation_id );
		$this->assertTrue( $reservation['allowed'] );
		$this->assertTrue( $service->mark_attempt_dispatched( $reservation['reservation_id'] ) );

		$reservations = get_option( 'acx_description_budget_reservations' );
		$reservations[ $reservation['reservation_id'] ]['expires_at'] = time() - 1;
		$this->setOption( 'acx_description_budget_reservations', $reservations );

		$next = $service->reserve_attempt( 'different-operation-43' );
		$this->assertFalse( $next['allowed'] );
		$this->assertSame( 'description_budget_attempt_limit_exceeded', $next['code'] );
		$this->assertSame( 1, $next['used'] );
		$this->assertArrayHasKey( $reservation['reservation_id'], get_option( 'acx_description_budget_reservations' ) );
	}

	public function testReservationIsReleasedWhenOptionReadResetsRowsAffected(): void {
		$GLOBALS['wpdb'] = new class extends \WPDBStub {
			public function get_results( $query, $output = OBJECT ) {
				$results = parent::get_results( $query, $output );
				if ( str_contains( (string) $query, 'wp_options' ) ) {
					$this->rows_affected = 0;
				}

				return $results;
			}
		};
		$GLOBALS['wpdb']->mockVar = '1';
		$GLOBALS['__ac_get_option_before_read']['acx_description_budget_reservations'] = static function ( string $key, int $calls ): void {
			unset( $key, $calls );
			$GLOBALS['wpdb']->get_results( 'SELECT option_value FROM wp_options WHERE option_name = \'acx_description_budget_reservations\'', ARRAY_A );
		};
		$this->setOption( 'acx_description_budget_max_attempts', 2 );

		$service = new DescriptionBudgetService();
		$reservation = $service->reserve_attempt();
		$this->assertTrue( $reservation['allowed'] );

		$service->record_success(
			media_id: 42,
			adapter: 'local_cpu',
			provider: 'local',
			duration_ms: 100,
			cached: false,
			write_status: 'drafted',
			reservation_id: $reservation['reservation_id']
		);

		$this->assertSame( array(), get_option( 'acx_description_budget_reservations' ) );
		$this->assertTrue( $service->reserve_attempt()['allowed'] );
	}

	/**
	 * @param string|null $reservation_id
	 */
	private function recordSuccess( DescriptionBudgetService $service, string $operation_id, ?string $reservation_id ): void {
		$service->record_success(
			media_id: 42,
			adapter: 'local_cpu',
			provider: 'local',
			duration_ms: 100,
			cached: false,
			write_status: 'drafted',
			reservation_id: $reservation_id,
			operation_id: $operation_id
		);
	}
}

final class AdvfixDescriptionBudgetTestHost implements DescribeHostInterface {
	/** @var array<string,mixed> */
	public array $last_body = array();
	public int $dispatches = 0;

	public function get_tenant_id(): string {
		return 'advfix-budget-tenant';
	}

	public function proxy_recognition_request(
		string $method,
		string $path,
		array $body = array(),
		array $query = array(),
		string $request_class = 'auto',
		string $body_kind = 'json',
		?int $max_body_bytes = null
	): WP_REST_Response|WP_Error {
		$this->last_body = $body;
		++$this->dispatches;

		return new WP_REST_Response(
			array(
				'tenant_id'              => $this->get_tenant_id(),
				'media_id'               => 42,
				'image_hash'              => str_repeat( 'a', 64 ),
				'context_hash'            => str_repeat( 'b', 64 ),
				'adapter'                 => 'seeded',
				'model_id'                => 'seeded-fixtures',
				'model_version'           => '1',
				'prompt_or_task_version'  => '1',
				'visual_facts'            => array( 'caption' => 'A photo.', 'objects' => array(), 'ocr_text' => null ),
				'alt_text_draft'          => 'A photo.',
				'context_used'            => array( 'sources' => array(), 'applied' => false ),
				'provider_disclosure'     => array( 'provider' => 'none', 'left_service_boundary' => false ),
				'cached'                  => true,
				'duration_ms'             => 3,
				'retention_class'         => 'retain_all',
				'tier'                    => 'provisional_cpu',
				'result_generation'       => 0,
			),
			200
		);
	}

	public function is_proxy_unavailable( WP_REST_Response|WP_Error $response ): bool {
		return false;
	}
}

final class AdvfixDescriptionBudgetTestRequest extends WP_REST_Request {
	/** @param array<string,mixed> $json_params */
	public function __construct( private array $json_params ) {
		parent::__construct( 'POST', '/acx/v1/recognition/describe' );
	}

	public function get_json_params(): ?array {
		return $this->json_params;
	}

	public function get_body_params(): array {
		return array();
	}
}
