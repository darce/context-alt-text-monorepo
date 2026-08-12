<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Api\AltTextWriteStatus;
use AltContext\Api\DescriptionWriteStatus;
use AltContext\Api\DescribeController;
use AltContext\Api\Services\DescriptionCandidateService;
use AltContext\Api\Services\DescribeMediaService;
use AltContext\Cli\DescriptionCommand;
use AltContext\Tests\TestCase;
use RuntimeException;
use WP_REST_Request;
use WP_REST_Response;

/**
 * gx3Status wave: canonical status vocabulary + honest CLI tally.
 *
 * @covers \AltContext\Api\AltTextWriteStatus
 * @covers \AltContext\Api\DescriptionWriteStatus
 * @covers \AltContext\Api\Services\DescribeMediaService
 * @covers \AltContext\Cli\DescriptionCommand
 */
class AltTextWriteStatusVocabularyTest extends TestCase
{
    private DescribeController $controller;
    private string $tempDir;

    protected function setUp(): void
    {
        parent::setUp();
        \WP_CLI::reset_cli_messages();
        $this->setOption('acx_recognition_url', 'http://localhost:8000');
        $this->setOption('acx_recognition_api_key', 'test-key');
        $this->controller = new DescribeController();
        $this->tempDir = sys_get_temp_dir() . '/acx-gx3-status-' . uniqid();
        mkdir($this->tempDir, 0o755, true);
    }

    protected function tearDown(): void
    {
        if (is_dir($this->tempDir)) {
            foreach (glob($this->tempDir . '/*') as $f) {
                @unlink($f);
            }
            @rmdir($this->tempDir);
        }
        parent::tearDown();
    }

    // ── R17-BR-10: DescriptionWriteStatus is independently file-addressable ──

    /**
     * Cold-process probe: requiring only class-description-write-status.php must
     * declare DescriptionWriteStatus (no freeride on class-alt-text-write-status
     * or Composer classmap). Modeled on DescribeControllerAutoloadTest.
     */
    public function testDescriptionWriteStatusIsIndependentlyAddressable(): void
    {
        $entrypoint = realpath(__DIR__ . '/../../src/api/class-description-write-status.php');
        self::assertIsString($entrypoint, 'class-description-write-status.php must exist');

        $script = sprintf(
            'require %s; var_export(%s);',
            var_export($entrypoint, true),
            "class_exists('AltContext\\\\Api\\\\DescriptionWriteStatus', false)"
            . " && !class_exists('AltContext\\\\Api\\\\AltTextWriteStatus', false)"
            . " && \\AltContext\\Api\\DescriptionWriteStatus::FAILED === 'failed'"
            . " && \\AltContext\\Api\\DescriptionWriteStatus::ALL === array("
            . "'written','forced_overwrite','skipped_no_long_text',"
            . "'skipped_existing_description','failed')"
        );
        $output = shell_exec(sprintf('php -r %s 2>&1', escapeshellarg($script)));
        $this->assertSame(
            'true',
            trim((string) $output),
            sprintf(
                'DescriptionWriteStatus must load from its own file alone; got: %s',
                var_export($output, true)
            )
        );
    }

    // ── BR-04 / BR-07: pin the PHP member set (TS parity is review-only) ──

