<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Api\BlobUrlRewriter;
use AltContext\Tests\TestCase;

/**
 * @covers \AltContext\Api\BlobUrlRewriter
 */
class BlobUrlRewriterTest extends TestCase
{
    public function testRewritesRecognitionBlobPathToRestUrl(): void
    {
        $rewritten = BlobUrlRewriter::rewrite_string('/recognition/blobs/job-x/42');

        $this->assertSame('http://example.test/wp-json/acx/v1/recognition/blobs/job-x/42', $rewritten);
    }

    public function testPassesThroughHttpUrlUnchanged(): void
    {
        $url = 'https://example.com/wp-content/uploads/foo.jpg';
        $this->assertSame($url, BlobUrlRewriter::rewrite_string($url));
    }

    public function testPassesThroughEmptyString(): void
    {
        $this->assertSame('', BlobUrlRewriter::rewrite_string(''));
    }

    public function testRecursivelyRewritesNestedSuggestionStructure(): void
    {
        $payload = [
            'suggestions' => [
                [
                    'id' => 's1',
                    'identity_media_url' => '/recognition/blobs/job-a/9',
                    'representative_media_url' => '/recognition/blobs/job-a/12',
                    'unrelated' => 'https://example.com/img.jpg',
                ],
                [
                    'id' => 's2',
                    'cluster_a_representative_media_url' => '/recognition/blobs/job-b/77',
                    'cluster_b_representative_media_url' => null,
                ],
            ],
            'total' => 2,
        ];

        $rewritten = BlobUrlRewriter::rewrite($payload);

        $this->assertSame('http://example.test/wp-json/acx/v1/recognition/blobs/job-a/9', $rewritten['suggestions'][0]['identity_media_url']);
        $this->assertSame('http://example.test/wp-json/acx/v1/recognition/blobs/job-a/12', $rewritten['suggestions'][0]['representative_media_url']);
        $this->assertSame('https://example.com/img.jpg', $rewritten['suggestions'][0]['unrelated']);
        $this->assertSame('http://example.test/wp-json/acx/v1/recognition/blobs/job-b/77', $rewritten['suggestions'][1]['cluster_a_representative_media_url']);
        $this->assertNull($rewritten['suggestions'][1]['cluster_b_representative_media_url']);
        $this->assertSame(2, $rewritten['total']);
    }

    public function testPreservesNonStringScalars(): void
    {
        $this->assertNull(BlobUrlRewriter::rewrite(null));
        $this->assertSame(42, BlobUrlRewriter::rewrite(42));
        $this->assertTrue(BlobUrlRewriter::rewrite(true));
    }

    public function testDoesNotRewritePathsWithSimilarButDifferentPrefix(): void
    {
        $value = '/recognition/blobsfoo/job/1';
        $this->assertSame($value, BlobUrlRewriter::rewrite_string($value));
    }
}
