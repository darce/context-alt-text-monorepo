<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Api\AltTextWriteStatus;
use AltContext\Api\Services\DescriptionCandidateService;
use AltContext\Api\Services\DescribeMediaService;
use AltContext\Cli\DescriptionCommand;
use AltContext\Tests\TestCase;
use RuntimeException;
use WP_Error;
use WP_REST_Request;
use WP_REST_Response;

/**
 * @covers \AltContext\Cli\DescriptionCommand
 */
class DescriptionCommandGenerateTest extends TestCase
{
    protected function setUp(): void
    {
        parent::setUp();
        \WP_CLI::reset_cli_messages();
    }

    public function testGenerateDryRunIsDefaultAndDoesNotWriteAltText(): void
    {
        $service = new RecordingDescribeService([
            301 => new WP_REST_Response(['media_id' => 301, 'alt_text_draft' => 'A red barn at sunrise.']),
        ]);
        $command = new DescriptionCommand(null, $service);

        $command->__invoke(['generate'], ['media-id' => '301', 'format' => 'json']);

        $payload = json_decode(\WP_CLI::$messages['log'][0] ?? '', true);

        $this->assertSame([301], $service->requestedMediaIds);
        $this->assertSame('', get_post_meta(301, '_wp_attachment_image_alt', true));
        $this->assertSame('dry_run', $payload['rows'][0]['status']);
        $this->assertSame('A red barn at sunrise.', $payload['rows'][0]['alt_text_draft']);
        $this->assertSame(0, $payload['failed'] ?? null);
        $this->assertSame(0, $payload['partial'] ?? null);
        $this->assertSame(1, $payload['dry_run'] ?? null);
        // JSON success path must leave the human success channel empty so
        // machine consumers can parse the entire stdout as one JSON document.
        $this->assertEmpty(\WP_CLI::$messages['success']);
    }

    public function testGenerateSurfacesUpstreamDetailOnErrorResponse(): void
    {
        $service = new RecordingDescribeService([
            302 => new WP_REST_Response(['detail' => 'tenant mismatch'], 403),
        ]);
        $command = new DescriptionCommand(null, $service);

        $caught = null;
        try {
            $command->__invoke(['generate'], ['media-id' => '302', 'format' => 'json']);
        } catch (RuntimeException $e) {
            $caught = $e;
        }

        $this->assertInstanceOf(RuntimeException::class, $caught);
        $payload = json_decode(\WP_CLI::$messages['log'][0] ?? '', true);

        $this->assertSame('failed', $payload['rows'][0]['status']);
        $this->assertSame('tenant mismatch', $payload['rows'][0]['error']);
        $this->assertSame(1, $payload['failed'] ?? null);
    }

    public function testGenerateWriteStoresAltTextAndProvenance(): void
    {
        $service = new RecordingDescribeService([
            401 => new WP_REST_Response(
                [
                    'media_id' => 401,
                    'alt_text_draft' => 'A black dog sitting by a window.',
                    'adapter' => 'seeded',
                    'model_id' => 'local-v1',
                    'model_version' => '2026-07-04',
                    'prompt_or_task_version' => 'describe-v1',
                ]
            ),
        ]);
        $command = new DescriptionCommand(null, $service);

        $command->__invoke(['generate'], ['media-id' => '401', 'write' => true, 'format' => 'json']);

        $payload = json_decode(\WP_CLI::$messages['log'][0] ?? '', true);
        $provenance = get_post_meta(401, '_acx_description_provenance', true);

        $writtenAlt = get_post_meta(401, '_wp_attachment_image_alt', true);
        $this->assertSame('A black dog sitting by a window.', $writtenAlt);
        $this->assertSame('written', $payload['rows'][0]['status']);
        $this->assertIsArray($provenance);
        $this->assertSame('cli', $provenance['source']);
        $this->assertSame('local-v1', $provenance['model_id']);
        $this->assertSame('describe-v1', $provenance['prompt_or_task_version']);
        // BR-100: CLI write stamps the exact alt string under alt_text_draft so
        // history can resolve the Generated-alt column.
        $this->assertSame($writtenAlt, $provenance['alt_text_draft']);
        $this->assertSame('A black dog sitting by a window.', $provenance['alt_text_draft']);
        $this->assertSame(1, $payload['written'] ?? null);
        $this->assertSame(0, $payload['failed'] ?? null);
        // Clean machine channel: no Success: trailer after the JSON envelope.
        $this->assertEmpty(\WP_CLI::$messages['success']);
    }

    public function testGenerateWriteSkipsExistingAltUnlessForced(): void
    {
        $this->setPostMeta(501, '_wp_attachment_image_alt', 'Existing editorial alt.');
        $service = new RecordingDescribeService([
            501 => new WP_REST_Response(['media_id' => 501, 'alt_text_draft' => 'Generated replacement alt.']),
        ]);
        $command = new DescriptionCommand(null, $service);

        $command->__invoke(['generate'], ['media-id' => '501', 'write' => true, 'format' => 'json']);
        $firstPayload = json_decode(\WP_CLI::$messages['log'][0] ?? '', true);

        $this->assertSame('Existing editorial alt.', get_post_meta(501, '_wp_attachment_image_alt', true));
        $this->assertSame('skipped_existing_alt', $firstPayload['rows'][0]['status']);
        // No alt write → no provenance, no fabricated alt_text_draft.
        $this->assertSame('', get_post_meta(501, '_acx_description_provenance', true));
        // R17-BR-09: all-skipped is distinguishable from all-written.
        $this->assertSame(1, $firstPayload['skipped_existing_alt'] ?? null);
        $this->assertArrayNotHasKey('written', $firstPayload);
        // Counts live in the JSON envelope; success channel stays empty on json.
        $this->assertEmpty(\WP_CLI::$messages['success']);

        \WP_CLI::reset_cli_messages();
        $command->__invoke(['generate'], ['media-id' => '501', 'write' => true, 'force' => true, 'format' => 'json']);
        $secondPayload = json_decode(\WP_CLI::$messages['log'][0] ?? '', true);

        $this->assertSame('Generated replacement alt.', get_post_meta(501, '_wp_attachment_image_alt', true));
        // R17-BR-13: CLI force success aligns with REST → forced_overwrite.
        $this->assertSame('forced_overwrite', $secondPayload['rows'][0]['status']);
        $this->assertSame(AltTextWriteStatus::FORCED_OVERWRITE, $secondPayload['rows'][0]['status']);
        $this->assertSame(1, $secondPayload['forced_overwrite'] ?? null);
        $forcedProvenance = get_post_meta(501, '_acx_description_provenance', true);
        $this->assertIsArray($forcedProvenance);
        $this->assertSame('Generated replacement alt.', $forcedProvenance['alt_text_draft']);
    }

    /**
     * BR-100: dry-run (no --write) must not stamp provenance with a fabricated
     * alt_text_draft for a draft that was never written to alt meta.
     */
    public function testGenerateDryRunDoesNotFabricateAltTextDraftInProvenance(): void
    {
        $service = new RecordingDescribeService([
            701 => new WP_REST_Response([
                'media_id' => 701,
                'alt_text_draft' => 'Would-be draft never written.',
                'adapter' => 'seeded',
                'model_id' => 'local-v1',
            ]),
        ]);
        $command = new DescriptionCommand(null, $service);

        $command->__invoke(['generate'], ['media-id' => '701', 'format' => 'json']);

        $payload = json_decode(\WP_CLI::$messages['log'][0] ?? '', true);
        $this->assertSame('dry_run', $payload['rows'][0]['status']);
        $this->assertSame('Would-be draft never written.', $payload['rows'][0]['alt_text_draft']);
        $this->assertSame('', get_post_meta(701, '_wp_attachment_image_alt', true));
        $this->assertSame('', get_post_meta(701, '_acx_description_provenance', true));
    }

    public function testGenerateReportsNonSuccessRestResponseAsFailed(): void
    {
        $service = new RecordingDescribeService([
            601 => new WP_REST_Response(['message' => 'Backend unavailable.'], 502),
        ]);
        $command = new DescriptionCommand(null, $service);

        $caught = null;
        try {
            $command->__invoke(['generate'], ['media-id' => '601', 'write' => true, 'format' => 'json']);
        } catch (RuntimeException $e) {
            $caught = $e;
        }

        $this->assertInstanceOf(RuntimeException::class, $caught);
        $payload = json_decode(\WP_CLI::$messages['log'][0] ?? '', true);

        $this->assertSame('', get_post_meta(601, '_wp_attachment_image_alt', true));
        $this->assertSame('failed', $payload['rows'][0]['status']);
        $this->assertSame('Backend unavailable.', $payload['rows'][0]['error']);
    }

    public function testGenerateRefusesUnboundedCandidateGeneration(): void
    {
        $command = new DescriptionCommand();

        $this->expectException(RuntimeException::class);
        $this->expectExceptionMessage('Pass --media-id or --limit for bounded generation.');

        $command->__invoke(['generate'], ['write' => true]);
    }

    /**
     * BR-104 CLI parity pin: empty draft never writes alt or provenance.
     */
    public function testGenerateWriteSkipsEmptyAltTextDraft(): void
    {
        $service = new RecordingDescribeService([
            801 => new WP_REST_Response([
                'media_id' => 801,
                'alt_text_draft' => '   ',
                'adapter' => 'seeded',
                'model_id' => 'local-v1',
            ]),
        ]);
        $command = new DescriptionCommand(null, $service);

        $command->__invoke(['generate'], ['media-id' => '801', 'write' => true, 'format' => 'json']);

        $payload = json_decode(\WP_CLI::$messages['log'][0] ?? '', true);

        $this->assertSame('skipped_empty_alt_text', $payload['rows'][0]['status']);
        $this->assertSame('', get_post_meta(801, '_wp_attachment_image_alt', true));
        $this->assertSame('', get_post_meta(801, '_acx_description_provenance', true));
        $this->assertSame(1, $payload['skipped_empty_alt_text'] ?? null);
    }