    /**
     * BR-04: pin the full produced union so contract docs / TS can be updated
     * to match. TS parity is enforced by review, not by a gate.
     */
    public function testPinnedAltTextWriteStatusMemberSet(): void
    {
        $this->assertSame(
            array(
                'written',
                'skipped_existing_alt',
                'skipped_empty_alt_text',
                'forced_overwrite',
                'provenance_healed',
                'partial',
                'failed',
                'dry_run',
            ),
            AltTextWriteStatus::ALL
        );
        $this->assertSame(
            array(
                'written',
                'skipped_existing_alt',
                'skipped_empty_alt_text',
                'forced_overwrite',
                'provenance_healed',
                'partial',
                'failed',
            ),
            AltTextWriteStatus::REST_STATUSES
        );
        $this->assertSame(
            array(
                'written',
                'skipped_existing_alt',
                'skipped_empty_alt_text',
                'forced_overwrite',
                'provenance_healed',
                'partial',
                'failed',
                'dry_run',
            ),
            AltTextWriteStatus::CLI_STATUSES
        );
        $this->assertSame(
            array(
                'provenance_write_failed',
                'description_write_failed',
            ),
            AltTextWriteStatus::PARTIAL_REASONS
        );
        $this->assertSame(
            array(
                'written',
                'forced_overwrite',
                'skipped_no_long_text',
                'skipped_existing_description',
                'failed',
            ),
            DescriptionWriteStatus::ALL
        );
        // Bulk apply bucket keys — SPA wire contract, ordered (R19-BR-21).
        $this->assertSame(
            array(
                'applied',
                'partial',
                'skipped_existing',
                'skipped_no_draft',
                'skipped_invalid',
                'failed',
            ),
            AltTextWriteStatus::BULK_APPLY_BUCKETS
        );
        // Non-bulk provenance-pending marker owners [R20-BR-16].
        $this->assertSame(
            array(
                'cli',
                'single_image',
            ),
            AltTextWriteStatus::MARKER_OWNERS
        );
        // Wire literals (not constant-to-constant) — durable recovery tokens.
        $this->assertSame('cli', AltTextWriteStatus::MARKER_OWNER_CLI);
        $this->assertSame('single_image', AltTextWriteStatus::MARKER_OWNER_SINGLE_IMAGE);
    }

    /**
     * R20-BR-16: every MARKER_OWNER_* sentinel const must appear in MARKER_OWNERS,
     * and MARKER_OWNERS must contain only those sentinels. A new owner const that
     * is never registered, or a list entry without a matching const, turns RED.
     * Bulk run UUIDs are not members — membership is the non-bulk discriminator.
     */
    public function testMarkerOwnerConstantsAreReflectedIntoMarkerOwners(): void
    {
        $reflection = new \ReflectionClass(AltTextWriteStatus::class);
        $owner_values = array();
        foreach ($reflection->getConstants() as $name => $value) {
            if (!is_string($value)) {
                continue;
            }
            if (!str_starts_with((string) $name, 'MARKER_OWNER_')) {
                continue;
            }
            $owner_values[$name] = $value;
        }

        $this->assertNotEmpty(
            $owner_values,
            'At least one MARKER_OWNER_* sentinel must be declared'
        );

        foreach ($owner_values as $name => $value) {
            $this->assertContains(
                $value,
                AltTextWriteStatus::MARKER_OWNERS,
                "Marker owner const {$name}={$value} must be a member of MARKER_OWNERS"
            );
        }

        $this->assertSame(
            count($owner_values),
            count(AltTextWriteStatus::MARKER_OWNERS),
            'MARKER_OWNERS must not contain entries beyond declared MARKER_OWNER_* consts'
        );

        foreach (AltTextWriteStatus::MARKER_OWNERS as $owner) {
            $this->assertContains(
                $owner,
                array_values($owner_values),
                "MARKER_OWNERS entry {$owner} must match a declared MARKER_OWNER_* const"
            );
        }

        // Bulk UUIDs are run ids, not sentinels — must never appear in the set.
        $this->assertNotContains(
            '11111111-1111-1111-1111-111111111111',
            AltTextWriteStatus::MARKER_OWNERS
        );
    }

