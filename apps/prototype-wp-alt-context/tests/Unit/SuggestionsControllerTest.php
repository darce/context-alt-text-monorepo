<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Api\SuggestionsController;
use AltContext\Tests\TestCase;
use WP_REST_Request;

/**
 * @covers \AltContext\Api\SuggestionsController
 */
class SuggestionsControllerTest extends TestCase
{
    private SuggestionsController $controller;

    protected function setUp(): void
    {
        parent::setUp();
        $this->setOption('acx_recognition_url', 'http://localhost:8000');
        $this->controller = new SuggestionsController();
    }

    public function testRegisterRoutesIncludesSuggestionEndpoints(): void
    {
        $this->controller->register_routes();

        $routes = array_map(
            static fn (array $definition): string => $definition['route'],
            $GLOBALS['__ac_rest_routes']
        );

        $this->assertContains('/recognition/suggestions', $routes);
        $this->assertContains('/recognition/suggestions/merge', $routes);
        $this->assertContains('/recognition/suggestions/(?P<suggestion_id>[a-f0-9-]+)/accept', $routes);
        $this->assertContains('/recognition/suggestions/merge/(?P<suggestion_id>[a-f0-9-]+)/accept', $routes);
        $this->assertContains('/recognition/suggestions/(?P<suggestion_id>[a-f0-9-]+)/reject', $routes);
        $this->assertContains('/recognition/suggestions/merge/(?P<suggestion_id>[a-f0-9-]+)/reject', $routes);
    }

    public function testRegisterRoutesDeclaresBatchIdentitySuggestionsWithStringIdentityIds(): void
    {
        $this->controller->register_routes();

        $definitions = array_values(array_filter(
            $GLOBALS['__ac_rest_routes'],
            static fn (array $definition): bool => '/recognition/identities/suggestions' === $definition['route']
        ));

        $this->assertCount(1, $definitions);
        $args = $definitions[0]['args']['args'] ?? [];

        // Guard: 'array' would trigger rest_sanitize_array -> wp_parse_list, splitting
        // the comma-joined scalar so add_query_arg emits identity_ids[0]=..., which
        // binds nothing on the FastAPI side. Must stay 'string'.
        $this->assertSame('string', $args['identity_ids']['type'] ?? null);
        $this->assertSame('integer', $args['top_k']['type'] ?? null);
    }

