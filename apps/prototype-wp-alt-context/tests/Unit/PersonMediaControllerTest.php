<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

require_once __DIR__ . '/../../src/api/class-person-media-controller.php';

use AltContext\Api\PersonMediaController;
use AltContext\Api\PersonMediaRowsSource;
use AltContext\Tests\TestCase;
use WP_Error;
use WP_REST_Request;
use WP_REST_Response;

/**
 * @covers \AltContext\Api\PersonMediaController
 */
class PersonMediaControllerTest extends TestCase
{
    public function testRoutesSharePermissionCallback(): void
    {
        $permission = static fn () => false;
        (new PersonMediaController())->register_routes($permission);

        $this->assertCount(1, $GLOBALS['__ac_rest_routes']);
        $route = $GLOBALS['__ac_rest_routes'][0];
        $this->assertSame('acx/v1', $route['namespace']);
        $this->assertSame('/roster/persons/(?P<id>[1-9][0-9]*)/media', $route['route']);
        $this->assertSame('GET', $route['args']['methods']);
        $this->assertSame($permission, $route['args']['permission_callback']);
    }

    public function testUnknownPersonReturns404AndDoesNotQueryMedia(): void
    {
        $source = $this->source();
        $controller = new PersonMediaController($source);

        $result = $controller->get_media($this->mediaRequest(['id' => 99]));

        $this->assertSame(404, $result->get_error_data()['status']);
        $this->assertSame('acx_person_not_found', $result->get_error_code());
        $this->assertSame([], $source->calls);
    }

