<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Api\DescribeController;
use AltContext\Api\Services\DescriptionHistoryService;
use AltContext\Tests\TestCase;
use WP_REST_Request;
use WP_REST_Response;

/**
 * @covers \AltContext\Api\Services\DescriptionHistoryService
 * @covers \AltContext\Api\DescribeController
 */
class DescriptionHistoryServiceTest extends TestCase
{
    public function testListHistoryReturnsGeneratedDraftAltAndProvenance(): void
    {
        $GLOBALS['__ac_get_posts_results'] = [101, 102];
        $GLOBALS['__ac_posts'][101] = (object) ['ID' => 101, 'post_title' => 'Bridge'];
        $GLOBALS['__ac_posts'][102] = (object) ['ID' => 102, 'post_title' => 'Ignored'];
        $GLOBALS['__ac_attachment_mimes'][101] = 'image/jpeg';
        $GLOBALS['__ac_attachment_mimes'][102] = 'image/png';
        $this->setPostMeta(101, '_wp_attachment_image_alt', 'Current bridge alt.');
        $this->setPostMeta(101, '_acx_description_provenance', [
            'alt_text_draft' => 'Generated bridge draft.',
            'generated_at' => '2026-07-04T12:00:00+00:00',
            'model_id' => 'local-v1',
        ]);
        $this->setPostMeta(101, '_acx_description_run_status', [
            'run_id' => 'run-1',
            'status' => 'succeeded',
        ]);

        $response = (new DescriptionHistoryService())->list_history(10);

        $this->assertSame(1, $response['total']);
        $this->assertSame(101, $response['items'][0]['media_id']);
        $this->assertSame('Bridge', $response['items'][0]['title']);
        $this->assertSame('Current bridge alt.', $response['items'][0]['current_alt_text']);
        $this->assertSame('Generated bridge draft.', $response['items'][0]['generated_alt_text']);
        $this->assertSame('local-v1', $response['items'][0]['provenance']['model_id']);
        $this->assertSame(['run_id' => 'run-1', 'status' => 'succeeded'], $response['items'][0]['run_status']);
    }

    public function testCorrectionUpdatesAltAndRecordsHumanEditWithoutRemovingProvenance(): void
    {
        $this->setPostMeta(201, '_wp_attachment_image_alt', 'Generated alt.');
        $this->setPostMeta(201, '_acx_description_provenance', [
            'alt_text_draft' => 'Generated alt.',
            'model_id' => 'local-v1',
        ]);

        $result = (new DescriptionHistoryService())->record_correction(201, 'Human corrected alt.');

        $this->assertSame('Human corrected alt.', get_post_meta(201, '_wp_attachment_image_alt', true));
        $this->assertSame(['alt_text_draft' => 'Generated alt.', 'model_id' => 'local-v1'], get_post_meta(201, '_acx_description_provenance', true));
        $this->assertSame('Human corrected alt.', $result['current_alt_text']);

        $humanEdit = get_post_meta(201, '_acx_description_human_edit', true);
        $this->assertIsArray($humanEdit);
        $this->assertSame('Human corrected alt.', $humanEdit['alt_text']);
        $this->assertSame(1, $humanEdit['user_id']);
    }

    public function testControllerRegistersHistoryRoutesAndDelegatesCorrection(): void
    {
        $controller = new DescribeController();
        $controller->register_routes();

        $routes = array_map(
            static fn(array $route): string => $route['namespace'] . $route['route'],
            $GLOBALS['__ac_rest_routes']
        );

        $this->assertContains('acx/v1/recognition/describe/history', $routes);
        $this->assertContains('acx/v1/recognition/describe/history/(?P<media_id>\\d+)/correction', $routes);

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/describe/history/301/correction');
        $request->set_param('media_id', 301);
        $request->set_param('alt_text', 'Corrected from controller.');

        $response = $controller->correct_description_history_item($request);

        $this->assertInstanceOf(WP_REST_Response::class, $response);
        $this->assertSame('Corrected from controller.', $response->get_data()['current_alt_text']);
    }
}
