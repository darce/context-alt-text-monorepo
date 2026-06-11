<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Api\ClustersController;
use AltContext\Api\ClustersHostInterface;
use AltContext\Tests\Support\ClustersReadCharacterizationScenarios;
use AltContext\Tests\TestCase;
use WP_Error;
use WP_REST_Response;

/**
 * Golden-JSON characterization safety net for all 5 clusters-read routes.
 *
 * Branch-coverage inventory (route × sub-branch):
 * - list_clusters: local, proxy-success, proxy-invalid-envelope, proxy-bootstrap-inline, proxy-bootstrap-cron
 * - list_top_unlabeled: local, proxy-success, proxy-invalid-envelope, proxy-bootstrapping-fallback, targeted-repair
 * - list_cluster_labels: local, proxy-success, proxy-invalid-envelope
 * - get_cluster_detail: local, proxy-success, local-not-found
 * - get_cluster_members: local, proxy-success, proxy-invalid-envelope, targeted-repair
 *
 * Shared-helper ownership (SH-01):
 * - cluster_row_should_have_members: ClusterProjectionSyncService (Slice 3)
 * - build_*_envelope: ClusterResponseEnvelopeService (Slice 2)
 *
 * Callback/getter ownership:
 * - perform_bootstrap_sync: controller-resident WP-action callback (CB-01)
 * - get_clusters_repository/get_sync_state_repository: public getters (FC-01)
 * - can_manage_recognition: inherited (CB-02)
 *
 * @covers \AltContext\Api\ClustersController
 */
class ClustersControllerCharacterizationTest extends TestCase
{
    private const FIXTURE_ROOT = __DIR__ . '/../fixtures/clusters-read';

    private ClustersController $controller;

    protected function setUp(): void
    {
        parent::setUp();
        $this->setOption('acx_recognition_url', 'http://localhost:8000');
        $this->controller = new ClustersController();
    }

    public function testControllerImplementsClustersHostInterface(): void
    {
        $this->assertInstanceOf(ClustersHostInterface::class, $this->controller);
    }

    public function testBranchCoverageInventoryIsComplete(): void
    {
        $expected = array_keys(ClustersReadCharacterizationScenarios::all());
        sort($expected);

        $entries = scandir(self::FIXTURE_ROOT);
        if ($entries === false) {
            $entries = [];
        }

        $fixtureDirs = array_values(array_filter(
            $entries,
            static fn (string $entry): bool => ! in_array($entry, ['.', '..'], true)
                && is_dir(self::FIXTURE_ROOT . '/' . $entry)
        ));
        sort($fixtureDirs);

        $this->assertSame($expected, $fixtureDirs, 'Golden fixture inventory must cover every characterized sub-branch.');
    }

    /**
     * @dataProvider goldenScenarioProvider
     */
    public function testGoldenScenario(string $handler): void
    {
        $scenarios = ClustersReadCharacterizationScenarios::all();
        $this->assertArrayHasKey($handler, $scenarios);

        $payload = $scenarios[$handler];
        $this->assertGolden($handler, $payload['response'], $payload['side_effects']);
    }

    /**
     * @return array<string, array{0: string}>
     */
    public static function goldenScenarioProvider(): array
    {
        $cases = [];
        foreach (array_keys(ClustersReadCharacterizationScenarios::all()) as $handler) {
            $cases[$handler] = [$handler];
        }

        return $cases;
    }

    /**
     * @param array<string,mixed> $sideEffects
     */
    private function assertGolden(string $handler, WP_REST_Response|WP_Error $response, array $sideEffects): void
    {
        $fixtureDir = self::FIXTURE_ROOT . '/' . $handler;
        $responseFixture = $fixtureDir . '/response.json';
        $sideEffectsFixture = $fixtureDir . '/side-effects.json';

        $this->assertFileExists($responseFixture, sprintf('Missing golden response fixture for %s.', $handler));
        $this->assertFileExists($sideEffectsFixture, sprintf('Missing golden side-effects fixture for %s.', $handler));

        $actualResponse = $this->serializeResponse($response);
        $expectedResponse = rtrim((string) file_get_contents($responseFixture));
        $this->assertSame(
            $expectedResponse,
            $actualResponse,
            sprintf('Golden response drift for %s.', $handler)
        );

        $actualSideEffects = $this->serializeSideEffects($sideEffects);
        $expectedSideEffects = rtrim((string) file_get_contents($sideEffectsFixture));
        $this->assertSame(
            $expectedSideEffects,
            $actualSideEffects,
            sprintf('Golden side-effects drift for %s.', $handler)
        );
    }

    private function serializeResponse(WP_REST_Response|WP_Error $response): string
    {
        if (is_wp_error($response)) {
            $payload = [
                'type' => 'error',
                'code' => $response->get_error_code(),
                'message' => $response->get_error_message(),
                'data' => $response->get_error_data(),
            ];
        } else {
            $payload = [
                'type' => 'response',
                'status' => $response->get_status(),
                'data' => $response->get_data(),
            ];
        }

        $encoded = wp_json_encode($payload, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
        $this->assertIsString($encoded);

        return $encoded;
    }

    /**
     * @param array<string,mixed> $sideEffects
     */
    private function serializeSideEffects(array $sideEffects): string
    {
        $encoded = wp_json_encode($sideEffects, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
        $this->assertIsString($encoded);

        return $encoded;
    }
}