    /**
     * BR-116: non-string draft uses the shared normaliser (→ ''), not (string)
     * cast. Writing is skipped; we never store '42'.
     */
    public function testGenerateWriteTreatsNonStringDraftAsEmptyViaSharedNormaliser(): void
    {
        $service = new RecordingDescribeService([
            802 => new WP_REST_Response([
                'media_id' => 802,
                'alt_text_draft' => 42,
                'adapter' => 'seeded',
                'model_id' => 'local-v1',
            ]),
        ]);
        $command = new DescriptionCommand(null, $service);

        $command->__invoke(['generate'], ['media-id' => '802', 'write' => true, 'format' => 'json']);

        $payload = json_decode(\WP_CLI::$messages['log'][0] ?? '', true);

        $this->assertSame('skipped_empty_alt_text', $payload['rows'][0]['status']);
        $this->assertSame('', $payload['rows'][0]['alt_text_draft']);
        $this->assertSame('', get_post_meta(802, '_wp_attachment_image_alt', true));
        $this->assertSame('', get_post_meta(802, '_acx_description_provenance', true));
    }

    /**
     * BR-104: force + empty draft must not clear an existing human alt (CLI).
     */
    public function testGenerateForceWriteDoesNotClearExistingAltOnEmptyDraft(): void
    {
        $this->setPostMeta(803, '_wp_attachment_image_alt', 'Existing editorial alt.');
        $service = new RecordingDescribeService([
            803 => new WP_REST_Response([
                'media_id' => 803,
                'alt_text_draft' => '',
            ]),
        ]);
        $command = new DescriptionCommand(null, $service);

        $command->__invoke(['generate'], [
            'media-id' => '803',
            'write' => true,
            'force' => true,
            'format' => 'json',
        ]);

        $payload = json_decode(\WP_CLI::$messages['log'][0] ?? '', true);

        $this->assertSame('skipped_empty_alt_text', $payload['rows'][0]['status']);
        $this->assertSame('Existing editorial alt.', get_post_meta(803, '_wp_attachment_image_alt', true));
        $this->assertSame('', get_post_meta(803, '_acx_description_provenance', true));
    }

    /**
     * BR-01: when the alt write fails, status is not `written` and provenance is
     * not stamped. Assert storage, not just the return value. [rg-015]
     */
    public function testGenerateWriteAltFailureDoesNotStampProvenance(): void
    {
        $service = new RecordingDescribeService([
            901 => new WP_REST_Response([
                'media_id' => 901,
                'alt_text_draft' => 'A draft that will not land.',
                'adapter' => 'seeded',
                'model_id' => 'local-v1',
            ]),
        ]);
        $GLOBALS['__ac_update_post_meta_fail'][901]['_wp_attachment_image_alt'] = true;
        $command = new DescriptionCommand(null, $service);

        $caught = null;
        try {
            $command->__invoke(['generate'], ['media-id' => '901', 'write' => true, 'format' => 'json']);
        } catch (RuntimeException $e) {
            $caught = $e;
        }

        $this->assertInstanceOf(RuntimeException::class, $caught);
        $payload = json_decode(\WP_CLI::$messages['log'][0] ?? '', true);

        $this->assertNotSame('written', $payload['rows'][0]['status']);
        $this->assertSame('failed', $payload['rows'][0]['status']);
        // Storage truth: alt empty, provenance absent — no fabricated Generated-alt.
        $this->assertSame('', get_post_meta(901, '_wp_attachment_image_alt', true));
        $this->assertSame('', get_post_meta(901, '_acx_description_provenance', true));
    }

    /**
     * BR-01 / R17-BR-06: alt succeeds, provenance fails → partial with
     * reason=provenance_write_failed. Alt stays written.
     */
    public function testGenerateWriteProvenanceFailureReportsPartial(): void
    {
        $service = new RecordingDescribeService([
            902 => new WP_REST_Response([
                'media_id' => 902,
                'alt_text_draft' => 'Alt lands, provenance does not.',
                'adapter' => 'seeded',
                'model_id' => 'local-v1',
            ]),
        ]);
        $GLOBALS['__ac_update_post_meta_fail'][902]['_acx_description_provenance'] = true;
        $command = new DescriptionCommand(null, $service);

        $caught = null;
        try {
            $command->__invoke(['generate'], ['media-id' => '902', 'write' => true, 'format' => 'json']);
        } catch (RuntimeException $e) {
            $caught = $e;
        }

        $this->assertInstanceOf(RuntimeException::class, $caught);
        $payload = json_decode(\WP_CLI::$messages['log'][0] ?? '', true);

        $this->assertSame('partial', $payload['rows'][0]['status']);
        $this->assertSame(
            AltTextWriteStatus::REASON_PROVENANCE_WRITE_FAILED,
            $payload['rows'][0]['reason'] ?? null
        );
        $this->assertSame('Alt lands, provenance does not.', get_post_meta(902, '_wp_attachment_image_alt', true));
        $this->assertSame('', get_post_meta(902, '_acx_description_provenance', true));
        $this->assertSame(1, $payload['partial'] ?? null);
        // R16-BR-06: partial only when recovery marker verified.
        $pending = get_post_meta(902, '_acx_description_provenance_pending', true);
        $this->assertIsArray($pending);
        $this->assertSame('cli', $pending['run_id'] ?? null);
        $this->assertSame(
            hash('sha256', 'Alt lands, provenance does not.'),
            $pending['draft_hash'] ?? null
        );
    }

    /**
     * WBUX-5-R16-BR-10 / R17-BR-12: natural no-op reapply (byte-identical alt,
     * update_post_meta returns false) reports forced_overwrite because read-back
     * confirmed the stored value — not because a false write return was ignored.
     * Skipping the false-branch leaves alt_ok false → failed. Does NOT pin
     * wp_unslash (ASCII is a fixed point); see *BackslashBearing* [TEST-15].
     *
     * Renamed from testGenerateWriteByteIdenticalRewriteIsNotReportedAsFailed /
     * the overclaiming testGenerateWriteIdempotentReapplyReportsWritten: status
     * is forced_overwrite (force + existing alt), not bare written.
     */
    public function testGenerateWriteIdempotentReapplyReportsForcedOverwrite(): void
    {
        $draft = 'Already present from a prior write.';
        $this->setPostMeta(903, '_wp_attachment_image_alt', $draft);
        $service = new RecordingDescribeService([
            903 => new WP_REST_Response([
                'media_id' => 903,
                'alt_text_draft' => $draft,
                'adapter' => 'seeded',
                'model_id' => 'local-v1',
            ]),
        ]);
        $command = new DescriptionCommand(null, $service);

        $command->__invoke(['generate'], [
            'media-id' => '903',
            'write' => true,
            'force' => true,
            'format' => 'json',
        ]);

        $payload = json_decode(\WP_CLI::$messages['log'][0] ?? '', true);
        $status  = $payload['rows'][0]['status'] ?? null;

        // Force + existing non-empty alt → forced_overwrite (R17-BR-13).
        $this->assertSame('forced_overwrite', $status);
        $this->assertNotSame('failed', $status);
        // Post-write stored value — pins that read-back accepted the no-op.
        $this->assertSame($draft, get_post_meta(903, '_wp_attachment_image_alt', true));
        $this->assertIsArray(get_post_meta(903, '_acx_description_provenance', true));
    }

    /**
     * BR-17 [TEST-15]: CLI generate-write with a backslash-bearing alt must save
     * and re-save successfully. update_post_meta unslashes on the way in; the
     * second write of the same raw string is a byte-identical no-op (false) and
     * the read-back guard must compare against wp_unslash( $alt_text_draft ).
     */
    public function testGenerateWriteBackslashBearingSavesAndResavesSuccessfully(): void
    {
        // PHP source \\ → one backslash char; unslash changes those bytes.
        $draft          = 'Blueprint of the C:\\Users share, annotated';
        $expectedStored = wp_unslash($draft);
        $this->assertNotSame($draft, $expectedStored, 'precondition: unslash must change the bytes');

        $service = new RecordingDescribeService([
            904 => new WP_REST_Response([
                'media_id' => 904,
                'alt_text_draft' => $draft,
                'adapter' => 'seeded',
                'model_id' => 'local-v1',
            ]),
        ]);
        $command = new DescriptionCommand(null, $service);

        $command->__invoke(['generate'], ['media-id' => '904', 'write' => true, 'format' => 'json']);
        $firstPayload = json_decode(\WP_CLI::$messages['log'][0] ?? '', true);

        $this->assertSame('written', $firstPayload['rows'][0]['status']);
        // WP stores the unslashed form; assert storage, not the raw draft.
        $this->assertSame($expectedStored, get_post_meta(904, '_wp_attachment_image_alt', true));

        \WP_CLI::reset_cli_messages();
        $command->__invoke(['generate'], [
            'media-id' => '904',
            'write' => true,
            'force' => true,
            'format' => 'json',
        ]);
        $secondPayload = json_decode(\WP_CLI::$messages['log'][0] ?? '', true);

        $this->assertSame(
            'forced_overwrite',
            $secondPayload['rows'][0]['status'],
            'Second force save with same backslash alt must not fail'
        );
        $this->assertSame($expectedStored, get_post_meta(904, '_wp_attachment_image_alt', true));
    }

    // ── R18-BR-01 / R17-BR-02: tally + exit policy for table AND json ──

    /**
     * R18-BR-01 (a) table: total failure → non-zero exit with counts.
     */
    public function testGenerateTableTotalFailureExitsNonZero(): void
    {
        $service = new RecordingDescribeService([
            910 => new WP_REST_Response(['detail' => 'upstream down'], 502),
        ]);
        $command = new DescriptionCommand(null, $service);

        $caught = null;
        try {
            $command->__invoke(['generate'], ['media-id' => '910', 'write' => true]);
        } catch (RuntimeException $e) {
            $caught = $e;
        }

        $this->assertInstanceOf(RuntimeException::class, $caught);
        $this->assertNotEmpty(\WP_CLI::$messages['error']);
        $this->assertEmpty(\WP_CLI::$messages['success']);
        $this->assertEmpty(\WP_CLI::$messages['warning']);
        $summary = \WP_CLI::$messages['error'][0];
        $this->assertStringContainsString('count=1', $summary);
        $this->assertStringContainsString('failed=1', $summary);
        $this->assertStringContainsString('partial=0', $summary);
        $this->assertStringContainsString('status=failed', \WP_CLI::$messages['log'][0] ?? '');
    }

