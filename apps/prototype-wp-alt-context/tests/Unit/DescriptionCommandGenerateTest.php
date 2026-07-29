<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Api\DescribeHostInterface;
use AltContext\Api\Services\DescribeMediaService;
use AltContext\Cli\DescriptionCommand;
use AltContext\Tests\TestCase;
use RuntimeException;
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
    }

    public function testGenerateSurfacesUpstreamDetailOnErrorResponse(): void
    {
        $service = new RecordingDescribeService([
            302 => new WP_REST_Response(['detail' => 'tenant mismatch'], 403),
        ]);
        $command = new DescriptionCommand(null, $service);

        $command->__invoke(['generate'], ['media-id' => '302', 'format' => 'json']);

        $payload = json_decode(\WP_CLI::$messages['log'][0] ?? '', true);

        $this->assertSame('failed', $payload['rows'][0]['status']);
        $this->assertSame('tenant mismatch', $payload['rows'][0]['error']);
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

        \WP_CLI::reset_cli_messages();
        $command->__invoke(['generate'], ['media-id' => '501', 'write' => true, 'force' => true, 'format' => 'json']);
        $secondPayload = json_decode(\WP_CLI::$messages['log'][0] ?? '', true);

        $this->assertSame('Generated replacement alt.', get_post_meta(501, '_wp_attachment_image_alt', true));
        $this->assertSame('written', $secondPayload['rows'][0]['status']);
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

        $command->__invoke(['generate'], ['media-id' => '601', 'write' => true, 'format' => 'json']);

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

        $command->__invoke(['generate'], ['media-id' => '901', 'write' => true, 'format' => 'json']);

        $payload = json_decode(\WP_CLI::$messages['log'][0] ?? '', true);

        $this->assertNotSame('written', $payload['rows'][0]['status']);
        $this->assertSame('failed', $payload['rows'][0]['status']);
        // Storage truth: alt empty, provenance absent — no fabricated Generated-alt.
        $this->assertSame('', get_post_meta(901, '_wp_attachment_image_alt', true));
        $this->assertSame('', get_post_meta(901, '_acx_description_provenance', true));
    }

    /**
     * BR-01: alt succeeds, provenance fails → partial. Alt stays written.
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

        $command->__invoke(['generate'], ['media-id' => '902', 'write' => true, 'format' => 'json']);

        $payload = json_decode(\WP_CLI::$messages['log'][0] ?? '', true);

        $this->assertSame('partial', $payload['rows'][0]['status']);
        $this->assertSame('Alt lands, provenance does not.', get_post_meta(902, '_wp_attachment_image_alt', true));
        $this->assertSame('', get_post_meta(902, '_acx_description_provenance', true));
    }

    /**
     * BR-17 / plain no-op: CLI re-write of a byte-identical alt is not reported
     * as failed. Does not pin the write-result guard itself (stays green if that
     * branch is neutered); see sibling failure tests and the backslash-bearing
     * save/resave pin for the unslash read-back path.
     */
    public function testGenerateWriteByteIdenticalRewriteIsNotReportedAsFailed(): void
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

        $this->assertSame('written', $payload['rows'][0]['status']);
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
            'written',
            $secondPayload['rows'][0]['status'],
            'Second save with same backslash alt must not fail'
        );
        $this->assertSame($expectedStored, get_post_meta(904, '_wp_attachment_image_alt', true));
    }
}

class RecordingDescribeService extends DescribeMediaService
{
    /** @var int[] */
    public array $requestedMediaIds = [];

    /** @param array<int,WP_REST_Response> $responses */
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
