# Prototype (archived)

Scripts from the first working version, kept for reference. The maintained code is in `src/shorts_studio/`:

| prototype | now |
|---|---|
| build_v2.py | render/renderer.py, render/subtitles.py, render/camera.py, render/mix.py |
| make_bgm.py | render/bgm.py |
| cuts_v2.json | examples/convenience-store/storyboard.json |
| build_video.py, cuts.json | first-generation slideshow (superseded) |
| cors_server.py | failed experiment (browser pane could not reach localhost); not used |

`build_v2.py` still runs on its own (it reads `cuts_v2.json` and `Downloads/shorts_v2`), but it is not tested.