    /**
     * R18-BR-01 (a) json: total failure → non-zero exit; envelope carries counts.
     */
    public function testGenerateJsonTotalFailureExitsNonZeroWithCounts(): void
    {
        $service = new RecordingDescribeService([
            911 => new WP_REST_Response(['detail' => 'upstream down'], 502),
        ]);
        $command = new DescriptionCommand(null, $service);

        $caught = null;
        try {
            $command->__invoke(['generate'], ['media-id' => '911', 'write' => true, 'format' => 'json']);
        } catch (RuntimeException $e) {
            $caught = $e;
        }

        $this->assertInstanceOf(RuntimeException::class, $caught);
        $payload = json_decode(\WP_CLI::$messages['log'][0] ?? '', true);
        $this->assertSame(1, $payload['count'] ?? null);
        $this->assertSame(1, $payload['failed'] ?? null);
        $this->assertSame(0, $payload['partial'] ?? null);
        $this->assertSame('failed', $payload['rows'][0]['status'] ?? null);
        $this->assertNotEmpty(\WP_CLI::$messages['error']);
        $this->assertEmpty(\WP_CLI::$messages['success']);
    }

    /**
     * R18-BR-01 (b) / R17-BR-02 table: mixed batch → non-zero (not warning/exit-0).
     * Exit-code expectation deliberately updated from prior warning/exit-0 policy.
     */
    public function testGenerateTableMixedBatchExitsNonZero(): void
    {
        $candidates = new FixedCandidateService([920, 921]);
        $describe   = new RecordingDescribeService([
            920 => new WP_REST_Response([
                'media_id' => 920,
                'alt_text_draft' => 'ok draft',
                'adapter' => 'seeded',
                'model_id' => 'local-v1',
            ]),
            921 => new WP_REST_Response(['detail' => 'boom'], 502),
        ]);
        $command = new DescriptionCommand($candidates, $describe);

        $caught = null;
        try {
            $command->__invoke(['generate'], ['limit' => '2', 'write' => true]);
        } catch (RuntimeException $e) {
            $caught = $e;
        }

        $this->assertInstanceOf(RuntimeException::class, $caught);
        $this->assertNotEmpty(\WP_CLI::$messages['error']);
        $this->assertEmpty(\WP_CLI::$messages['success']);
        $this->assertEmpty(\WP_CLI::$messages['warning']);
        $summary = \WP_CLI::$messages['error'][0];
        $this->assertStringContainsString('count=2', $summary);
        $this->assertStringContainsString('failed=1', $summary);
        $this->assertStringContainsString('partial=0', $summary);
        $this->assertStringContainsString('written=1', $summary);
    }

    /**
     * R18-BR-01 (b) / R17-BR-02 json: mixed batch → non-zero with envelope counts.
     */
    public function testGenerateJsonMixedBatchExitsNonZeroWithCounts(): void
    {
        $candidates = new FixedCandidateService([922, 923]);
        $describe   = new RecordingDescribeService([
            922 => new WP_REST_Response([
                'media_id' => 922,
                'alt_text_draft' => 'ok draft',
                'adapter' => 'seeded',
                'model_id' => 'local-v1',
            ]),
            923 => new WP_REST_Response(['detail' => 'boom'], 502),
        ]);
        $command = new DescriptionCommand($candidates, $describe);

        $caught = null;
        try {
            $command->__invoke(['generate'], ['limit' => '2', 'write' => true, 'format' => 'json']);
        } catch (RuntimeException $e) {
            $caught = $e;
        }

        $this->assertInstanceOf(RuntimeException::class, $caught);
        $payload = json_decode(\WP_CLI::$messages['log'][0] ?? '', true);
        $this->assertSame(2, $payload['count'] ?? null);
        $this->assertSame(1, $payload['failed'] ?? null);
        $this->assertSame(0, $payload['partial'] ?? null);
        $this->assertSame(1, $payload['written'] ?? null);
        $this->assertNotEmpty(\WP_CLI::$messages['error']);
        $this->assertEmpty(\WP_CLI::$messages['success']);
    }

    /**
     * R18-BR-01 (c) table: empty batch stays exit-0 (nothing-to-do ≠ failure).
     */
    public function testGenerateTableEmptyBatchExitsZero(): void
    {
        $candidates = new FixedCandidateService([]);
        $command    = new DescriptionCommand($candidates, new RecordingDescribeService([]));

        $command->__invoke(['generate'], ['limit' => '10', 'write' => true]);

        $this->assertEmpty(\WP_CLI::$messages['error']);
        $this->assertEmpty(\WP_CLI::$messages['warning']);
        $this->assertNotEmpty(\WP_CLI::$messages['success']);
        $summary = \WP_CLI::$messages['success'][0];
        $this->assertStringContainsString('count=0', $summary);
        $this->assertStringContainsString('failed=0', $summary);
        $this->assertStringContainsString('partial=0', $summary);
    }

    /**
     * R18-BR-01 (c) json: empty batch stays exit-0 with count/failed/partial keys.
     */
    public function testGenerateJsonEmptyBatchExitsZeroWithCounts(): void
    {
        $candidates = new FixedCandidateService([]);
        $command    = new DescriptionCommand($candidates, new RecordingDescribeService([]));

        $command->__invoke(['generate'], ['limit' => '10', 'write' => true, 'format' => 'json']);

        $this->assertEmpty(\WP_CLI::$messages['error']);
        // Empty-batch json is still exit-0; no human Success: trailer on stdout.
        $this->assertEmpty(\WP_CLI::$messages['success']);
        $payload = json_decode(\WP_CLI::$messages['log'][0] ?? '', true);
        $this->assertSame(0, $payload['count'] ?? null);
        $this->assertSame(0, $payload['failed'] ?? null);
        $this->assertSame(0, $payload['partial'] ?? null);
        $this->assertSame([], $payload['rows'] ?? null);
    }

    /**
     * F-07 / R20-BR-13: successful --format=json must leave stdout as one JSON
     * document. Asserts the stub's real stdout channel (log → stdout; success
     * would also land there with a "Success: " prefix) — not a hand-joined
     * reconstruction from level buckets.
     */
    public function testGenerateJsonSuccessStdoutIsEntirelyOneJsonDocument(): void
    {
        $service = new RecordingDescribeService([
            950 => new WP_REST_Response(['media_id' => 950, 'alt_text_draft' => 'Clean JSON channel.']),
        ]);
        $command = new DescriptionCommand(null, $service);

        $command->__invoke(['generate'], ['media-id' => '950', 'format' => 'json']);

        $stdout = \WP_CLI::get_stdout();
        $decoded = json_decode($stdout, true);
        $this->assertSame(
            JSON_ERROR_NONE,
            json_last_error(),
            'Entire stdout must parse as one JSON document; got: ' . $stdout
        );
        $this->assertIsArray($decoded);
        // R20-BR-24: json_decode accepts trailing whitespace; require exact one document.
        $this->assertSame(
            (string) wp_json_encode($decoded),
            $stdout,
            'stdout must equal the encoded envelope with no trailing blank line'
        );
        $this->assertSame('generate', $decoded['command'] ?? null);
        $this->assertSame(1, $decoded['count'] ?? null);
        $this->assertEmpty(\WP_CLI::$messages['success']);
        $this->assertSame('', \WP_CLI::get_stderr());
    }

    /**
     * R20-BR-13: failure-path --format=json keeps stdout as exactly one JSON
     * document; human-readable Error: text is on stderr only.
     */
    public function testGenerateJsonFailureStdoutIsOneJsonDocumentErrorOnStderr(): void
    {
        $service = new RecordingDescribeService([
            951 => new WP_REST_Response(['detail' => 'upstream down'], 502),
        ]);
        $command = new DescriptionCommand(null, $service);

        $caught = null;
        try {
            $command->__invoke(['generate'], ['media-id' => '951', 'write' => true, 'format' => 'json']);
        } catch (RuntimeException $e) {
            $caught = $e;
        }

        $this->assertInstanceOf(RuntimeException::class, $caught);

        $stdout = \WP_CLI::get_stdout();
        $decoded = json_decode($stdout, true);
        $this->assertSame(
            JSON_ERROR_NONE,
            json_last_error(),
            'Failure-path stdout must be one JSON document; got: ' . $stdout
        );
        $this->assertIsArray($decoded);
        // R20-BR-24: reject trailing blank lines json_decode would still accept.
        $this->assertSame(
            (string) wp_json_encode($decoded),
            $stdout,
            'stdout must equal the encoded envelope with no trailing blank line'
        );
        $this->assertSame('generate', $decoded['command'] ?? null);
        $this->assertSame(1, $decoded['failed'] ?? null);
        $this->assertSame('failed', $decoded['rows'][0]['status'] ?? null);

        $stderr = \WP_CLI::get_stderr();
        $this->assertStringContainsString('Error:', $stderr);
        $this->assertStringContainsString('failed=1', $stderr);
        $this->assertStringNotContainsString('Error:', $stdout);
        $this->assertStringNotContainsString('Success:', $stdout);
    }

