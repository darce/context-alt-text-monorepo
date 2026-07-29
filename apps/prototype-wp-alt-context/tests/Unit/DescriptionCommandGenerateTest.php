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