    public function testPersonOnOtherTenantReturns404(): void
    {
        $this->seedPerson(7, 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb');
        $source = $this->source([[
            'total_count' => 1,
            'identity_uuid' => 'id-1',
            'attachment_id' => 22,
            'cluster_uuid' => 'cluster-1',
        ]]);

        $result = (new PersonMediaController($source))->get_media($this->mediaRequest(['id' => 7]));

        $this->assertSame(404, $result->get_error_data()['status']);
        $this->assertSame([], $source->calls);
    }

    public function testPagingReadsTotalFromQueryNotPhpCount(): void
    {
        $this->seedPerson(7);
        $GLOBALS['__ac_attachment_urls'][22] = 'https://example.test/media/22.jpg';
        $GLOBALS['__ac_attachment_urls'][23] = 'https://example.test/media/23.jpg';
        $source = $this->source([
            [
                'total_count' => 5,
                'identity_uuid' => 'id-1',
                'attachment_id' => 22,
                'cluster_uuid' => 'cluster-a',
                'bbox_json' => '{"pixels":{"x":1,"y":2,"width":3,"height":4}}',
                'similarity' => 0.91,
            ],
            [
                'total_count' => 5,
                'identity_uuid' => 'id-2',
                'attachment_id' => 23,
                'cluster_uuid' => 'cluster-a',
                'bbox_json' => null,
            ],
        ]);

        $response = (new PersonMediaController($source))->get_media(
            $this->mediaRequest(['id' => 7, 'limit' => 2, 'offset' => 0])
        );

        $this->assertInstanceOf(WP_REST_Response::class, $response);
        $this->assertSame(200, $response->get_status());
        $data = $response->get_data();
        $this->assertSame(2, $data['limit']);
        $this->assertSame(0, $data['offset']);
        $this->assertSame(5, $data['total']);
        $this->assertTrue($data['truncated']);
        $this->assertCount(2, $data['media']);
        $this->assertSame([
            'identity_id' => 'id-1',
            'media_id' => 22,
            'media_url' => 'https://example.test/media/22.jpg',
            'bbox' => ['x' => 1, 'y' => 2, 'width' => 3, 'height' => 4],
            'similarity' => 0.91,
            'cluster_id' => 'cluster-a',
        ], $data['media'][0]);
        $this->assertArrayNotHasKey('total_count', $data['media'][0]);
        $this->assertSame([
            'tenant_id' => self::currentTenantId(),
            'person_id' => 7,
            'limit' => 2,
            'offset' => 0,
        ], $source->calls[0]);
    }

    public function testEmptyFirstPageIs200WithTotalZero(): void
    {
        $this->seedPerson(7);
        $source = $this->source([]);

        $response = (new PersonMediaController($source))->get_media(
            $this->mediaRequest(['id' => 7, 'limit' => 50])
        );

        $this->assertInstanceOf(WP_REST_Response::class, $response);
        $data = $response->get_data();
        $this->assertSame([], $data['media']);
        $this->assertSame(50, $data['limit']);
        $this->assertSame(0, $data['offset']);
        $this->assertSame(0, $data['total']);
        $this->assertFalse($data['truncated']);
    }

    public function testMissingTotalCountOnNonEmptyPageFailsClosed(): void
    {
        $this->seedPerson(7);
        $source = $this->source([
            ['identity_uuid' => 'id-1', 'attachment_id' => 22, 'cluster_uuid' => 'cluster-a'],
            ['identity_uuid' => 'id-2', 'attachment_id' => 23, 'cluster_uuid' => 'cluster-a'],
        ]);

        $result = (new PersonMediaController($source))->get_media($this->mediaRequest(['id' => 7]));

        $this->assertInstanceOf(WP_Error::class, $result);
        $this->assertSame('invalid_person_media_envelope', $result->get_error_code());
        $this->assertSame(502, $result->get_error_data()['status']);
    }

    public function testMissingTotalCountOnLaterEmptyPageFailsClosed(): void
    {
        $this->seedPerson(7);
        $source = $this->source([]);

        $result = (new PersonMediaController($source))->get_media(
            $this->mediaRequest(['id' => 7, 'offset' => 50])
        );

        $this->assertSame('invalid_person_media_envelope', $result->get_error_code());
        $this->assertSame(502, $result->get_error_data()['status']);
    }

    public function testTenantIdQueryParamDoesNotOverrideServerTenant(): void
    {
        $this->seedPerson(7);
        $source = $this->source([
            ['total_count' => 0],
        ]);
        $request = $this->mediaRequest(['id' => 7, 'tenant_id' => 'untrusted']);

        (new PersonMediaController($source))->get_media($request);

        $this->assertSame(self::currentTenantId(), $source->calls[0]['tenant_id']);
        $this->assertSame('untrusted', $request->get_param('tenant_id'));
    }

    public function testInvalidLimitAndOffsetRejected(): void
    {
        $this->seedPerson(7);
        $source = $this->source();
        $controller = new PersonMediaController($source);

        foreach ([0, -1, 501, 'x'] as $limit) {
            $result = $controller->get_media($this->mediaRequest(['id' => 7, 'limit' => $limit]));
            $this->assertSame(400, $result->get_error_data()['status'], (string) json_encode($limit));
            $this->assertSame('invalid_limit', $result->get_error_code());
        }

        $result = $controller->get_media($this->mediaRequest(['id' => 7, 'offset' => -1]));
        $this->assertSame(400, $result->get_error_data()['status']);
        $this->assertSame('invalid_offset', $result->get_error_code());
        $this->assertSame([], $source->calls);
    }

    public function testInvalidPersonIdRejected(): void
    {
        $source = $this->source();
        $controller = new PersonMediaController($source);
        foreach ([null, 0, -1, 1.5, '2x', []] as $id) {
            $request = new WP_REST_Request('GET');
            $request->set_param('id', $id);
            $this->assertSame(400, $controller->get_media($request)->get_error_data()['status']);
        }
        $this->assertSame([], $source->calls);
    }

    public function testDefaultSourceQueryUsesWindowCountAndTenantScope(): void
    {
        $this->seedPerson(7);
        global $wpdb;
        $captured = [];
        $wpdb->onGetResults = static function (string $sql) use (&$captured): array {
            $captured[] = $sql;
            return [[
                'total_count' => 1,
                'identity_uuid' => 'id-1',
                'attachment_id' => 22,
                'cluster_uuid' => 'cluster-a',
                'bbox_json' => null,
                'thumb_path' => '',
            ]];
        };
        $GLOBALS['__ac_attachment_urls'][22] = 'https://example.test/media/22.jpg';

        $response = (new PersonMediaController())->get_media(
            $this->mediaRequest(['id' => 7, 'limit' => 10, 'offset' => 2])
        );

        $this->assertInstanceOf(WP_REST_Response::class, $response);
        $this->assertNotSame([], $captured);
        $sql = $captured[0];
        $this->assertStringContainsString('COUNT(*) OVER() AS total_count', $sql);
        $this->assertStringContainsString('tenant_id', $sql);
        $this->assertStringContainsString("'" . addslashes(self::currentTenantId()) . "'", $sql);
        $this->assertStringContainsString('person_id', $sql);
        $this->assertStringContainsString('LIMIT 10 OFFSET 2', $sql);
        $this->assertSame(1, $response->get_data()['total']);
        $this->assertFalse($response->get_data()['truncated']);
    }

    /**
     * @param array<int, array<string, mixed>> $rows
     */
    private function source(array $rows = []): PersonMediaRowsSource
    {
        return new class ($rows) implements PersonMediaRowsSource {
            /** @var list<array{tenant_id:string,person_id:int,limit:int,offset:int}> */
            public array $calls = [];

            /**
             * @param array<int, array<string, mixed>> $rows
             */
            public function __construct(private array $rows)
            {
            }

            public function list_projected_cluster_rows_by_person(
                string $tenant_id,
                int $person_id,
                int $limit,
                int $offset
            ): array {
                $this->calls[] = compact('tenant_id', 'person_id', 'limit', 'offset');
                return $this->rows;
            }
        };
    }

    /**
     * @param array<string, mixed> $params
     */
    private function mediaRequest(array $params): WP_REST_Request
    {
        $request = new WP_REST_Request('GET', '/acx/v1/roster/persons/' . (string) ($params['id'] ?? 7) . '/media');
        foreach ($params as $key => $value) {
            $request->set_param($key, $value);
        }
        return $request;
    }

    private function seedPerson(int $id, ?string $tenant_id = null): void
    {
        global $wpdb;
        $wpdb->tableRows['wp_acx_persons'][] = [
            'id' => $id,
            'tenant_id' => $tenant_id ?? self::currentTenantId(),
            'name' => 'Ada',
            'person_uuid' => 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
        ];
    }
}
