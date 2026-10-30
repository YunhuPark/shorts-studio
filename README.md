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
python -m shorts_studio image-consistency examples/convenience-store/storyboard.json \
    --character grandpa --shots 5,16,21 --model <gemini-image-model-id> [--dry-run]
python -m unittest discover -s tests
```
Shots without an image are skipped, so the renderer works on a partial set.

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
