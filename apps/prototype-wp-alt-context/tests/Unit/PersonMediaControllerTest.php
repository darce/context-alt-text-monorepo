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
        $this->assertArrayHasKey('with_person_ids', $route['args']['args']);
        $this->assertSame('array', $route['args']['args']['with_person_ids']['type']);
        $this->assertFalse($route['args']['args']['with_person_ids']['required']);
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
            'with_person_ids' => [],
        ], $source->calls[0]);
    }

    public function testDuplicateDetectionsOnOneAttachmentReturnOnePhoto(): void
    {
        $this->seedPerson(7);
        $GLOBALS['__ac_attachment_urls'][22] = 'https://example.test/media/22.jpg';
        $source = $this->source([[
            'total_count' => 1,
            'identity_uuid' => 'id-earlier',
            'attachment_id' => 22,
            'cluster_uuid' => 'cluster-a',
        ]]);

        $response = (new PersonMediaController($source))->get_media(
            $this->mediaRequest(['id' => 7, 'limit' => 50, 'offset' => 0])
        );

        $this->assertInstanceOf(WP_REST_Response::class, $response);
        $this->assertSame(200, $response->get_status());
        $data = $response->get_data();
        $this->assertCount(1, $data['media']);
        $this->assertSame(22, $data['media'][0]['media_id']);
        $this->assertSame('id-earlier', $data['media'][0]['identity_id']);
        $this->assertSame(1, $data['total']);
        $this->assertFalse($data['truncated']);
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
        $this->assertStringContainsString('ROW_NUMBER() OVER (PARTITION BY m.attachment_id ORDER BY m.assigned_at ASC, m.identity_uuid ASC)', $sql);
        $this->assertStringContainsString('tenant_id', $sql);
        $this->assertStringContainsString("'" . addslashes(self::currentTenantId()) . "'", $sql);
        $this->assertStringContainsString('person_id', $sql);
        $this->assertStringContainsString('LIMIT 10 OFFSET 2', $sql);
        $this->assertStringContainsString('ORDER BY assigned_at ASC, identity_uuid LIMIT 10 OFFSET 2', $sql);
        $this->assertStringNotContainsString('HAVING COUNT(DISTINCT', $sql);
        $rnPos = strpos($sql, 'rn = 1');
        $limitPos = strpos($sql, 'LIMIT 10 OFFSET 2');
        $this->assertNotFalse($rnPos);
        $this->assertNotFalse($limitPos);
        $this->assertLessThan($limitPos, $rnPos);
        $this->assertSame(1, $response->get_data()['total']);
        $this->assertFalse($response->get_data()['truncated']);
    }

    public function testIdentifierPlaceholderCompatPreparesTenantScopedQueries(): void
    {
        global $wpdb;
        $original = $wpdb;
        $wpdb = new class extends \WPDBStub {
            public function has_cap(string $cap): bool
            {
                return false;
            }
        };

        try {
            $this->seedPerson(7);
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
            $this->assertSame(200, $response->get_status());
            $this->assertSame(1, $response->get_data()['total']);
            $this->assertCount(1, $response->get_data()['media']);
            $this->assertNotSame([], $wpdb->queries);
            $this->assertNotSame([], $captured);

            $personSql = $wpdb->queries[0];
            $mediaSql = $captured[0];
            foreach ([$personSql, $mediaSql] as $sql) {
                $this->assertStringNotContainsString('%i', $sql);
                $this->assertStringContainsString('tenant_id', $sql);
                $this->assertStringContainsString("'" . addslashes(self::currentTenantId()) . "'", $sql);
            }
            $this->assertStringContainsString('`wp_acx_persons`', $personSql);
            $this->assertStringContainsString('`wp_acx_identity_members`', $mediaSql);
            $this->assertStringContainsString('`wp_acx_clusters`', $mediaSql);
            $this->assertStringContainsString('person_id', $mediaSql);
        } finally {
            $wpdb = $original;
        }
    }

    public function testUnavailableAdapterReturns500NotEmpty200(): void
    {
        global $wpdb;
        $original = $wpdb;
        $this->seedPerson(7);
        $wpdb = new class ($original) {
            public string $prefix;
            public string $last_error = '';

            public function __construct(private object $inner)
            {
                $this->prefix = $inner->prefix;
            }

            public function has_cap(string $cap): bool
            {
                return $this->inner->has_cap($cap);
            }

            public function prepare(string $query, ...$args): string
            {
                return $this->inner->prepare($query, ...$args);
            }

            public function get_row($query, $output = \ARRAY_A)
            {
                return $this->inner->get_row($query, $output);
            }
        };

        try {
            $result = (new PersonMediaController())->get_media($this->mediaRequest(['id' => 7]));

            $this->assertInstanceOf(WP_Error::class, $result);
            $this->assertNotInstanceOf(WP_REST_Response::class, $result);
            $this->assertSame('acx_projection_query_failed', $result->get_error_code());
            $this->assertSame(500, $result->get_error_data()['status']);
            $this->assertStringContainsString('get_person_media', $result->get_error_message());
        } finally {
            $wpdb = $original;
        }
    }

    public function testThumbPathFallbackNullsBbox(): void
    {
        $this->seedPerson(7);
        $source = $this->source([[
            'total_count' => 1,
            'identity_uuid' => 'id-1',
            'attachment_id' => 22,
            'cluster_uuid' => 'cluster-a',
            'bbox_json' => '{"pixels":{"x":1,"y":2,"width":3,"height":4}}',
            'thumb_path' => 'https://example.test/thumbs/face.jpg',
        ]]);

        $response = (new PersonMediaController($source))->get_media($this->mediaRequest(['id' => 7]));

        $this->assertInstanceOf(WP_REST_Response::class, $response);
        $this->assertSame(200, $response->get_status());
        $item = $response->get_data()['media'][0];
        $this->assertSame('https://example.test/thumbs/face.jpg', $item['media_url']);
        $this->assertNull($item['bbox']);
    }

    public function testInvalidWithPersonIdsRejected(): void
    {
        $this->seedPerson(7);
        $source = $this->source();
        $controller = new PersonMediaController($source);

        foreach ([0, -1, 1.5, 'x', '2x', [0], [-1], ['x'], [[8]], true, false, new \stdClass()] as $value) {
            $result = $controller->get_media($this->mediaRequest(['id' => 7, 'with_person_ids' => $value]));
            $this->assertInstanceOf(WP_Error::class, $result, (string) json_encode($value));
            $this->assertSame(400, $result->get_error_data()['status'], (string) json_encode($value));
            $this->assertSame('invalid_with_person_ids', $result->get_error_code());
        }

        $result = $controller->get_media(
            $this->mediaRequest(['id' => 7, 'with_person_ids' => [1, 2, 3, 4, 5, 6]])
        );
        $this->assertSame(400, $result->get_error_data()['status']);
        $this->assertSame('invalid_with_person_ids', $result->get_error_code());
        $this->assertSame([], $source->calls);
    }

    public function testEmptyWithPersonIdsDoesNotFilter(): void
    {
        $this->seedPerson(7);
        $source = $this->source([]);

        $response = (new PersonMediaController($source))->get_media(
            $this->mediaRequest(['id' => 7, 'with_person_ids' => []])
        );

        $this->assertInstanceOf(WP_REST_Response::class, $response);
        $this->assertSame([], $source->calls[0]['with_person_ids']);
    }

    public function testSingleWithPersonIdIsAccepted(): void
    {
        $this->seedPerson(7);
        $source = $this->source([[
            'total_count' => 1,
            'identity_uuid' => 'id-1',
            'attachment_id' => 22,
            'cluster_uuid' => 'cluster-a',
        ]]);

        $response = (new PersonMediaController($source))->get_media(
            $this->mediaRequest(['id' => 7, 'with_person_ids' => 8])
        );

        $this->assertInstanceOf(WP_REST_Response::class, $response);
        $this->assertSame([8], $source->calls[0]['with_person_ids']);
    }

    public function testWithPersonIdsDeduplicatesWithinMax(): void
    {
        $this->seedPerson(7);
        $source = $this->source([['total_count' => 0]]);

        (new PersonMediaController($source))->get_media(
            $this->mediaRequest(['id' => 7, 'with_person_ids' => [8, 8, 9]])
        );

        $this->assertSame([8, 9], $source->calls[0]['with_person_ids']);
    }

    public function testWithPersonIdsIntersectionUsesQueryTotal(): void
    {
        $this->seedPerson(7);
        $GLOBALS['__ac_attachment_urls'][22] = 'https://example.test/media/22.jpg';
        $source = $this->source([[
            'total_count' => 3,
            'identity_uuid' => 'id-1',
            'attachment_id' => 22,
            'cluster_uuid' => 'cluster-a',
        ]]);

        $response = (new PersonMediaController($source))->get_media(
            $this->mediaRequest(['id' => 7, 'limit' => 2, 'offset' => 0, 'with_person_ids' => [8, 9]])
        );

        $this->assertInstanceOf(WP_REST_Response::class, $response);
        $data = $response->get_data();
        $this->assertSame(2, $data['limit']);
        $this->assertSame(0, $data['offset']);
        $this->assertSame(3, $data['total']);
        $this->assertTrue($data['truncated']);
        $this->assertCount(1, $data['media']);
        $this->assertSame(22, $data['media'][0]['media_id']);
        $this->assertSame([
            'tenant_id' => self::currentTenantId(),
            'person_id' => 7,
            'limit' => 2,
            'offset' => 0,
            'with_person_ids' => [8, 9],
        ], $source->calls[0]);
    }

    public function testWithPersonIdsIntersectionIsComputedInSql(): void
    {
        $this->seedPerson(7);
        global $wpdb;
        $captured = [];
        $wpdb->onGetResults = static function (string $sql) use (&$captured): array {
            $captured[] = $sql;
            return [[
                'total_count' => 4,
                'identity_uuid' => 'id-1',
                'attachment_id' => 22,
                'cluster_uuid' => 'cluster-a',
                'bbox_json' => null,
                'thumb_path' => '',
            ]];
        };
        $GLOBALS['__ac_attachment_urls'][22] = 'https://example.test/media/22.jpg';

        $response = (new PersonMediaController())->get_media(
            $this->mediaRequest(['id' => 7, 'limit' => 10, 'offset' => 2, 'with_person_ids' => [8, 9]])
        );

        $this->assertInstanceOf(WP_REST_Response::class, $response);
        $this->assertSame(4, $response->get_data()['total']);
        $this->assertCount(1, $captured);
        $sql = $captured[0];
        $this->assertStringContainsString('COUNT(*) OVER() AS total_count', $sql);
        $this->assertStringContainsString('ROW_NUMBER() OVER (PARTITION BY m.attachment_id ORDER BY m.assigned_at ASC, m.identity_uuid ASC)', $sql);
        $this->assertStringContainsString('m.attachment_id', $sql);
        $this->assertStringContainsString('GROUP BY mx.attachment_id', $sql);
        $this->assertStringContainsString('HAVING COUNT(DISTINCT cx.person_id) = 3', $sql);
        $this->assertStringContainsString('cx.person_id IN (7, 8, 9)', $sql);
        $this->assertStringContainsString('c.person_id = 7', $sql);
        $this->assertStringContainsString('`wp_acx_identity_members`', $sql);
        $this->assertStringContainsString('`wp_acx_clusters`', $sql);
        $this->assertStringContainsString("'" . addslashes(self::currentTenantId()) . "'", $sql);
        $this->assertStringContainsString('LIMIT 10 OFFSET 2', $sql);
        $this->assertStringContainsString('ORDER BY assigned_at ASC, identity_uuid LIMIT 10 OFFSET 2', $sql);
        $this->assertStringNotContainsString('%i', $sql);
        $havingPos = strpos($sql, 'HAVING COUNT(DISTINCT cx.person_id) = 3');
        $rnPos = strpos($sql, 'rn = 1');
        $limitPos = strpos($sql, 'LIMIT 10 OFFSET 2');
        $this->assertNotFalse($havingPos);
        $this->assertNotFalse($rnPos);
        $this->assertNotFalse($limitPos);
        $this->assertLessThan($rnPos, $havingPos);
        $this->assertLessThan($limitPos, $rnPos);
    }

    /**
     * @param array<int, array<string, mixed>> $rows
     */
    private function source(array $rows = []): PersonMediaRowsSource
    {
        return new class ($rows) implements PersonMediaRowsSource {
            /** @var list<array{tenant_id:string,person_id:int,limit:int,offset:int,with_person_ids:array<int,int>}> */
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
                int $offset,
                array $with_person_ids = []
            ): array {
                $this->calls[] = compact('tenant_id', 'person_id', 'limit', 'offset', 'with_person_ids');
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
