"use client";

import Link from "next/link";
import { useEffect, useRef } from "react";
import gsap from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";
import { useGSAP } from "@gsap/react";
import { createScene, type SceneHandle } from "@/lib/landing/scene";
import s from "./landing.module.css";

gsap.registerPlugin(useGSAP, ScrollTrigger);

const DEMO = "/projects/convenience-store";
const FRAMES = Array.from({ length: 14 }, (_, i) => `/landing/f${String(i + 1).padStart(2, "0")}.jpg`);

const STEPS = [
  { name: "쓴다", text: "컷마다 대사와 장면을 씁니다. 자막은 쓰는 대로 미리 보이고, ‘두 개’ 같은 말은 줄이 바뀌어도 한 덩어리로 붙어 있습니다." },
  { name: "고른다", text: "화자마다 목소리를 고릅니다. 나이와 성격에 맞는 후보를 추천받고, 샘플을 들어 본 뒤 정합니다." },
  { name: "다시 만든다", text: "마음에 안 드는 컷만 이미지를 다시 만듭니다. 등장인물의 얼굴이 컷마다 같은 사람인지는 얼굴 검사가 먼저 알려 줍니다." },
  { name: "내보낸다", text: "자막과 BGM을 얹어 9:16 영상으로 렌더합니다. ‘AI 생성’ 표시는 영상과 파일 정보에 함께 남길 수 있습니다." },
];

const GUARDS = [
  { term: "비용 상한", text: "이미지 생성은 하루 한도를 넘으면 멈추고 월 한도도 따로 있습니다. 만들기 전에 비용을 먼저 잡아 두고, 실패하면 돌려받습니다." },
  { term: "입력 검수", text: "제목·대사·장면 설명을 먼저 훑어 성적 콘텐츠, 자해 방법, 무기·마약 제조, 딥페이크·사기 같은 명백한 위반이면 생성과 렌더를 거부합니다. 단어 목록 기반이라 의도까지 읽지는 못합니다." },
  { term: "AI 생성 표시", text: "영상 위 배지와 파일 메타데이터에 AI로 만들었다는 사실을 남기는 옵션이 있습니다. 쓸지 말지는 만드는 사람이 정합니다." },
  { term: "읽기 전용 데모", text: "이 사이트의 데모에는 키도 유료 호출도 없습니다. 미리 만든 결과를 재생하고, 고친 내용은 저장되지 않으며, 요청 횟수는 방문자마다 제한됩니다." },
];