    /**
     * R20-BR-13: partial-path --format=json keeps stdout as exactly one JSON
     * document; human-readable Error: text is on stderr only.
     */
    public function testGenerateJsonPartialStdoutIsOneJsonDocumentErrorOnStderr(): void
    {
        $service = new RecordingDescribeService([
            952 => new WP_REST_Response([
                'media_id' => 952,
                'alt_text_draft' => 'Alt lands, provenance does not.',
                'adapter' => 'seeded',
                'model_id' => 'local-v1',
            ]),
        ]);
        $GLOBALS['__ac_update_post_meta_fail'][952]['_acx_description_provenance'] = true;
        $command = new DescriptionCommand(null, $service);

        $caught = null;
        try {
            $command->__invoke(['generate'], ['media-id' => '952', 'write' => true, 'format' => 'json']);
        } catch (RuntimeException $e) {
            $caught = $e;
        }

        $this->assertInstanceOf(RuntimeException::class, $caught);

        $stdout = \WP_CLI::get_stdout();
        $decoded = json_decode($stdout, true);
        $this->assertSame(
            JSON_ERROR_NONE,
            json_last_error(),
            'Partial-path stdout must be one JSON document; got: ' . $stdout
        );
        $this->assertIsArray($decoded);
        // R20-BR-24: reject trailing blank lines json_decode would still accept.
        $this->assertSame(
            (string) wp_json_encode($decoded),
            $stdout,
            'stdout must equal the encoded envelope with no trailing blank line'
        );
        $this->assertSame('generate', $decoded['command'] ?? null);
        $this->assertSame(1, $decoded['partial'] ?? null);
        $this->assertSame(AltTextWriteStatus::PARTIAL, $decoded['rows'][0]['status'] ?? null);

        $stderr = \WP_CLI::get_stderr();
        $this->assertStringContainsString('Error:', $stderr);
        $this->assertStringContainsString('partial=1', $stderr);
        $this->assertStringNotContainsString('Error:', $stdout);
        $this->assertStringNotContainsString('Success:', $stdout);
    }

    /**
     * R17-BR-09 table: all-skipped reports skipped_existing_alt, not bare success.
     */
    public function testGenerateTableAllSkippedReportsStatusCounts(): void
    {
        $this->setPostMeta(930, '_wp_attachment_image_alt', 'Already here.');
        $service = new RecordingDescribeService([
            930 => new WP_REST_Response(['media_id' => 930, 'alt_text_draft' => 'new draft']),
        ]);
        $command = new DescriptionCommand(null, $service);

        $command->__invoke(['generate'], ['media-id' => '930', 'write' => true]);

        $this->assertNotEmpty(\WP_CLI::$messages['success']);
        $summary = \WP_CLI::$messages['success'][0];
        $this->assertStringContainsString('count=1', $summary);
        $this->assertStringContainsString('failed=0', $summary);
        $this->assertStringContainsString('partial=0', $summary);
        $this->assertStringContainsString('skipped_existing_alt=1', $summary);
        $this->assertStringNotContainsString('written=', $summary);
    }

    /**
     * R17-BR-06 table: partial row log carries reason=provenance_write_failed.
     */
    public function testGenerateTablePartialLogCarriesReason(): void
    {
        $service = new RecordingDescribeService([
            931 => new WP_REST_Response([
                'media_id' => 931,
                'alt_text_draft' => 'Alt lands, provenance does not.',
                'adapter' => 'seeded',
                'model_id' => 'local-v1',
            ]),
        ]);
        $GLOBALS['__ac_update_post_meta_fail'][931]['_acx_description_provenance'] = true;
        $command = new DescriptionCommand(null, $service);

        $caught = null;
        try {
            $command->__invoke(['generate'], ['media-id' => '931', 'write' => true]);
        } catch (RuntimeException $e) {
            $caught = $e;
        }

        $this->assertInstanceOf(RuntimeException::class, $caught);
        $log = \WP_CLI::$messages['log'][0] ?? '';
        $this->assertStringContainsString('status=partial', $log);
        $this->assertStringContainsString(
            'reason=' . AltTextWriteStatus::REASON_PROVENANCE_WRITE_FAILED,
            $log
        );
    }

    /**
     * R18-BR-02: describe_media() WP_Error maps to FAILED, surfaces message,
     * batch exits non-zero.
     */
    public function testGenerateWpErrorMapsToFailedAndExitsNonZero(): void
    {
        $service = new RecordingDescribeService([
            940 => new WP_Error('acx_describe_unreachable', 'Recognition service unreachable.'),
        ]);
        $command = new DescriptionCommand(null, $service);

        $caught = null;
        try {
            $command->__invoke(['generate'], ['media-id' => '940', 'write' => true, 'format' => 'json']);
        } catch (RuntimeException $e) {
            $caught = $e;
        }

        $this->assertInstanceOf(RuntimeException::class, $caught);
        $payload = json_decode(\WP_CLI::$messages['log'][0] ?? '', true);
        $this->assertSame(AltTextWriteStatus::FAILED, $payload['rows'][0]['status'] ?? null);
        $this->assertSame('Recognition service unreachable.', $payload['rows'][0]['error'] ?? null);
        $this->assertSame(1, $payload['failed'] ?? null);
        $this->assertNotEmpty(\WP_CLI::$messages['error']);
        $this->assertEmpty(\WP_CLI::$messages['success']);
    }

    /**
     * R18-BR-02 table variant: WP_Error → failed row log + non-zero exit.
     */
    public function testGenerateTableWpErrorMapsToFailedAndExitsNonZero(): void
    {
        $service = new RecordingDescribeService([
            941 => new WP_Error('acx_not_found', 'Attachment not found.'),
        ]);
        $command = new DescriptionCommand(null, $service);

        $caught = null;
        try {
            $command->__invoke(['generate'], ['media-id' => '941', 'write' => true]);
        } catch (RuntimeException $e) {
            $caught = $e;
        }

        $this->assertInstanceOf(RuntimeException::class, $caught);
        $this->assertStringContainsString('status=failed', \WP_CLI::$messages['log'][0] ?? '');
        $this->assertStringContainsString('failed=1', \WP_CLI::$messages['error'][0] ?? '');
    }

    /**
     * F-19: table row log must surface the same error detail JSON already carries
     * so operators need not re-run as --format=json to learn the cause.
     */
    public function testGenerateTableFailedRowLogCarriesError(): void
    {
        $service = new RecordingDescribeService([
            942 => new WP_REST_Response(['detail' => 'tenant mismatch'], 403),
        ]);
        $command = new DescriptionCommand(null, $service);

        $caught = null;
        try {
            $command->__invoke(['generate'], ['media-id' => '942', 'write' => true]);
        } catch (RuntimeException $e) {
            $caught = $e;
        }

        $this->assertInstanceOf(RuntimeException::class, $caught);
        $log = \WP_CLI::$messages['log'][0] ?? '';
        $this->assertStringContainsString('status=failed', $log);
        // R20-BR-04: free-text error values are quote-and-escaped.
        $this->assertStringContainsString('error="tenant mismatch"', $log);
    }

    /**
     * F-01 pin 1: non-force retry after a provenance-gap partial converges.
     * Must not report skipped_existing_alt; status is exactly provenance_healed.
     */
    public function testGenerateProvenanceGapPartialIsRetryableWithoutForce(): void
    {
        $body = array(
            'media_id' => 960,
            'alt_text_draft' => 'Alt lands, provenance does not.',
            'adapter' => 'seeded',
            'model_id' => 'local-v1',
            'model_version' => '2026-07-04',
            'prompt_or_task_version' => 'describe-v1',
        );
        $service = new RecordingDescribeService([
            960 => new WP_REST_Response($body),
        ]);
        $command = new DescriptionCommand(null, $service);

        // Pass 1: provenance write fails after alt lands.
        $GLOBALS['__ac_update_post_meta_fail'][960]['_acx_description_provenance'] = true;
        $caught = null;
        try {
            $command->__invoke(['generate'], ['media-id' => '960', 'write' => true, 'format' => 'json']);
        } catch (RuntimeException $e) {
            $caught = $e;
        }
        $this->assertInstanceOf(RuntimeException::class, $caught);
        $first = json_decode(\WP_CLI::$messages['log'][0] ?? '', true);
        $this->assertSame(AltTextWriteStatus::PARTIAL, $first['rows'][0]['status'] ?? null);
        $this->assertSame(
            AltTextWriteStatus::REASON_PROVENANCE_WRITE_FAILED,
            $first['rows'][0]['reason'] ?? null
        );
        $this->assertSame('Alt lands, provenance does not.', get_post_meta(960, '_wp_attachment_image_alt', true));
        $this->assertSame('', get_post_meta(960, '_acx_description_provenance', true));

        // Pass 2: clear fail hook; retry WITHOUT force. Must heal provenance.
        unset($GLOBALS['__ac_update_post_meta_fail'][960]['_acx_description_provenance']);
        \WP_CLI::reset_cli_messages();
        $command->__invoke(['generate'], ['media-id' => '960', 'write' => true, 'format' => 'json']);
        $second = json_decode(\WP_CLI::$messages['log'][0] ?? '', true);
        $secondStatus = $second['rows'][0]['status'] ?? null;

        $this->assertNotSame(
            AltTextWriteStatus::SKIPPED_EXISTING_ALT,
            $secondStatus,
            'Provenance-gap retry without force must not be trapped as skipped_existing_alt'
        );
        // Exact wire pin — not assertContains over a set of acceptable values.
        $this->assertSame(AltTextWriteStatus::PROVENANCE_HEALED, $secondStatus);
        $this->assertSame('provenance_healed', $secondStatus);
        $this->assertSame(1, $second['provenance_healed'] ?? null);
        $this->assertSame('Alt lands, provenance does not.', get_post_meta(960, '_wp_attachment_image_alt', true));
        $prov = get_post_meta(960, '_acx_description_provenance', true);
        $this->assertIsArray($prov);
        $this->assertSame('cli', $prov['source'] ?? null);
        $this->assertSame('Alt lands, provenance does not.', $prov['alt_text_draft'] ?? null);
    }

