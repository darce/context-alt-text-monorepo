<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

require_once __DIR__ . '/../../src/api/class-context-category-policy.php';

use AltContext\Api\ContextCategoryPolicy;
use AltContext\Tests\TestCase;

/**
 * @covers \AltContext\Api\ContextCategoryPolicy
 */
class ContextCategoryPolicyTest extends TestCase {
	public function testIsValidListAcceptsKnownUniqueAndEmptyLists(): void {
		$this->assertTrue( ContextCategoryPolicy::is_valid_list( array() ) );
		$this->assertTrue(
			ContextCategoryPolicy::is_valid_list(
				array( ContextCategoryPolicy::POST, ContextCategoryPolicy::PRODUCT )
			)
		);
	}

	public function testIsValidListRejectsUnknownName(): void {
		$this->assertFalse( ContextCategoryPolicy::is_valid_list( array( 'attachment', 'unknown' ) ) );
	}

	public function testIsValidListRejectsDuplicateName(): void {
		$this->assertFalse( ContextCategoryPolicy::is_valid_list( array( 'post', 'post' ) ) );
	}

	public function testIsValidListRejectsNonListArray(): void {
		$this->assertFalse( ContextCategoryPolicy::is_valid_list( array( 'primary' => 'attachment' ) ) );
	}

	public function testIsValidListRejectsNonArray(): void {
		$this->assertFalse( ContextCategoryPolicy::is_valid_list( 'attachment' ) );
	}

	public function testCanonicalReturnsNamesInDefinedOrder(): void {
		$this->assertSame(
			array( 'attachment', 'taxonomy_terms', 'product' ),
			ContextCategoryPolicy::canonical( array( 'product', 'taxonomy_terms', 'attachment' ) )
		);
	}

	public function testResolveReturnsNullPairWhenOptionIsAbsent(): void {
		$this->assertSame(
			array(
				'categories' => null,
				'error'      => null,
			),
			ContextCategoryPolicy::resolve()
		);
	}

	public function testResolveReturnsCanonicalValidSubset(): void {
		$this->setOption(
			ContextCategoryPolicy::OPTION_NAME,
			array( 'product', 'attachment' )
		);

		$this->assertSame(
			array(
				'categories' => array( 'attachment', 'product' ),
				'error'      => null,
			),
			ContextCategoryPolicy::resolve()
		);
	}

	public function testResolveFailsClosedForMalformedStoredValue(): void {
		$this->setOption( ContextCategoryPolicy::OPTION_NAME, 'product' );

		$result = ContextCategoryPolicy::resolve();

		$this->assertSame( array( 'attachment' ), $result['categories'] );
		$this->assertStringContainsString( 'invalid', $result['error'] );
		$this->assertStringContainsString( 'only attachment details are sent', $result['error'] );
	}
}
