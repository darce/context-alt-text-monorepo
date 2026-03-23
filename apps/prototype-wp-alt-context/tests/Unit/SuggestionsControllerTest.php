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
        $this->assertSame(0, $data['total'] ?? null);
        $this->assertSame(25, $data['limit'] ?? null);
        $this->assertSame(0, $data['offset'] ?? null);
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
        $this->assertSame(0, $data['total'] ?? null);
        $this->assertSame(10, $data['limit'] ?? null);
        $this->assertSame(0, $data['offset'] ?? null);
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
            'body' => '{"suggestions":[],"total":0,"limit":15,"offset":5}',
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
        $this->assertSame(0, $data['total'] ?? null);
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
}
