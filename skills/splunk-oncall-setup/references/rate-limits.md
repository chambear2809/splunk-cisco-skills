# Public API Rate Limits

Verified by reading the Splunk On-Call public API spec at
`https://portal.victorops.com/public/api-docs.html`. The spec opens with
"your account may be limited to a total number of API calls per month",
which is enforced by Splunk On-Call regardless of the per-endpoint values
below.

## Per-endpoint limits

| Endpoint group | Limit |
|----------------|-------|
| **Default** for nearly every endpoint | 2 calls / second |
| `POST /api-public/v1/user/batch` | 1 call / second |
| `GET /api-public/v1/profile/{username}/policies` (V1 read) | 1 call / second |
| `GET /api-reporting/v2/incidents` | **1 call / minute** |

Every endpoint returns HTTP `429` with a `Retry-After` header (seconds) when
the limit is hit.

## How the skill enforces limits

`oncall_api.py` implements a per-endpoint token-bucket governor that is
authoritative regardless of plan order. The buckets are seeded at the
documented rates above and the API client sleeps when the bucket is empty
before issuing the next call. The renderer pre-batches actions to keep the
expected wall-clock duration of a full apply within reason and surfaces a
**daily-budget estimate** in `coverage-report.json`:

```json
{
  "rate_limits": {
    "default_per_sec": 2.0,
    "user_batch_per_sec": 1.0,
    "personal_paging_v1_read_per_sec": 1.0,
    "reporting_v2_incidents_per_min": 1.0,
    "monthly_quota_warning": "Splunk On-Call may impose a per-account monthly call quota. Confirm in the org's portal."
  },
  "daily_budget": {
    "estimated_apply_calls": 47,
    "estimated_validate_calls": 3,
    "rough_minutes_to_complete": 1
  }
}
```

The retry policy is **jittered exponential backoff with `Retry-After`
override** for `429`/`502`/`503`/`504`, capped at 30 seconds per attempt and
4 attempts per call.

## Headers on every response

| Header | Notes |
|--------|-------|
| `X-VO-Request-Id` | Forwarded into `apply-plan.json` responses for support ticket correlation. |
| `Retry-After` | Honored on `429`/`5xx`. |

## Failure modes

- 400 — invalid request body. The validator catches most bad shapes before
  the API client is ever called.
- 401 — bad API ID/key, or rate-limit reached on the auth endpoint.
- 403 — disabled account.
- 404 — wrong path (the validator refuses unresolved `{placeholders}`).
- 429 — rate limit reached. Retried with the documented backoff.
- 500 — server error. Retried with exponential backoff.
