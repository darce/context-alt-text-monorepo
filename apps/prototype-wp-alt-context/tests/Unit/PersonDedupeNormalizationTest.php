<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Api\Services\PersonResolutionService;
use AltContext\Tests\TestCase;

/**
 * Property pins for trim + Unicode case-fold normalization (no diacritic folding).
 *
 * @covers \AltContext\Api\Services\PersonResolutionService
 */
class PersonDedupeNormalizationTest extends TestCase
{
	public function testTrimsWhitespaceBeforeCaseFold(): void
	{
		$this->assertSame('ada', PersonResolutionService::normalize_name("  Ada  \t"));
	}

	public function testUnicodeCaseFoldMapsAsciiCaseVariants(): void
	{
		$this->assertSame(
			PersonResolutionService::normalize_name('Ada'),
			PersonResolutionService::normalize_name('ada')
		);
		$this->assertSame(
			PersonResolutionService::normalize_name('ADA LOVELACE'),
			PersonResolutionService::normalize_name('ada lovelace')
		);
	}

	public function testDoesNotFoldDiacritics(): void
	{
		// Product policy (E21-9 Q3): "José" ≠ "Jose".
		$jose = PersonResolutionService::normalize_name('José');
		$joseAscii = PersonResolutionService::normalize_name('Jose');

		$this->assertNotSame($jose, $joseAscii);
		$this->assertSame('josé', $jose);
		$this->assertSame('jose', $joseAscii);
	}

	public function testEmptyAfterTrimIsEmptyString(): void
	{
		$this->assertSame('', PersonResolutionService::normalize_name('   '));
		$this->assertSame('', PersonResolutionService::normalize_name(''));
	}
}
