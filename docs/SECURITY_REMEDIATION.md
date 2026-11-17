# Thumbnail and speech boundaries

Thumbnail cache version `thumbs-v2` uses the authenticated owner and SHA-256 of the exact image bytes being rendered. Matching project names and timestamps across users no longer share a thumbnail. Stop the service and remove only the obsolete `<SHORTS_DATA>/cache/thumbs` directory after verifying the data root; it is no longer read. Never remove the project or user directories as part of cache cleanup.

GET `/api/voices/sample` serves prebuilt demo/static audio only. A missing sample returns 404 without creating a paid provider. The dashboard then asks for confirmation and sends POST `/api/voices/sample` with `confirm: true`; clients must handle 429 (budget exhausted) and 503 (invalid provider/budget configuration). Public demo mode always replays static audio/render jobs and never calls Azure or Gemini.

Both confirmed voice samples and every queued render synthesis use `BudgetedVoiceProvider`. Set the same environment configuration on the API and each standalone worker:

| Variable | Meaning |
| --- | --- |
| `SHORTS_DATA` | Shared local data directory containing the same `ledger.sqlite3` and owner cache directories |
| `SHORTS_DAILY_CAP_USD` | Per-user daily estimated image + TTS spend, default 2; 0 disables paid work |
| `SHORTS_MONTHLY_CAP_USD` | All-user monthly estimated spend; 0 means no monthly cap |
| `SHORTS_TTS_GLOBAL_DAILY_CAP_USD` | Positive all-user daily cap checked before each TTS attempt, default 10 |
| `SHORTS_TTS_USD_PER_CHARACTER` | Positive conservative estimate per character, default 0.00005; update for your Azure voice tier |

Daily/monthly accounting uses the server's local calendar. Keep timezone settings consistent between processes. SQLite `BEGIN IMMEDIATE` serializes reservations across API threads and worker processes, so deployments need the same persistent local filesystem/ledger; do not run replicas against independent data directories or unsuitable network filesystems. Provider credentials stay in the server environment.

Speech text must be 1–3,000 characters (sample API further limits to 120). Invalid/nonfinite caps or character prices fail closed. Speech cache keys include voice/provider/rate/pitch/text under the owner's directory. A completed cached voice costs nothing; new attempts are reserved before constructing a provider and remain charged after provider failures or worker crashes, since billing is uncertain. Audio is published atomically from isolated scratch directories. Azure transport uses a 30-second socket timeout and reads at most 8 MiB plus one overflow-detection byte; oversized audio is rejected before cache publication. These are conservative application estimates, not invoice guarantees; retain provider-side quotas and billing alerts.

Regression checks: `python -m pytest -q` (API, demo/auth, exact-owner image content, sample/render budgets, independent process concurrency); frontend: `npm run build` from `frontend`. All provider calls in tests use synthetic fakes.
