.PHONY: help check lint typecheck arch test test-watch check-php php-cs php-test phpstan

help:
	@echo "Available commands:"
	@echo "  make check      - Run frontend lint, typecheck, architecture checks, and tests"
	@echo "  make lint       - Run ESLint"
	@echo "  make typecheck  - Run TypeScript checks"
	@echo "  make arch       - Run frontend architecture compliance checks"
	@echo "  make test       - Run frontend tests (vitest run)"
	@echo "  make test-watch - Run frontend tests in watch mode"
	@echo "  make check-php  - Run plugin PHP checks (cs, phpunit, phpstan)"

check:
	@npm run check

lint:
	@npm run lint

typecheck:
	@npm run typecheck

arch:
	@npm run arch

test:
	@npm run test -- --run

test-watch:
	@npm run test:watch

check-php: php-cs php-test phpstan
	@echo "✓ PHP checks passed"

php-cs:
	@composer cs-check

php-test:
	@composer test

phpstan:
	@if [ ! -x vendor/bin/phpstan ]; then \
		echo "phpstan is not installed in vendor/bin."; \
		echo "Run 'composer update phpstan/phpstan' when Packagist access is available."; \
		exit 1; \
	fi
	@composer phpstan