    /**
     * F-01 pin 2: a genuinely different human alt still reports skipped_existing_alt
     * without force — the heal path must not become a licence to overwrite.
     */
    public function testGenerateHumanAuthoredAltStillSkipsWithoutForceWhenDifferentFromDraft(): void
    {
        $this->setPostMeta(961, '_wp_attachment_image_alt', 'Human-authored editorial alt.');
        $service = new RecordingDescribeService([
            961 => new WP_REST_Response([
                'media_id' => 961,
                'alt_text_draft' => 'Generated replacement that must not land.',
                'adapter' => 'seeded',
                'model_id' => 'local-v1',
            ]),
        ]);
        $command = new DescriptionCommand(null, $service);

        $command->__invoke(['generate'], ['media-id' => '961', 'write' => true, 'format' => 'json']);
        $payload = json_decode(\WP_CLI::$messages['log'][0] ?? '', true);

        $this->assertSame(AltTextWriteStatus::SKIPPED_EXISTING_ALT, $payload['rows'][0]['status'] ?? null);
        $this->assertSame('skipped_existing_alt', $payload['rows'][0]['status'] ?? null);
        $this->assertSame('Human-authored editorial alt.', get_post_meta(961, '_wp_attachment_image_alt', true));
        $this->assertSame('', get_post_meta(961, '_acx_description_provenance', true));
    }

    /**
     * F-01 pin 3 / companion: heal status is asserted exactly as provenance_healed
     * when existing alt already equals the draft and provenance is missing.
     */
    public function testGenerateMatchingAltWithMissingProvenanceReportsProvenanceHealedExactly(): void
    {
        $draft = 'Already stored matching draft.';
        $this->setPostMeta(962, '_wp_attachment_image_alt', $draft);
        // Provenance deliberately absent — gap heal without force.
        $service = new RecordingDescribeService([
            962 => new WP_REST_Response([
                'media_id' => 962,
                'alt_text_draft' => $draft,
                'adapter' => 'seeded',
                'model_id' => 'local-v1',
                'model_version' => '1',
                'prompt_or_task_version' => 'describe-v1',
            ]),
        ]);
        $command = new DescriptionCommand(null, $service);

        $command->__invoke(['generate'], ['media-id' => '962', 'write' => true, 'format' => 'json']);
        $payload = json_decode(\WP_CLI::$messages['log'][0] ?? '', true);
        $status  = $payload['rows'][0]['status'] ?? null;

        $this->assertSame('provenance_healed', $status);
        $this->assertSame(AltTextWriteStatus::PROVENANCE_HEALED, $status);
        $this->assertNotSame(AltTextWriteStatus::SKIPPED_EXISTING_ALT, $status);
        $this->assertNotSame(AltTextWriteStatus::WRITTEN, $status);
        $this->assertSame($draft, get_post_meta(962, '_wp_attachment_image_alt', true));
        $this->assertIsArray(get_post_meta(962, '_acx_description_provenance', true));
    }

    /**
     * F-15R: CLI generate-write read-back uses the shared post-transform model
     * (unslash + sanitize_post_meta_* filter). Filter leg only — harness has no
     * sanitize_meta(). ASCII alone cannot pin this (filter must change bytes).
     */
    public function testGenerateWriteSanitizeMetaFilterNoOpReadBackSucceeds(): void
    {
        $submitted = 'CLI draft before meta sanitize';
        add_filter(
            'sanitize_post_meta__wp_attachment_image_alt',
            static function ($value) {
                return is_string($value) ? $value . ' [meta-sanitized]' : $value;
            },
            10,
            1
        );
        // What the service expects after unslash + filter. Plant it: stub write
        // path does not call sanitize_meta / the filter on store.
        $storedForm = apply_filters(
            'sanitize_post_meta__wp_attachment_image_alt',
            wp_unslash($submitted),
            '_wp_attachment_image_alt',
            'post'
        );
        $this->assertSame($submitted . ' [meta-sanitized]', $storedForm);
        $this->assertNotSame($submitted, $storedForm);
        $this->setPostMeta(963, '_wp_attachment_image_alt', $storedForm);

        $service = new RecordingDescribeService([
            963 => new WP_REST_Response([
                'media_id' => 963,
                'alt_text_draft' => $submitted,
                'adapter' => 'seeded',
                'model_id' => 'local-v1',
            ]),
        ]);
        // Force so gate does not take heal/skip; exercise the write read-back.
        // Simulate core no-op (false) after a prior successful sanitize store.
        $GLOBALS['__ac_update_post_meta_fail'][963]['_wp_attachment_image_alt'] = true;
        $command = new DescriptionCommand(null, $service);

        $command->__invoke([
            'generate',
        ], [
            'media-id' => '963',
            'write' => true,
            'force' => true,
            'format' => 'json',
        ]);
        $payload = json_decode(\WP_CLI::$messages['log'][0] ?? '', true);

        $this->assertSame(
            'forced_overwrite',
            $payload['rows'][0]['status'] ?? null,
            'Filter-altered stored alt must not false-fail the no-op read-back'
        );
        $this->assertSame($storedForm, get_post_meta(963, '_wp_attachment_image_alt', true));
        $this->assertIsArray(get_post_meta(963, '_acx_description_provenance', true));
    }

    // ── R20-BR-01 / R20-BR-04 / R20-BR-05 / R20-BR-08 ──

    /**
     * R20-BR-01: identity-complete row with a stale provenance alt_text_draft is
     * healed by generate --write without --force; status stays skipped_existing_alt.
     */
    public function testGenerateIdentityCompleteHealsStaleAltTextDraftAndStillSkips(): void
    {
        $draft = 'Matching stored alt.';
        $this->setPostMeta(970, '_wp_attachment_image_alt', $draft);
        $this->setPostMeta(970, '_acx_description_provenance', [
            'adapter' => 'seeded',
            'model_id' => 'local-v1',
            'model_version' => '2026-07-04',
            'prompt_or_task_version' => 'describe-v1',
            'generated_at' => '2026-01-01T00:00:00+00:00',
            'alt_text_draft' => 'STALE DRAFT',
        ]);
        $service = new RecordingDescribeService([
            970 => new WP_REST_Response([
                'media_id' => 970,
                'alt_text_draft' => $draft,
                'adapter' => 'seeded',
                'model_id' => 'local-v1',
                'model_version' => '2026-07-04',
                'prompt_or_task_version' => 'describe-v1',
            ]),
        ]);
        $command = new DescriptionCommand(null, $service);

        $command->__invoke(['generate'], ['media-id' => '970', 'write' => true, 'format' => 'json']);
        $payload = json_decode(\WP_CLI::$messages['log'][0] ?? '', true);

        $this->assertSame(AltTextWriteStatus::SKIPPED_EXISTING_ALT, $payload['rows'][0]['status'] ?? null);
        $this->assertSame('skipped_existing_alt', $payload['rows'][0]['status'] ?? null);
        $this->assertSame($draft, get_post_meta(970, '_wp_attachment_image_alt', true));
        $prov = get_post_meta(970, '_acx_description_provenance', true);
        $this->assertIsArray($prov);
        $this->assertSame($draft, $prov['alt_text_draft'] ?? null);
        $this->assertNotSame('STALE DRAFT', $prov['alt_text_draft'] ?? null);
        // Draft-key heal only — identity + generated_at preserved.
        $this->assertSame('2026-01-01T00:00:00+00:00', $prov['generated_at'] ?? null);
        $this->assertSame('local-v1', $prov['model_id'] ?? null);
    }

    /**
     * R20-BR-01: identity-complete heal failure reports partial + provenance
     * reason — same wire as heal_gap / provenance stamp failure.
     */
    public function testGenerateIdentityCompleteHealFailureReportsPartial(): void
    {
        $draft = 'Matching stored alt for heal fail.';
        $this->setPostMeta(971, '_wp_attachment_image_alt', $draft);
        $this->setPostMeta(971, '_acx_description_provenance', [
            'adapter' => 'seeded',
            'model_id' => 'local-v1',
            'model_version' => '2026-07-04',
            'prompt_or_task_version' => 'describe-v1',
            'generated_at' => '2026-01-01T00:00:00+00:00',
            'alt_text_draft' => 'STALE',
        ]);
        $GLOBALS['__ac_update_post_meta_fail'][971]['_acx_description_provenance'] = true;
        $service = new RecordingDescribeService([
            971 => new WP_REST_Response([
                'media_id' => 971,
                'alt_text_draft' => $draft,
                'adapter' => 'seeded',
                'model_id' => 'local-v1',
                'model_version' => '2026-07-04',
                'prompt_or_task_version' => 'describe-v1',
            ]),
        ]);
        $command = new DescriptionCommand(null, $service);

        $caught = null;
        try {
            $command->__invoke(['generate'], ['media-id' => '971', 'write' => true, 'format' => 'json']);
        } catch (RuntimeException $e) {
            $caught = $e;
        }

        $this->assertInstanceOf(RuntimeException::class, $caught);
        $payload = json_decode(\WP_CLI::$messages['log'][0] ?? '', true);
        $this->assertSame(AltTextWriteStatus::PARTIAL, $payload['rows'][0]['status'] ?? null);
        $this->assertSame(
            AltTextWriteStatus::REASON_PROVENANCE_WRITE_FAILED,
            $payload['rows'][0]['reason'] ?? null
        );
        // Alt untouched; stale draft left uncorrected.
        $this->assertSame($draft, get_post_meta(971, '_wp_attachment_image_alt', true));
        $prov = get_post_meta(971, '_acx_description_provenance', true);
        $this->assertIsArray($prov);
        $this->assertSame('STALE', $prov['alt_text_draft'] ?? null);
        $this->assertSame(1, $payload['partial'] ?? null);
    }

