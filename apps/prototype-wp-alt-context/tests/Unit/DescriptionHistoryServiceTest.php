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
            ['media_id', 'title', 'mime_type', 'current_alt_text', 'generated_alt_text', 'provenance', 'human_edit', 'run_status'],
            array_keys($result)
        );
        $this->assertSame($mediaId, $result['media_id']);
        $this->assertSame($sameAlt, $result['current_alt_text']);
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
