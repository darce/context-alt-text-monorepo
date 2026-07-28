<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Api\DescribeController;
use AltContext\Api\Services\DescriptionHistoryService;
use AltContext\Tests\TestCase;
use WP_Error;
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

    /**
     * S3-02 / naive-fix regression: update_post_meta returns false for a
     * byte-identical no-op overwrite. A bare `false === $result` would turn
     * a legitimate re-save into an error; the read-back must keep it green.
     */
    public function testNoOpOverwriteStillSucceeds(): void
    {
        $mediaId = 401;
        $sameAlt = 'Already stored alt.';
        $this->setPostMeta($mediaId, '_wp_attachment_image_alt', $sameAlt);
        $this->setPostMeta($mediaId, '_acx_description_provenance', [
            'alt_text_draft' => 'Generated draft.',
            'model_id' => 'local-v1',
        ]);
        // Force update_post_meta to return false without persisting — same as a
        // WP no-op overwrite when the stored value is already identical.
        $GLOBALS['__ac_update_post_meta_fail'][$mediaId]['_wp_attachment_image_alt'] = true;

        $result = (new DescriptionHistoryService())->record_correction($mediaId, $sameAlt);

        $this->assertNotInstanceOf(WP_Error::class, $result);
        $this->assertSame($sameAlt, $result['current_alt_text']);
        $this->assertSame($sameAlt, get_post_meta($mediaId, '_wp_attachment_image_alt', true));

        $humanEdit = get_post_meta($mediaId, '_acx_description_human_edit', true);
        $this->assertIsArray($humanEdit);
        $this->assertSame($sameAlt, $humanEdit['alt_text']);
    }

    /**
     * A genuine alt write failure must not report the requested text as current
     * and must surface as a non-2xx WP_Error through the controller. [HAI-13]
     */
    public function testFailedAltWriteReturnsErrorAndDoesNotReportRequestedText(): void
    {
        $mediaId = 402;
        $existingAlt = 'Existing stored alt.';
        $requestedAlt = 'Requested but unwritable alt.';
        $this->setPostMeta($mediaId, '_wp_attachment_image_alt', $existingAlt);
        $this->setPostMeta($mediaId, '_acx_description_provenance', [
            'alt_text_draft' => 'Generated draft.',
            'model_id' => 'local-v1',
        ]);
        // Real failure: write returns false and does not persist.
        $GLOBALS['__ac_update_post_meta_fail'][$mediaId]['_wp_attachment_image_alt'] = true;

        $serviceResult = (new DescriptionHistoryService())->record_correction($mediaId, $requestedAlt);

        $this->assertInstanceOf(WP_Error::class, $serviceResult);
        $this->assertSame('description_correction_failed', $serviceResult->get_error_code());
        $this->assertSame(
            ['status' => 500],
            $serviceResult->get_error_data()
        );
        // Storage still holds the prior value — not the request body. [rg-015]
        $this->assertSame($existingAlt, get_post_meta($mediaId, '_wp_attachment_image_alt', true));
        // Failed alt write must not stamp human-edit meta. [INT-11]
        $this->assertSame('', get_post_meta($mediaId, '_acx_description_human_edit', true));

        $controller = new DescribeController();
        $request = new WP_REST_Request('POST', '/acx/v1/recognition/describe/history/' . $mediaId . '/correction');
        $request->set_param('media_id', $mediaId);
        $request->set_param('alt_text', $requestedAlt);

        $response = $controller->correct_description_history_item($request);

        $this->assertInstanceOf(WP_Error::class, $response);
        $this->assertSame('description_correction_failed', $response->get_error_code());
        $this->assertSame(500, $response->get_error_data()['status']);
        // Failure envelope must not claim the requested text as current.
        $this->assertStringNotContainsString($requestedAlt, $response->get_error_message());
    }

    /**
     * Human-edit meta is provenance/telemetry. A failed human-edit write after a
     * verified alt save is not failure-worthy — the operator's data already
     * persisted. Pins the "alt is data, human-edit is telemetry" decision.
     */
    public function testHumanEditWriteFailureIsNonFatal(): void
    {
        $mediaId = 403;
        $newAlt = 'Operator-corrected alt.';
        $this->setPostMeta($mediaId, '_wp_attachment_image_alt', 'Old alt.');
        $this->setPostMeta($mediaId, '_acx_description_provenance', [
            'alt_text_draft' => 'Generated draft.',
            'model_id' => 'local-v1',
        ]);
        // Alt write succeeds; only the human-edit meta write is forced to fail.
        $GLOBALS['__ac_update_post_meta_fail'][$mediaId]['_acx_description_human_edit'] = true;

        $result = (new DescriptionHistoryService())->record_correction($mediaId, $newAlt);

        $this->assertNotInstanceOf(WP_Error::class, $result);
        // Alt text from storage, not a fabricated request echo. [rg-015]
        $this->assertSame($newAlt, $result['current_alt_text']);
        $this->assertSame($newAlt, get_post_meta($mediaId, '_wp_attachment_image_alt', true));
        // Telemetry write did not persist.
        $this->assertSame('', get_post_meta($mediaId, '_acx_description_human_edit', true));
    }
}