    /**
     * R20-BR-06: every status-valued public const must appear in ALL; ALL equals
     * REST ∪ CLI; neither surface introduces members absent from ALL. REASON_*
     * consts are excluded by prefix (reasons, not statuses). A new status const
     * absent from the lists must turn this suite RED.
     */
    public function testStatusConstantsAreReflectedIntoListSurfaces(): void
    {
        $reflection = new \ReflectionClass(AltTextWriteStatus::class);
        $status_values = array();
        foreach ($reflection->getConstants() as $name => $value) {
            if (!is_string($value)) {
                continue;
            }
            // Reasons are not statuses — exclude by explicit named prefix rule.
            if (str_starts_with((string) $name, 'REASON_')) {
                continue;
            }
            // Marker owners are recovery sentinels, not alt-write statuses [R20-BR-16].
            if (str_starts_with((string) $name, 'MARKER_OWNER_')) {
                continue;
            }
            // Recovery descriptor kinds are provenance vocabulary, not alt-write
            // statuses [R23-BR-20/21/22].
            if (str_starts_with((string) $name, 'RECOVERY_KIND_')) {
                continue;
            }
            // List surfaces themselves are array constants, not status values.
            if (is_array($reflection->getConstant($name))) {
                continue;
            }
            $status_values[$name] = $value;
        }

        foreach ($status_values as $name => $value) {
            $this->assertContains(
                $value,
                AltTextWriteStatus::ALL,
                "Status const {$name}={$value} must be a member of ALL"
            );
        }

        $rest_cli_union = array_values(
            array_unique(
                array_merge(AltTextWriteStatus::REST_STATUSES, AltTextWriteStatus::CLI_STATUSES)
            )
        );
        sort($rest_cli_union);
        $all_sorted = AltTextWriteStatus::ALL;
        sort($all_sorted);
        $this->assertSame(
            $all_sorted,
            $rest_cli_union,
            'ALL must equal the union of REST_STATUSES and CLI_STATUSES'
        );

        foreach (AltTextWriteStatus::REST_STATUSES as $status) {
            $this->assertContains($status, AltTextWriteStatus::ALL);
        }
        foreach (AltTextWriteStatus::CLI_STATUSES as $status) {
            $this->assertContains($status, AltTextWriteStatus::ALL);
        }
    }

    /**
     * R20-BR-06: DescriptionWriteStatus list surface must include every
     * status-valued public const (no reason prefix on this class).
     */
    public function testDescriptionWriteStatusConstantsAreReflectedIntoAll(): void
    {
        $reflection = new \ReflectionClass(DescriptionWriteStatus::class);
        foreach ($reflection->getConstants() as $name => $value) {
            if (!is_string($value)) {
                continue;
            }
            if (is_array($reflection->getConstant($name))) {
                continue;
            }
            $this->assertContains(
                $value,
                DescriptionWriteStatus::ALL,
                "DescriptionWriteStatus::{$name} must be a member of ALL"
            );
        }
    }

    /**
     * BR-07: each status constant is load-bearing — values must stay
     * byte-identical to the pre-wave wire strings. Mutating a constant reds
     * both this pin and the consumer emission tests below.
     */
    public function testStatusConstantValuesAreByteIdenticalToWireStrings(): void
    {
        $this->assertSame('written', AltTextWriteStatus::WRITTEN);
        $this->assertSame('skipped_existing_alt', AltTextWriteStatus::SKIPPED_EXISTING_ALT);
        $this->assertSame('skipped_empty_alt_text', AltTextWriteStatus::SKIPPED_EMPTY_ALT_TEXT);
        $this->assertSame('forced_overwrite', AltTextWriteStatus::FORCED_OVERWRITE);
        $this->assertSame('provenance_healed', AltTextWriteStatus::PROVENANCE_HEALED);
        $this->assertSame('partial', AltTextWriteStatus::PARTIAL);
        $this->assertSame('failed', AltTextWriteStatus::FAILED);
        $this->assertSame('dry_run', AltTextWriteStatus::DRY_RUN);
        $this->assertSame('provenance_write_failed', AltTextWriteStatus::REASON_PROVENANCE_WRITE_FAILED);
        $this->assertSame('description_write_failed', AltTextWriteStatus::REASON_DESCRIPTION_WRITE_FAILED);
        $this->assertSame('written', DescriptionWriteStatus::WRITTEN);
        $this->assertSame('forced_overwrite', DescriptionWriteStatus::FORCED_OVERWRITE);
        $this->assertSame('skipped_no_long_text', DescriptionWriteStatus::SKIPPED_NO_LONG_TEXT);
        $this->assertSame('skipped_existing_description', DescriptionWriteStatus::SKIPPED_EXISTING_DESCRIPTION);
        $this->assertSame('failed', DescriptionWriteStatus::FAILED);
    }