    /**
     * R20-BR-04: hostile error (newline + tab + =) stays one parseable line and
     * the value round-trips through quote-and-escape.
     */
    public function testGenerateTableHostileErrorValueStaysOneParseableLine(): void
    {
        $hostile = "upstream broke\nnext line\tkey=injected";
        $service = new RecordingDescribeService([
            972 => new WP_REST_Response(['detail' => $hostile], 502),
        ]);
        $command = new DescriptionCommand(null, $service);

        $caught = null;
        try {
            $command->__invoke(['generate'], ['media-id' => '972', 'write' => true]);
        } catch (RuntimeException $e) {
            $caught = $e;
        }

        $this->assertInstanceOf(RuntimeException::class, $caught);
        $log = \WP_CLI::$messages['log'][0] ?? '';
        // One logical row: no raw newline/tab in the log entry.
        $this->assertStringNotContainsString("\n", $log);
        $this->assertStringNotContainsString("\t", $log);
        $this->assertStringContainsString('status=failed', $log);
        // Round-trip: extract quoted error= value and unescape.
        $this->assertMatchesRegularExpression('/ error="([^"]*(?:\\\\.[^"]*)*)"/', $log);
        if (!preg_match('/ error="((?:\\\\.|[^"\\\\])*)"/', $log, $m)) {
            $this->fail('error= quoted value not found in: ' . $log);
        }
        $unescaped = str_replace(
            ['\\\\', '\\"', '\\n', '\\r', '\\t'],
            ['\\', '"', "\n", "\r", "\t"],
            $m[1]
        );
        $this->assertSame($hostile, $unescaped);
        // Unquoted form must not appear (would be ambiguous with k=v).
        $this->assertStringNotContainsString(' error=' . $hostile, $log);
    }

    /**
     * R20-BR-05 table: alt-write failure carries an error= cause.
     */
    public function testGenerateTableAltWriteFailureCarriesError(): void
    {
        $service = new RecordingDescribeService([
            973 => new WP_REST_Response([
                'media_id' => 973,
                'alt_text_draft' => 'A draft that will not land.',
                'adapter' => 'seeded',
                'model_id' => 'local-v1',
            ]),
        ]);
        $GLOBALS['__ac_update_post_meta_fail'][973]['_wp_attachment_image_alt'] = true;
        $command = new DescriptionCommand(null, $service);

        $caught = null;
        try {
            $command->__invoke(['generate'], ['media-id' => '973', 'write' => true]);
        } catch (RuntimeException $e) {
            $caught = $e;
        }

        $this->assertInstanceOf(RuntimeException::class, $caught);
        $log = \WP_CLI::$messages['log'][0] ?? '';
        $this->assertStringContainsString('status=failed', $log);
        $this->assertStringContainsString('error="Alt meta write returned false."', $log);
    }

    /**
     * R20-BR-05 JSON: alt-write failure carries an error key.
     */
    public function testGenerateJsonAltWriteFailureCarriesError(): void
    {
        $service = new RecordingDescribeService([
            974 => new WP_REST_Response([
                'media_id' => 974,
                'alt_text_draft' => 'A draft that will not land.',
                'adapter' => 'seeded',
                'model_id' => 'local-v1',
            ]),
        ]);
        $GLOBALS['__ac_update_post_meta_fail'][974]['_wp_attachment_image_alt'] = true;
        $command = new DescriptionCommand(null, $service);

        $caught = null;
        try {
            $command->__invoke(['generate'], ['media-id' => '974', 'write' => true, 'format' => 'json']);
        } catch (RuntimeException $e) {
            $caught = $e;
        }

        $this->assertInstanceOf(RuntimeException::class, $caught);
        $payload = json_decode(\WP_CLI::$messages['log'][0] ?? '', true);
        $this->assertSame('failed', $payload['rows'][0]['status'] ?? null);
        $this->assertSame('Alt meta write returned false.', $payload['rows'][0]['error'] ?? null);
    }

    /**
     * R20-BR-05: write accepted but storage diverges → read-back mismatch, not
     * the write-returned-false message.
     */
    public function testGenerateAltWriteReadBackMismatchIsDistinguishable(): void
    {
        $service = new RecordingDescribeService([
            975 => new WP_REST_Response([
                'media_id' => 975,
                'alt_text_draft' => 'Expected draft text.',
                'adapter' => 'seeded',
                'model_id' => 'local-v1',
            ]),
        ]);
        // Write returns non-false but stores a different value.
        $GLOBALS['__ac_update_post_meta_mutate'][975]['_wp_attachment_image_alt'] = 'MUTATED STORE';
        $command = new DescriptionCommand(null, $service);

        $caught = null;
        try {
            $command->__invoke(['generate'], ['media-id' => '975', 'write' => true, 'format' => 'json']);
        } catch (RuntimeException $e) {
            $caught = $e;
        }

        $this->assertInstanceOf(RuntimeException::class, $caught);
        $payload = json_decode(\WP_CLI::$messages['log'][0] ?? '', true);
        $this->assertSame('failed', $payload['rows'][0]['status'] ?? null);
        $this->assertSame('Alt meta write read-back mismatch.', $payload['rows'][0]['error'] ?? null);
        $this->assertNotSame(
            'Alt meta write returned false.',
            $payload['rows'][0]['error'] ?? null
        );
        // No provenance when alt did not verify.
        $this->assertSame('', get_post_meta(975, '_acx_description_provenance', true));
    }

    /**
     * R20-BR-08: successful table row must not contain a bare or empty error=.
     */
    public function testGenerateTableSuccessRowHasNoErrorSubstring(): void
    {
        $service = new RecordingDescribeService([
            976 => new WP_REST_Response([
                'media_id' => 976,
                'alt_text_draft' => 'Clean success draft.',
                'adapter' => 'seeded',
                'model_id' => 'local-v1',
            ]),
        ]);
        $command = new DescriptionCommand(null, $service);

        $command->__invoke(['generate'], ['media-id' => '976', 'write' => true]);

        $log = \WP_CLI::$messages['log'][0] ?? '';
        $this->assertStringContainsString('status=written', $log);
        $this->assertStringNotContainsString('error=', $log);
    }

    /**
     * R20-BR-08: skipped table row must not contain a bare or empty error=.
     */
    public function testGenerateTableSkipRowHasNoErrorSubstring(): void
    {
        $this->setPostMeta(977, '_wp_attachment_image_alt', 'Human alt stays.');
        $service = new RecordingDescribeService([
            977 => new WP_REST_Response([
                'media_id' => 977,
                'alt_text_draft' => 'Different generated draft.',
            ]),
        ]);
        $command = new DescriptionCommand(null, $service);

        $command->__invoke(['generate'], ['media-id' => '977', 'write' => true]);

        $log = \WP_CLI::$messages['log'][0] ?? '';
        $this->assertStringContainsString('status=skipped_existing_alt', $log);
        $this->assertStringNotContainsString('error=', $log);
    }

    /**
     * R17-BR-13: force success reports forced_overwrite on table log and is a
     * CLI_STATUSES member (tally key).
     */
    public function testGenerateForceSuccessEmitsForcedOverwriteOnTableAndJson(): void
    {
        $this->setPostMeta(980, '_wp_attachment_image_alt', 'Prior human alt.');
        $service = new RecordingDescribeService([
            980 => new WP_REST_Response([
                'media_id' => 980,
                'alt_text_draft' => 'Forced replacement draft.',
                'adapter' => 'seeded',
                'model_id' => 'local-v1',
            ]),
        ]);
        $command = new DescriptionCommand(null, $service);

        $command->__invoke([
            'generate',
        ], [
            'media-id' => '980',
            'write' => true,
            'force' => true,
            'format' => 'json',
        ]);
        $payload = json_decode(\WP_CLI::$messages['log'][0] ?? '', true);
        $this->assertSame(AltTextWriteStatus::FORCED_OVERWRITE, $payload['rows'][0]['status'] ?? null);
        $this->assertSame('forced_overwrite', $payload['rows'][0]['status'] ?? null);
        $this->assertSame(1, $payload['forced_overwrite'] ?? null);
        $this->assertContains(AltTextWriteStatus::FORCED_OVERWRITE, AltTextWriteStatus::CLI_STATUSES);

        \WP_CLI::reset_cli_messages();
        $this->setPostMeta(981, '_wp_attachment_image_alt', 'Prior human alt.');
        $command->__invoke([
            'generate',
        ], [
            'media-id' => '981',
            'write' => true,
            'force' => true,
        ]);
        $this->assertStringContainsString('status=forced_overwrite', \WP_CLI::$messages['log'][0] ?? '');
        $this->assertStringContainsString('forced_overwrite=1', \WP_CLI::$messages['success'][0] ?? '');
    }

    /**
     * R16-BR-06: provenance fails + marker lands → partial + reason, marker readable.
     */
    public function testGenerateProvenanceFailurePlantsVerifiedRecoveryMarker(): void
    {
        $draft = 'Alt lands, provenance does not — marker stays.';
        $service = new RecordingDescribeService([
            982 => new WP_REST_Response([
                'media_id' => 982,
                'alt_text_draft' => $draft,
                'adapter' => 'seeded',
                'model_id' => 'local-v1',
            ]),
        ]);
        $GLOBALS['__ac_update_post_meta_fail'][982]['_acx_description_provenance'] = true;
        $command = new DescriptionCommand(null, $service);

        $caught = null;
        try {
            $command->__invoke(['generate'], ['media-id' => '982', 'write' => true, 'format' => 'json']);
        } catch (RuntimeException $e) {
            $caught = $e;
        }

        $this->assertInstanceOf(RuntimeException::class, $caught);
        $payload = json_decode(\WP_CLI::$messages['log'][0] ?? '', true);
        $this->assertSame(AltTextWriteStatus::PARTIAL, $payload['rows'][0]['status'] ?? null);
        $this->assertSame(
            AltTextWriteStatus::REASON_PROVENANCE_WRITE_FAILED,
            $payload['rows'][0]['reason'] ?? null
        );
        $pending = get_post_meta(982, '_acx_description_provenance_pending', true);
        $this->assertIsArray($pending);
        $this->assertSame('cli', $pending['run_id']);
        $this->assertSame(hash('sha256', $draft), $pending['draft_hash']);
        $this->assertSame($draft, get_post_meta(982, '_wp_attachment_image_alt', true));
    }

