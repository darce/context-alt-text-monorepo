<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Api\DescribeController;
use AltContext\Api\Services\DescribeMediaService;
use AltContext\Api\Services\DescriptionHistoryService;
use AltContext\Cli\DescriptionCommand;
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

    /**
     * WBUX-5-R16-BR-06 pin 1: provenance-gap (alt present, provenance null,
     * durable pending marker array) appears in history with honest null envelope.
     */
    public function testListHistoryIncludesProvenanceGapWhenPendingMarkerAndAltPresent(): void
    {
        $mediaId = 501;
        $GLOBALS['__ac_get_posts_results'] = [$mediaId];
        $this->seedAttachment($mediaId, 'Gap photo');
        $this->setPostMeta($mediaId, '_wp_attachment_image_alt', 'Alt landed without provenance.');
        $this->setPostMeta($mediaId, '_acx_description_provenance_pending', [
            'run_id'     => 'single_image',
            'draft_hash' => hash('sha256', 'Alt landed without provenance.'),
        ]);

        $response = (new DescriptionHistoryService())->list_history(10);

        $this->assertSame(1, $response['total']);
        $item = $response['items'][0];
        $this->assertSame($mediaId, $item['media_id']);
        $this->assertSame('Alt landed without provenance.', $item['current_alt_text']);
        $this->assertNull($item['provenance']);
        $this->assertNull($item['human_edit']);
        $this->assertSame('', $item['generated_alt_text']);
    }

    /**
     * WBUX-5-R16-BR-06 pin 3: human-authored alt with no `_acx_*` trail and no
     * pending marker must stay out of history (anti-regression for the rejected
     * "any non-empty alt" inclusion gate).
     */
    public function testListHistoryExcludesHumanAuthoredAltWithNoAcxTrail(): void
    {
        $mediaId = 502;
        $GLOBALS['__ac_get_posts_results'] = [$mediaId];
        $this->seedAttachment($mediaId, 'Library photo');
        $this->setPostMeta($mediaId, '_wp_attachment_image_alt', 'A human wrote this in the media library.');
        // No provenance, human_edit, or pending marker.

        $response = (new DescriptionHistoryService())->list_history(10);

        $this->assertSame(0, $response['total']);
        $this->assertSame([], $response['items']);
    }

    /**
     * WBUX-5-R16-BR-06 pin 4: fully stamped item still appears exactly once.
     */
    public function testListHistoryIncludesFullyStampedItemExactlyOnce(): void
    {
        $mediaId = 503;
        $GLOBALS['__ac_get_posts_results'] = [$mediaId];
        $this->seedAttachment($mediaId, 'Stamped');
        $this->setPostMeta($mediaId, '_wp_attachment_image_alt', 'Generated stamp.');
        $this->setPostMeta($mediaId, '_acx_description_provenance', [
            'alt_text_draft' => 'Generated stamp.',
            'model_id'       => 'local-v1',
        ]);

        $response = (new DescriptionHistoryService())->list_history(10);

        $this->assertSame(1, $response['total']);
        $this->assertCount(1, $response['items']);
        $this->assertSame($mediaId, $response['items'][0]['media_id']);
        $this->assertIsArray($response['items'][0]['provenance']);
    }

    /**
     * WBUX-5-R16-BR-06 pin 5: human_edit-only row (no provenance) still appears.
     */
    public function testListHistoryIncludesHumanEditOnlyRow(): void
    {
        $mediaId = 504;
        $GLOBALS['__ac_get_posts_results'] = [$mediaId];
        $this->seedAttachment($mediaId, 'Edited only');
        $this->setPostMeta($mediaId, '_wp_attachment_image_alt', 'Operator correction only.');
        $this->setPostMeta($mediaId, '_acx_description_human_edit', [
            'alt_text'  => 'Operator correction only.',
            'edited_at' => '2026-07-04 12:00:00',
            'user_id'   => 1,
        ]);

        $response = (new DescriptionHistoryService())->list_history(10);

        $this->assertSame(1, $response['total']);
        $item = $response['items'][0];
        $this->assertSame($mediaId, $item['media_id']);
        $this->assertNull($item['provenance']);
        $this->assertIsArray($item['human_edit']);
        $this->assertSame('Operator correction only.', $item['human_edit']['alt_text']);
    }

    /**
     * Pending marker without alt must not invent a history row (narrow gate).
     */
    public function testListHistoryExcludesPendingMarkerWhenAltEmpty(): void
    {
        $mediaId = 505;
        $GLOBALS['__ac_get_posts_results'] = [$mediaId];
        $this->seedAttachment($mediaId, 'Marker only');
        $this->setPostMeta($mediaId, '_wp_attachment_image_alt', '');
        $this->setPostMeta($mediaId, '_acx_description_provenance_pending', [
            'run_id'     => 'single_image',
            'draft_hash' => hash('sha256', 'unused'),
        ]);

        $response = (new DescriptionHistoryService())->list_history(10);

        $this->assertSame(0, $response['total']);
    }

    /**
     * BR-100 end-to-end pin: plant a provenance envelope exactly as the single-
     * image REST writer (DescribeMediaService::build_generated_provenance) now
     * produces it, run it through DescriptionHistoryService, and assert
     * generated_alt_text is the draft — not ''. This is the assertion that
     * actually pins the History page's empty Generated-alt column bug.
     */
    public function testHistoryResolvesGeneratedAltFromRestWriterProvenanceShape(): void
    {
        $mediaId = 801;
        $draft = 'A photo of a red kayak on still water.';
        $GLOBALS['__ac_get_posts_results'] = [$mediaId];
        $this->seedAttachment($mediaId, 'Kayak');
        // Current alt may have been human-corrected after generation.
        $this->setPostMeta($mediaId, '_wp_attachment_image_alt', 'Human-corrected kayak alt.');
        // Envelope shape matches DescribeMediaService::build_generated_provenance
        // after BR-100 (identity keys + measured alt_text_draft).
        $this->setPostMeta($mediaId, '_acx_description_provenance', [
            'adapter'                => 'seeded',
            'model_id'               => 'seeded-fixtures',
            'model_version'          => '1',
            'prompt_or_task_version' => '1',
            'image_hash'             => str_repeat('a', 64),
            'context_hash'           => str_repeat('b', 64),
            'generated_at'           => '2026-07-04T12:00:00+00:00',
            'alt_text_draft'         => $draft,
        ]);

        $response = (new DescriptionHistoryService())->list_history(10);

        $this->assertSame(1, $response['total']);
        $item = $response['items'][0];
        $this->assertSame($mediaId, $item['media_id']);
        $this->assertSame('Human-corrected kayak alt.', $item['current_alt_text']);
        // The bug: without alt_text_draft on the envelope this was ''.
        $this->assertSame($draft, $item['generated_alt_text']);
        $this->assertNotSame('', $item['generated_alt_text']);
    }

    /**
     * BR-100 end-to-end pin for the CLI writer envelope shape (source => cli).
     */
    public function testHistoryResolvesGeneratedAltFromCliWriterProvenanceShape(): void
    {
        $mediaId = 802;
        $draft = 'A black dog sitting by a window.';
        $GLOBALS['__ac_get_posts_results'] = [$mediaId];
        $this->seedAttachment($mediaId, 'Dog');
        $this->setPostMeta($mediaId, '_wp_attachment_image_alt', $draft);
        // Envelope shape matches DescriptionCommand::build_provenance after BR-100.
        $this->setPostMeta($mediaId, '_acx_description_provenance', [
            'source'                 => 'cli',
            'media_id'               => $mediaId,
            'generated_at'           => '2026-07-04T12:00:00+00:00',
            'adapter'                => 'seeded',
            'model_id'               => 'local-v1',
            'model_version'          => '2026-07-04',
            'prompt_or_task_version' => 'describe-v1',
            'alt_text_draft'         => $draft,
        ]);

        $response = (new DescriptionHistoryService())->list_history(10);

        $this->assertSame(1, $response['total']);
        $item = $response['items'][0];
        $this->assertSame($mediaId, $item['media_id']);
        $this->assertSame($draft, $item['current_alt_text']);
        $this->assertSame($draft, $item['generated_alt_text']);
        $this->assertNotSame('', $item['generated_alt_text']);
        $this->assertSame('cli', $item['provenance']['source']);
    }

    /**
     * BR-100 regression: pre-fix provenance without any draft key still yields
     * empty generated_alt_text — history must not invent a draft from current alt.
     */
    public function testHistoryReturnsEmptyGeneratedAltWhenProvenanceLacksDraftKeys(): void
    {
        $mediaId = 803;
        $GLOBALS['__ac_get_posts_results'] = [$mediaId];
        $this->seedAttachment($mediaId, 'Legacy');
        $this->setPostMeta($mediaId, '_wp_attachment_image_alt', 'Some current alt.');
        // Pre-BR-100 single-image write shape: identity keys only, no draft.
        $this->setPostMeta($mediaId, '_acx_description_provenance', [
            'adapter'                => 'seeded',
            'model_id'               => 'seeded-fixtures',
            'model_version'          => '1',
            'prompt_or_task_version' => '1',
            'image_hash'             => str_repeat('a', 64),
            'context_hash'           => str_repeat('b', 64),
            'generated_at'           => '2026-01-01T00:00:00+00:00',
        ]);

        $response = (new DescriptionHistoryService())->list_history(10);

        $this->assertSame(1, $response['total']);
        $this->assertSame('Some current alt.', $response['items'][0]['current_alt_text']);
        $this->assertSame('', $response['items'][0]['generated_alt_text']);
    }

    /**
     * BR-123: preference order is load-bearing. When both the current key and a
     * legacy key are present with different strings, alt_text_draft wins.
     * Presence-only fixtures cannot pin priority — reordering the resolver
     * array must go RED against this test [TEST-15].
     */
    public function testGeneratedAltPrefersAltTextDraftOverLegacyKeys(): void
    {
        $mediaId = 804;
        $GLOBALS['__ac_get_posts_results'] = [$mediaId];
        $this->seedAttachment($mediaId, 'Priority');
        $this->setPostMeta($mediaId, '_wp_attachment_image_alt', 'Current alt.');
        $this->setPostMeta($mediaId, '_acx_description_provenance', [
            // Distinct strings so a reordered preference cannot pass by luck.
            'generated_alt_text' => 'LEGACY generated_alt_text value',
            'alt_text'           => 'LEGACY alt_text value',
            'alt_text_draft'     => 'CANONICAL alt_text_draft value',
            'model_id'           => 'local-v1',
        ]);

        $response = (new DescriptionHistoryService())->list_history(10);

        $this->assertSame(1, $response['total']);
        $this->assertSame(
            'CANONICAL alt_text_draft value',
            $response['items'][0]['generated_alt_text']
        );
        $this->assertNotSame(
            'LEGACY generated_alt_text value',
            $response['items'][0]['generated_alt_text']
        );
        $this->assertNotSame(
            'LEGACY alt_text value',
            $response['items'][0]['generated_alt_text']
        );
    }

    /**
     * BR-118 companion: when only a legacy key is present, the resolver still
     * surfaces it (fallbacks retained as defensive readers).
     */
    public function testGeneratedAltFallsBackToLegacyGeneratedAltTextKey(): void
    {
        $mediaId = 805;
        $GLOBALS['__ac_get_posts_results'] = [$mediaId];
        $this->seedAttachment($mediaId, 'Legacy-only');
        $this->setPostMeta($mediaId, '_wp_attachment_image_alt', 'Current alt.');
        $this->setPostMeta($mediaId, '_acx_description_provenance', [
            'generated_alt_text' => 'Only legacy draft present.',
            'model_id'           => 'local-v1',
        ]);

        $response = (new DescriptionHistoryService())->list_history(10);

        $this->assertSame(1, $response['total']);
        $this->assertSame('Only legacy draft present.', $response['items'][0]['generated_alt_text']);
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
     *
     * Code is description_correction_partial (not description_correction_failed):
     * the alt text IS in storage — material to client cache reconciliation. [WBUX-5-BR-55 task 2]
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
        $this->assertSame('description_correction_partial', $result->get_error_code());
        $this->assertSame(500, $result->get_error_data()['status']);
        $this->assertSame($newAlt, $result->get_error_data()['stored_alt_text']);
        $this->assertStringContainsString('Alt text was saved', $result->get_error_message());
        // Partial success: alt persisted, human-edit did not. [INT-11] does not undo alt.
        $this->assertSame($newAlt, get_post_meta($mediaId, '_wp_attachment_image_alt', true));
        $this->assertSame('', get_post_meta($mediaId, '_acx_description_human_edit', true));
    }

    /**
     * The partial WP_Error must report the *normalized* stored value, never echo
     * the raw request body. Client reconcile patches from this field; inventing
     * from the request would show markup/whitespace storage does not hold.
     * [rg-015]
     */
    public function testPartialErrorCarriesNormalizedStoredAltTextNotRawRequest(): void
    {
        $mediaId = 408;
        $rawRequest = '  <em>Sunset</em> over the bay  ';
        $normalized = 'Sunset over the bay';
        $this->seedAttachment($mediaId, 'Attachment 408');
        $this->setPostMeta($mediaId, '_wp_attachment_image_alt', 'Old alt.');
        $this->setPostMeta($mediaId, '_acx_description_provenance', [
            'alt_text_draft' => 'Generated draft.',
            'model_id' => 'local-v1',
        ]);
        $GLOBALS['__ac_update_post_meta_fail'][$mediaId]['_acx_description_human_edit'] = true;

        $result = (new DescriptionHistoryService())->record_correction($mediaId, $rawRequest);

        $this->assertInstanceOf(WP_Error::class, $result);
        $this->assertSame('description_correction_partial', $result->get_error_code());
        $errorData = $result->get_error_data();
        $this->assertIsArray($errorData);
        $this->assertSame(500, $errorData['status']);
        $this->assertArrayHasKey('stored_alt_text', $errorData);
        $this->assertSame($normalized, $errorData['stored_alt_text']);
        // Must not echo the unsanitized request body back in error data.
        $this->assertNotSame($rawRequest, $errorData['stored_alt_text']);
        $this->assertStringNotContainsString('<em>', (string) $errorData['stored_alt_text']);
        // Storage holds the same normalized value the error reports.
        $this->assertSame($normalized, get_post_meta($mediaId, '_wp_attachment_image_alt', true));
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
            ['media_id', 'title', 'mime_type', 'current_alt_text', 'generated_alt_text', 'provenance', 'human_edit', 'run_status', 'is_decorative'],
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
        $this->assertFalse($result['is_decorative']);
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
        $this->assertSame('description_correction_partial', $result->get_error_code());
        $this->assertSame(500, $result->get_error_data()['status']);
        $this->assertSame($newAlt, get_post_meta($mediaId, '_wp_attachment_image_alt', true));
        $this->assertSame('', get_post_meta($mediaId, '_acx_description_human_edit', true));
    }

    /**
     * BR-48b: the accepting branch of the human-edit read-back guard.
     * update_post_meta returns false for a full-payload no-op. Seed storage with
     * the exact marker this request would write, force the write to return false,
     * and require 200 with the full item envelope — not a spurious 500.
     */
    public function testHumanEditNoOpOverwriteStillSucceeds(): void
    {
        $mediaId = 406;
        $sameAlt = 'Already human-edited alt.';
        $this->seedAttachment($mediaId, 'Attachment 406');
        $this->setPostMeta($mediaId, '_wp_attachment_image_alt', $sameAlt);
        $this->setPostMeta($mediaId, '_acx_description_provenance', [
            'alt_text_draft' => 'Generated draft.',
            'model_id' => 'local-v1',
        ]);
        // BR-50: freeze current_time so seed and record_correction share one
        // edited_at by construction — not by same-second luck across a boundary.
        $GLOBALS['__ac_current_time'] = 1_700_000_000;
        $frozenMysql = current_time('mysql');
        // Matching full marker: same alt_text, edited_at, user_id.
        // A genuine same-second re-save produces an identical payload; the write
        // returns false as a no-op and the read-back must still accept it.
        $matchingMarker = [
            'alt_text' => $sameAlt,
            'edited_at' => $frozenMysql,
            'user_id' => get_current_user_id(),
        ];
        $this->setPostMeta($mediaId, '_acx_description_human_edit', $matchingMarker);
        $GLOBALS['__ac_update_post_meta_fail'][$mediaId]['_acx_description_human_edit'] = true;

        $result = (new DescriptionHistoryService())->record_correction($mediaId, $sameAlt);

        $this->assertNotInstanceOf(WP_Error::class, $result);
        $this->assertIsArray($result);
        $this->assertSame(
            ['media_id', 'title', 'mime_type', 'current_alt_text', 'generated_alt_text', 'provenance', 'human_edit', 'run_status', 'is_decorative'],
            array_keys($result)
        );
        $this->assertSame($mediaId, $result['media_id']);
        $this->assertSame($sameAlt, $result['current_alt_text']);
        $this->assertFalse($result['is_decorative']);
        $this->assertIsArray($result['human_edit']);
        $this->assertSame($matchingMarker, $result['human_edit']);
        $this->assertSame($matchingMarker, get_post_meta($mediaId, '_acx_description_human_edit', true));
        // [TEST-15] / BR-50: seed and constructed payloads share edited_at by
        // freeze construction (fixed unix second), not wall-clock luck.
        $this->assertSame('2023-11-14 22:13:20', $frozenMysql);
        $this->assertSame($frozenMysql, $result['human_edit']['edited_at']);
        unset($GLOBALS['__ac_current_time']);
    }

    /**
     * BR-48a: a stale prior marker with the same alt_text but different edited_at
     * / user_id must not forge success when the human-edit write fails. Full
     * payload equality is required; alt_text-only comparison would 200 incorrectly.
     */
    public function testStaleHumanEditMarkerDoesNotForgeNoOpSuccess(): void
    {
        $mediaId = 407;
        $sameAlt = 'Same text, stale telemetry.';
        $this->seedAttachment($mediaId, 'Attachment 407');
        $this->setPostMeta($mediaId, '_wp_attachment_image_alt', $sameAlt);
        $this->setPostMeta($mediaId, '_acx_description_provenance', [
            'alt_text_draft' => 'Generated draft.',
            'model_id' => 'local-v1',
        ]);
        // BR-50: freeze so the constructed request payload is deterministic while
        // the stored marker stays intentionally stale (full-array inequality).
        $GLOBALS['__ac_current_time'] = 1_700_000_000;
        // Prior session marker: same alt_text, older time, different operator.
        $staleMarker = [
            'alt_text' => $sameAlt,
            'edited_at' => '2020-01-01 00:00:00',
            'user_id' => 999,
        ];
        $this->setPostMeta($mediaId, '_acx_description_human_edit', $staleMarker);
        $GLOBALS['__ac_update_post_meta_fail'][$mediaId]['_acx_description_human_edit'] = true;

        $result = (new DescriptionHistoryService())->record_correction($mediaId, $sameAlt);

        $this->assertInstanceOf(WP_Error::class, $result);
        // Same third-case code as a fresh human-edit write failure: alt is verified
        // (no-op read-back), human-edit marker is not. [WBUX-5-BR-55 task 2]
        $this->assertSame('description_correction_partial', $result->get_error_code());
        $this->assertSame(500, $result->get_error_data()['status']);
        // No-op alt write still stored the value; the partial must report it.
        $this->assertSame($sameAlt, $result->get_error_data()['stored_alt_text']);
        $this->assertStringContainsString('Alt text was saved', $result->get_error_message());
        // Stale marker left untouched — must not be treated as this correction's telemetry.
        $this->assertSame($staleMarker, get_post_meta($mediaId, '_acx_description_human_edit', true));
        $this->assertSame($sameAlt, get_post_meta($mediaId, '_wp_attachment_image_alt', true));
        unset($GLOBALS['__ac_current_time']);
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
     * BR-55: the post-write build_item-null path is unreachable under normal
     * control flow (verified human-edit write implies an array is in storage,
     * so build_item is total). A silent success envelope on that state is the
     * [RLSE-05] shape BR-40 removed. Production must return WP_Error 500, not
     * a hand-built eight-key (or any) success array.
     *
     * Forced via protected override — no legitimate input reaches null after
     * verified writes under the stubs (or real WP storage).
     */
    public function testBuildItemNullAfterVerifiedWritesReturnsErrorNotSuccessEnvelope(): void
    {
        $mediaId = 701;
        $this->seedAttachment($mediaId, 'Force-null photo', 'image/jpeg');
        $this->setPostMeta($mediaId, '_wp_attachment_image_alt', 'Prior alt.');

        $service = new class() extends DescriptionHistoryService {
            protected function build_item(int $media_id): ?array
            {
                return null;
            }
        };

        $result = $service->record_correction($mediaId, 'Corrected despite null build.');

        $this->assertInstanceOf(WP_Error::class, $result);
        $this->assertSame('description_correction_failed', $result->get_error_code());
        $this->assertSame(500, $result->get_error_data()['status']);
        $this->assertStringContainsString('could not be loaded', $result->get_error_message());
        // Writes still landed — this is assembly failure, not a rolled-back correction.
        $this->assertSame('Corrected despite null build.', get_post_meta($mediaId, '_wp_attachment_image_alt', true));
        $this->assertIsArray(get_post_meta($mediaId, '_acx_description_human_edit', true));
    }

    /**
     * Task 2 discrimination: bare alt-write failure (nothing persisted) keeps
     * description_correction_failed — must not be conflated with the partial code.
     * Companion to testHumanEditWriteFailureReturnsErrorAfterAltSaved.
     */
    public function testAltWriteFailureKeepsFailedCodeNotPartial(): void
    {
        $mediaId = 702;
        $existingAlt = 'Still the only alt.';
        $requestedAlt = 'Never lands.';
        $this->seedAttachment($mediaId, 'Attachment 702');
        $this->setPostMeta($mediaId, '_wp_attachment_image_alt', $existingAlt);
        $GLOBALS['__ac_update_post_meta_fail'][$mediaId]['_wp_attachment_image_alt'] = true;

        $result = (new DescriptionHistoryService())->record_correction($mediaId, $requestedAlt);

        $this->assertInstanceOf(WP_Error::class, $result);
        $this->assertSame('description_correction_failed', $result->get_error_code());
        $this->assertNotSame('description_correction_partial', $result->get_error_code());
        $this->assertSame(500, $result->get_error_data()['status']);
        $this->assertSame($existingAlt, get_post_meta($mediaId, '_wp_attachment_image_alt', true));
    }

    /**
     * BR-17: alt text containing a Windows path backslash must save successfully,
     * and saving it a second and third time must still succeed — not a permanent
     * 500. Pre-fix: compare against the raw draft (not wp_unslash) treated every
     * re-save as failure because update_metadata() stores the unslashed form.
     */
    public function testBackslashBearingAltSavesAndResavesSuccessfully(): void
    {
        $mediaId = 801;
        // Literal backslash before U — the value operators type for Windows paths.
        $altWithBackslash = 'Blueprint of the C:\\Users share, annotated';
        $this->seedAttachment($mediaId, 'Attachment 801');
        $this->setPostMeta($mediaId, '_acx_description_provenance', [
            'alt_text_draft' => 'Generated draft.',
            'model_id' => 'local-v1',
        ]);

        $service = new DescriptionHistoryService();

        $first = $service->record_correction($mediaId, $altWithBackslash);
        $this->assertNotInstanceOf(WP_Error::class, $first);
        $this->assertIsArray($first);
        // WP stores the unslashed form; history reports what storage holds.
        $stored = get_post_meta($mediaId, '_wp_attachment_image_alt', true);
        $this->assertSame(wp_unslash($altWithBackslash), $stored);
        $this->assertSame($stored, $first['current_alt_text']);

        $second = $service->record_correction($mediaId, $altWithBackslash);
        $this->assertNotInstanceOf(WP_Error::class, $second, 'Second save with same backslash alt must not 500');
        $this->assertIsArray($second);

        $third = $service->record_correction($mediaId, $altWithBackslash);
        $this->assertNotInstanceOf(WP_Error::class, $third, 'Third save with same backslash alt must not 500');
        $this->assertIsArray($third);
        $this->assertSame(wp_unslash($altWithBackslash), get_post_meta($mediaId, '_wp_attachment_image_alt', true));
    }

    /**
     * WBUX-5-R16-BR-10 / BR-17 / S3-02: natural no-op (byte-identical re-save;
     * update_post_meta returns false like core) succeeds because read-back
     * confirmed the stored value — not because a false write return was ignored.
     * Skipping the false-branch leaves alt_ok false → error. Distinct from the
     * forced-false testNoOpOverwriteStillSucceeds.
     */
    public function testNaturalNoOpOverwriteStillSucceeds(): void
    {
        $mediaId = 802;
        $sameAlt = 'Already stored alt for natural no-op.';
        $this->seedAttachment($mediaId, 'Attachment 802');
        $this->setPostMeta($mediaId, '_wp_attachment_image_alt', $sameAlt);
        $this->setPostMeta($mediaId, '_acx_description_provenance', [
            'alt_text_draft' => 'Generated draft.',
            'model_id' => 'local-v1',
        ]);

        $result = (new DescriptionHistoryService())->record_correction($mediaId, $sameAlt);

        $this->assertNotInstanceOf(WP_Error::class, $result);
        $this->assertIsArray($result);
        $this->assertSame($sameAlt, $result['current_alt_text']);
        // Post-write stored value — pins that read-back accepted the no-op.
        $this->assertSame($sameAlt, get_post_meta($mediaId, '_wp_attachment_image_alt', true));
        $humanEdit = get_post_meta($mediaId, '_acx_description_human_edit', true);
        $this->assertIsArray($humanEdit);
        $this->assertSame($sameAlt, $humanEdit['alt_text'] ?? null);
    }

    /**
     * R16-BR-15: when a sanitize_post_meta_{key} filter alters the stored alt,
     * the no-op read-back must still succeed. Core update_metadata unslashes then
     * sanitize_meta before store/equality; comparing only wp_unslash() false-500s
     * a write that landed.
     *
     * Stub fidelity: tests/stubs/wp.php update_post_meta unslashes but does NOT
     * call sanitize_meta. This test therefore plants the post-sanitize form and
     * forces update_post_meta false (core no-op after a prior successful write),
     * rather than relying on the stub to round-trip the filter. The filter is
     * still registered so the service's expected-value path exercises it.
     */
    public function testSanitizeMetaAlteredAltReportsSuccessOnNoOpReadBack(): void
    {
        $mediaId = 901;
        $submitted = 'Operator alt before meta sanitize';
        $normalized = sanitize_text_field(trim($submitted));

        // Filter that actually changes the value — identity would not pin R16-BR-15.
        add_filter(
            'sanitize_post_meta__wp_attachment_image_alt',
            static function ($value) {
                return is_string($value) ? $value . ' [meta-sanitized]' : $value;
            },
            10,
            1
        );

        // What core stores after unslash + sanitize_meta (and what the service
        // must expect). Plant it: the stub write path would not. Harness has no
        // sanitize_meta; apply the same filter chain sanitize_meta dispatches.
        $storedForm = apply_filters(
            'sanitize_post_meta__wp_attachment_image_alt',
            wp_unslash($normalized),
            '_wp_attachment_image_alt',
            'post'
        );
        $this->assertSame($normalized . ' [meta-sanitized]', $storedForm);
        $this->assertNotSame($normalized, $storedForm);

        $this->seedAttachment($mediaId, 'Attachment 901');
        $this->setPostMeta($mediaId, '_wp_attachment_image_alt', $storedForm);
        $this->setPostMeta($mediaId, '_acx_description_provenance', [
            'alt_text_draft' => 'Generated draft.',
            'model_id' => 'local-v1',
        ]);
        // Simulate no-op return after core would have stored the sanitized form.
        $GLOBALS['__ac_update_post_meta_fail'][$mediaId]['_wp_attachment_image_alt'] = true;

        $result = (new DescriptionHistoryService())->record_correction($mediaId, $submitted);

        $this->assertNotInstanceOf(
            WP_Error::class,
            $result,
            'sanitize_meta-altered stored alt must not false-500 on no-op read-back'
        );
        $this->assertIsArray($result);
        // Storage still holds the sanitized form; history reports it.
        $this->assertSame($storedForm, get_post_meta($mediaId, '_wp_attachment_image_alt', true));
        $this->assertSame($storedForm, $result['current_alt_text']);
        $this->assertIsArray($result['human_edit']);
    }

    /**
     * R16-BR-15 companion: HUMAN_EDIT_META guard must also apply sanitize_meta
     * before full-payload no-op comparison. A filter that mutates the array
     * shape must not forge description_correction_partial when storage already
     * holds the sanitized payload. Full-array equality remains (BR-48a).
     *
     * Same stub limitation as the alt test: plant sanitized form + fail hook.
     */
    public function testSanitizeMetaAlteredHumanEditReportsSuccessOnNoOpReadBack(): void
    {
        $mediaId = 902;
        $sameAlt = 'Human-edit sanitize no-op alt.';
        $this->seedAttachment($mediaId, 'Attachment 902');
        $this->setPostMeta($mediaId, '_wp_attachment_image_alt', $sameAlt);
        $this->setPostMeta($mediaId, '_acx_description_provenance', [
            'alt_text_draft' => 'Generated draft.',
            'model_id' => 'local-v1',
        ]);

        add_filter(
            'sanitize_post_meta__acx_description_human_edit',
            static function ($value) {
                if (!is_array($value)) {
                    return $value;
                }
                // Distinct key so bare unslash equality fails while full sanitize matches.
                $value['sanitized_by'] = 'meta-filter';
                return $value;
            },
            10,
            1
        );

        $GLOBALS['__ac_current_time'] = 1_700_000_000;
        $frozenMysql = current_time('mysql');
        $rawPayload = [
            'alt_text' => $sameAlt,
            'edited_at' => $frozenMysql,
            'user_id' => get_current_user_id(),
        ];
        // Harness has no sanitize_meta; same filter chain core/sanitize_meta uses.
        $storedForm = apply_filters(
            'sanitize_post_meta__acx_description_human_edit',
            wp_unslash($rawPayload),
            '_acx_description_human_edit',
            'post'
        );
        $this->assertIsArray($storedForm);
        $this->assertSame('meta-filter', $storedForm['sanitized_by']);
        $this->assertNotSame($rawPayload, $storedForm);

        $this->setPostMeta($mediaId, '_acx_description_human_edit', $storedForm);
        $GLOBALS['__ac_update_post_meta_fail'][$mediaId]['_acx_description_human_edit'] = true;

        $result = (new DescriptionHistoryService())->record_correction($mediaId, $sameAlt);

        $this->assertNotInstanceOf(WP_Error::class, $result);
        $this->assertIsArray($result);
        $this->assertSame($storedForm, get_post_meta($mediaId, '_acx_description_human_edit', true));
        $this->assertSame($storedForm, $result['human_edit']);
        unset($GLOBALS['__ac_current_time']);
    }

    /**
     * R20-BR-21: empty-array pending meta is not a recovery marker.
     */
    public function testListHistoryExcludesEmptyArrayPendingMarker(): void
    {
        $mediaId = 510;
        $GLOBALS['__ac_get_posts_results'] = [$mediaId];
        $this->seedAttachment($mediaId, 'Empty marker');
        $this->setPostMeta($mediaId, '_wp_attachment_image_alt', 'Human-authored alt');
        $this->setPostMeta($mediaId, '_acx_description_provenance_pending', []);

        $response = (new DescriptionHistoryService())->list_history(10);

        $this->assertSame(0, $response['total']);
        $this->assertSame([], $response['items']);
    }

    /**
     * R20-BR-21: partial-shape pending (missing draft_hash) is not recovery evidence.
     */
    public function testListHistoryExcludesPartialShapePendingMarker(): void
    {
        $mediaId = 511;
        $GLOBALS['__ac_get_posts_results'] = [$mediaId];
        $this->seedAttachment($mediaId, 'Partial marker');
        $this->setPostMeta($mediaId, '_wp_attachment_image_alt', 'Human-authored alt');
        $this->setPostMeta($mediaId, '_acx_description_provenance_pending', [
            'run_id' => 'single_image',
            // draft_hash absent
        ]);

        $response = (new DescriptionHistoryService())->list_history(10);

        $this->assertSame(0, $response['total']);
        $this->assertSame([], $response['items']);
    }

    /**
     * R21-BR-12: empty-string draft_hash is not a verified recovery marker.
     * Dropping the empty-string check on draft_hash must redden this pin.
     */
    public function testListHistoryExcludesEmptyStringDraftHashPendingMarker(): void
    {
        $mediaId = 513;
        $GLOBALS['__ac_get_posts_results'] = [$mediaId];
        $this->seedAttachment($mediaId, 'Empty draft_hash');
        $this->setPostMeta($mediaId, '_wp_attachment_image_alt', 'Human-authored alt');
        $this->setPostMeta($mediaId, '_acx_description_provenance_pending', [
            'run_id' => 'single_image',
            'draft_hash' => '',
        ]);

        $response = (new DescriptionHistoryService())->list_history(10);

        $this->assertSame(0, $response['total']);
        $this->assertFalse(
            DescriptionHistoryService::is_verified_pending_marker([
                'run_id' => 'single_image',
                'draft_hash' => '',
            ])
        );
    }

    /**
     * R21-BR-12: empty-string run_id is not a verified recovery marker.
     */
    public function testListHistoryExcludesEmptyStringRunIdPendingMarker(): void
    {
        $mediaId = 514;
        $GLOBALS['__ac_get_posts_results'] = [$mediaId];
        $this->seedAttachment($mediaId, 'Empty run_id');
        $this->setPostMeta($mediaId, '_wp_attachment_image_alt', 'Human-authored alt');
        $this->setPostMeta($mediaId, '_acx_description_provenance_pending', [
            'run_id' => '',
            'draft_hash' => hash('sha256', 'Human-authored alt'),
        ]);

        $response = (new DescriptionHistoryService())->list_history(10);

        $this->assertSame(0, $response['total']);
        $this->assertFalse(
            DescriptionHistoryService::is_verified_pending_marker([
                'run_id' => '',
                'draft_hash' => hash('sha256', 'Human-authored alt'),
            ])
        );
    }

    /**
     * R21-BR-12: whitespace-only fields are rejected (predicate trims).
     */
    public function testListHistoryExcludesWhitespaceOnlyPendingMarkerFields(): void
    {
        $mediaId = 515;
        $GLOBALS['__ac_get_posts_results'] = [$mediaId];
        $this->seedAttachment($mediaId, 'Whitespace marker');
        $this->setPostMeta($mediaId, '_wp_attachment_image_alt', 'Human-authored alt');
        $this->setPostMeta($mediaId, '_acx_description_provenance_pending', [
            'run_id' => '   ',
            'draft_hash' => "\t",
        ]);

        $response = (new DescriptionHistoryService())->list_history(10);

        $this->assertSame(0, $response['total']);
        $this->assertFalse(
            DescriptionHistoryService::is_verified_pending_marker([
                'run_id' => '   ',
                'draft_hash' => "\t",
            ])
        );
        // Integer 0 is not a string — also rejected.
        $this->assertFalse(
            DescriptionHistoryService::is_verified_pending_marker([
                'run_id' => 'single_image',
                'draft_hash' => 0,
            ])
        );
    }

    /**
     * R23-BR-01 [TEST-15]: alt write returns non-false but storage diverges →
     * description_correction_failed (not success). Pins unconditional alt
     * read-back. RED under: restore `if ( false === $alt_written )` around the
     * alt read-back so a non-false mutate-on-write is trusted.
     */
    public function testAltWriteDivergentNonFalseStoreReportsCorrectionFailed(): void
    {
        $mediaId = 903;
        $this->seedAttachment($mediaId, 'Attachment 903');
        $this->setPostMeta($mediaId, '_wp_attachment_image_alt', 'Prior alt.');
        $this->setPostMeta($mediaId, '_acx_description_provenance', [
            'alt_text_draft' => 'Generated draft.',
            'model_id' => 'local-v1',
        ]);
        $GLOBALS['__ac_update_post_meta_mutate'][$mediaId]['_wp_attachment_image_alt'] = 'MUTATED HISTORY ALT';

        $result = (new DescriptionHistoryService())->record_correction($mediaId, 'Operator corrected alt.');

        $this->assertInstanceOf(WP_Error::class, $result);
        $this->assertSame('description_correction_failed', $result->get_error_code());
        $this->assertSame(500, $result->get_error_data()['status']);
        $this->assertSame('MUTATED HISTORY ALT', get_post_meta($mediaId, '_wp_attachment_image_alt', true));
        // [INT-11] failed alt must not stamp human-edit meta.
        $this->assertSame('', get_post_meta($mediaId, '_acx_description_human_edit', true));
    }

    /**
     * R23-BR-01 [TEST-15]: human-edit write returns non-false but storage
     * diverges → description_correction_partial. Pins unconditional human-edit
     * full-payload read-back [BR-48a]. RED under: restore
     * `if ( false === $human_written )` only (alt leg stays fixed so this pin
     * cannot vouch for both).
     */
    public function testHumanEditWriteDivergentNonFalseStoreReportsPartial(): void
    {
        $mediaId = 904;
        $newAlt = 'Operator corrected alt for partial pin.';
        $this->seedAttachment($mediaId, 'Attachment 904');
        $this->setPostMeta($mediaId, '_wp_attachment_image_alt', 'Prior alt.');
        $this->setPostMeta($mediaId, '_acx_description_provenance', [
            'alt_text_draft' => 'Generated draft.',
            'model_id' => 'local-v1',
        ]);
        $GLOBALS['__ac_update_post_meta_mutate'][$mediaId]['_acx_description_human_edit'] = ['garbage' => true];

        $result = (new DescriptionHistoryService())->record_correction($mediaId, $newAlt);

        $this->assertInstanceOf(WP_Error::class, $result);
        $this->assertSame('description_correction_partial', $result->get_error_code());
        $this->assertSame(500, $result->get_error_data()['status']);
        $this->assertSame($newAlt, $result->get_error_data()['stored_alt_text']);
        // Alt verified and left in place; human-edit holds the divergent garbage.
        $this->assertSame($newAlt, get_post_meta($mediaId, '_wp_attachment_image_alt', true));
        $this->assertSame(['garbage' => true], get_post_meta($mediaId, '_acx_description_human_edit', true));
    }

    /**
     * R20-BR-25: successful record_correction must delete a zombie pending marker.
     */
    public function testRecordCorrectionDeletesStaleProvenancePendingMarker(): void
    {
        $mediaId = 512;
        $this->seedAttachment($mediaId, 'Correction clears marker');
        $this->setPostMeta($mediaId, '_wp_attachment_image_alt', 'Prior alt with gap.');
        $this->setPostMeta($mediaId, '_acx_description_provenance_pending', [
            'run_id'     => 'single_image',
            'draft_hash' => hash('sha256', 'Prior alt with gap.'),
        ]);

        $result = (new DescriptionHistoryService())->record_correction($mediaId, 'Operator fixed alt.');

        $this->assertNotInstanceOf(WP_Error::class, $result);
        $this->assertSame('', get_post_meta($mediaId, '_acx_description_provenance_pending', true));
        $this->assertIsArray(get_post_meta($mediaId, '_acx_description_human_edit', true));

        $GLOBALS['__ac_get_posts_results'] = [$mediaId];
        $history = (new DescriptionHistoryService())->list_history(10);
        $this->assertSame(1, $history['total']);
        $this->assertIsArray($history['items'][0]['human_edit']);
        $this->assertNull($history['items'][0]['provenance']);
        // Not a pure gap: human_edit present, marker gone.
        $this->assertSame('', get_post_meta($mediaId, '_acx_description_provenance_pending', true));
    }

    /**
     * WBUX-5-S2C3C-BR-01: decorative=true + empty alt stores the marker AND empty alt.
     * Discriminates against code that ignores the flag or refuses empty alt.
     */
    public function testDecorativeCorrectionStoresEmptyAltAndMarker(): void
    {
        $mediaId = 601;
        $this->seedAttachment($mediaId, 'Spacer image');
        $this->setPostMeta($mediaId, '_wp_attachment_image_alt', 'Prior descriptive alt.');

        $result = (new DescriptionHistoryService())->record_correction($mediaId, '', true);

        $this->assertNotInstanceOf(WP_Error::class, $result);
        $this->assertSame('', get_post_meta($mediaId, '_wp_attachment_image_alt', true));
        $this->assertSame('1', get_post_meta($mediaId, 'acx_alt_decorative', true));
        $this->assertSame('', $result['current_alt_text']);
        // Human-edit telemetry still lands for a deliberate decorative decision.
        $humanEdit = get_post_meta($mediaId, '_acx_description_human_edit', true);
        $this->assertIsArray($humanEdit);
        $this->assertSame('', $humanEdit['alt_text']);
    }

    /**
     * Contradiction: decorative=true with non-empty alt is 400; neither alt nor
     * marker is written. Discriminates against silent coercion (blanking alt or
     * ignoring the flag) and against accepting the request as success.
     */
    public function testDecorativeWithNonEmptyAltIsRejectedAndWritesNothing(): void
    {
        $mediaId = 602;
        $priorAlt = 'Prior real alt.';
        $this->seedAttachment($mediaId, 'Contradiction image');
        $this->setPostMeta($mediaId, '_wp_attachment_image_alt', $priorAlt);
        // Ensure no marker exists beforehand.
        $this->assertSame('', get_post_meta($mediaId, 'acx_alt_decorative', true));

        $result = (new DescriptionHistoryService())->record_correction(
            $mediaId,
            'Should not land',
            true
        );

        $this->assertInstanceOf(WP_Error::class, $result);
        $this->assertSame('description_correction_failed', $result->get_error_code());
        $this->assertSame(400, $result->get_error_data()['status']);
        $this->assertStringContainsString('decorative', strtolower($result->get_error_message()));
        $this->assertStringContainsString('non-empty', strtolower($result->get_error_message()));
        // Neither alt nor marker written.
        $this->assertSame($priorAlt, get_post_meta($mediaId, '_wp_attachment_image_alt', true));
        $this->assertSame('', get_post_meta($mediaId, 'acx_alt_decorative', true));
        $this->assertSame('', get_post_meta($mediaId, '_acx_description_human_edit', true));

        // Controller path surfaces the same 400.
        $controller = new DescribeController();
        $request = new WP_REST_Request('POST', '/acx/v1/recognition/describe/history/' . $mediaId . '/correction');
        $request->set_param('media_id', $mediaId);
        $request->set_param('alt_text', 'Should not land');
        $request->set_param('decorative', true);

        $response = $controller->correct_description_history_item($request);
        $this->assertInstanceOf(WP_Error::class, $response);
        $this->assertSame('description_correction_failed', $response->get_error_code());
        $this->assertSame(400, $response->get_error_data()['status']);
        $this->assertSame($priorAlt, get_post_meta($mediaId, '_wp_attachment_image_alt', true));
        $this->assertSame('', get_post_meta($mediaId, 'acx_alt_decorative', true));
    }

    /**
     * Self-healing: non-empty alt correction on a previously-decorative image
     * clears the marker. Discriminates against code that only plants the marker
     * and never deletes it.
     */
    public function testNonEmptyCorrectionClearsPriorDecorativeMarker(): void
    {
        $mediaId = 603;
        $this->seedAttachment($mediaId, 'Was decorative');
        $this->setPostMeta($mediaId, '_wp_attachment_image_alt', '');
        $this->setPostMeta($mediaId, 'acx_alt_decorative', '1');

        $result = (new DescriptionHistoryService())->record_correction(
            $mediaId,
            'Now has a real description.'
        );

        $this->assertNotInstanceOf(WP_Error::class, $result);
        $this->assertSame('Now has a real description.', get_post_meta($mediaId, '_wp_attachment_image_alt', true));
        // Marker deleted (not set to ''/'0') — get_post_meta returns '' when absent.
        $this->assertSame('', get_post_meta($mediaId, 'acx_alt_decorative', true));
        $this->assertArrayNotHasKey(
            'acx_alt_decorative',
            $GLOBALS['__ac_post_meta'][$mediaId] ?? []
        );

        // Candidate service reclassifies to has_alt_text, not decorative.
        $candidate = new \AltContext\Api\Services\DescriptionCandidateService();
        $status = $candidate->get_status_for_media_ids([$mediaId]);
        $this->assertSame('has_alt_text', $status[0]['reason']);
        $this->assertNotSame('decorative', $status[0]['reason']);
    }

    /**
     * A-04: decorative clear must be verified. If delete_post_meta fails and the
     * marker remains '1', return description_correction_partial (same code +
     * stored_alt_text shape as the plant failure) so the client onError reconcile
     * path runs. Claiming 200 while isDecorative stays true on the next fetch is
     * a durable-contract lie [rg-002][INT-09].
     *
     * CO-01: clear-failure PARTIAL is deferred until after human-edit write —
     * human_edit meta must be present even when the marker clear failed.
     */
    public function testDecorativeMarkerClearFailureReturnsPartial(): void
    {
        $mediaId = 611;
        $newAlt = 'Described after decorative clear fail.';
        $this->seedAttachment($mediaId, 'Decorative clear fail');
        $this->setPostMeta($mediaId, '_wp_attachment_image_alt', '');
        $this->setPostMeta($mediaId, 'acx_alt_decorative', '1');
        // Force delete of the decorative marker to no-op; read-back still sees '1'.
        $GLOBALS['__ac_delete_post_meta_fail'][$mediaId]['acx_alt_decorative'] = true;

        $result = (new DescriptionHistoryService())->record_correction($mediaId, $newAlt);

        $this->assertInstanceOf(WP_Error::class, $result);
        $this->assertSame('description_correction_partial', $result->get_error_code());
        $errorData = $result->get_error_data();
        $this->assertIsArray($errorData);
        $this->assertSame(500, $errorData['status']);
        $this->assertSame($newAlt, $errorData['stored_alt_text']);
        // Alt write landed; marker still present (delete failed).
        $this->assertSame($newAlt, get_post_meta($mediaId, '_wp_attachment_image_alt', true));
        $this->assertSame('1', get_post_meta($mediaId, 'acx_alt_decorative', true));
        // [CO-01] human_edit must land even when clear failed — deferred failure.
        $this->assertIsArray(get_post_meta($mediaId, '_acx_description_human_edit', true));
        $this->assertStringContainsString('decorative marker could not be cleared', strtolower($result->get_error_message()));
    }

    /**
     * Empty non-decorative correction must leave a prior decorative marker intact.
     * Blanking alt does not un-mark a decorative image; only a non-empty alt does.
     * [WBUX-5-R1-02][WBUX-5-D-01]
     */
    public function testEmptyNonDecorativeCorrectionPreservesPriorDecorativeMarker(): void
    {
        $mediaId = 609;
        $this->seedAttachment($mediaId, 'Stay decorative');
        $this->setPostMeta($mediaId, '_wp_attachment_image_alt', '');
        $this->setPostMeta($mediaId, 'acx_alt_decorative', '1');

        $result = (new DescriptionHistoryService())->record_correction($mediaId, '');

        $this->assertNotInstanceOf(WP_Error::class, $result);
        $this->assertSame('', get_post_meta($mediaId, '_wp_attachment_image_alt', true));
        $this->assertSame('1', get_post_meta($mediaId, 'acx_alt_decorative', true));
    }

    /**
     * Human-edit PARTIAL after a verified non-empty alt must still clear a prior
     * decorative marker. Clear runs as soon as alt verifies — before the human-edit
     * write — so the early PARTIAL return leaves disk consistent. [WBUX-5-R3-01]
     */
    public function testPartialHumanEditFailureClearsPriorDecorativeMarkerOnNonEmptyAlt(): void
    {
        $mediaId = 610;
        $newAlt = 'Partial-saved real description.';
        $this->seedAttachment($mediaId, 'Partial self-heal');
        $this->setPostMeta($mediaId, '_wp_attachment_image_alt', '');
        $this->setPostMeta($mediaId, 'acx_alt_decorative', '1');
        $GLOBALS['__ac_update_post_meta_fail'][$mediaId]['_acx_description_human_edit'] = true;

        $result = (new DescriptionHistoryService())->record_correction($mediaId, $newAlt);

        $this->assertInstanceOf(WP_Error::class, $result);
        $this->assertSame('description_correction_partial', $result->get_error_code());
        $this->assertSame($newAlt, get_post_meta($mediaId, '_wp_attachment_image_alt', true));
        $this->assertSame($newAlt, $result->get_error_data()['stored_alt_text']);
        // Marker must be gone even though human-edit failed.
        $this->assertSame('', get_post_meta($mediaId, 'acx_alt_decorative', true));
        $this->assertArrayNotHasKey(
            'acx_alt_decorative',
            $GLOBALS['__ac_post_meta'][$mediaId] ?? []
        );
    }

    /**
     * Failed alt write must not plant the decorative marker. Discriminates
     * against writing the marker before alt read-back verification.
     */
    public function testFailedAltWriteDoesNotPlantDecorativeMarker(): void
    {
        $mediaId = 604;
        $this->seedAttachment($mediaId, 'Unwritable decorative');
        $this->setPostMeta($mediaId, '_wp_attachment_image_alt', 'Existing alt.');
        // Force alt write failure (returns false, does not persist).
        $GLOBALS['__ac_update_post_meta_fail'][$mediaId]['_wp_attachment_image_alt'] = true;

        $result = (new DescriptionHistoryService())->record_correction($mediaId, '', true);

        $this->assertInstanceOf(WP_Error::class, $result);
        $this->assertSame('description_correction_failed', $result->get_error_code());
        $this->assertSame(500, $result->get_error_data()['status']);
        // Prior alt unchanged; decorative marker never planted.
        $this->assertSame('Existing alt.', get_post_meta($mediaId, '_wp_attachment_image_alt', true));
        $this->assertSame('', get_post_meta($mediaId, 'acx_alt_decorative', true));
        $this->assertArrayNotHasKey(
            'acx_alt_decorative',
            $GLOBALS['__ac_post_meta'][$mediaId] ?? []
        );
        $this->assertSame('', get_post_meta($mediaId, '_acx_description_human_edit', true));
    }

    /**
     * Partial-failure path (alt landed, human-edit did not) must not plant the
     * decorative marker either — a marker without a completed correction is a lie.
     */
    public function testPartialFailureDoesNotPlantDecorativeMarker(): void
    {
        $mediaId = 605;
        $this->seedAttachment($mediaId, 'Partial decorative');
        $this->setPostMeta($mediaId, '_wp_attachment_image_alt', 'Old alt.');
        $GLOBALS['__ac_update_post_meta_fail'][$mediaId]['_acx_description_human_edit'] = true;

        $result = (new DescriptionHistoryService())->record_correction($mediaId, '', true);

        $this->assertInstanceOf(WP_Error::class, $result);
        $this->assertSame('description_correction_partial', $result->get_error_code());
        // Alt empty landed; marker must not.
        $this->assertSame('', get_post_meta($mediaId, '_wp_attachment_image_alt', true));
        $this->assertSame('', get_post_meta($mediaId, 'acx_alt_decorative', true));
        $this->assertArrayNotHasKey(
            'acx_alt_decorative',
            $GLOBALS['__ac_post_meta'][$mediaId] ?? []
        );
    }

    /**
     * S7-BR-03: decorative marker write must be read back. If update_post_meta for
     * acx_alt_decorative fails (same __ac_update_post_meta_fail injection as alt /
     * human-edit), record_correction must return WP_Error — never a success
     * envelope while the durable marker is absent. Empty alt may land; without
     * the marker DescriptionCandidateService would misclassify as missing_alt.
     */
    public function testDecorativeMarkerWriteFailureReturnsErrorAndDoesNotClaimSuccess(): void
    {
        $mediaId = 608;
        $this->seedAttachment($mediaId, 'Decorative marker fail');
        $this->setPostMeta($mediaId, '_wp_attachment_image_alt', 'Prior alt.');
        // Force only the decorative-marker write to fail; alt + human-edit succeed.
        $GLOBALS['__ac_update_post_meta_fail'][$mediaId]['acx_alt_decorative'] = true;

        $result = (new DescriptionHistoryService())->record_correction($mediaId, '', true);

        $this->assertInstanceOf(WP_Error::class, $result);
        $this->assertSame('description_correction_partial', $result->get_error_code());
        $this->assertSame(500, $result->get_error_data()['status']);
        // Marker must be absent — success would lie about decorative finish.
        $this->assertSame('', get_post_meta($mediaId, 'acx_alt_decorative', true));
        $this->assertArrayNotHasKey(
            'acx_alt_decorative',
            $GLOBALS['__ac_post_meta'][$mediaId] ?? []
        );
        // Empty alt and human-edit did land (partial: substantive writes, marker not).
        $this->assertSame('', get_post_meta($mediaId, '_wp_attachment_image_alt', true));
        $this->assertIsArray(get_post_meta($mediaId, '_acx_description_human_edit', true));
        // Partial wire contract: client reconciles workbench cache from stored_alt_text
        // (useCorrectMediaAlt onError). Omitting it leaves the UI on the prior alt while
        // the server already holds '' — pin presence and reconciled value. [rg-015]
        $errorData = $result->get_error_data();
        $this->assertIsArray($errorData);
        $this->assertArrayHasKey(
            'stored_alt_text',
            $errorData,
            'Decorative partial error must carry stored_alt_text for client cache reconcile'
        );
        $this->assertSame(
            '',
            $errorData['stored_alt_text'],
            'Decorative partial stored_alt_text must be the reconciled empty alt, not the prior value'
        );
    }

    /**
     * Existing two-argument record_correction and correction requests that omit
     * decorative behave exactly as before (no marker planted on non-empty alt).
     */
    public function testTwoArgCorrectionAndOmittedDecorativeFlagBehaveAsBefore(): void
    {
        $mediaId = 606;
        $this->seedAttachment($mediaId, 'Legacy caller');
        $this->setPostMeta($mediaId, '_wp_attachment_image_alt', 'Old.');

        // Two-argument service call (existing callers) — third param defaults null
        // (unspecified ≡ today's prior default-false clear behaviour) [A-02].
        $result = (new DescriptionHistoryService())->record_correction($mediaId, 'Legacy corrected alt.');
        $this->assertNotInstanceOf(WP_Error::class, $result);
        $this->assertSame('Legacy corrected alt.', get_post_meta($mediaId, '_wp_attachment_image_alt', true));
        $this->assertSame('', get_post_meta($mediaId, 'acx_alt_decorative', true));
        $this->assertArrayNotHasKey(
            'acx_alt_decorative',
            $GLOBALS['__ac_post_meta'][$mediaId] ?? []
        );

        // Controller request omitting decorative entirely.
        $mediaId2 = 607;
        $this->seedAttachment($mediaId2, 'Controller omit flag');
        $this->setPostMeta($mediaId2, '_wp_attachment_image_alt', 'Prior.');
        $controller = new DescribeController();
        $request = new WP_REST_Request('POST', '/acx/v1/recognition/describe/history/' . $mediaId2 . '/correction');
        $request->set_param('media_id', $mediaId2);
        $request->set_param('alt_text', 'Controller corrected without flag.');
        // decorative intentionally not set.

        $response = $controller->correct_description_history_item($request);
        $this->assertInstanceOf(WP_REST_Response::class, $response);
        $this->assertSame(
            'Controller corrected without flag.',
            $response->get_data()['current_alt_text']
        );
        $this->assertSame('', get_post_meta($mediaId2, 'acx_alt_decorative', true));
    }

    /**
     * A-01: plant keys on verified alt read-back, not the request flag alone.
     *
     * A sanitize_post_meta__wp_attachment_image_alt filter can map '' → non-empty
     * after the pre-write 400 guard. The plant path must refuse to co-locate
     * acx_alt_decorative='1' with a non-empty stored alt [rg-015][DATA-14].
     */
    public function testDecorativePlantRefusesWhenSanitizeFilterInjectsNonEmptyAlt(): void
    {
        $mediaId = 612;
        $injected = 'Injected default alt';
        $this->seedAttachment($mediaId, 'Sanitize inject decorative');
        $this->setPostMeta($mediaId, '_wp_attachment_image_alt', 'Prior alt.');

        // Core-faithful filter name (no subtype): sanitize_post_meta_{$key}.
        add_filter(
            'sanitize_post_meta__wp_attachment_image_alt',
            static function ($value) use ($injected) {
                if (is_string($value) && '' === trim($value)) {
                    return $injected;
                }
                return $value;
            },
            10,
            1
        );

        $result = (new DescriptionHistoryService())->record_correction($mediaId, '', true);

        // Refuse-and-error (partial): alt + human-edit may have landed; marker must not.
        $this->assertInstanceOf(WP_Error::class, $result);
        $this->assertSame('description_correction_partial', $result->get_error_code());
        $errorData = $result->get_error_data();
        $this->assertIsArray($errorData);
        $this->assertSame(500, $errorData['status']);
        $this->assertSame($injected, $errorData['stored_alt_text']);
        $this->assertArrayHasKey('is_decorative', $errorData);
        $this->assertFalse($errorData['is_decorative']);

        // Invariant: marker never '1' beside non-empty stored alt via this path.
        $this->assertSame($injected, get_post_meta($mediaId, '_wp_attachment_image_alt', true));
        $this->assertSame('', get_post_meta($mediaId, 'acx_alt_decorative', true));
        $this->assertArrayNotHasKey(
            'acx_alt_decorative',
            $GLOBALS['__ac_post_meta'][$mediaId] ?? []
        );
        // Human-edit did land (partial: substantive writes, decorative plant refused).
        $this->assertIsArray(get_post_meta($mediaId, '_acx_description_human_edit', true));
    }

    /**
     * A-01 prior-marker variant: refuse-to-plant when a sanitize filter injects
     * a non-empty alt must still clear a pre-existing acx_alt_decorative marker.
     * Without the clear, disk holds non-empty alt + marker='1' — the invariant
     * the refuse path claims to uphold. Sibling of
     * testDecorativePlantRefusesWhenSanitizeFilterInjectsNonEmptyAlt (no prior
     * marker) [DATA-14][TEST-15].
     */
    public function testDecorativePlantRefuseClearsPriorMarkerWhenSanitizeFilterInjectsNonEmptyAlt(): void
    {
        $mediaId = 629;
        $injected = 'Injected default alt';
        $this->seedAttachment($mediaId, 'Prior-marker sanitize inject refuse');
        // Decorative disk state: empty alt + marker planted.
        $this->setPostMeta($mediaId, '_wp_attachment_image_alt', '');
        $this->setPostMeta($mediaId, 'acx_alt_decorative', '1');

        add_filter(
            'sanitize_post_meta__wp_attachment_image_alt',
            static function ($value) use ($injected) {
                if (is_string($value) && '' === trim($value)) {
                    return $injected;
                }
                return $value;
            },
            10,
            1
        );

        $result = (new DescriptionHistoryService())->record_correction($mediaId, '', true);

        $this->assertInstanceOf(WP_Error::class, $result);
        $this->assertSame('description_correction_partial', $result->get_error_code());
        $errorData = $result->get_error_data();
        $this->assertIsArray($errorData);
        $this->assertSame(500, $errorData['status']);
        $this->assertSame($injected, $errorData['stored_alt_text']);
        // is_decorative is storage read-back after the refuse-path clear [DATA-14].
        $this->assertArrayHasKey('is_decorative', $errorData);
        $this->assertFalse($errorData['is_decorative']);

        // Invariant: non-empty stored alt must never coexist with the marker.
        $this->assertSame($injected, get_post_meta($mediaId, '_wp_attachment_image_alt', true));
        $this->assertSame('', get_post_meta($mediaId, 'acx_alt_decorative', true));
        $this->assertArrayNotHasKey(
            'acx_alt_decorative',
            $GLOBALS['__ac_post_meta'][$mediaId] ?? []
        );
    }

    /**
     * A-03: success envelope from build_item emits is_decorative as a boolean
     * read from storage — true when planted, false when not [rg-015].
     */
    public function testSuccessEnvelopeEmitsIsDecorativeBooleanFromStorage(): void
    {
        $mediaId = 613;
        $this->seedAttachment($mediaId, 'Decorative success wire');
        $this->setPostMeta($mediaId, '_wp_attachment_image_alt', 'Prior.');

        $decorative = (new DescriptionHistoryService())->record_correction($mediaId, '', true);
        $this->assertNotInstanceOf(WP_Error::class, $decorative);
        $this->assertIsArray($decorative);
        $this->assertArrayHasKey('is_decorative', $decorative);
        $this->assertTrue($decorative['is_decorative']);
        $this->assertSame('', $decorative['current_alt_text']);
        $this->assertIsBool($decorative['is_decorative']);

        $mediaId2 = 614;
        $this->seedAttachment($mediaId2, 'Non-decorative success wire');
        $this->setPostMeta($mediaId2, '_wp_attachment_image_alt', 'Prior.');
        $described = (new DescriptionHistoryService())->record_correction(
            $mediaId2,
            'A real description.'
        );
        $this->assertNotInstanceOf(WP_Error::class, $described);
        $this->assertIsArray($described);
        $this->assertArrayHasKey('is_decorative', $described);
        $this->assertFalse($described['is_decorative']);
        $this->assertSame('A real description.', $described['current_alt_text']);
    }

    /**
     * A-03: human-edit PARTIAL carries is_decorative from post-write read-back.
     * Non-empty alt self-heals the marker before human-edit, so false.
     */
    public function testHumanEditPartialEmitsIsDecorativeFalseAfterNonEmptyClear(): void
    {
        $mediaId = 615;
        $newAlt = 'Partial-saved real description.';
        $this->seedAttachment($mediaId, 'Partial is_decorative wire');
        $this->setPostMeta($mediaId, '_wp_attachment_image_alt', '');
        $this->setPostMeta($mediaId, 'acx_alt_decorative', '1');
        $GLOBALS['__ac_update_post_meta_fail'][$mediaId]['_acx_description_human_edit'] = true;

        $result = (new DescriptionHistoryService())->record_correction($mediaId, $newAlt);

        $this->assertInstanceOf(WP_Error::class, $result);
        $this->assertSame('description_correction_partial', $result->get_error_code());
        $errorData = $result->get_error_data();
        $this->assertIsArray($errorData);
        $this->assertSame($newAlt, $errorData['stored_alt_text']);
        $this->assertArrayHasKey('is_decorative', $errorData);
        $this->assertFalse($errorData['is_decorative']);
        $this->assertIsBool($errorData['is_decorative']);
    }

    /**
     * A-03: decorative plant PARTIAL (marker write failed) carries is_decorative false.
     */
    public function testDecorativePlantPartialEmitsIsDecorativeFalse(): void
    {
        $mediaId = 616;
        $this->seedAttachment($mediaId, 'Plant fail is_decorative wire');
        $this->setPostMeta($mediaId, '_wp_attachment_image_alt', 'Prior alt.');
        $GLOBALS['__ac_update_post_meta_fail'][$mediaId]['acx_alt_decorative'] = true;

        $result = (new DescriptionHistoryService())->record_correction($mediaId, '', true);

        $this->assertInstanceOf(WP_Error::class, $result);
        $this->assertSame('description_correction_partial', $result->get_error_code());
        $errorData = $result->get_error_data();
        $this->assertIsArray($errorData);
        $this->assertSame('', $errorData['stored_alt_text']);
        $this->assertArrayHasKey('is_decorative', $errorData);
        $this->assertFalse($errorData['is_decorative']);
    }

    /**
     * A-03: empty non-decorative human-edit PARTIAL preserves prior marker and
     * reports is_decorative true (plant path never ran; marker left alone).
     */
    public function testEmptyNonDecorativePartialEmitsIsDecorativeTrueWhenPriorMarker(): void
    {
        $mediaId = 617;
        $this->seedAttachment($mediaId, 'Preserve marker partial wire');
        $this->setPostMeta($mediaId, '_wp_attachment_image_alt', '');
        $this->setPostMeta($mediaId, 'acx_alt_decorative', '1');
        $GLOBALS['__ac_update_post_meta_fail'][$mediaId]['_acx_description_human_edit'] = true;

        $result = (new DescriptionHistoryService())->record_correction($mediaId, '');

        $this->assertInstanceOf(WP_Error::class, $result);
        $this->assertSame('description_correction_partial', $result->get_error_code());
        $errorData = $result->get_error_data();
        $this->assertIsArray($errorData);
        $this->assertSame('', $errorData['stored_alt_text']);
        $this->assertArrayHasKey('is_decorative', $errorData);
        $this->assertTrue($errorData['is_decorative']);
        $this->assertSame('1', get_post_meta($mediaId, 'acx_alt_decorative', true));
    }

    /**
     * Correction route args register optional decorative with NO schema default
     * so absent and explicit false remain distinguishable [A-02].
     */
    public function testCorrectionRouteRegistersOptionalDecorativeArg(): void
    {
        $controller = new DescribeController();
        $controller->register_routes();

        $correction = null;
        foreach ($GLOBALS['__ac_rest_routes'] as $route) {
            if (($route['route'] ?? '') === '/recognition/describe/history/(?P<media_id>\d+)/correction') {
                $correction = $route;
                break;
            }
        }
        $this->assertIsArray($correction);
        // register_rest_route stores the whole route config under 'args'; the
        // REST arg schema is nested one level deeper at ['args']['args'].
        $schema = $correction['args']['args'] ?? [];
        $this->assertArrayHasKey('decorative', $schema);
        $this->assertSame('boolean', $schema['decorative']['type']);
        $this->assertFalse($schema['decorative']['required']);
        // No default — schema default would collapse absent into false [A-02].
        $this->assertArrayNotHasKey('default', $schema['decorative']);
        // Existing alt_text arg still required.
        $this->assertTrue($schema['alt_text']['required']);
    }

    /**
     * A-02 tri-state matrix: true / explicit false / omitted against empty and
     * non-empty stored alt. Omitted must be byte-for-byte today's prior false
     * (clear only on non-empty); explicit false un-marks even when empty.
     */
    public function testDecorativeTriStateClearMatrix(): void
    {
        $service = new DescriptionHistoryService();

        // true + empty: plant marker.
        $idPlant = 620;
        $this->seedAttachment($idPlant, 'Plant');
        $this->setPostMeta($idPlant, '_wp_attachment_image_alt', 'Prior');
        $r = $service->record_correction($idPlant, '', true);
        $this->assertNotInstanceOf(WP_Error::class, $r);
        $this->assertSame('1', get_post_meta($idPlant, 'acx_alt_decorative', true));
        $this->assertSame('', get_post_meta($idPlant, '_wp_attachment_image_alt', true));

        // omitted (null) + empty + prior marker: preserve marker.
        $idOmitEmpty = 621;
        $this->seedAttachment($idOmitEmpty, 'Omit empty');
        $this->setPostMeta($idOmitEmpty, '_wp_attachment_image_alt', '');
        $this->setPostMeta($idOmitEmpty, 'acx_alt_decorative', '1');
        $r = $service->record_correction($idOmitEmpty, '');
        $this->assertNotInstanceOf(WP_Error::class, $r);
        $this->assertSame('1', get_post_meta($idOmitEmpty, 'acx_alt_decorative', true));

        // omitted (null) + non-empty + prior marker: clear.
        $idOmitNonEmpty = 622;
        $this->seedAttachment($idOmitNonEmpty, 'Omit non-empty');
        $this->setPostMeta($idOmitNonEmpty, '_wp_attachment_image_alt', '');
        $this->setPostMeta($idOmitNonEmpty, 'acx_alt_decorative', '1');
        $r = $service->record_correction($idOmitNonEmpty, 'Now described.');
        $this->assertNotInstanceOf(WP_Error::class, $r);
        $this->assertSame('', get_post_meta($idOmitNonEmpty, 'acx_alt_decorative', true));
        $this->assertArrayNotHasKey('acx_alt_decorative', $GLOBALS['__ac_post_meta'][$idOmitNonEmpty] ?? []);

        // explicit false + empty + prior marker: un-mark [INT-09].
        $idFalseEmpty = 623;
        $this->seedAttachment($idFalseEmpty, 'Unmark empty');
        $this->setPostMeta($idFalseEmpty, '_wp_attachment_image_alt', '');
        $this->setPostMeta($idFalseEmpty, 'acx_alt_decorative', '1');
        $r = $service->record_correction($idFalseEmpty, '', false);
        $this->assertNotInstanceOf(WP_Error::class, $r);
        $this->assertSame('', get_post_meta($idFalseEmpty, 'acx_alt_decorative', true));
        $this->assertArrayNotHasKey('acx_alt_decorative', $GLOBALS['__ac_post_meta'][$idFalseEmpty] ?? []);
        $this->assertSame('', get_post_meta($idFalseEmpty, '_wp_attachment_image_alt', true));

        // explicit false + non-empty + prior marker: clear.
        $idFalseNonEmpty = 624;
        $this->seedAttachment($idFalseNonEmpty, 'Unmark non-empty');
        $this->setPostMeta($idFalseNonEmpty, '_wp_attachment_image_alt', '');
        $this->setPostMeta($idFalseNonEmpty, 'acx_alt_decorative', '1');
        $r = $service->record_correction($idFalseNonEmpty, 'Also described.', false);
        $this->assertNotInstanceOf(WP_Error::class, $r);
        $this->assertSame('', get_post_meta($idFalseNonEmpty, 'acx_alt_decorative', true));
        $this->assertSame('Also described.', get_post_meta($idFalseNonEmpty, '_wp_attachment_image_alt', true));
    }

    /**
     * A-02 un-mark: after explicit false with empty alt, candidate service
     * classifies missing_alt — the row returns to the describe queue.
     * human_edit is not considered by classification; empty + no marker is
     * the whole signal [INT-09].
     */
    public function testUnmarkDecorativeReturnsRowToMissingAltQueue(): void
    {
        $mediaId = 625;
        $this->seedAttachment($mediaId, 'Unmark to queue');
        $this->setPostMeta($mediaId, '_wp_attachment_image_alt', '');
        $this->setPostMeta($mediaId, 'acx_alt_decorative', '1');

        // Precondition: decorative exclusion.
        $candidate = new \AltContext\Api\Services\DescriptionCandidateService();
        $before = $candidate->get_status_for_media_ids([$mediaId]);
        $this->assertSame('decorative', $before[0]['reason']);

        $result = (new DescriptionHistoryService())->record_correction($mediaId, '', false);
        $this->assertNotInstanceOf(WP_Error::class, $result);
        $this->assertFalse($result['is_decorative']);
        $this->assertSame('', get_post_meta($mediaId, 'acx_alt_decorative', true));
        $this->assertArrayNotHasKey('acx_alt_decorative', $GLOBALS['__ac_post_meta'][$mediaId] ?? []);

        $after = $candidate->get_status_for_media_ids([$mediaId]);
        $this->assertSame('missing_alt', $after[0]['reason']);
        $this->assertSame('missing_alt', $after[0]['candidate_reason']);
        // list_missing_alt_candidates uses get_posts over the full library; the
        // dedicated DescriptionCandidateServiceTest covers that path. Here we
        // pin classification for this media_id after the un-mark write.
    }

    /**
     * CO-01: when decorative clear fails, do not return before human_edit.
     * human_edit meta must be present after a forced clear failure; the
     * returned PARTIAL is still the clear-failure message (not human-edit).
     */
    public function testClearFailureDefersUntilAfterHumanEditWrite(): void
    {
        $mediaId = 626;
        $newAlt = 'Clear fail still stamps human edit.';
        $this->seedAttachment($mediaId, 'CO-01 clear defer');
        $this->setPostMeta($mediaId, '_wp_attachment_image_alt', '');
        $this->setPostMeta($mediaId, 'acx_alt_decorative', '1');
        $GLOBALS['__ac_delete_post_meta_fail'][$mediaId]['acx_alt_decorative'] = true;

        $result = (new DescriptionHistoryService())->record_correction($mediaId, $newAlt);

        $this->assertInstanceOf(WP_Error::class, $result);
        $this->assertSame('description_correction_partial', $result->get_error_code());
        $this->assertStringContainsString(
            'decorative marker could not be cleared',
            strtolower($result->get_error_message())
        );
        $human = get_post_meta($mediaId, '_acx_description_human_edit', true);
        $this->assertIsArray($human, 'human_edit must be written before clear-failure PARTIAL returns [CO-01]');
        $this->assertSame($newAlt, $human['alt_text'] ?? null);
        $this->assertTrue($result->get_error_data()['is_decorative']);
    }

    /**
     * CO-01: when both clear and human_edit fail, human_edit PARTIAL wins
     * (strictly worse: no provenance). is_decorative still read-back-derived.
     */
    public function testClearAndHumanEditBothFailReturnsHumanEditPartial(): void
    {
        $mediaId = 627;
        $newAlt = 'Both fail alt.';
        $this->seedAttachment($mediaId, 'CO-01 both fail');
        $this->setPostMeta($mediaId, '_wp_attachment_image_alt', '');
        $this->setPostMeta($mediaId, 'acx_alt_decorative', '1');
        $GLOBALS['__ac_delete_post_meta_fail'][$mediaId]['acx_alt_decorative'] = true;
        $GLOBALS['__ac_update_post_meta_fail'][$mediaId]['_acx_description_human_edit'] = true;

        $result = (new DescriptionHistoryService())->record_correction($mediaId, $newAlt);

        $this->assertInstanceOf(WP_Error::class, $result);
        $this->assertSame('description_correction_partial', $result->get_error_code());
        $this->assertStringContainsString(
            'human-edit record could not be stored',
            strtolower($result->get_error_message())
        );
        $this->assertSame($newAlt, $result->get_error_data()['stored_alt_text']);
        $this->assertTrue($result->get_error_data()['is_decorative']);
        $this->assertSame('1', get_post_meta($mediaId, 'acx_alt_decorative', true));
    }

    /**
     * Single-image REST describe is decorative-blind without the post-write
     * clear: empty existing alt always returns 'proceed', so a decorative
     * attachment (alt '' + marker '1') accepts a non-empty draft and leaves
     * the marker on disk. Assert the marker is gone after a verified write
     * [DATA-14][TEST-15].
     */
    public function testSingleImageDescribeClearsDecorativeMarkerWhenWritingNonEmptyAlt(): void
    {
        $mediaId = 640;
        $tempDir = sys_get_temp_dir() . '/acx-f5b-desc-' . uniqid();
        mkdir($tempDir, 0o755, true);
        $path = $tempDir . "/{$mediaId}.jpg";
        file_put_contents($path, "\xff\xd8\xff\xe0bytes");
        $GLOBALS['__ac_attached_file'][$mediaId] = $path;
        $GLOBALS['__ac_posts'][$mediaId] = (object) [
            'post_title'   => "Photo {$mediaId}",
            'post_excerpt' => 'A caption.',
            'post_content' => 'A long description.',
            'post_type'    => 'attachment',
            'ID'           => $mediaId,
        ];
        // Decorative: empty alt + marker. Gate treats empty alt as proceed.
        $this->setPostMeta($mediaId, '_wp_attachment_image_alt', '');
        $this->setPostMeta($mediaId, 'acx_alt_decorative', '1');
        $this->assertSame('1', get_post_meta($mediaId, 'acx_alt_decorative', true));

        $this->setOption('acx_recognition_url', 'http://localhost:8000');
        $this->setOption('acx_recognition_api_key', 'test-key');
        $draft = 'A generated description for a formerly decorative image.';
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body'     => (string) json_encode([
                'tenant_id'              => self::currentTenantId(),
                'media_id'               => $mediaId,
                'image_hash'             => str_repeat('a', 64),
                'context_hash'           => str_repeat('b', 64),
                'adapter'                => 'seeded',
                'model_id'               => 'seeded-fixtures',
                'model_version'          => '1',
                'prompt_or_task_version' => '1',
                'visual_facts'           => ['caption' => $draft, 'objects' => [], 'ocr_text' => null],
                'alt_text_draft'         => $draft,
                'context_used'           => ['sources' => [], 'applied' => false],
                'provider_disclosure'    => ['provider' => 'none', 'left_service_boundary' => false],
                'cached'                 => false,
                'duration_ms'            => 3,
                'retention_class'        => 'retain_all',
                'tier'                   => 'provisional_cpu',
                'result_generation'      => 0,
            ]),
        ]);

        $req = new WP_REST_Request('POST', '/acx/v1/recognition/describe');
        $req->set_param('media_id', $mediaId);
        $req->set_param('write_alt', true);
        $result = (new DescribeController())->describe_media($req);

        $this->assertInstanceOf(WP_REST_Response::class, $result);
        $this->assertSame($draft, get_post_meta($mediaId, '_wp_attachment_image_alt', true));
        $this->assertSame('written', $result->get_data()['alt_text_write']['status'] ?? null);
        // Invariant: non-empty alt must not coexist with the decorative marker.
        $this->assertSame('', get_post_meta($mediaId, 'acx_alt_decorative', true));
        $this->assertArrayNotHasKey(
            'acx_alt_decorative',
            $GLOBALS['__ac_post_meta'][$mediaId] ?? []
        );

        @unlink($path);
        @rmdir($tempDir);
    }

    /**
     * CLI generate --write is the other decorative-blind writer: same empty-alt
     * proceed gate, then an unguarded alt write. After a verified non-empty
     * write the marker must be gone [DATA-14][TEST-15].
     */
    public function testCliGenerateClearsDecorativeMarkerWhenWritingNonEmptyAlt(): void
    {
        $mediaId = 641;
        $draft = 'CLI-generated description over a decorative marker.';
        $this->seedAttachment($mediaId, 'CLI decorative clear');
        $this->setPostMeta($mediaId, '_wp_attachment_image_alt', '');
        $this->setPostMeta($mediaId, 'acx_alt_decorative', '1');
        $this->assertSame('1', get_post_meta($mediaId, 'acx_alt_decorative', true));

        \WP_CLI::reset_cli_messages();
        $responses = [
            $mediaId => new WP_REST_Response([
                'media_id'               => $mediaId,
                'alt_text_draft'         => $draft,
                'adapter'                => 'seeded',
                'model_id'               => 'local-v1',
                'model_version'          => '2026-07-04',
                'prompt_or_task_version' => 'describe-v1',
            ]),
        ];
        $service = new class($responses) extends DescribeMediaService {
            /** @param array<int,WP_REST_Response|WP_Error> $responses */
            public function __construct(private array $responses)
            {
            }

            public function describe_media(WP_REST_Request $request): WP_REST_Response|\WP_Error
            {
                $id = (int) $request->get_param('media_id');
                return $this->responses[$id] ?? new WP_REST_Response([
                    'media_id'       => $id,
                    'alt_text_draft' => 'fallback',
                ]);
            }
        };
        $command = new DescriptionCommand(null, $service);
        $command->__invoke(['generate'], [
            'media-id' => (string) $mediaId,
            'write' => true,
            'format' => 'json',
        ]);

        $payload = json_decode(\WP_CLI::$messages['log'][0] ?? '', true);
        $this->assertSame('written', $payload['rows'][0]['status'] ?? null);
        $this->assertSame($draft, get_post_meta($mediaId, '_wp_attachment_image_alt', true));
        $this->assertSame('', get_post_meta($mediaId, 'acx_alt_decorative', true));
        $this->assertArrayNotHasKey(
            'acx_alt_decorative',
            $GLOBALS['__ac_post_meta'][$mediaId] ?? []
        );
    }

    /**
     * A-02: controller passes explicit false through as un-mark (not null).
     */
    public function testControllerPassesExplicitFalseAsUnmark(): void
    {
        $mediaId = 628;
        $this->seedAttachment($mediaId, 'Controller unmark');
        $this->setPostMeta($mediaId, '_wp_attachment_image_alt', '');
        $this->setPostMeta($mediaId, 'acx_alt_decorative', '1');

        $controller = new DescribeController();
        $request = new WP_REST_Request(
            'POST',
            '/acx/v1/recognition/describe/history/' . $mediaId . '/correction'
        );
        $request->set_param('media_id', $mediaId);
        $request->set_param('alt_text', '');
        $request->set_param('decorative', false);

        $response = $controller->correct_description_history_item($request);
        $this->assertInstanceOf(WP_REST_Response::class, $response);
        $this->assertFalse($response->get_data()['is_decorative']);
        $this->assertSame('', get_post_meta($mediaId, 'acx_alt_decorative', true));
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
