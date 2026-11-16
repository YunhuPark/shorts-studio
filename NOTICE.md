# Notices

The source code of this repository is released under the [MIT License](LICENSE). The items below are **not** covered
by it; each keeps its own terms. Versions and licenses were read from the installed packages on 2026-11-12.

## Files shipped in this repository

| What | Where | License |
|---|---|---|
| Pretendard Bold (subtitle font) | `assets/fonts/` | SIL Open Font License 1.1 (`assets/fonts/Pretendard-LICENSE.txt`) |
| YuNet face detector (license text only) | `assets/models/YuNet-LICENSE.txt` | MIT |
| SFace face recogniser (license text only) | `assets/models/SFace-LICENSE.txt` | Apache-2.0 |

The two face-model files themselves are **not** stored in git. `python -m shorts_studio fetch-models` downloads them and
checks their sha256; they are used locally and are not redistributed here.

## Generated media is not licensed for reuse

`demo/`, `docs/media/` and `frontend/public/landing/` contain images generated with Google Gemini, speech synthesized with Azure Speech and videos
and screenshots made from them. They are shown to demonstrate the project, are **not** covered by the MIT License, and
remain subject to the terms of the providers that produced them. The story "새벽 3시, 컵라면 두 개" and these media are
not offered for reuse. Videos produced with the "AI 생성" label option carry the label and an AI-generation note in the
file metadata.

## Software the project depends on (installed from package registries, not copied into this repository)

| Package | License |
|---|---|
| fastapi 0.162.0, starlette 1.10.0, pydantic 2.14.2, PyJWT 2.15.1, ruff 0.17.3 | MIT |
| uvicorn 0.54.0, httpx 0.28.1 | BSD-3-Clause |
| numpy 2.5.4 | BSD-3-Clause and others (0BSD, MIT, Zlib, CC0-1.0) |
| pillow 13.0.0 | MIT-CMU |
| imageio-ffmpeg 0.7.0 | BSD-2-Clause |
| opencv-python-headless 5.0.0.93 | Apache-2.0 |
| cryptography 50.0.2 | Apache-2.0 OR BSD-3-Clause |
| next 16.4.3, react 19.3.0, react-dom 19.3.0 | MIT |
| three 0.187.0, @types/three 0.187.0 | MIT |
| gsap 3.15.1, @gsap/react 2.1.2 | GreenSock Standard "no charge" license (https://gsap.com/standard-license): free to use, **not** an open-source license |
| @fontsource/black-han-sans 5.3.0 (Black Han Sans), pretendard 1.3.9 (Pretendard) | SIL Open Font License 1.1; the font files are bundled into the web build |
| @playwright/test 1.64.1, typescript 5.9.3 | Apache-2.0 |

Things to know if you redistribute binaries or images built from this project:

- `imageio-ffmpeg` downloads an ffmpeg build that is **GPL** (it enables x264/x265). The project only runs it; it is neither
  vendored nor shipped. The demo container does not include ffmpeg at all.
- The `opencv-python-headless` wheel bundles FFmpeg (LGPL 2.1), Intel IPP and other libraries; see the
  `LICENSE-3RD-PARTY.txt` inside the wheel. The demo container does not include OpenCV.
- Model weights chosen for other features were checked before use: two candidates (MusicGen, OmniVoice) were rejected
  because their weights are CC-BY-NC even though their code is MIT/Apache; see `docs/open-source-decisions.md`.

## Third-party services

Images (Google Gemini API), speech (Azure AI Speech) and, optionally, login tokens (Supabase) are used through their own
APIs under their own terms. No API key is stored in this repository.
