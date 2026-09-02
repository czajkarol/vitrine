# Testing rules

Loaded when working inside `tests/`. Strategy is in `docs/testing.md`.

- No test in the default suite touches the network or a paid API. `respx` intercepts httpx.
- Tests that hit real services are marked `@pytest.mark.live` and excluded from the default run
  and from CI. They exist to catch API drift and are run by hand.
- AIC fixtures are recorded real responses in `tests/fixtures/aic/`, not hand-written dicts.
  A hand-written fixture tests your idea of the API, which is exactly the thing that goes wrong.
- Test behaviour, not implementation. Asserting that a mock was called is rarely a real test.
- Every failure path in `docs/product-spec.md` has a test: image 404, malformed response,
  timeout, provider down, budget exhausted, corrupt cache.
- Scoring tests assert relative ordering, not exact float values, so weight tuning does not
  break the suite.
- Playwright covers five smoke flows only. Push everything else down to unit tests.
