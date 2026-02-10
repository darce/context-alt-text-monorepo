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
}
