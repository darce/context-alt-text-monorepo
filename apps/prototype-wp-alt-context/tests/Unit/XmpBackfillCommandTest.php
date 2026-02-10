<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Cli\XmpBackfillCommand;
use AltContext\Media\AttachmentXmpMetricsPersistor;
use AltContext\Media\ImageXmpWriter;
use AltContext\Tests\TestCase;
use RuntimeException;

/**
 * @covers \AltContext\Cli\XmpBackfillCommand
 */
class XmpBackfillCommandTest extends TestCase
{
    protected function setUp(): void
    {
        parent::setUp();
        \WP_CLI::reset_cli_messages();
    }

    public function testInvokeEmbedsForProvidedAttachmentIds(): void
    {
        $writer = new class() extends ImageXmpWriter {
            public array $writtenIds = [];

            public function __construct() {}

            public function write_for_attachment(int $attachment_id, string $original_path): string
            {
                $this->writtenIds[] = $attachment_id;
                return self::STATUS_WRITTEN;
            }
        };

        $persistor = new AttachmentXmpMetricsPersistor($writer);
        $command = new XmpBackfillCommand($persistor);

        $GLOBALS['__ac_attached_file'][101] = '/tmp/image-101.jpg';
        $GLOBALS['__ac_attached_file'][202] = '/tmp/image-202.jpg';

        $command->__invoke(['101', '202'], []);

        $this->assertSame([101, 202], $writer->writtenIds);
        $this->assertNotEmpty(\WP_CLI::$messages['success']);
        $this->assertStringContainsString('processed=2', \WP_CLI::$messages['success'][0]);
    }

    public function testInvokeErrorsWhenNoAttachmentIdsProvided(): void
    {
        $writer = new class() extends ImageXmpWriter {
            public function __construct() {}

            public function write_for_attachment(int $attachment_id, string $original_path): string
            {
                return self::STATUS_WRITTEN;
            }
        };

        $persistor = new AttachmentXmpMetricsPersistor($writer);
        $command = new XmpBackfillCommand($persistor);

        $this->expectException(RuntimeException::class);
        $this->expectExceptionMessage('No media IDs provided. Pass IDs directly or use --all.');

        $command->__invoke([], []);
    }

    public function testInvokeAllHonorsLimitFlag(): void
    {
        $writer = new class() extends ImageXmpWriter {
            public array $writtenIds = [];

            public function __construct() {}

            public function write_for_attachment(int $attachment_id, string $original_path): string
            {
                $this->writtenIds[] = $attachment_id;
                return self::STATUS_WRITTEN;
            }
        };

        $persistor = new AttachmentXmpMetricsPersistor($writer);
        $command = new XmpBackfillCommand($persistor);

        $GLOBALS['__ac_get_posts_results'] = [301, 302, 303];
        $GLOBALS['__ac_attached_file'][301] = '/tmp/image-301.jpg';
        $GLOBALS['__ac_attached_file'][302] = '/tmp/image-302.jpg';
        $GLOBALS['__ac_attached_file'][303] = '/tmp/image-303.jpg';

        $command->__invoke([], ['all' => true, 'limit' => 2]);

        $this->assertSame([301, 302], $writer->writtenIds);
        $this->assertNotEmpty(\WP_CLI::$messages['success']);
        $this->assertStringContainsString('processed=2', \WP_CLI::$messages['success'][0]);
    }
}
