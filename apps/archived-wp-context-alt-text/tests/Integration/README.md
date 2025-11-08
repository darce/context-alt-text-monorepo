# Integration Tests

## Status

⚠️ **Integration tests are currently outdated** and need to be updated to match the current recognition service API contract.

## Known Issues

The integration tests in `RecognitionServiceIntegrationTest.php` expect an older API contract:

- Expected: `health()` returns `['status' => 'ok']`
- Actual: Service returns `['status' => 'ready', 'message' => '...', 'initialization_status' => [...]]`

Similar mismatches exist for:

- Service info endpoint structure
- Scene analysis response format
- Embeddings endpoint response
- Roster listing response

## Running Integration Tests

To run integration tests (they will currently fail):

```bash
CAT_RUN_RECOGNITION_TESTS=1 composer test
```

## TODO

Update `RecognitionServiceIntegrationTest.php` to match the current recognition service API:

1. Update health check assertions
2. Update service info structure expectations
3. Update analyze scene response format
4. Update embeddings response format
5. Update roster listing response format
6. Fix `wp_delete_attachment()` undefined function error

## Current Test Status

- ✅ **408 unit/functional tests**: All passing
- ⚠️ **12 integration tests**: Currently failing due to API contract mismatch