    /**
     * BR-07: consumer (REST) emits the constant; pin the wire literal so
     * mutating the constant value makes this test go red.
     */
    public function testRestWrittenEmissionUsesCanonicalConstant(): void
    {
        $this->plantWritableAttachment(42);
        $this->queueHttpResponse(array(
            'response' => array('code' => 200, 'message' => 'OK'),
            'body'     => (string) json_encode($this->validBackendBody(42)),
        ));

        $result = $this->controller->describe_media($this->writeRequest(42));

        $this->assertInstanceOf(WP_REST_Response::class, $result);
        $status = $result->get_data()['alt_text_write']['status'] ?? null;
        // Literal pin — goes red if AltTextWriteStatus::WRITTEN is mutated.
        $this->assertSame('written', $status);
        $this->assertSame(AltTextWriteStatus::WRITTEN, $status);
    }

    /**
     * BR-07: CLI consumer also routes through the shared constant.
     */
    public function testCliWrittenEmissionUsesCanonicalConstant(): void
    {
        $service = new StatusVocabRecordingDescribeService([
            401 => new WP_REST_Response([
                'media_id' => 401,
                'alt_text_draft' => 'A black dog sitting by a window.',
                'adapter' => 'seeded',
                'model_id' => 'local-v1',
                'model_version' => '2026-07-04',
                'prompt_or_task_version' => 'describe-v1',
            ]),
        ]);
        $command = new DescriptionCommand(null, $service);

        $command->__invoke(['generate'], ['media-id' => '401', 'write' => true, 'format' => 'json']);

        $payload = json_decode(\WP_CLI::$messages['log'][0] ?? '', true);
        $status  = $payload['rows'][0]['status'] ?? null;
        $this->assertSame('written', $status);
        $this->assertSame(AltTextWriteStatus::WRITTEN, $status);
    }

    public function testCliDryRunEmissionUsesCanonicalConstant(): void
    {
        $service = new StatusVocabRecordingDescribeService([
            301 => new WP_REST_Response(['media_id' => 301, 'alt_text_draft' => 'draft']),
        ]);
        $command = new DescriptionCommand(null, $service);

        $command->__invoke(['generate'], ['media-id' => '301', 'format' => 'json']);

        $payload = json_decode(\WP_CLI::$messages['log'][0] ?? '', true);
        $this->assertSame('dry_run', $payload['rows'][0]['status'] ?? null);
        $this->assertSame(AltTextWriteStatus::DRY_RUN, $payload['rows'][0]['status'] ?? null);
    }

    // ── BR-08: two partial meanings distinguishable via reason ──

    /**
     * BR-08: provenance stamp failed → partial + reason=provenance_write_failed.
     */
    public function testPartialProvenanceFailureEmitsReason(): void
    {
        $this->plantWritableAttachment(42);
        $this->queueHttpResponse(array(
            'response' => array('code' => 200, 'message' => 'OK'),
            'body'     => (string) json_encode($this->validBackendBody(42)),
        ));
        $GLOBALS['__ac_update_post_meta_fail'][42]['_acx_description_provenance'] = true;

        $result = $this->controller->describe_media($this->writeRequest(42));

        $this->assertInstanceOf(WP_REST_Response::class, $result);
        $write = $result->get_data()['alt_text_write'];
        $this->assertSame('partial', $write['status'] ?? null);
        // Literal pin — goes red if reason field is dropped or value mutated.
        $this->assertSame('provenance_write_failed', $write['reason'] ?? null);
        $this->assertSame(AltTextWriteStatus::REASON_PROVENANCE_WRITE_FAILED, $write['reason'] ?? null);
        $this->assertArrayNotHasKey('description_write', $write);
    }

