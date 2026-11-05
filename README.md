# shorts-studio

Storyboard → images → voices → rendered 9:16 short. Phase 0 of the service MVP in
[docs/mvp-design.md](docs/mvp-design.md): the prototype refactored into a provider-based library and CLI.

## Layout
```
src/shorts_studio/
  models.py            Storyboard / Shot / VoiceSpec (JSON schema of examples/*/storyboard.json)
  providers/           ImageProvider, VoiceProvider interfaces + Azure voice, Gemini image, directory source
  render/              camera, subtitles, bgm (procedural score), mix, renderer
  qa.py                deterministic storyboard checks
  cli.py               render | lint | voice-samples | image-consistency
examples/convenience-store/storyboard.json
docs/                  MVP design, open-source decisions
scripts/               measure_shake.py (jitter metric), compare_renders.py (regression check)
tests/                 unittest, no extra dependencies
```

## Setup
Python 3.11+, `pip install pillow numpy imageio-ffmpeg` (ffmpeg comes bundled with imageio-ffmpeg).
Run from the repo root with `PYTHONPATH=src`, or `pip install -e .`.

Environment variables (never commit keys):
- `AZURE_SPEECH_KEY`, `AZURE_SPEECH_REGION` — voices
- `GEMINI_API_KEY` — image-consistency harness (paid: image generation has no free tier)
- `SHORTS_FONT` — optional subtitle font path

## Use
```bash
python -m shorts_studio lint examples/convenience-store/storyboard.json --images <folder with cutNN.png>
python -m shorts_studio render examples/convenience-store/storyboard.json --images <folder> --out output/short.mp4
python -m shorts_studio render ... --only 5,14,16          # preview a few shots
python -m shorts_studio voice-samples --out output/voice_samples
python -m shorts_studio bgm-sample --seconds 30 --out output/bgm/bgm.wav   # audition the 3 score styles
python -m shorts_studio render ... --bgm-style warm_major                    # night_piano (default) / warm_major / tense_low
python -m shorts_studio image-consistency examples/convenience-store/storyboard.json \
    --character grandpa --shots 5,16,21 --model <gemini-image-model-id> [--dry-run]
python -m shorts_studio generate examples/convenience-store/storyboard.json --images <folder> \
    --model <gemini-image-model-id> --char-ref grandpa=<folder>/cut05.png --char-ref alba=<folder>/cut13.png \
    [--shot-ref 24=<folder>/cut26.png] [--shots 22,23] [--replace 1] [--dry-run]   # make missing shots with reference images
python -m unittest discover -s tests
```
`generate` writes `cutNN.png` plus `cutNN.meta.json` (model, prompt, references) and keeps a replaced image as `cutNN_prev.png`.
Shots without an image are skipped, so the renderer works on a partial set.

## Local dashboard (FastAPI + Next.js)
A single-user web UI over the same library: edit the storyboard (dialogue, camera, highlight words, live subtitle
preview), audition and pick voices, regenerate one shot's image (with a cost confirmation), render, and play/download.
```bash
python -m venv .venv && .venv/Scripts/python -m pip install -e ".[api,dev]"      # backend deps
cd frontend && npm install && cd ..                                              # frontend deps

# once per project: copy a storyboard + images into the dashboard data folder (.data/, git-ignored)
python -m shorts_studio import-project convenience-store examples/convenience-store/storyboard.json \
    --images <folder with cutNN.png> --char-ref grandpa=cut05.png --char-ref alba=cut13.png

python -m shorts_studio serve --data .data --port 8765          # API, localhost only
npm --prefix frontend run dev -- -p 3010                        # UI -> http://localhost:3010
```
- Keys come from the environment of the **API process** (`AZURE_SPEECH_KEY/REGION`, `GEMINI_API_KEY`) and are never
  sent to the browser; the UI only shows whether they are set.
- Paid actions (image regeneration) need an explicit confirmation and stop at an estimated daily cap
  (`SHORTS_DAILY_CAP_USD`, default 2.00; unit price estimate `SHORTS_IMAGE_PRICE_USD`, default 0.067). The ledger is
  `.data/spend.jsonl` and holds estimates, not invoices.
- Port 8000 is reserved by Windows on some machines (that is why the default is 8765). The frontend proxies `/api/*` to
  `API_ORIGIN` (default `http://127.0.0.1:8765`).
- Jobs (image regeneration, render) are rows in `<data>/jobs.sqlite3`, so they survive restarts. By default two worker
  threads run inside the API process. To run them elsewhere: `serve --no-worker` plus one or more
  `python -m shorts_studio worker --data .data` in other terminals (same folder). A job whose worker died (no heartbeat
  for 60 s) is marked failed and, for an image job, its reserved spend is refunded.
- Edits are written to `storyboard.json` atomically and the previous version is kept as `storyboard.json.bak`.
- Tests: `.venv/Scripts/python -m unittest discover -s tests`; frontend: `cd frontend && npx tsc --noEmit && npx next build`.

## Quality tooling
```bash
.venv/Scripts/python -m pip install -e ".[api,vision,dev]"      # + opencv-python-headless, ruff
.venv/Scripts/ruff check .                                       # lint (config in pyproject.toml)
.venv/Scripts/python -m unittest discover -s tests               # 110 tests

python -m shorts_studio fetch-models                             # YuNet + SFace (~37 MB, sha256-checked, not in git)
python -m shorts_studio face-check examples/convenience-store/storyboard.json --images <folder>     --reference grandpa=<folder>/cut05.png --reference alba=<folder>/cut13.png

cd frontend && npx playwright install chromium && npm run test:e2e   # 13 browser tests, fake providers, no real keys
```
`face-check` assigns every face in a shot to the closest reference character and flags faces that match nobody
(`drift?`) or are too small to judge (`small`). It is reliable for frontal faces; profiles, overhead and back views
often score low, so use it to pick shots for a human to look at, not to reject them automatically.
The E2E tests run against a private API (`tests/e2e_server.py`) and a separate build folder (`.next-e2e`), so they never
touch your data, real keys, or a dev server you have open.

## Fonts
Subtitles need a Korean bold font. Resolution order: `--font`, `SHORTS_FONT`, `assets/fonts/Pretendard*Bold*` or
`NotoSansKR*Bold*`, then Windows Malgun Gothic (development fallback only — not redistributable in a hosted service).
Both Pretendard and Noto Sans KR are SIL OFL fonts.

## Status
See [docs/mvp-design.md](docs/mvp-design.md) section 11.
- Done: provider-based library + CLI, output identical to the prototype (pixel diff 0.0000 on sampled frames),
  bundled open font (Pretendard Bold, SIL OFL 1.1; licence text in `assets/fonts/Pretendard-LICENSE.txt`).
- Done: real-API reference-image consistency test (see "Phase 0 results" in docs/mvp-design.md).
- Next: multi-character shots, an objective face-similarity check, and Phase 1 (API + worker).
