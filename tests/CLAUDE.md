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
- Playwright covers nine smoke flows only. Push everything else down to unit tests. A tenth has
  to argue for itself the way the sixth through ninth did: it earns a slot only by covering a
  rule that exists nowhere but in the browser, or by crossing layers no smaller test can.
- Only one flow is allowed to be slow, and it already exists. Flow 9 waits out a real rotation
  interval because a clock that should not be ticking cannot be observed any faster. Do not add
  a second `wait_for_timeout` of that size without the same kind of argument.