    public function testGetIdentitiesSuggestionsForwardsUnchangedScalarIdentityIdsAndTopK(): void
    {
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => '{"matches":{}}',
        ]);

        // 60 ids: proves the comma-joined scalar survives the hop intact past the
        // $_GET last-wins and add_query_arg array-syntax traps.
        $identityIds = implode(',', array_map(
            static fn (int $i): string => sprintf('aaaaaaaa-bbbb-cccc-dddd-%012d', $i),
            range(1, 60)
        ));

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/identities/suggestions');
        $request->set_param('identity_ids', $identityIds);
        $request->set_param('top_k', 1);

        $response = $this->controller->get_identities_suggestions($request);

        $this->assertInstanceOf(\WP_REST_Response::class, $response);
        $this->assertSame(200, $response->get_status());

        $calls = $this->getHttpCalls();
        $this->assertCount(1, $calls);
        $this->assertStringContainsString('/recognition/identities/suggestions', $calls[0]['url']);
        // No PHP-array query syntax on the wire.
        $this->assertStringNotContainsString('identity_ids%5B', $calls[0]['url']);
        $this->assertStringNotContainsString('identity_ids[', $calls[0]['url']);

        $query = [];
        $queryString = parse_url($calls[0]['url'], PHP_URL_QUERY);
        parse_str(is_string($queryString) ? $queryString : '', $query);

        $this->assertSame($identityIds, $query['identity_ids'] ?? null);
        $this->assertSame('1', (string) ($query['top_k'] ?? ''));
        $this->assertNotEmpty($query['tenant_id'] ?? '');
    }

    public function testGetIdentitySuggestionsForwardsNoThresholdParam(): void
    {
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => '{"matches":[]}',
        ]);

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/identities/abc123/suggestions');
        $request->set_param('identity_id', 'abc123');
        $request->set_param('top_k', 5);
        // Even an explicit client threshold must not reach the wire: the recognition
        // route accepts only min_confidence, so the param never bound (0b-5).
        $request->set_param('threshold', 0.42);

        $response = $this->controller->get_identity_suggestions($request);

        $this->assertInstanceOf(\WP_REST_Response::class, $response);
        $calls = $this->getHttpCalls();
        $this->assertCount(1, $calls);
        $this->assertStringContainsString('/recognition/identities/abc123/suggestions', $calls[0]['url']);

        $query = [];
        $queryString = parse_url($calls[0]['url'], PHP_URL_QUERY);
        parse_str(is_string($queryString) ? $queryString : '', $query);

        $this->assertArrayNotHasKey('threshold', $query);
        $this->assertSame('5', (string) ($query['top_k'] ?? ''));
        $this->assertNotEmpty($query['tenant_id'] ?? '');
    }

    public function testGetIdentitiesSuggestionsRequiresIdentityIds(): void
    {
        $request = new WP_REST_Request('GET', '/acx/v1/recognition/identities/suggestions');

        $response = $this->controller->get_identities_suggestions($request);

        $this->assertInstanceOf(\WP_Error::class, $response);
        $this->assertSame('missing_identity_ids', $response->get_error_code());
    }

    public function testGetIdentitiesSuggestionsReturnsEmptyMatchesWhenProxyUnavailable(): void
    {
        $this->queueHttpResponse(new \WP_Error('proxy_failed', 'Proxy failure.'));
        $this->queueHttpResponse(new \WP_Error('proxy_failed', 'Proxy failure.'));
        $this->queueHttpResponse(new \WP_Error('proxy_failed', 'Proxy failure.'));

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/identities/suggestions');
        $request->set_param('identity_ids', 'aaaaaaaa-bbbb-cccc-dddd-000000000001');

        $response = $this->controller->get_identities_suggestions($request);

        $this->assertInstanceOf(\WP_REST_Response::class, $response);
        $this->assertSame(200, $response->get_status());
        $data = $response->get_data();
        // Keyed-by-id envelope: empty mapping must serialize as {} rather than [].
        $this->assertEquals(new \stdClass(), $data['matches'] ?? null);
        // BR-08: the offline path must carry data_source so the UI distinguishes
        // "unreachable" from a genuine empty result. Transport error => unavailable.
        $this->assertSame('unavailable', $data['data_source'] ?? null);
    }

    /**
     * R4G-BR-09: refused 3xx is endpoint_error, not unavailable.
     */
    public function testGetIdentitiesSuggestionsReturnsEndpointErrorOnUnexpectedRedirect(): void
    {
        $this->queueHttpResponse([
            'response' => ['code' => 302, 'message' => 'Found'],
            'headers' => ['Location' => 'https://attacker.example/collect'],
            'body' => '',
        ]);

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/identities/suggestions');
        $request->set_param('identity_ids', 'aaaaaaaa-bbbb-cccc-dddd-000000000001');

        $response = $this->controller->get_identities_suggestions($request);

        $this->assertInstanceOf(\WP_REST_Response::class, $response);
        $this->assertSame(200, $response->get_status());
        $data = $response->get_data();
        $this->assertEquals(new \stdClass(), $data['matches'] ?? null);
        $this->assertSame(
            'endpoint_error',
            $data['data_source'] ?? null,
            'refused 3xx must not be laundered as unavailable'
        );
    }

    /**
     * R6L-BR-01: singular get_identity_suggestions must classify refused 3xx as
     * endpoint_error. List envelope — matches is [], not {}. Mirrors the plural
     * pin above. Goes red if is_proxy_redirect_refused is dropped from the
     * singular branch (~:240): the WP_Error then matches no branch and falls
     * through as a raw 502 recognition_unexpected_redirect.
     */
    public function testGetIdentitySuggestionsReturnsEndpointErrorOnUnexpectedRedirect(): void
    {
        $this->queueHttpResponse([
            'response' => ['code' => 302, 'message' => 'Found'],
            'headers' => ['Location' => 'https://attacker.example/collect'],
            'body' => '',
        ]);

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/identities/abc123/suggestions');
        $request->set_param('identity_id', 'abc123');

        $response = $this->controller->get_identity_suggestions($request);

        $this->assertInstanceOf(\WP_REST_Response::class, $response);
        $this->assertSame(200, $response->get_status());
        $data = $response->get_data();
        // List envelope for a single identity: empty matches is [], not {}.
        $this->assertSame([], $data['matches'] ?? null);
        $this->assertSame(
            'endpoint_error',
            $data['data_source'] ?? null,
            'refused 3xx on singular identity suggestions must not fall through to raw 502'
        );
    }

    public function testGetIdentitiesSuggestionsReturnsEndpointErrorWhenBackendReturns5xx(): void
    {
        $this->queueHttpResponse([
            'response' => ['code' => 500, 'message' => 'Internal Server Error'],
            'body' => '{"error":"boom"}',
        ]);
        $this->queueHttpResponse([
            'response' => ['code' => 500, 'message' => 'Internal Server Error'],
            'body' => '{"error":"boom"}',
        ]);
        $this->queueHttpResponse([
            'response' => ['code' => 500, 'message' => 'Internal Server Error'],
            'body' => '{"error":"boom"}',
        ]);

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/identities/suggestions');
        $request->set_param('identity_ids', 'aaaaaaaa-bbbb-cccc-dddd-000000000001');

        $response = $this->controller->get_identities_suggestions($request);

        $this->assertInstanceOf(\WP_REST_Response::class, $response);
        $this->assertSame(200, $response->get_status());
        $data = $response->get_data();
        // BR-08/BR-05: a reachable-but-erroring backend is endpoint_error, not unavailable.
        $this->assertEquals(new \stdClass(), $data['matches'] ?? null);
        $this->assertSame('endpoint_error', $data['data_source'] ?? null);
    }

    public function testGetIdentitiesSuggestionsPropagatesBackendOverloadedAs503(): void
    {
        $this->queueHttpResponse([
            'response' => ['code' => 503, 'message' => 'Service Unavailable'],
            'headers' => ['Retry-After' => '5'],
            'body' => '{"error":"database_unavailable","trace_id":"trace-1","path":"/recognition/identities/suggestions"}',
        ]);

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/identities/suggestions');
        $request->set_param('identity_ids', 'aaaaaaaa-bbbb-cccc-dddd-000000000001');

        $response = $this->controller->get_identities_suggestions($request);

        $this->assertInstanceOf(\WP_REST_Response::class, $response);
        $this->assertSame(503, $response->get_status());
        $this->assertSame(['error' => 'backend_overloaded', 'retry_after' => 5], $response->get_data());
    }

    public function testGetPendingSuggestionsForwardsLimitOffsetQuery(): void
    {
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => '[]',
        ]);

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/suggestions');
        $request->set_param('limit', 12);
        $request->set_param('offset', 7);

        $response = $this->controller->get_pending_suggestions($request);

        $this->assertInstanceOf(\WP_REST_Response::class, $response);
        $this->assertSame(200, $response->get_status());

        $calls = $this->getHttpCalls();
        $this->assertCount(1, $calls);

        $query = [];
        $queryString = parse_url($calls[0]['url'], PHP_URL_QUERY);
        parse_str(is_string($queryString) ? $queryString : '', $query);

        $this->assertSame('12', (string) ($query['limit'] ?? ''));
        $this->assertSame('7', (string) ($query['offset'] ?? ''));
        $this->assertNotEmpty($query['tenant_id'] ?? '');
        $this->assertSame(10, $calls[0]['args']['timeout'] ?? null);
    }

    public function testGetPendingSuggestionsReturnsEmptyPayloadWhenProxyUnavailable(): void
    {
        $this->queueHttpResponse(new \WP_Error('proxy_failed', 'Proxy failure.'));
        $this->queueHttpResponse(new \WP_Error('proxy_failed', 'Proxy failure.'));
        $this->queueHttpResponse(new \WP_Error('proxy_failed', 'Proxy failure.'));

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/suggestions');
        $request->set_param('limit', 25);
        $request->set_param('offset', 0);

        $response = $this->controller->get_pending_suggestions($request);

        $this->assertInstanceOf(\WP_REST_Response::class, $response);
        $this->assertSame(200, $response->get_status());
        $data = $response->get_data();
        $this->assertSame([], $data['suggestions'] ?? null);
        $this->assertArrayNotHasKey('total', $data);
        $this->assertSame(25, $data['limit'] ?? null);
        $this->assertSame(0, $data['offset'] ?? null);
        $this->assertSame('unavailable', $data['data_source'] ?? null);
    }

    /**
     * R5G-BR-01 / R4G-BR-09: refused 3xx on pending is endpoint_error, not unavailable.
     * Pins the is_proxy_redirect_refused branch so a reorder that drops it goes red.
     */
    public function testGetPendingSuggestionsReturnsEndpointErrorOnUnexpectedRedirect(): void
    {
        $this->queueHttpResponse([
            'response' => ['code' => 302, 'message' => 'Found'],
            'headers' => ['Location' => 'https://attacker.example/collect'],
            'body' => '',
        ]);

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/suggestions');
        $request->set_param('limit', 25);
        $request->set_param('offset', 0);

        $response = $this->controller->get_pending_suggestions($request);

        $this->assertInstanceOf(\WP_REST_Response::class, $response);
        $this->assertSame(200, $response->get_status());
        $data = $response->get_data();
        $this->assertSame([], $data['suggestions'] ?? null);
        $this->assertSame(
            'endpoint_error',
            $data['data_source'] ?? null,
            'refused 3xx on pending must not be laundered as unavailable'
        );
    }

    public function testGetPendingSuggestionsReturnsEndpointErrorPayloadWhenBackendFails(): void
    {
        $this->queueHttpResponse([
            'response' => ['code' => 500, 'message' => 'Internal Server Error'],
            'body' => '{"error":"backend_failure"}',
        ]);

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/suggestions');
        $request->set_param('limit', 25);
        $request->set_param('offset', 0);

        $response = $this->controller->get_pending_suggestions($request);

        $this->assertInstanceOf(\WP_REST_Response::class, $response);
        $this->assertSame(200, $response->get_status());
        $data = $response->get_data();
        $this->assertSame([], $data['suggestions'] ?? null);
        $this->assertArrayNotHasKey('total', $data);
        $this->assertSame(25, $data['limit'] ?? null);
        $this->assertSame(0, $data['offset'] ?? null);
        $this->assertSame('endpoint_error', $data['data_source'] ?? null);
    }

    public function testBackendOverloadedDetectionMatchesOnlyHttp503Responses(): void
    {
        $controller = new class() extends SuggestionsController {
            public function detectBackendOverloaded($response): bool
            {
                return $this->is_backend_overloaded($response);
            }
        };

        $this->assertTrue($controller->detectBackendOverloaded(new \WP_REST_Response([], 503)));
        $this->assertFalse($controller->detectBackendOverloaded(new \WP_REST_Response([], 500)));
        $this->assertFalse($controller->detectBackendOverloaded(new \WP_Error('proxy_failed', 'Proxy failure.')));
    }

    public function testGetPendingSuggestionsPropagatesBackendOverloadedAs503(): void
    {
        $this->queueHttpResponse([
            'response' => ['code' => 503, 'message' => 'Service Unavailable'],
            'headers' => ['Retry-After' => '5'],
            'body' => '{"error":"database_unavailable","trace_id":"trace-1","path":"/recognition/suggestions"}',
        ]);

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/suggestions');
        $request->set_param('limit', 25);
        $request->set_param('offset', 0);

        $response = $this->controller->get_pending_suggestions($request);

        $this->assertInstanceOf(\WP_REST_Response::class, $response);
        $this->assertSame(503, $response->get_status());
        $this->assertSame(['error' => 'backend_overloaded', 'retry_after' => 5], $response->get_data());
        $this->assertSame('5', $response->get_headers()['Retry-After'] ?? null);
    }

    public function testGetPendingMergeSuggestionsReturnsEmptyPayloadWhenProxyUnavailable(): void
    {
        $this->queueHttpResponse(new \WP_Error('proxy_failed', 'Proxy failure.'));
        $this->queueHttpResponse(new \WP_Error('proxy_failed', 'Proxy failure.'));
        $this->queueHttpResponse(new \WP_Error('proxy_failed', 'Proxy failure.'));

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/suggestions/merge');
        $request->set_param('limit', 10);
        $request->set_param('offset', 0);

        $response = $this->controller->get_pending_merge_suggestions($request);

        $this->assertInstanceOf(\WP_REST_Response::class, $response);
        $this->assertSame(200, $response->get_status());
        $data = $response->get_data();
        $this->assertSame([], $data['suggestions'] ?? null);
        $this->assertArrayNotHasKey('total', $data);
        $this->assertSame(10, $data['limit'] ?? null);
        $this->assertSame(0, $data['offset'] ?? null);
        $this->assertSame('unavailable', $data['data_source'] ?? null);
    }

    /**
     * R5G-BR-01 / R4G-BR-09: refused 3xx on merge-pending is endpoint_error, not unavailable.
     */
    public function testGetPendingMergeSuggestionsReturnsEndpointErrorOnUnexpectedRedirect(): void
    {
        $this->queueHttpResponse([
            'response' => ['code' => 302, 'message' => 'Found'],
            'headers' => ['Location' => 'https://attacker.example/collect'],
            'body' => '',
        ]);

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/suggestions/merge');
        $request->set_param('limit', 10);
        $request->set_param('offset', 0);

        $response = $this->controller->get_pending_merge_suggestions($request);

        $this->assertInstanceOf(\WP_REST_Response::class, $response);
        $this->assertSame(200, $response->get_status());
        $data = $response->get_data();
        $this->assertSame([], $data['suggestions'] ?? null);
        $this->assertSame(
            'endpoint_error',
            $data['data_source'] ?? null,
            'refused 3xx on merge-pending must not be laundered as unavailable'
        );
    }

    public function testGetPendingSuggestionsAnnotatesBackendProxyEnvelope(): void
    {
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => '[{"id":"suggestion-1","identity_id":"identity-1","cluster_id":"cluster-1","rep_similarity":0.91,"status":"pending"}]',
        ]);

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/suggestions');
        $request->set_param('limit', 10);
        $request->set_param('offset', 4);
        $response = $this->controller->get_pending_suggestions($request);

        $this->assertInstanceOf(\WP_REST_Response::class, $response);
        $data = $response->get_data();
        $this->assertSame('backend_proxy', $data['data_source'] ?? null);
        $this->assertSame(10, $data['limit'] ?? null);
        $this->assertSame(4, $data['offset'] ?? null);
        $this->assertArrayNotHasKey('total', $data);
    }

    public function testGetPendingSuggestionsOmitsAuthoritativeTotal(): void
    {
        // COR-3 (rg-015): upstream returns a bare page with no global count, so the
        // boundary must not synthesize an authoritative total from count(page).
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode([
                ['id' => 's1', 'identity_id' => 'i1', 'status' => 'pending'],
                ['id' => 's2', 'identity_id' => 'i2', 'status' => 'pending'],
                ['id' => 's3', 'identity_id' => 'i3', 'status' => 'pending'],
            ]),
        ]);

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/suggestions');
        $request->set_param('limit', 25);
        $request->set_param('offset', 0);
        $response = $this->controller->get_pending_suggestions($request);

        $this->assertInstanceOf(\WP_REST_Response::class, $response);
        $data = $response->get_data();

        // No fabricated authoritative total — consumers count loaded items instead.
        $this->assertArrayNotHasKey('total', $data);
        $this->assertCount(3, $data['suggestions']);
        // limit and offset still echo the request parameters.
        $this->assertSame(25, $data['limit']);
        $this->assertSame(0, $data['offset']);
        $this->assertSame('backend_proxy', $data['data_source']);
    }

    public function testGetPendingSuggestionsRejectsUnexpectedEnvelopePayload(): void
    {
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => '{"suggestions":[],"total":0,"limit":10,"offset":0}',
        ]);

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/suggestions');
        $response = $this->controller->get_pending_suggestions($request);

        $this->assertInstanceOf(\WP_Error::class, $response);
        $this->assertSame('invalid_suggestions_payload', $response->get_error_code());
    }

    public function testGetPendingMergeSuggestionsWrapsBackendArrayResponses(): void
    {
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => '[{"id":"merge-1","source_cluster_id":"cluster-a","target_cluster_id":"cluster-b"}]',
        ]);

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/suggestions/merge');
        $request->set_param('limit', 15);
        $request->set_param('offset', 5);
        $response = $this->controller->get_pending_merge_suggestions($request);

        $this->assertInstanceOf(\WP_REST_Response::class, $response);
        $data = $response->get_data();
        $this->assertSame('backend_proxy', $data['data_source'] ?? null);
        $this->assertCount(1, $data['suggestions'] ?? []);
        // total from count(items), limit/offset from request params
        $this->assertArrayNotHasKey('total', $data);
        $this->assertSame(15, $data['limit'] ?? null);
        $this->assertSame(5, $data['offset'] ?? null);
    }

    /**
     * Accept-merge proxy must pass through recognition's authoritative
     * source_cluster_id / target_cluster_id unchanged (no invented fields).
     */
    public function testAcceptMergeSuggestionPassesThroughAuthoritativeMergeIds(): void
    {
        $suggestionId = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee';
        $sourceId = '11111111-1111-1111-1111-111111111111';
        $targetId = '22222222-2222-2222-2222-222222222222';
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode([
                'id' => $suggestionId,
                'cluster_a_id' => $sourceId,
                'cluster_b_id' => $targetId,
                'similarity' => 0.91,
                'status' => 'accepted',
                'source_cluster_id' => $sourceId,
                'target_cluster_id' => $targetId,
            ]),
        ]);

        $request = new WP_REST_Request(
            'POST',
            '/acx/v1/recognition/suggestions/merge/' . $suggestionId . '/accept'
        );
        $request->set_param('suggestion_id', $suggestionId);
        $response = $this->controller->accept_merge_suggestion($request);

        $this->assertInstanceOf(\WP_REST_Response::class, $response);
        $this->assertSame(200, $response->get_status());
        $data = $response->get_data();
        $this->assertIsArray($data);
        $this->assertSame($sourceId, $data['source_cluster_id'] ?? null);
        $this->assertSame($targetId, $data['target_cluster_id'] ?? null);
        $this->assertSame('accepted', $data['status'] ?? null);
        // Proxy must not invent extra envelope fields beyond upstream body.
        $this->assertArrayNotHasKey('data_source', $data);
        $this->assertArrayNotHasKey('survivor_id', $data);
        $this->assertArrayNotHasKey('retired_id', $data);
    }

    /**
     * E215-BR-05: when upstream omits source/target keys, the proxy must not invent them.
     */
    public function testAcceptMergeSuggestionDoesNotInventSourceTargetWhenUpstreamOmitsThem(): void
    {
        $suggestionId = 'aaaaaaaa-bbbb-cccc-dddd-ffffffffffff';
        $clusterA = '11111111-1111-1111-1111-111111111111';
        $clusterB = '22222222-2222-2222-2222-222222222222';
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode([
                'id' => $suggestionId,
                'cluster_a_id' => $clusterA,
                'cluster_b_id' => $clusterB,
                'similarity' => 0.88,
                'status' => 'accepted',
                // Intentionally no source_cluster_id / target_cluster_id.
            ]),
        ]);

        $request = new WP_REST_Request(
            'POST',
            '/acx/v1/recognition/suggestions/merge/' . $suggestionId . '/accept'
        );
        $request->set_param('suggestion_id', $suggestionId);
        $response = $this->controller->accept_merge_suggestion($request);

        $this->assertInstanceOf(\WP_REST_Response::class, $response);
        $this->assertSame(200, $response->get_status());
        $data = $response->get_data();
        $this->assertIsArray($data);
        $this->assertArrayNotHasKey('source_cluster_id', $data);
        $this->assertArrayNotHasKey('target_cluster_id', $data);
        $this->assertSame('accepted', $data['status'] ?? null);
        $this->assertSame($clusterA, $data['cluster_a_id'] ?? null);
        $this->assertSame($clusterB, $data['cluster_b_id'] ?? null);
    }

    public function testRegisterRoutesIncludesNameSuggestionEndpoints(): void
    {
        $this->controller->register_routes();

        $routes = array_map(
            static fn (array $definition): string => $definition['route'],
            $GLOBALS['__ac_rest_routes']
        );

        $this->assertContains('/recognition/suggestions/name', $routes);
        $this->assertContains('/recognition/suggestions/name/(?P<suggestion_id>[a-f0-9-]+)/accept', $routes);
        $this->assertContains('/recognition/suggestions/name/(?P<suggestion_id>[a-f0-9-]+)/reject', $routes);
        $this->assertContains('/recognition/suggestions/bulk-accept', $routes);
    }

    public function testListNameSuggestionsForwardsParams(): void
    {
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => '[]',
        ]);

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/suggestions/name');
        $request->set_param('min_confidence', 0.8);
        $request->set_param('limit', 15);
        $request->set_param('offset', 5);

        $response = $this->controller->list_name_suggestions($request);

        $this->assertInstanceOf(\WP_REST_Response::class, $response);
        $this->assertSame(200, $response->get_status());

        $calls = $this->getHttpCalls();
        $this->assertCount(1, $calls);

        $query = [];
        $queryString = parse_url($calls[0]['url'], PHP_URL_QUERY);
        parse_str(is_string($queryString) ? $queryString : '', $query);

        $this->assertEqualsWithDelta(0.8, (float) ($query['min_confidence'] ?? 0), 0.001);
        $this->assertSame('15', (string) ($query['limit'] ?? ''));
        $this->assertSame('5', (string) ($query['offset'] ?? ''));
        $this->assertNotEmpty($query['tenant_id'] ?? '');
        $this->assertSame(10, $calls[0]['args']['timeout'] ?? null);
    }

    public function testListNameSuggestionsReturnsEmptyPayloadWhenProxyUnavailable(): void
    {
        $this->queueHttpResponse(new \WP_Error('proxy_failed', 'Proxy failure.'));
        $this->queueHttpResponse(new \WP_Error('proxy_failed', 'Proxy failure.'));
        $this->queueHttpResponse(new \WP_Error('proxy_failed', 'Proxy failure.'));

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/suggestions/name');
        $request->set_param('limit', 25);
        $request->set_param('offset', 0);

        $response = $this->controller->list_name_suggestions($request);

        $this->assertInstanceOf(\WP_REST_Response::class, $response);
        $this->assertSame(200, $response->get_status());
        $data = $response->get_data();
        $this->assertSame([], $data['suggestions'] ?? null);
        $this->assertArrayNotHasKey('total', $data);
        $this->assertSame('unavailable', $data['data_source'] ?? null);
    }

    /**
     * R5G-BR-01: refused 3xx on name path is endpoint_error, not unavailable.
     * Production previously used coarse is_proxy_unavailable() which laundered
     * recognition_unexpected_redirect as DATA_SOURCE_UNAVAILABLE.
     */
    public function testListNameSuggestionsReturnsEndpointErrorOnUnexpectedRedirect(): void
    {
        $this->queueHttpResponse([
            'response' => ['code' => 302, 'message' => 'Found'],
            'headers' => ['Location' => 'https://attacker.example/collect'],
            'body' => '',
        ]);

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/suggestions/name');
        $request->set_param('limit', 25);
        $request->set_param('offset', 0);

        $response = $this->controller->list_name_suggestions($request);

        $this->assertInstanceOf(\WP_REST_Response::class, $response);
        $this->assertSame(200, $response->get_status());
        $data = $response->get_data();
        $this->assertSame([], $data['suggestions'] ?? null);
        $this->assertSame(
            'endpoint_error',
            $data['data_source'] ?? null,
            'refused 3xx on name path must not be laundered as unavailable'
        );
    }

    public function testListNameSuggestionsAnnotatesBackendProxyArrayResponse(): void
    {
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => '[{"id":"name-1","cluster_id":"cluster-a","suggested_name":"Alice","confidence_score":0.88,"source":"roster","status":"pending"}]',
        ]);

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/suggestions/name');
        $request->set_param('limit', 25);
        $request->set_param('offset', 6);
        $response = $this->controller->list_name_suggestions($request);

        $this->assertInstanceOf(\WP_REST_Response::class, $response);
        $data = $response->get_data();
        $this->assertSame('backend_proxy', $data['data_source'] ?? null);
        $this->assertSame(25, $data['limit'] ?? null);
        $this->assertSame(6, $data['offset'] ?? null);
        $this->assertArrayNotHasKey('total', $data);
    }

    public function testListNameSuggestionsRejectsUnexpectedEnvelopePayload(): void
    {
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => '{"suggestions":[],"total":0,"limit":25,"offset":0}',
        ]);

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/suggestions/name');
        $response = $this->controller->list_name_suggestions($request);

        $this->assertInstanceOf(\WP_Error::class, $response);
        $this->assertSame('invalid_name_suggestions_payload', $response->get_error_code());
    }

    public function testListNameSuggestionsWrapsBackendArrayResponses(): void
    {
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => '[{"id":"name-1","cluster_id":"cluster-a","suggested_name":"Alice"}]',
        ]);

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/suggestions/name');
        $response = $this->controller->list_name_suggestions($request);

        $this->assertInstanceOf(\WP_REST_Response::class, $response);
        $data = $response->get_data();
        $this->assertSame('backend_proxy', $data['data_source'] ?? null);
        $this->assertCount(1, $data['suggestions'] ?? []);
        $this->assertArrayNotHasKey('total', $data);
    }

    public function testAcceptNameSuggestionForwardsSuggestionId(): void
    {
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => '{}',
        ]);

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/suggestions/name/abc-123/accept');
        $request->set_param('suggestion_id', 'abc-123');

        $response = $this->controller->accept_name_suggestion($request);

        $this->assertInstanceOf(\WP_REST_Response::class, $response);

        $calls = $this->getHttpCalls();
        $this->assertCount(1, $calls);
        $this->assertStringContainsString('/recognition/suggestions/name/abc-123/accept', $calls[0]['url']);
    }

    public function testRejectNameSuggestionForwardsSuggestionId(): void
    {
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => '{}',
        ]);

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/suggestions/name/def-456/reject');
        $request->set_param('suggestion_id', 'def-456');

        $response = $this->controller->reject_name_suggestion($request);

        $this->assertInstanceOf(\WP_REST_Response::class, $response);

        $calls = $this->getHttpCalls();
        $this->assertCount(1, $calls);
        $this->assertStringContainsString('/recognition/suggestions/name/def-456/reject', $calls[0]['url']);
    }

    public function testBulkAcceptSuggestionsForwardsPayload(): void
    {
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => '{"accepted_count":3,"skipped_count":1}',
        ]);

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/suggestions/bulk-accept');
        $request->set_param('suggestion_type', 'assignment');
        $request->set_param('min_confidence', 0.75);

        $response = $this->controller->bulk_accept_suggestions($request);

        $this->assertInstanceOf(\WP_REST_Response::class, $response);
        $this->assertSame(200, $response->get_status());

        $calls = $this->getHttpCalls();
        $this->assertCount(1, $calls);
        $this->assertStringContainsString('/recognition/suggestions/bulk-accept', $calls[0]['url']);
    }

    public function testBulkAcceptSuggestionsReturnsEmptyPayloadWhenProxyUnavailable(): void
    {
        $this->queueHttpResponse(new \WP_Error('proxy_failed', 'Proxy failure.'));
        $this->queueHttpResponse(new \WP_Error('proxy_failed', 'Proxy failure.'));
        $this->queueHttpResponse(new \WP_Error('proxy_failed', 'Proxy failure.'));

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/suggestions/bulk-accept');
        $request->set_param('suggestion_type', 'name');
        $request->set_param('min_confidence', 0.6);

        $response = $this->controller->bulk_accept_suggestions($request);

        $this->assertInstanceOf(\WP_REST_Response::class, $response);
        $this->assertSame(200, $response->get_status());
        $data = $response->get_data();
        $this->assertSame(0, $data['accepted_count'] ?? null);
        $this->assertSame(0, $data['skipped_count'] ?? null);
    }

    /**
     * R5G-BR-01 / R4G-BR-09: refused 3xx on bulk-accept is endpoint_error, not unavailable.
     */
    public function testBulkAcceptSuggestionsReturnsEndpointErrorOnUnexpectedRedirect(): void
    {
        $this->queueHttpResponse([
            'response' => ['code' => 302, 'message' => 'Found'],
            'headers' => ['Location' => 'https://attacker.example/collect'],
            'body' => '',
        ]);

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/suggestions/bulk-accept');
        $request->set_param('suggestion_type', 'name');
        $request->set_param('min_confidence', 0.6);

        $response = $this->controller->bulk_accept_suggestions($request);

        $this->assertInstanceOf(\WP_REST_Response::class, $response);
        $this->assertSame(200, $response->get_status());
        $data = $response->get_data();
        $this->assertSame(0, $data['accepted_count'] ?? null);
        $this->assertSame(0, $data['skipped_count'] ?? null);
        $this->assertSame(
            'endpoint_error',
            $data['data_source'] ?? null,
            'refused 3xx on bulk-accept must not be laundered as unavailable'
        );
    }

    public function testRegisterRoutesIncludesRosterCandidates(): void
    {
        $this->controller->register_routes();

        $definitions = array_values(array_filter(
            $GLOBALS['__ac_rest_routes'],
            static fn (array $definition): bool => '/recognition/clusters/(?P<cluster_id>[a-f0-9-]+)/roster-candidates' === $definition['route']
        ));

        $this->assertCount(1, $definitions);
        $this->assertSame('GET', $definitions[0]['args']['methods'] ?? null);
        $this->assertSame(
            [$this->controller, 'can_manage_recognition'],
            $definitions[0]['args']['permission_callback'] ?? null
        );
        $topK = $definitions[0]['args']['args']['top_k'] ?? [];
        $this->assertSame('integer', $topK['type'] ?? null);
        $this->assertSame(10, $topK['default'] ?? null);
        $this->assertSame(1, $topK['minimum'] ?? null);
        $this->assertSame(50, $topK['maximum'] ?? null);
        $this->assertArrayHasKey('validate_callback', $topK);
        $validate = $topK['validate_callback'];
        $request = new WP_REST_Request('GET', '/acx/v1/recognition/clusters/cccccccc-dddd-eeee-ffff-000000000001/roster-candidates');
        $this->assertFalse($validate(-5, $request, 'top_k'));
        $this->assertFalse($validate(0, $request, 'top_k'));
        $this->assertFalse($validate(51, $request, 'top_k'));
        $this->assertTrue($validate(1, $request, 'top_k'));
        $this->assertTrue($validate(50, $request, 'top_k'));
    }

    public function testGetRosterCandidatesForwardsTopKAndMapsRosterEntryId(): void
    {
        $clusterId = 'aaaaaaaa-bbbb-cccc-dddd-000000000111';
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode([
                'model_id' => 'opencv-sface+cv5@128d/l2/cosine',
                'embedding_model' => 'opencv-sface+cv5@128d/l2/cosine',
                'computed_at' => '2026-08-18T12:00:00+00:00',
                'reference_face_count' => 2,
                'thresholds' => [
                    'suggestion_floor' => 0.35,
                    'suggestion_ceiling' => 0.55,
                    'similarity_threshold' => 0.55,
                ],
                'quality_flag' => 'ok',
                'probe_face_count' => 2,
                'candidates' => [
                    [
                        'cluster_id' => $clusterId,
                        'name' => 'Ada',
                        'similarity' => 0.81,
                        'band' => 'strong',
                    ],
                    [
                        'cluster_id' => 'bbbbbbbb-cccc-dddd-eeee-000000000222',
                        'name' => 'Orphan cluster',
                        'similarity' => 0.60,
                        'band' => 'possible',
                    ],
                ],
            ], JSON_THROW_ON_ERROR),
        ]);

        global $wpdb;
        $wpdb->mockResults = [
            [
                'cluster_uuid' => $clusterId,
                'person_id' => 42,
                'name' => 'Ada Lovelace',
            ],
        ];

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/clusters/cccccccc-dddd-eeee-ffff-000000000001/roster-candidates');
        $request->set_param('cluster_id', 'cccccccc-dddd-eeee-ffff-000000000001');
        $request->set_param('top_k', 7);

        $response = $this->controller->get_roster_candidates($request);

        $this->assertInstanceOf(\WP_REST_Response::class, $response);
        $this->assertSame(200, $response->get_status());

        $calls = $this->getHttpCalls();
        $this->assertCount(1, $calls);
        $this->assertStringContainsString(
            '/recognition/clusters/cccccccc-dddd-eeee-ffff-000000000001/roster-candidates',
            $calls[0]['url']
        );
        $this->assertSame(10, $calls[0]['args']['timeout'] ?? null, 'R1-07: post_scan_read timeout, not ui_read 2s');

        $query = [];
        $queryString = parse_url($calls[0]['url'], PHP_URL_QUERY);
        parse_str(is_string($queryString) ? $queryString : '', $query);
        $this->assertSame('7', (string) ($query['top_k'] ?? ''));
        $this->assertNotEmpty($query['tenant_id'] ?? '');

        $data = $response->get_data();
        $this->assertSame(42, $data['candidates'][0]['roster_entry_id'] ?? null);
        $this->assertSame($clusterId, $data['candidates'][0]['cluster_id'] ?? null);
        $this->assertSame('Ada Lovelace', $data['candidates'][0]['name'] ?? null);
        $this->assertArrayHasKey('roster_entry_id', $data['candidates'][1]);
        $this->assertNull($data['candidates'][1]['roster_entry_id']);
        $this->assertSame('Orphan cluster', $data['candidates'][1]['name'] ?? null);
        $this->assertArrayNotHasKey('total', $data);
        $this->assertArrayNotHasKey('limit', $data);
        $this->assertSame('opencv-sface+cv5@128d/l2/cosine', $data['model_id'] ?? null);
        $this->assertSame('ok', $data['quality_flag'] ?? null);

        $this->assertNotEmpty($wpdb->queries);
        $sql = implode("\n", $wpdb->queries);
        $this->assertStringContainsString('wp_acx_clusters', $sql);
        $this->assertStringContainsString('cluster_uuid', $sql);
        $this->assertStringContainsString('person_id', $sql);
        $this->assertStringContainsString('tenant_id', $sql);
        $this->assertStringContainsString($clusterId, $sql);
        $this->assertStringContainsString('bbbbbbbb-cccc-dddd-eeee-000000000222', $sql);
        $this->assertStringContainsString(self::currentTenantId(), $sql);
    }

    public function testGetRosterCandidatesCollapsesDuplicateRosterEntryIds(): void
    {
        $winner = 'aaaaaaaa-bbbb-cccc-dddd-000000000111';
        $loser = 'bbbbbbbb-cccc-dddd-eeee-000000000222';
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode([
                'model_id' => 'opencv-sface+cv5@128d/l2/cosine',
                'embedding_model' => 'opencv-sface+cv5@128d/l2/cosine',
                'computed_at' => '2026-08-18T12:00:00+00:00',
                'probe_face_count' => 1,
                'reference_face_count' => 2,
                'quality_flag' => 'ok',
                'thresholds' => [
                    'suggestion_floor' => 0.35,
                    'suggestion_ceiling' => 0.55,
                    'similarity_threshold' => 0.55,
                ],
                'candidates' => [
                    [
                        'cluster_id' => $winner,
                        'name' => 'Ada-cluster-a',
                        'similarity' => 0.91,
                        'band' => 'strong',
                    ],
                    [
                        'cluster_id' => $loser,
                        'name' => 'Ada-cluster-b',
                        'similarity' => 0.70,
                        'band' => 'possible',
                    ],
                ],
            ], JSON_THROW_ON_ERROR),
        ]);

        global $wpdb;
        $wpdb->mockResults = [
            ['cluster_uuid' => $winner, 'person_id' => 42, 'name' => 'Ada Lovelace'],
            ['cluster_uuid' => $loser, 'person_id' => 42, 'name' => 'Ada Lovelace'],
        ];

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/clusters/cccccccc-dddd-eeee-ffff-000000000001/roster-candidates');
        $request->set_param('cluster_id', 'cccccccc-dddd-eeee-ffff-000000000001');
        $request->set_param('top_k', 10);

        $response = $this->controller->get_roster_candidates($request);
        $data = $response->get_data();
        $this->assertCount(1, $data['candidates']);
        $this->assertSame(42, $data['candidates'][0]['roster_entry_id']);
        $this->assertSame(0.91, $data['candidates'][0]['similarity']);
        $this->assertSame('strong', $data['candidates'][0]['band']);
        $this->assertSame('Ada Lovelace', $data['candidates'][0]['name']);
        $this->assertSame($winner, $data['candidates'][0]['cluster_id']);
    }

    public function testGetRosterCandidatesRejectsInvalidTopKWithoutSignFlip(): void
    {
        $request = new WP_REST_Request('GET', '/acx/v1/recognition/clusters/cccccccc-dddd-eeee-ffff-000000000001/roster-candidates');
        $request->set_param('cluster_id', 'cccccccc-dddd-eeee-ffff-000000000001');
        $request->set_param('top_k', -5);

        $response = $this->controller->get_roster_candidates($request);
        $this->assertInstanceOf(\WP_Error::class, $response);
        $this->assertSame('invalid_top_k', $response->get_error_code());
        $this->assertSame(400, $response->get_error_data()['status'] ?? null);
        $this->assertSame([], $this->getHttpCalls());

        $request->set_param('top_k', 0);
        $response = $this->controller->get_roster_candidates($request);
        $this->assertInstanceOf(\WP_Error::class, $response);
        $this->assertSame('invalid_top_k', $response->get_error_code());
    }

    public function testGetRosterCandidatesUnavailableIs503WithoutFabricatedEnvelope(): void
    {
        $this->queueHttpResponse(new \WP_Error('proxy_failed', 'Proxy failure.'));
        $this->queueHttpResponse(new \WP_Error('proxy_failed', 'Proxy failure.'));
        $this->queueHttpResponse(new \WP_Error('proxy_failed', 'Proxy failure.'));

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/clusters/cccccccc-dddd-eeee-ffff-000000000001/roster-candidates');
        $request->set_param('cluster_id', 'cccccccc-dddd-eeee-ffff-000000000001');

        $response = $this->controller->get_roster_candidates($request);
        $this->assertInstanceOf(\WP_Error::class, $response);
        $this->assertSame(503, $response->get_error_data()['status'] ?? null);
        $this->assertArrayNotHasKey('total', (array) $response->get_error_data());
        $this->assertArrayNotHasKey('limit', (array) $response->get_error_data());
        $this->assertArrayNotHasKey('candidates', (array) $response->get_error_data());
    }

    public function testGetRosterCandidatesEndpointErrorIs502WithoutFabricatedEnvelope(): void
    {
        $this->queueHttpResponse([
            'response' => ['code' => 500, 'message' => 'Internal Server Error'],
            'body' => '{"detail":"boom"}',
        ]);

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/clusters/cccccccc-dddd-eeee-ffff-000000000001/roster-candidates');
        $request->set_param('cluster_id', 'cccccccc-dddd-eeee-ffff-000000000001');

        $response = $this->controller->get_roster_candidates($request);
        $this->assertInstanceOf(\WP_Error::class, $response);
        $this->assertSame(502, $response->get_error_data()['status'] ?? null);
        $this->assertArrayNotHasKey('total', (array) $response->get_error_data());
        $this->assertArrayNotHasKey('limit', (array) $response->get_error_data());
        $this->assertArrayNotHasKey('candidates', (array) $response->get_error_data());
    }
}
