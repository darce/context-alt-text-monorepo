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
        $this->seedAttachment(201, 'Attachment 201');
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
        $this->seedAttachment(301, 'Attachment 301');
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
        $this->seedAttachment($mediaId, 'Attachment 401');
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
        $this->seedAttachment($mediaId, 'Attachment 402');
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
     * BR-40 option (a): a failed human-edit write after a verified alt save is
     * failure-worthy. Alt stays written (no rollback); response is 500 so the
     * client never treats missing stored telemetry as a successful correction.
     * Message tells the operator the alt landed and to retry for history accuracy.
     */
    public function testHumanEditWriteFailureReturnsErrorAfterAltSaved(): void
    {
        $mediaId = 403;
        $newAlt = 'Operator-corrected alt.';
        $this->seedAttachment($mediaId, 'Attachment 403');
        $this->setPostMeta($mediaId, '_wp_attachment_image_alt', 'Old alt.');
        $this->setPostMeta($mediaId, '_acx_description_provenance', [
            'alt_text_draft' => 'Generated draft.',
            'model_id' => 'local-v1',
        ]);
        // Alt write succeeds; only the human-edit meta write is forced to fail.
        $GLOBALS['__ac_update_post_meta_fail'][$mediaId]['_acx_description_human_edit'] = true;

        $result = (new DescriptionHistoryService())->record_correction($mediaId, $newAlt);

        $this->assertInstanceOf(WP_Error::class, $result);
        $this->assertSame('description_correction_failed', $result->get_error_code());
        $this->assertSame(500, $result->get_error_data()['status']);
        $this->assertStringContainsString('Alt text was saved', $result->get_error_message());
        // Partial success: alt persisted, human-edit did not. [INT-11] does not undo alt.
        $this->assertSame($newAlt, get_post_meta($mediaId, '_wp_attachment_image_alt', true));
        $this->assertSame('', get_post_meta($mediaId, '_acx_description_human_edit', true));
    }

    /**
     * BR-41: success never returns the two-field partial. No prior provenance is
     * fine when human-edit lands — envelope is still the full item shape.
     */
    public function testCorrectionWithoutProvenanceReturnsFullItemEnvelope(): void
    {
        $mediaId = 404;
        $this->seedAttachment($mediaId, 'No-provenance photo', 'image/png');
        $this->setPostMeta($mediaId, '_wp_attachment_image_alt', 'Old bare alt.');

        $result = (new DescriptionHistoryService())->record_correction($mediaId, 'Bare corrected alt.');

        $this->assertNotInstanceOf(WP_Error::class, $result);
        $this->assertIsArray($result);
        $this->assertSame(
            ['media_id', 'title', 'mime_type', 'current_alt_text', 'generated_alt_text', 'provenance', 'human_edit', 'run_status'],
            array_keys($result)
        );
        $this->assertSame($mediaId, $result['media_id']);
        $this->assertSame('No-provenance photo', $result['title']);
        $this->assertSame('image/png', $result['mime_type']);
        $this->assertSame('Bare corrected alt.', $result['current_alt_text']);
        $this->assertSame('', $result['generated_alt_text']);
        $this->assertNull($result['provenance']);
        $this->assertIsArray($result['human_edit']);
        $this->assertSame('Bare corrected alt.', $result['human_edit']['alt_text']);
        $this->assertNull($result['run_status']);
    }

    /**
     * BR-40 + BR-41 interaction: human-edit failure with no provenance must not
     * fall through to a 200 two-field partial; it is an error like any other
     * human-edit failure.
     */
    public function testHumanEditFailureWithoutProvenanceIsErrorNotPartial(): void
    {
        $mediaId = 405;
        $newAlt = 'Would-be partial alt.';
        $this->seedAttachment($mediaId, 'Attachment 405');
        $this->setPostMeta($mediaId, '_wp_attachment_image_alt', 'Prior alt.');
        $GLOBALS['__ac_update_post_meta_fail'][$mediaId]['_acx_description_human_edit'] = true;

        $result = (new DescriptionHistoryService())->record_correction($mediaId, $newAlt);

        $this->assertInstanceOf(WP_Error::class, $result);
        $this->assertSame(500, $result->get_error_data()['status']);
        $this->assertSame($newAlt, get_post_meta($mediaId, '_wp_attachment_image_alt', true));
        $this->assertSame('', get_post_meta($mediaId, '_acx_description_human_edit', true));
        // Not a success array with only media_id + current_alt_text.
        $this->assertFalse(is_array($result) && isset($result['media_id']) && !isset($result['title']));
    }

    /**
     * BR-42: a media_id with no post behind it must not write orphan alt or
     * human-edit meta. Boundary validation before any update_post_meta call.
     */
    public function testNonexistentMediaIdReturnsNotFoundAndWritesNoMeta(): void
    {
        $mediaId = 999999;
        $metaBefore = $GLOBALS['__ac_post_meta'];

        $result = (new DescriptionHistoryService())->record_correction($mediaId, 'Orphan alt');

        $this->assertInstanceOf(WP_Error::class, $result);
        $this->assertSame('description_correction_failed', $result->get_error_code());
        $this->assertSame(404, $result->get_error_data()['status']);
        // The part that matters: meta store is untouched.
        $this->assertSame($metaBefore, $GLOBALS['__ac_post_meta']);
        $this->assertArrayNotHasKey($mediaId, $GLOBALS['__ac_post_meta']);
    }

    /**
     * BR-42: an existing post that is not an attachment must be refused with
     * 400 and must not receive alt/human-edit meta.
     */
    public function testNonAttachmentPostReturnsBadRequestAndWritesNoMeta(): void
    {
        $mediaId = 501;
        $GLOBALS['__ac_posts'][$mediaId] = (object) [
            'ID' => $mediaId,
            'post_type' => 'post',
            'post_title' => 'Regular post',
        ];
        $metaBefore = $GLOBALS['__ac_post_meta'];

        $result = (new DescriptionHistoryService())->record_correction($mediaId, 'Should not land');

        $this->assertInstanceOf(WP_Error::class, $result);
        $this->assertSame('description_correction_failed', $result->get_error_code());
        $this->assertSame(400, $result->get_error_data()['status']);
        $this->assertSame($metaBefore, $GLOBALS['__ac_post_meta']);
        $this->assertArrayNotHasKey($mediaId, $GLOBALS['__ac_post_meta']);
    }

    /**
     * BR-42 happy path: a real attachment receives the alt write and returns
     * the full history item envelope (title, mime, provenance, human_edit).
     */
    public function testHappyPathWritesAndReturnsFullItem(): void
    {
        $mediaId = 601;
        $this->seedAttachment($mediaId, 'Harbor photo', 'image/jpeg');
        $this->setPostMeta($mediaId, '_wp_attachment_image_alt', 'Old harbor alt.');
        $this->setPostMeta($mediaId, '_acx_description_provenance', [
            'alt_text_draft' => 'Generated harbor draft.',
            'model_id' => 'local-v1',
        ]);

        $result = (new DescriptionHistoryService())->record_correction($mediaId, 'Corrected harbor alt.');

        $this->assertNotInstanceOf(WP_Error::class, $result);
        $this->assertIsArray($result);
        $this->assertSame($mediaId, $result['media_id']);
        $this->assertSame('Harbor photo', $result['title']);
        $this->assertSame('image/jpeg', $result['mime_type']);
        $this->assertSame('Corrected harbor alt.', $result['current_alt_text']);
        $this->assertSame('Generated harbor draft.', $result['generated_alt_text']);
        $this->assertSame(
            ['alt_text_draft' => 'Generated harbor draft.', 'model_id' => 'local-v1'],
            $result['provenance']
        );
        $this->assertIsArray($result['human_edit']);
        $this->assertSame('Corrected harbor alt.', $result['human_edit']['alt_text']);
        $this->assertSame('Corrected harbor alt.', get_post_meta($mediaId, '_wp_attachment_image_alt', true));
    }

    /**
     * @param int    $mediaId
     * @param string $title
     * @param string $mime
     */
    private function seedAttachment(int $mediaId, string $title = '', string $mime = 'image/jpeg'): void
    {
        $GLOBALS['__ac_posts'][$mediaId] = (object) [
            'ID' => $mediaId,
            'post_type' => 'attachment',
            'post_title' => $title,
        ];
        $GLOBALS['__ac_attachment_mimes'][$mediaId] = $mime;
    }
}
