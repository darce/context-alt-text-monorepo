<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Api\Api;
use AltContext\Support\LifecycleManager;
use AltContext\Tests\TestCase;
use WP_REST_Request;
use WP_REST_Response;

/**
 * UXW2-4-R6-01: acx_persons uniqueness is tenant-scoped.
 *
 * @covers \AltContext\Api\Api
 * @covers \AltContext\Support\LifecycleManager
 */
class PersonTenantScopedUniquenessTest extends TestCase
{
    private Api $api;

    protected function setUp(): void
    {
        parent::setUp();
        $this->api = new Api();
        $this->setUserCapability('manage_options', true);
    }

    public function testCreatePersonAllowsSameNormalizedNameAcrossTenantsAndDedupesWithinTenant(): void
    {
        $this->api->register_routes();
        global $wpdb;

        $tenantA = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
        $tenantB = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';

        $this->setOption('acx_recognition_tenant_id', $tenantA);
        $requestA = new WP_REST_Request('POST', '/acx/v1/roster/persons');
        $requestA->set_param('name', 'Jane Doe');
        $requestA->set_param('tags', []);
        $responseA = $this->api->create_person($requestA);

        $this->assertInstanceOf(WP_REST_Response::class, $responseA);
        $this->assertSame(201, $responseA->get_status());
        $dataA = $responseA->get_data();
        $this->assertIsArray($dataA);
        $this->assertArrayHasKey('id', $dataA);
        $idA = $dataA['id'];

        $this->setOption('acx_recognition_tenant_id', $tenantB);
        $requestB = new WP_REST_Request('POST', '/acx/v1/roster/persons');
        $requestB->set_param('name', 'Jane Doe');
        $requestB->set_param('tags', []);
        $responseB = $this->api->create_person($requestB);

        $this->assertInstanceOf(
            WP_REST_Response::class,
            $responseB,
            'tenant B creating Jane Doe must not 409 against tenant A (cross-tenant existence oracle)'
        );
        $this->assertSame(201, $responseB->get_status());
        $dataB = $responseB->get_data();
        $this->assertIsArray($dataB);
        $this->assertArrayHasKey('id', $dataB);
        $idB = $dataB['id'];
        $this->assertNotSame($idA, $idB, 'tenant B Jane Doe must be a distinct person id');

        $requestBDup = new WP_REST_Request('POST', '/acx/v1/roster/persons');
        $requestBDup->set_param('name', 'Jane Doe');
        $responseBDup = $this->api->create_person($requestBDup);

        $this->assertInstanceOf(\WP_Error::class, $responseBDup);
        $this->assertSame(409, $responseBDup->get_error_data()['status']);
        $this->assertSame('acx_person_exists', $responseBDup->get_error_code());

        $personsSql = (new LifecycleManager())
            ->build_projection_schema_statements((string) $wpdb->prefix, '')['acx_persons'] ?? '';
        $this->assertIsString($personsSql);
        $this->assertNotSame('', $personsSql);
        $this->assertMatchesRegularExpression(
            '/UNIQUE\s+KEY\s+idx_tenant_normalized_name\s*\(\s*tenant_id\s*,\s*normalized_name\s*\)/i',
            $personsSql,
            'UNIQUE(normalized_name) alone would reject tenant B Jane Doe after tenant A created it'
        );
    }

    public function testMaybeUpgradeDropsLegacyGlobalNormalizedNameUniqueIndex(): void
    {
        global $wpdb;

        $this->setOption('acx_version', '0.0.1-stale');
        $GLOBALS['__ac_error_log'] = [];
        $wpdb->tableIndexes['wp_acx_persons'] = ['idx_normalized_name'];

        (new LifecycleManager())->maybe_upgrade();

        $drop = null;
        foreach ($wpdb->queries as $query) {
            if (preg_match('/DROP\s+INDEX\s+`idx_normalized_name`(?:\s|$)/i', $query) === 1) {
                $drop = $query;
                break;
            }
        }
        $this->assertNotNull($drop, 'dbDelta never DROP INDEXes; must DROP legacy idx_normalized_name');
        $this->assertStringContainsString('wp_acx_persons', $drop);
        $this->assertSame(ACX_VERSION, get_option('acx_version'), 'legacy unique drop must not prevent stamp');
        $this->assertNotContains(
            'idx_normalized_name',
            $wpdb->tableIndexes['wp_acx_persons'] ?? [],
            'legacy global unique must be removed from the achieved index set'
        );
        $this->assertStringContainsString('idx_normalized_name', implode("\n", $this->getErrorLog()));
    }
}