    /**
     * R16-BR-06: provenance fails + marker write also fails → failed, not partial.
     */
    public function testGenerateProvenanceAndMarkerFailureReportsFailedNotPartial(): void
    {
        $service = new RecordingDescribeService([
            983 => new WP_REST_Response([
                'media_id' => 983,
                'alt_text_draft' => 'Alt lands; marker does not.',
                'adapter' => 'seeded',
                'model_id' => 'local-v1',
            ]),
        ]);
        $GLOBALS['__ac_update_post_meta_fail'][983]['_acx_description_provenance'] = true;
        $GLOBALS['__ac_update_post_meta_fail'][983]['_acx_description_provenance_pending'] = true;
        $command = new DescriptionCommand(null, $service);

        $caught = null;
        try {
            $command->__invoke(['generate'], ['media-id' => '983', 'write' => true, 'format' => 'json']);
        } catch (RuntimeException $e) {
            $caught = $e;
        }

        $this->assertInstanceOf(RuntimeException::class, $caught);
        $payload = json_decode(\WP_CLI::$messages['log'][0] ?? '', true);
        $this->assertSame(AltTextWriteStatus::FAILED, $payload['rows'][0]['status'] ?? null);
        $this->assertNotSame(AltTextWriteStatus::PARTIAL, $payload['rows'][0]['status'] ?? null);
        $this->assertSame(1, $payload['failed'] ?? null);
        $this->assertSame(0, $payload['partial'] ?? null);
        $this->assertSame('Alt lands; marker does not.', get_post_meta(983, '_wp_attachment_image_alt', true));
        $this->assertSame('', get_post_meta(983, '_acx_description_provenance', true));
        $this->assertSame('', get_post_meta(983, '_acx_description_provenance_pending', true));
    }

    /**
     * R16-BR-06: success path leaves no recovery marker behind.
     */
    public function testGenerateSuccessLeavesNoRecoveryMarker(): void
    {
        $service = new RecordingDescribeService([
            984 => new WP_REST_Response([
                'media_id' => 984,
                'alt_text_draft' => 'Full success draft.',
                'adapter' => 'seeded',
                'model_id' => 'local-v1',
            ]),
        ]);
        $command = new DescriptionCommand(null, $service);

        $command->__invoke(['generate'], ['media-id' => '984', 'write' => true, 'format' => 'json']);

        $payload = json_decode(\WP_CLI::$messages['log'][0] ?? '', true);
        $this->assertSame(AltTextWriteStatus::WRITTEN, $payload['rows'][0]['status'] ?? null);
        $this->assertSame('', get_post_meta(984, '_acx_description_provenance_pending', true));
        $this->assertIsArray(get_post_meta(984, '_acx_description_provenance', true));
    }

    /**
     * R20-BR-18: CLI identity_complete success must clear a stale pending marker.
     */
    public function testGenerateIdentityCompleteSuccessClearsStaleMarker(): void
    {
        $draft = 'Matching stored alt for clear.';
        $this->setPostMeta(985, '_wp_attachment_image_alt', $draft);
        $this->setPostMeta(985, '_acx_description_provenance', [
            'adapter' => 'seeded',
            'model_id' => 'local-v1',
            'model_version' => '2026-07-04',
            'prompt_or_task_version' => 'describe-v1',
            'generated_at' => '2026-01-01T00:00:00+00:00',
            'alt_text_draft' => $draft,
        ]);
        $this->setPostMeta(985, '_acx_description_provenance_pending', [
            'run_id' => 'cli',
            'draft_hash' => hash('sha256', 'stale-gap'),
        ]);
        $service = new RecordingDescribeService([
            985 => new WP_REST_Response([
                'media_id' => 985,
                'alt_text_draft' => $draft,
                'adapter' => 'seeded',
                'model_id' => 'local-v1',
                'model_version' => '2026-07-04',
                'prompt_or_task_version' => 'describe-v1',
            ]),
        ]);
        $command = new DescriptionCommand(null, $service);

        $command->__invoke(['generate'], ['media-id' => '985', 'write' => true, 'format' => 'json']);
        $payload = json_decode(\WP_CLI::$messages['log'][0] ?? '', true);

        $this->assertSame(AltTextWriteStatus::SKIPPED_EXISTING_ALT, $payload['rows'][0]['status'] ?? null);
        $this->assertSame('', get_post_meta(985, '_acx_description_provenance_pending', true));

        $GLOBALS['__ac_get_posts_results'] = [985];
        $GLOBALS['__ac_posts'][985] = (object) [
            'ID' => 985,
            'post_type' => 'attachment',
            'post_title' => 'CLI clear',
        ];
        $GLOBALS['__ac_attachment_mimes'][985] = 'image/jpeg';
        $history = (new \AltContext\Api\Services\DescriptionHistoryService())->list_history(10);
        $this->assertSame(1, $history['total']);
        $this->assertIsArray($history['items'][0]['provenance']);
    }

    /**
     * R21-BR-02: CLI skip_existing clears a STALE pending marker (hash ≠ stored alt).
     */
    public function testGenerateSkipExistingClearsStaleProvenancePendingMarker(): void
    {
        $this->setPostMeta(988, '_wp_attachment_image_alt', 'Human-authored CLI alt');
        $this->setPostMeta(988, '_acx_description_provenance_pending', [
            'run_id' => 'cli',
            'draft_hash' => hash('sha256', 'stale-gap'),
        ]);
        $service = new RecordingDescribeService([
            988 => new WP_REST_Response([
                'media_id' => 988,
                'alt_text_draft' => 'Different model draft',
                'adapter' => 'seeded',
                'model_id' => 'local-v1',
            ]),
        ]);
        $command = new DescriptionCommand(null, $service);

        $command->__invoke(['generate'], ['media-id' => '988', 'write' => true, 'format' => 'json']);
        $payload = json_decode(\WP_CLI::$messages['log'][0] ?? '', true);

        $this->assertSame(AltTextWriteStatus::SKIPPED_EXISTING_ALT, $payload['rows'][0]['status'] ?? null);
        $this->assertSame('', get_post_meta(988, '_acx_description_provenance_pending', true));

        $GLOBALS['__ac_get_posts_results'] = [988];
        $GLOBALS['__ac_posts'][988] = (object) [
            'ID' => 988,
            'post_type' => 'attachment',
            'post_title' => 'CLI skip stale',
        ];
        $GLOBALS['__ac_attachment_mimes'][988] = 'image/jpeg';
        $history = (new \AltContext\Api\Services\DescriptionHistoryService())->list_history(10);
        $this->assertSame(0, $history['total'], 'stale pure gap must leave history after marker clear');
    }

    /**
     * R21-BR-02 / R22-BR-01 / R22-BR-07 [TEST-15]: CLI skip_existing must preserve
     * a LIVE recovery marker planted by the production writer. Backslash-bearing
     * draft so raw vs stored hash domains diverge; marker produced via partial
     * path (not hand-shaped to the predicate).
     *
     * RED under: plant draft_hash = hash(raw draft) instead of stored form.
     */
    public function testGenerateSkipExistingPreservesLiveProvenancePendingMarker(): void
    {
        $rawDraft  = 'AC\\DC concert poster';
        $storedAlt = wp_unslash($rawDraft);
        $this->assertNotSame($rawDraft, $storedAlt, 'precondition: unslash must change the bytes');

        // Production plant: alt lands, provenance fails → marker via writer path.
        $service = new RecordingDescribeService([
            989 => new WP_REST_Response([
                'media_id' => 989,
                'alt_text_draft' => $rawDraft,
                'adapter' => 'seeded',
                'model_id' => 'local-v1',
            ]),
        ]);
        $GLOBALS['__ac_update_post_meta_fail'][989]['_acx_description_provenance'] = true;
        $command = new DescriptionCommand(null, $service);

        $caught = null;
        try {
            $command->__invoke(['generate'], ['media-id' => '989', 'write' => true, 'format' => 'json']);
        } catch (RuntimeException $e) {
            $caught = $e;
        }
        $this->assertInstanceOf(RuntimeException::class, $caught);
        $payload = json_decode(\WP_CLI::$messages['log'][0] ?? '', true);
        $this->assertSame(AltTextWriteStatus::PARTIAL, $payload['rows'][0]['status'] ?? null);
        $this->assertSame($storedAlt, get_post_meta(989, '_wp_attachment_image_alt', true));
        $liveMarker = get_post_meta(989, '_acx_description_provenance_pending', true);
        $this->assertIsArray($liveMarker);

        // Second generate: DIFFERENT draft, force=false → skip_existing. Marker survives.
        // Load-bearing [TEST-15] claim: RED when plant hashes raw draft while
        // is_live_recovery_marker_for_alt hashes stored form (R22-BR-01).
        unset($GLOBALS['__ac_update_post_meta_fail'][989]['_acx_description_provenance']);
        \WP_CLI::reset_cli_messages();
        $service2 = new RecordingDescribeService([
            989 => new WP_REST_Response([
                'media_id' => 989,
                'alt_text_draft' => 'A different draft from the model',
                'adapter' => 'seeded',
                'model_id' => 'local-v1',
            ]),
        ]);
        $command2 = new DescriptionCommand(null, $service2);
        $command2->__invoke(['generate'], ['media-id' => '989', 'write' => true, 'format' => 'json']);
        $payload2 = json_decode(\WP_CLI::$messages['log'][0] ?? '', true);

        $this->assertSame(AltTextWriteStatus::SKIPPED_EXISTING_ALT, $payload2['rows'][0]['status'] ?? null);
        $this->assertSame(
            $liveMarker,
            get_post_meta(989, '_acx_description_provenance_pending', true),
            'live recovery marker must survive skip_existing'
        );
        $this->assertSame(
            \AltContext\Api\Services\DescriptionHistoryService::hash_for_stored_alt($storedAlt),
            $liveMarker['draft_hash'] ?? null,
            'production plant must hash the stored form, not the raw draft'
        );

        $GLOBALS['__ac_get_posts_results'] = [989];
        $GLOBALS['__ac_posts'][989] = (object) [
            'ID' => 989,
            'post_type' => 'attachment',
            'post_title' => 'CLI skip live',
        ];
        $GLOBALS['__ac_attachment_mimes'][989] = 'image/jpeg';
        $history = (new \AltContext\Api\Services\DescriptionHistoryService())->list_history(10);
        $this->assertSame(1, $history['total'], 'live gap row must remain in history');
        $this->assertArrayHasKey('provenance', $history['items'][0]);
        $this->assertNull($history['items'][0]['provenance']);
        $this->assertSame($storedAlt, $history['items'][0]['current_alt_text'] ?? null);
    }