    /**
     * BR-08: long-description failed after alt+prov landed → partial +
     * reason=description_write_failed. Distinguishable from provenance gap
     * from the status payload alone.
     */
    public function testPartialDescriptionWriteFailureEmitsReason(): void
    {
        $this->plantWritableAttachment(42);
        $this->setOption('acx_alt_style', 'alt_plus_description');
        $this->queueHttpResponse(array(
            'response' => array('code' => 200, 'message' => 'OK'),
            'body'     => (string) json_encode($this->validBackendBodyWithLong(42)),
        ));
        $GLOBALS['__ac_wp_update_post_fail'][42] = true;

        $result = $this->controller->describe_media($this->writeRequest(42));

        $this->assertInstanceOf(WP_REST_Response::class, $result);
        $write = $result->get_data()['alt_text_write'];
        $this->assertSame('partial', $write['status'] ?? null);
        $this->assertSame('description_write_failed', $write['reason'] ?? null);
        $this->assertSame(AltTextWriteStatus::REASON_DESCRIPTION_WRITE_FAILED, $write['reason'] ?? null);
        $this->assertSame('failed', $write['description_write'] ?? null);
        // The two partial meanings must not share the same reason.
        $this->assertNotSame(
            AltTextWriteStatus::REASON_PROVENANCE_WRITE_FAILED,
            $write['reason']
        );
    }

    /**
     * BR-08 / R20-BR-28: pin the partial-reason wire set as literals so a
     * rewritten REASON_* value (even if still distinct and still listed via
     * self::) turns this test RED. Vacuous self::-to-list membership is not
     * enough — the wire contract is the string bytes.
     */
    public function testPartialReasonsAreDistinct(): void
    {
        $this->assertSame('provenance_write_failed', AltTextWriteStatus::REASON_PROVENANCE_WRITE_FAILED);
        $this->assertSame('description_write_failed', AltTextWriteStatus::REASON_DESCRIPTION_WRITE_FAILED);
        $this->assertNotSame(
            AltTextWriteStatus::REASON_PROVENANCE_WRITE_FAILED,
            AltTextWriteStatus::REASON_DESCRIPTION_WRITE_FAILED
        );
        $this->assertSame(
            array(
                'provenance_write_failed',
                'description_write_failed',
            ),
            AltTextWriteStatus::PARTIAL_REASONS
        );
    }

    /**
     * R20-BR-19: every REASON_* const must appear in PARTIAL_REASONS, and
     * PARTIAL_REASONS must contain only those consts. Modeled on
     * testMarkerOwnerConstantsAreReflectedIntoMarkerOwners — a new reason
     * const that is never registered, or a list entry without a matching
     * const, turns RED. (testStatusConstantsAreReflectedIntoListSurfaces
     * deliberately excludes REASON_* from ALL; this is the reciprocal pin.)
     */
    public function testReasonConstantsAreReflectedIntoPartialReasons(): void
    {
        $reflection = new \ReflectionClass(AltTextWriteStatus::class);
        $reason_values = array();
        foreach ($reflection->getConstants() as $name => $value) {
            if (!is_string($value)) {
                continue;
            }
            if (!str_starts_with((string) $name, 'REASON_')) {
                continue;
            }
            $reason_values[$name] = $value;
        }

        $this->assertNotEmpty(
            $reason_values,
            'At least one REASON_* const must be declared'
        );

        foreach ($reason_values as $name => $value) {
            $this->assertContains(
                $value,
                AltTextWriteStatus::PARTIAL_REASONS,
                "Reason const {$name}={$value} must be a member of PARTIAL_REASONS"
            );
        }

        $this->assertSame(
            count($reason_values),
            count(AltTextWriteStatus::PARTIAL_REASONS),
            'PARTIAL_REASONS must not contain entries beyond declared REASON_* consts'
        );

        foreach (AltTextWriteStatus::PARTIAL_REASONS as $reason) {
            $this->assertContains(
                $reason,
                array_values($reason_values),
                "PARTIAL_REASONS entry {$reason} must match a declared REASON_* const"
            );
        }
    }