export function Landing() {
  const root = useRef<HTMLDivElement>(null);
  const host = useRef<HTMLDivElement>(null);
  const scene = useRef<SceneHandle | null>(null);

  // the three.js background lives outside GSAP's context: it has its own lifecycle (and may finish loading after unmount)
  useEffect(() => {
    const el = host.current;
    if (!el) return;
    let cancelled = false;
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const narrow = window.matchMedia("(max-width: 760px)").matches;
    createScene(el, FRAMES, { reduced, narrow })
      .then((handle) => {
        if (cancelled) return handle.dispose();
        scene.current = handle;
        el.dataset.ready = "true";
      })
      .catch(() => {
        // no WebGL (old device, blocked GPU): the CSS background below carries the page
        if (!cancelled) el.dataset.fallback = "true";
      });
    const onMove = (e: PointerEvent) => scene.current?.setPointer((e.clientX / window.innerWidth) * 2 - 1, -((e.clientY / window.innerHeight) * 2 - 1));
    const fine = window.matchMedia("(pointer: fine)").matches && !reduced;
    if (fine) window.addEventListener("pointermove", onMove, { passive: true });
    return () => {
      cancelled = true;
      window.removeEventListener("pointermove", onMove);
      scene.current?.dispose();
      scene.current = null;
    };
  }, []);

  useGSAP(
    () => {
      // once the visitor leaves the hero the header gets a solid backing so it never collides with the text below
      ScrollTrigger.create({
        start: 80,
        end: "max",
        onToggle: (self) => root.current?.querySelector("[data-nav]")?.setAttribute("data-solid", String(self.isActive)),
      });

      const mm = gsap.matchMedia();
      mm.add("(prefers-reduced-motion: no-preference)", () => {
        // the one authored moment: the headline rises out of its mask word by word, then everything else settles in
        gsap
          .timeline({ defaults: { ease: "expo.out" } })
          .from("[data-word]", { yPercent: 115, duration: 1.1, stagger: 0.09 }, 0.15)
          .from("[data-hero-fade]", { autoAlpha: 0, y: 18, duration: 0.9, stagger: 0.12 }, 0.7)
          .from("[data-nav]", { autoAlpha: 0, y: -12, duration: 0.8 }, 0.5);

        // the story: the section is pinned and four beats trade places while the camera keeps flying
        const beats = gsap.utils.toArray<HTMLElement>("[data-beat]");
        const marks = gsap.utils.toArray<HTMLElement>("[data-mark]");
        // opacity, not autoAlpha: a beat that is invisible must stay in the accessibility tree so screen readers can still read every step
        gsap.set(beats.slice(1), { opacity: 0 });
        const tl = gsap.timeline({
          defaults: { ease: "none" },
          scrollTrigger: { trigger: "[data-story]", start: "top top", end: "+=320%", pin: "[data-stage]", scrub: 0.6 },
        });
        beats.forEach((beat, i) => {
          const at = i * 2;
          if (i > 0) tl.fromTo(beat, { opacity: 0, y: 36, filter: "blur(10px)" }, { opacity: 1, y: 0, filter: "blur(0px)", duration: 0.5, ease: "expo.out" }, at);
          if (i < beats.length - 1) tl.to(beat, { opacity: 0, y: -28, filter: "blur(8px)", duration: 0.4 }, at + 1.6);
          tl.to(marks[i], { opacity: 1, duration: 0.2 }, at);
          if (i < marks.length - 1) tl.to(marks[i], { opacity: 0.35, duration: 0.2 }, at + 1.8);
        });
        tl.fromTo("[data-rail]", { scaleX: 0 }, { scaleX: 1, duration: beats.length * 2 - 0.4 }, 0);
        tl.to({}, { duration: 0.4 }); // let the last beat rest before the pin releases

        // the camera follows how far the visitor is through hero + pinned story. Its end is the pin's end, read on every
        // refresh: measuring the wrapper instead would ignore the pin's spacing and the camera would arrive far too early
        ScrollTrigger.create({
          start: 0,
          end: () => tl.scrollTrigger?.end ?? ScrollTrigger.maxScroll(window),
          onUpdate: (self) => scene.current?.setProgress(self.progress),
        });

        // the guards slide in as a group, once
        ScrollTrigger.batch("[data-guard]", {
          start: "top 88%",
          once: true,
          onEnter: (els) => gsap.from(els, { autoAlpha: 0, y: 32, duration: 0.9, stagger: 0.12, ease: "expo.out", clearProps: "all" }),
        });
        gsap.from("[data-finale-word]", {
          yPercent: 115,
          duration: 1.1,
          stagger: 0.1,
          ease: "expo.out",
          scrollTrigger: { trigger: "[data-finale]", start: "top 70%", once: true },
        });
      });

      mm.add("(prefers-reduced-motion: reduce)", () => {
        // no pin here, so the wrapper's own height is the right measure
        ScrollTrigger.create({
          trigger: "[data-journey]",
          start: "top top",
          end: "bottom bottom",
          onUpdate: (self) => scene.current?.setProgress(self.progress),
        });
      });

      document.fonts?.ready.then(() => ScrollTrigger.refresh());
      return () => mm.revert();
    },
    { scope: root },
  );

  return (
    <div ref={root} className={s.page}>
      <div ref={host} className={s.scene} aria-hidden="true" />
      <div className={s.scrim} aria-hidden="true" />

      <header className={s.nav} data-nav>
        <Link href="/" className={s.brand}>Shorts Studio</Link>
        <nav aria-label="주 메뉴" className={s.navlinks}>
          <a href="#story" className={s.hideNarrow}>만드는 방법</a>
          <a href="#guard" className={s.hideNarrow}>안전장치</a>
          <Link href="/projects" className={s.hideNarrow}>프로젝트</Link>
          <Link href={DEMO} className={s.navcta}>데모 열기</Link>
        </nav>
      </header>

      <main>
        <div data-journey className={s.journey}>
          <section className={s.hero} aria-labelledby="hero-title">
            <h1 id="hero-title" className={s.title}>
              <span className={s.mask}><span data-word>스토리보드</span></span>{" "}
              <span className={s.mask}><span data-word>한 편이</span></span>{" "}
              <br />
              <span className={s.mask}><span data-word>쇼츠가</span></span>{" "}
              <span className={s.mask}><span data-word>됩니다</span></span>
            </h1>
            <p className={s.lede} data-hero-fade>
              컷마다 이미지를 만들고, 목소리를 고르고, 자막과 BGM을 얹어 9:16 영상으로 렌더합니다. 뒤에 흐르는 스물여섯 장면은 모두 이 도구로 만든 결과입니다.
            </p>
            <div className={s.actions} data-hero-fade>
              <Link href={DEMO} className={s.primary}>데모 열어 보기</Link>
              <a href="#story" className={s.ghost}>어떻게 만드는지</a>
            </div>
          </section>

          <section id="story" data-story className={s.story} aria-label="만드는 방법">
            <div data-stage className={s.stage}>
              <div className={s.beats}>
                {STEPS.map((step) => (
                  <article key={step.name} data-beat className={s.beat}>
                    <h2 className={s.beatTitle}>{step.name}</h2>
                    <p className={s.beatText}>{step.text}</p>
                  </article>
                ))}
              </div>
              <div className={s.track} aria-hidden="true">
                <ul className={s.marks}>
                  {STEPS.map((step, i) => (
                    <li key={step.name} data-mark style={{ opacity: i === 0 ? 1 : 0.35 }}>{step.name}</li>
                  ))}
                </ul>
                <div className={s.railBase}><i data-rail className={s.rail} /></div>
              </div>
            </div>
          </section>
        </div>

        <section id="guard" className={s.guard} aria-labelledby="guard-title">
          <h2 id="guard-title" className={s.guardTitle}>돈이 새지 않게, 사고가 나지 않게</h2>
          <dl className={s.rows}>
            {GUARDS.map((g) => (
              <div key={g.term} data-guard className={s.row}>
                <dt>{g.term}</dt>
                <dd>{g.text}</dd>
              </div>
            ))}
          </dl>
        </section>

        <section data-finale className={s.finale} aria-labelledby="finale-title">
          <h2 id="finale-title" className={s.finaleTitle}>
            <span className={s.mask}><span data-finale-word>직접</span></span>{" "}
            <span className={s.mask}><span data-finale-word>눌러</span></span>{" "}
            <span className={s.mask}><span data-finale-word>보세요</span></span>
          </h2>
          <p className={s.finaleText}>
            새벽 3시 편의점의 컵라면 두 개, 그 한 편의 스토리보드가 그대로 열려 있습니다. 대사를 고쳐 보고, 목소리를 들어 보고, 이미지 다시 만들기와 렌더를 눌러 볼 수 있습니다. 모두 미리 만든 결과를 재생하며 고친 내용은 저장되지 않습니다.
          </p>
          <div className={s.actions}>
            <Link href={DEMO} className={s.primary}>데모 열어 보기</Link>
            <Link href="/projects" className={s.ghost}>프로젝트 목록</Link>
          </div>
        </section>
      </main>

      <footer className={s.footer}>
        <span>Shorts Studio · 포트폴리오 프로젝트</span>
        <span>이미지는 Google Gemini, 음성은 Azure Speech로 만들었습니다.</span>
      </footer>
    </div>
  );
}