    /**
     * R20-BR-20 / R21-BR-03: CLI marker plant stores verified-SHAPE array with
     * wrong draft_hash → failed (draft_hash match leg).
     */
    public function testGenerateMarkerWriteDivergentStoreReportsFailedNotPartial(): void
    {
        $service = new RecordingDescribeService([
            986 => new WP_REST_Response([
                'media_id' => 986,
                'alt_text_draft' => 'Alt lands; marker garbled.',
                'adapter' => 'seeded',
                'model_id' => 'local-v1',
            ]),
        ]);
        $GLOBALS['__ac_update_post_meta_fail'][986]['_acx_description_provenance'] = true;
        $divergent = [
            'run_id' => 'wrong',
            'draft_hash' => 'deadbeef',
        ];
        $GLOBALS['__ac_update_post_meta_mutate'][986]['_acx_description_provenance_pending'] = $divergent;
        $command = new DescriptionCommand(null, $service);

        $caught = null;
        try {
            $command->__invoke(['generate'], ['media-id' => '986', 'write' => true, 'format' => 'json']);
        } catch (RuntimeException $e) {
            $caught = $e;
        }

        $this->assertInstanceOf(RuntimeException::class, $caught);
        $payload = json_decode(\WP_CLI::$messages['log'][0] ?? '', true);
        $this->assertSame(AltTextWriteStatus::FAILED, $payload['rows'][0]['status'] ?? null);
        $this->assertNotSame(AltTextWriteStatus::PARTIAL, $payload['rows'][0]['status'] ?? null);
        $this->assertSame($divergent, get_post_meta(986, '_acx_description_provenance_pending', true));
    }

    /**
     * R21-BR-03: CLI non-array marker store fails the shape leg alone.
     */
    public function testGenerateMarkerWriteNonArrayStoreReportsFailedNotPartial(): void
    {
        $service = new RecordingDescribeService([
            990 => new WP_REST_Response([
                'media_id' => 990,
                'alt_text_draft' => 'Alt lands; marker non-array.',
                'adapter' => 'seeded',
                'model_id' => 'local-v1',
            ]),
        ]);
        $GLOBALS['__ac_update_post_meta_fail'][990]['_acx_description_provenance'] = true;
        $GLOBALS['__ac_update_post_meta_mutate'][990]['_acx_description_provenance_pending'] = 'GARBAGE';
        $command = new DescriptionCommand(null, $service);

        $caught = null;
        try {
            $command->__invoke(['generate'], ['media-id' => '990', 'write' => true, 'format' => 'json']);
        } catch (RuntimeException $e) {
            $caught = $e;
        }

        $this->assertInstanceOf(RuntimeException::class, $caught);
        $payload = json_decode(\WP_CLI::$messages['log'][0] ?? '', true);
        $this->assertSame(AltTextWriteStatus::FAILED, $payload['rows'][0]['status'] ?? null);
        $this->assertSame('GARBAGE', get_post_meta(990, '_acx_description_provenance_pending', true));
    }

    /**
     * R21-BR-04: CLI provenance write accepts but stores divergent ARRAY → partial.
     */
    public function testGenerateProvenanceWriteDivergentArrayStoreReportsPartial(): void
    {
        $service = new RecordingDescribeService([
            991 => new WP_REST_Response([
                'media_id' => 991,
                'alt_text_draft' => 'Alt lands; provenance mutated.',
                'adapter' => 'seeded',
                'model_id' => 'local-v1',
            ]),
        ]);
        $GLOBALS['__ac_update_post_meta_mutate'][991]['_acx_description_provenance'] = [
            'adapter' => 'MUTATED_NOT_THIS_RUN',
            'model_id' => 'wrong',
        ];
        $command = new DescriptionCommand(null, $service);

        $caught = null;
        try {
            $command->__invoke(['generate'], ['media-id' => '991', 'write' => true, 'format' => 'json']);
        } catch (RuntimeException $e) {
            $caught = $e;
        }

        $this->assertInstanceOf(RuntimeException::class, $caught);
        $payload = json_decode(\WP_CLI::$messages['log'][0] ?? '', true);
        $this->assertSame(AltTextWriteStatus::PARTIAL, $payload['rows'][0]['status'] ?? null);
        $this->assertSame(
            AltTextWriteStatus::REASON_PROVENANCE_WRITE_FAILED,
            $payload['rows'][0]['reason'] ?? null
        );
        $this->assertNotSame(AltTextWriteStatus::WRITTEN, $payload['rows'][0]['status'] ?? null);
        $pending = get_post_meta(991, '_acx_description_provenance_pending', true);
        $this->assertIsArray($pending);
        $this->assertSame(hash('sha256', 'Alt lands; provenance mutated.'), $pending['draft_hash'] ?? null);
    }

    /**
     * R21-BR-08: CLI accepts pre-existing same-draft bulk marker when plant fails.
     */
    public function testGenerateAcceptsPreExistingSameDraftBulkMarkerWhenPlantFails(): void
    {
        $draft = 'CLI alt with pre-existing bulk marker.';
        $bulkMarker = [
            'run_id' => '11111111-1111-1111-1111-111111111111',
            'draft_hash' => hash('sha256', $draft),
        ];
        $this->setPostMeta(992, '_acx_description_provenance_pending', $bulkMarker);
        $service = new RecordingDescribeService([
            992 => new WP_REST_Response([
                'media_id' => 992,
                'alt_text_draft' => $draft,
                'adapter' => 'seeded',
                'model_id' => 'local-v1',
            ]),
        ]);
        $GLOBALS['__ac_update_post_meta_fail'][992]['_acx_description_provenance'] = true;
        $GLOBALS['__ac_update_post_meta_fail'][992]['_acx_description_provenance_pending'] = true;
        $command = new DescriptionCommand(null, $service);

        $caught = null;
        try {
            $command->__invoke(['generate'], ['media-id' => '992', 'write' => true, 'format' => 'json']);
        } catch (RuntimeException $e) {
            $caught = $e;
        }

        $this->assertInstanceOf(RuntimeException::class, $caught);
        $payload = json_decode(\WP_CLI::$messages['log'][0] ?? '', true);
        $this->assertSame(AltTextWriteStatus::PARTIAL, $payload['rows'][0]['status'] ?? null);
        $this->assertNotSame(AltTextWriteStatus::FAILED, $payload['rows'][0]['status'] ?? null);
        $this->assertSame($bulkMarker, get_post_meta(992, '_acx_description_provenance_pending', true));
    }

    /**
     * R20-BR-20: pre-plant identical CLI marker so update returns false; read-back admits partial.
     */
    public function testGenerateMarkerWriteNoOpFalseReturnAcceptedWhenReadBackMatches(): void
    {
        $draft  = 'Alt lands; marker already identical.';
        $marker = [
            'run_id' => 'cli',
            'draft_hash' => hash('sha256', $draft),
        ];
        $this->setPostMeta(987, '_acx_description_provenance_pending', $marker);
        $service = new RecordingDescribeService([
            987 => new WP_REST_Response([
                'media_id' => 987,
                'alt_text_draft' => $draft,
                'adapter' => 'seeded',
                'model_id' => 'local-v1',
            ]),
        ]);
        $GLOBALS['__ac_update_post_meta_fail'][987]['_acx_description_provenance'] = true;
        $command = new DescriptionCommand(null, $service);

        $caught = null;
        try {
            $command->__invoke(['generate'], ['media-id' => '987', 'write' => true, 'format' => 'json']);
        } catch (RuntimeException $e) {
            $caught = $e;
        }

        $this->assertInstanceOf(RuntimeException::class, $caught);
        $payload = json_decode(\WP_CLI::$messages['log'][0] ?? '', true);
        $this->assertSame(AltTextWriteStatus::PARTIAL, $payload['rows'][0]['status'] ?? null);
        $this->assertSame(
            AltTextWriteStatus::REASON_PROVENANCE_WRITE_FAILED,
            $payload['rows'][0]['reason'] ?? null
        );
        $this->assertSame($marker, get_post_meta(987, '_acx_description_provenance_pending', true));
    }
}

class RecordingDescribeService extends DescribeMediaService
{
    /** @var int[] */
    public array $requestedMediaIds = [];

    /** @param array<int,WP_REST_Response|WP_Error> $responses */
    public function __construct(private array $responses)
    {
    }

    public function describe_media(WP_REST_Request $request): WP_REST_Response|\WP_Error
    {
        $mediaId = (int) $request->get_param('media_id');
        $this->requestedMediaIds[] = $mediaId;

        return $this->responses[$mediaId] ?? new WP_REST_Response(
            ['media_id' => $mediaId, 'alt_text_draft' => 'Generated alt text.']
        );
    }
}

/**
 * Candidate service that returns a fixed media_id list so multi-row / empty
 * CLI generate can exercise the real tally path without planting get_posts.
 */
class FixedCandidateService extends DescriptionCandidateService
{
    /** @param list<int> $mediaIds */
    public function __construct(private array $mediaIds)
    {
    }

    public function list_missing_alt_candidates(int $limit = 50, int $offset = 0): array
    {
        $candidates = array();
        foreach ($this->mediaIds as $id) {
            $candidates[] = array(
                'media_id' => $id,
                'title' => "Photo {$id}",
                'candidate_reason' => 'missing_alt',
                'has_alt_text' => false,
                'provenance' => null,
            );
        }

        return array(
            'candidates' => array_slice($candidates, $offset, $limit),
            'exclusions' => array(),
            'limit' => $limit,
            'offset' => $offset,
            'total_candidates' => count($candidates),
            'total_exclusions' => 0,
        );
    }
}