    // ── BR-05: CLI generate tally honesty ──

    /**
     * BR-05: every row failed → WP_CLI::error (non-zero), never success.
     * Exit code changes deliberately so a scripted caller can detect total
     * failure (stub throws RuntimeException from WP_CLI::error).
     */
    public function testGenerateTableFormatTotalFailureEmitsErrorNotSuccess(): void
    {
        $service = new StatusVocabRecordingDescribeService([
            40 => new WP_REST_Response(['detail' => 'upstream down'], 502),
        ]);
        $command = new DescriptionCommand(null, $service);

        $caught = null;
        try {
            $command->__invoke(['generate'], ['media-id' => '40', 'write' => true]);
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
        // Per-row log remains honest.
        $this->assertStringContainsString('status=failed', \WP_CLI::$messages['log'][0] ?? '');
    }

    /**
     * BR-05: every row partial → also total failure (error, not success).
     */
    public function testGenerateTableFormatAllPartialEmitsError(): void
    {
        $service = new StatusVocabRecordingDescribeService([
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
            $command->__invoke(['generate'], ['media-id' => '902', 'write' => true]);
        } catch (RuntimeException $e) {
            $caught = $e;
        }

        $this->assertInstanceOf(RuntimeException::class, $caught);
        $this->assertNotEmpty(\WP_CLI::$messages['error']);
        $this->assertEmpty(\WP_CLI::$messages['success']);
        $summary = \WP_CLI::$messages['error'][0];
        $this->assertStringContainsString('failed=0', $summary);
        $this->assertStringContainsString('partial=1', $summary);
    }

    /**
     * BR-05: all clean rows → success with counts (including failed=0 partial=0).
     */
    public function testGenerateTableFormatAllSuccessEmitsSuccessWithCounts(): void
    {
        $service = new StatusVocabRecordingDescribeService([
            401 => new WP_REST_Response([
                'media_id' => 401,
                'alt_text_draft' => 'ok draft',
                'adapter' => 'seeded',
                'model_id' => 'local-v1',
            ]),
        ]);
        $command = new DescriptionCommand(null, $service);

        $command->__invoke(['generate'], ['media-id' => '401', 'write' => true]);

        $this->assertNotEmpty(\WP_CLI::$messages['success']);
        $this->assertEmpty(\WP_CLI::$messages['error']);
        $this->assertEmpty(\WP_CLI::$messages['warning']);
        $summary = \WP_CLI::$messages['success'][0];
        $this->assertStringContainsString('count=1', $summary);
        $this->assertStringContainsString('failed=0', $summary);
        $this->assertStringContainsString('partial=0', $summary);
    }

    /**
     * R17-BR-02: a mixed batch (one written, one failed) exits non-zero via
     * error, not warning. Supersedes the BR-05 exit-0 mixed policy this test
     * previously encoded: WP_CLI::error fires only after every row has been
     * processed and logged, so a non-zero exit aborts nothing mid-pipeline,
     * and `generate` must not report a different exit contract than `refresh`
     * for the same degree of damage. The summary still carries per-status
     * counts so a caller can discriminate mixed from total failure [R17-BR-09].
     */
    public function testGenerateTableFormatMixedExitsNonZeroWithCounts(): void
    {
        $candidates = new StatusVocabFixedCandidateService([501, 502]);
        $describe   = new StatusVocabRecordingDescribeService([
            501 => new WP_REST_Response([
                'media_id' => 501,
                'alt_text_draft' => 'ok',
                'adapter' => 'seeded',
                'model_id' => 'local-v1',
            ]),
            502 => new WP_REST_Response(['detail' => 'boom'], 502),
        ]);
        $command = new DescriptionCommand($candidates, $describe);

        $thrown = null;
        try {
            $command->__invoke(['generate'], ['limit' => '2', 'write' => true]);
        } catch (RuntimeException $e) {
            $thrown = $e;
        }

        $this->assertInstanceOf(
            RuntimeException::class,
            $thrown,
            'mixed batch must exit non-zero (WP_CLI::error throws in the stub)'
        );
        $this->assertEmpty(\WP_CLI::$messages['success']);
        $this->assertEmpty(\WP_CLI::$messages['warning']);
        $this->assertNotEmpty(\WP_CLI::$messages['error']);
        $summary = \WP_CLI::$messages['error'][0];
        $this->assertStringContainsString('count=2', $summary);
        $this->assertStringContainsString('failed=1', $summary);
        $this->assertStringContainsString('partial=0', $summary);
        $this->assertStringContainsString('written=1', $summary);
    }

    // ── helpers ──

    /**
     * @return array<string,mixed>
     */
    private function validBackendBody(int $media_id): array
    {
        return array(
            'tenant_id'              => self::currentTenantId(),
            'media_id'               => $media_id,
            'image_hash'             => str_repeat('a', 64),
            'context_hash'           => str_repeat('b', 64),
            'adapter'                => 'seeded',
            'model_id'               => 'seeded-fixtures',
            'model_version'          => '1',
            'prompt_or_task_version' => '1',
            'visual_facts'           => array('caption' => 'A photo.', 'objects' => array(), 'ocr_text' => null),
            'alt_text_draft'         => 'A photo.',
            'context_used'           => array('sources' => array(), 'applied' => false),
            'provider_disclosure'    => array('provider' => 'none', 'left_service_boundary' => false),
            'cached'                 => false,
            'duration_ms'            => 3,
            'retention_class'        => 'retain_all',
            'tier'                   => 'provisional_cpu',
            'result_generation'      => 0,
        );
    }

    /**
     * @return array<string,mixed>
     */
    private function validBackendBodyWithLong(int $media_id, string $long = 'A long description body.'): array
    {
        $body = $this->validBackendBody($media_id);
        $body['alt_text_long'] = $long;
        return $body;
    }

    private function plantWritableAttachment(int $id): void
    {
        $path = $this->tempDir . "/{$id}.jpg";
        file_put_contents($path, "\xff\xd8\xff\xe0bytes");
        $GLOBALS['__ac_attached_file'][$id] = $path;
        $GLOBALS['__ac_posts'][$id] = (object) array(
            'post_title'   => "Photo {$id}",
            'post_excerpt' => 'A caption.',
            'post_content' => '',
        );
    }

    private function writeRequest(int $media_id, bool $force = false): WP_REST_Request
    {
        $req = new WP_REST_Request('POST', '/acx/v1/recognition/describe');
        $req->set_param('media_id', $media_id);
        $req->set_param('write_alt', true);
        if ($force) {
            $req->set_param('force', true);
        }
        return $req;
    }
}

/**
 * Test double: describe_media returns a canned response per media_id.
 */
class StatusVocabRecordingDescribeService extends DescribeMediaService
{
    /** @param array<int,WP_REST_Response> $responses */
    public function __construct(private array $responses)
    {
    }

    public function describe_media(WP_REST_Request $request): WP_REST_Response|\WP_Error
    {
        $mediaId = (int) $request->get_param('media_id');

        return $this->responses[$mediaId] ?? new WP_REST_Response(
            ['media_id' => $mediaId, 'alt_text_draft' => 'Generated alt text.']
        );
    }
}

/**
 * Candidate service that returns a fixed media_id list so multi-row CLI
 * generate can exercise the real tally path without planting get_posts.
 */
class StatusVocabFixedCandidateService extends DescriptionCandidateService
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
