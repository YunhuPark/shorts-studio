"""Command line: render a storyboard, audition voices, lint, and run the image-consistency harness."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .generate import plan_generation, run_generation
from .models import Storyboard, VoiceSpec
from .providers import AzureVoiceProvider, DirectoryImageSource, GeminiImageProvider, ProviderError
from .qa import lint, missing_images
from .render import RenderOptions, render

SAMPLE_TEXT = "오늘이 우리 결혼기념일이라서. 집사람 몫이야."
SAMPLE_VOICES = ["ko-KR-BongJinNeural", "ko-KR-GookMinNeural", "ko-KR-HyunsuNeural",
                 "ko-KR-HyunsuMultilingualNeural", "ko-KR-InJoonNeural"]


def parse_only(value: str | None) -> set[int] | None:
    return {int(x) for x in value.split(",")} if value else None


def cmd_render(a: argparse.Namespace) -> int:
    sb = Storyboard.load(a.storyboard)
    if a.speaker_voice:
        for item in a.speaker_voice:
            who, voice = item.split("=", 1)
            old = sb.voices[who]
            sb.voices[who] = VoiceSpec(old.provider, voice, a.speaker_rate or old.rate, old.pitch)
    errors = [i for i in lint(sb) if i.level == "error"]
    if errors:
        print("\n".join(map(str, errors)), file=sys.stderr)
        return 2
    opts = RenderOptions(work_dir=Path(a.work), font=a.font)
    voices = AzureVoiceProvider(cache_dir=a.tts_cache or Path(a.work) / "tts")
    render(sb, DirectoryImageSource(a.images), voices, a.out, opts, parse_only(a.only))
    return 0


def cmd_lint(a: argparse.Namespace) -> int:
    sb = Storyboard.load(a.storyboard)
    issues = lint(sb)
    for i in issues:
        print(i)
    if a.images:
        print("missing images:", missing_images(sb, DirectoryImageSource(a.images)) or "none")
    print(f"{len(issues)} issue(s)")
    return 1 if any(i.level == "error" for i in issues) else 0


def cmd_voice_samples(a: argparse.Namespace) -> int:
    provider = AzureVoiceProvider(cache_dir=Path(a.out))
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    for v in a.voices or SAMPLE_VOICES:
        wav = provider.synthesize(a.text, VoiceSpec("azure", v, a.rate, "0%"))
        target = out / (v.replace("ko-KR-", "").replace("Neural", "") + ".wav")
        target.write_bytes(wav.read_bytes())
        print("sample:", target)
    return 0


def cmd_image_consistency(a: argparse.Namespace) -> int:
    """Phase 0 harness: does a reference image keep a character's face across shots?

    1) make a reference portrait of the character, 2) make each requested shot with that portrait attached,
    3) write a contact sheet for a person to judge. Costs (1 + number of shots) image calls.
    """
    sb = Storyboard.load(a.storyboard)
    shots = [s for s in sb.shots if s.n in (parse_only(a.shots) or set())]
    if a.character not in sb.characters:
        print(f"unknown character '{a.character}'; have: {list(sb.characters)}", file=sys.stderr)
        return 2
    ref_prompt = (f"Front-facing neutral portrait, plain background, even soft light. {sb.characters[a.character]}. "
                  f"{sb.style}")
    prompts = [("reference", ref_prompt, [])] + [
        (f"shot{s.n:02d}", ("Use exactly the same person as in the reference image (same face, glasses, hat, clothes). "
                            + sb.image_prompt(s)), ["reference"]) for s in shots]
    print(f"{len(prompts)} image call(s) with model '{a.model}'")
    if a.dry_run:
        for name, prompt, _ in prompts:
            print(f"--- {name}\n{prompt}\n")
        return 0
    out = Path(a.out)
    provider = GeminiImageProvider(a.model)
    made: dict[str, Path] = {}
    try:
        for name, prompt, ref_names in prompts:
            made[name] = provider.generate(prompt, [made[r] for r in ref_names], out / f"{name}.png")
            print("made", made[name])
    except ProviderError as e:
        print(f"stopped: {e}", file=sys.stderr)
        return 1
    from PIL import Image
    ims = [Image.open(p).convert("RGB") for p in made.values()]
    h = 640
    ims = [im.resize((int(im.width * h / im.height), h)) for im in ims]
    sheet = Image.new("RGB", (sum(im.width for im in ims), h), "black")
    x = 0
    for im in ims:
        sheet.paste(im, (x, 0))
        x += im.width
    sheet.save(out / "contact.png")
    print("contact sheet:", out / "contact.png")
    return 0


def _pairs(items: list[str] | None) -> list[tuple[str, Path]]:
    out = []
    for item in items or []:
        key, path = item.split("=", 1)
        out.append((key, Path(path)))
    return out


def cmd_generate(a: argparse.Namespace) -> int:
    """Create missing (or --replace) shot images conditioned on reference images."""
    sb = Storyboard.load(a.storyboard)
    char_refs = dict(_pairs(a.char_ref))
    shot_refs: dict[int, list[Path]] = {}
    for key, path in _pairs(a.shot_ref):
        shot_refs.setdefault(int(key), []).append(path)
    for path in [*char_refs.values(), *(p for ps in shot_refs.values() for p in ps)]:
        if not path.exists():
            print(f"reference image not found: {path}", file=sys.stderr)
            return 2
    images = DirectoryImageSource(a.images)
    items = plan_generation(sb, images, char_refs, shot_refs, parse_only(a.shots), parse_only(a.replace))
    print(f"{len(items)} image call(s) with model '{a.model}': shots {[i.shot.n for i in items]}")
    for item in items:
        note = f" (existing image will be kept as cut{item.shot.n:02d}_prev.png)" if item.replaces else ""
        print(f"--- shot {item.shot.n}: refs={[r.name for r in item.refs]}{note}")
        if a.dry_run:
            print(item.prompt, "\n")
    if a.dry_run or not items:
        return 0
    try:
        run_generation(items, GeminiImageProvider(a.model), Path(a.images), a.model)
    except ProviderError as e:
        print(f"stopped: {e}", file=sys.stderr)
        return 1
    return 0


def cmd_serve(a: argparse.Namespace) -> int:
    """Run the local dashboard API on localhost only."""
    import uvicorn

    from .api.app import Settings, create_app
    settings = Settings.from_env()
    settings.root = Path(a.data)
    print(f"dashboard API: http://127.0.0.1:{a.port}  (data: {settings.root.resolve()})")
    uvicorn.run(create_app(settings), host="127.0.0.1", port=a.port, log_level="info")
    return 0


def cmd_import_project(a: argparse.Namespace) -> int:
    """Create a dashboard project from a storyboard file and an images folder."""
    import shutil

    from .api.store import ProjectStore
    store = ProjectStore(a.data)
    shot_refs: dict[str, list[str]] = {}
    for key, path in _pairs(a.shot_ref):
        shot_refs.setdefault(key, []).append(path.name)
    settings = {"model": a.model, "char_refs": {k: p.name for k, p in _pairs(a.char_ref)}, "shot_refs": shot_refs}
    d = store.create(a.id, a.storyboard, a.images, settings)
    if a.tts_cache_from:  # reuse already-synthesised wavs so the first render does not re-spend characters
        dest = Path(a.data) / "cache" / "tts"
        dest.mkdir(parents=True, exist_ok=True)
        for f in Path(a.tts_cache_from).glob("*.wav"):
            shutil.copyfile(f, dest / f.name)
    print(f"created project '{a.id}' at {d} with {len(list((d / 'images').glob('cut*.png')))} images")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="shorts-studio")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("render", help="render a storyboard with existing images")
    r.add_argument("storyboard")
    r.add_argument("--images", required=True, help="folder with cutNN.png")
    r.add_argument("--out", default="output/short.mp4")
    r.add_argument("--only", help="comma separated shot numbers, e.g. 5,14,16")
    r.add_argument("--work", default=".cache/work")
    r.add_argument("--tts-cache", help="folder of cached wavs (default: <work>/tts)")
    r.add_argument("--font", help="subtitle font file (default: bundled font or SHORTS_FONT)")
    r.add_argument("--speaker-voice", action="append", metavar="WHO=VOICE", help="override a speaker's voice")
    r.add_argument("--speaker-rate", help="rate for overridden voices, e.g. -10%%")
    r.set_defaults(fn=cmd_render)

    l = sub.add_parser("lint", help="check a storyboard")
    l.add_argument("storyboard")
    l.add_argument("--images")
    l.set_defaults(fn=cmd_lint)

    v = sub.add_parser("voice-samples", help="write the same line in several voices")
    v.add_argument("--out", default="output/voice_samples")
    v.add_argument("--text", default=SAMPLE_TEXT)
    v.add_argument("--rate", default="-10%")
    v.add_argument("--voices", nargs="*")
    v.set_defaults(fn=cmd_voice_samples)

    c = sub.add_parser("image-consistency", help="test reference-image consistency with the Gemini API")
    c.add_argument("storyboard")
    c.add_argument("--character", required=True)
    c.add_argument("--shots", required=True, help="comma separated shot numbers using that character")
    c.add_argument("--model", required=True, help="Gemini image model id (check Google's current model list)")
    c.add_argument("--out", default="output/consistency")
    c.add_argument("--dry-run", action="store_true", help="print the prompts, make no API calls")
    c.set_defaults(fn=cmd_image_consistency)

    g = sub.add_parser("generate", help="make missing shot images using reference images (Gemini API)")
    g.add_argument("storyboard")
    g.add_argument("--images", required=True, help="folder with cutNN.png; new images are written here")
    g.add_argument("--model", required=True)
    g.add_argument("--char-ref", action="append", metavar="CHARACTER=IMAGE", help="reference image per character")
    g.add_argument("--shot-ref", action="append", metavar="N=IMAGE", help="extra reference image for shot N (repeatable)")
    g.add_argument("--shots", help="limit to these shot numbers")
    g.add_argument("--replace", help="shot numbers to regenerate even if an image exists (old one kept as _prev)")
    g.add_argument("--dry-run", action="store_true", help="print the plan and prompts, make no API calls")
    g.set_defaults(fn=cmd_generate)

    s = sub.add_parser("serve", help="run the local dashboard API (localhost only)")
    s.add_argument("--data", default=".data", help="folder for projects, caches and the spend ledger")
    s.add_argument("--port", type=int, default=8765, help="(8000 is reserved by Windows on some machines)")
    s.set_defaults(fn=cmd_serve)

    i = sub.add_parser("import-project", help="create a dashboard project from a storyboard and images")
    i.add_argument("id", help="lowercase letters, digits and hyphens")
    i.add_argument("storyboard")
    i.add_argument("--images", required=True)
    i.add_argument("--data", default=".data")
    i.add_argument("--model", default="gemini-3.1-flash-image")
    i.add_argument("--char-ref", action="append", metavar="CHARACTER=IMAGE", help="reference image per character")
    i.add_argument("--shot-ref", action="append", metavar="N=IMAGE", help="extra reference for shot N (repeatable)")
    i.add_argument("--tts-cache-from", help="folder of cached wavs to copy in")
    i.set_defaults(fn=cmd_import_project)

    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
