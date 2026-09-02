# 0008. Serve images direct, fall back to a backend proxy

Status: Accepted
Date: 2026-09-03

Supersedes the "do not build an image proxy" rule in `docs/aic-api.md` and `CLAUDE.md`.

## Context

The original guidance was explicit: load IIIF images directly in the browser, never proxy them,
because AIC serves images with `Access-Control-Allow-Origin: *` and permits hotlinking. A proxy
would add a failure mode and bandwidth cost for nothing.

That guidance no longer holds. `www.artic.edu`, which serves the IIIF images, is behind
Cloudflare Bot Management. Measured 2026-09-03, deterministic over three trials per case:

| Request headers | Result |
|---|---|
| none | `403`, `cf-mitigated: challenge` |
| `AIC-User-Agent` only | `403`, `cf-mitigated: challenge` |
| browser `User-Agent` only | `403`, `cf-mitigated: challenge` |
| browser `User-Agent` **+** `AIC-User-Agent` | `200`, `image/jpeg`, `ACAO: *` |

Getting a `200` requires a custom request header. A browser cannot set a header on an `<img>`
request, and an `<img>` subresource cannot execute Cloudflare's JavaScript challenge. The two
facts together make hotlinking impossible from page markup.

Confirmed in a real browser. Three `<img>` + `decode()` calls in one execution, from a page on
`localhost`, after the browser had already solved the challenge by top-level navigation and held
a `cf_clearance` cookie for `www.artic.edu`:

```
PROXIED  same-origin /api/image: OK 843x565 (211ms)
DIRECT   artic.edu IIIF:         FAIL EncodingError (126ms)
CONTROL  placehold.co:           OK 300x200 (266ms)
```

The control matters: unrelated cross-origin images load and render normally, so this is not CORS,
not mixed content, and not a local browser policy. The clearance cookie does not carry to a
cross-site subresource request.

Two caveats keep this from being a settled fact about AIC. Cloudflare scores partly on IP
reputation, so this is one network on one day and may not reproduce everywhere. And AIC almost
certainly does not intend it: the `AIC-User-Agent` bypass rule exists so that API clients keep
working, and image hotlinking looks like collateral damage. It may be fixed without notice.

## Decision

The frontend tries the direct AIC IIIF URL first. On `decode()` rejection or image error it
retries once through a backend endpoint, `GET /api/image/{image_id}?w={width}`, which fetches
from AIC with both required headers and streams the bytes back.

The outcome is remembered for the session. Once a direct load has failed, subsequent artworks go
straight to the proxy rather than paying the failed round trip every rotation.

The proxy validates `image_id` against the expected UUID shape and `w` against the cached IIIF
ladder (`200`, `400`, `600`, `843`, `1686`). It is not a general-purpose URL fetcher.

## Alternatives considered

**Proxy unconditionally.** Simpler, one code path, no probing. Rejected because it makes every
user pay bandwidth through the app for a restriction that may be local to some networks and may
disappear, and it discards AIC's edge caching, which is the reason `843` is the recommended width
in the first place.

**Hotlink only, and let blocked images skip to the next artwork.** This is what the current spec
implies. Rejected because when the block is in force *every* image fails, so "skip to the next
artwork" skips forever and the app shows nothing. A failure mode that degrades to a blank screen
is not a failure mode, it is the product not working.

**Solve the challenge server-side and pass a cookie to the browser.** Fragile, adversarial, and
squarely against the spirit of AIC's terms. Not considered seriously.

**Download and cache images locally at index time.** Turns a display app into a mirror of the
collection, with the storage and rights questions that implies. ADR-0007 exists partly to avoid
that class of problem.

## Consequences

A picture reliably appears, which is the entire point of M0.

The cost is a second code path in `display.js` — the one file the spec already calls the
genuinely tricky one — plus an endpoint that must not become an open proxy, hence the
allow-listed widths and the id format check.

Where hotlinking works, behaviour is unchanged and AIC's edge cache is still used. Where it does
not, the app degrades to slower first paint rather than to a blank screen.

This should be re-tested periodically. If AIC widens the bypass, the fallback becomes dead code
and can be deleted; the probe already tells us which world we are in. `tests/` carries a `live`
test asserting the direct URL's behaviour so the change is noticed rather than assumed.
