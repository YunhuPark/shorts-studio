"use client";

import Link from "next/link";
import { use, useCallback, useEffect, useState } from "react";
import { api, ApiError, describe, FaceCheck, imageUrl, Project, Settings, Shot } from "@/lib/api";
import { DemoBanner } from "@/components/DemoBanner";
import { ImagesPanel } from "@/components/ImagesPanel";
import { RenderPanel } from "@/components/RenderPanel";
import { ShotCard } from "@/components/ShotCard";
import { VoicePanel } from "@/components/VoicePanel";

export function ProjectView({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const [project, setProject] = useState<Project | null>(null);
  const [settings, setSettings] = useState<Settings | null>(null);
  const [error, setError] = useState("");
  const [open, setOpen] = useState<number | null>(null);
  const [faceBusy, setFaceBusy] = useState(false);
  const [faceError, setFaceError] = useState("");
  const [faceRun, setFaceRun] = useState<{ byShot: Map<number, FaceCheck>; versions: Map<number, number | null> } | null>(null);

  const load = useCallback(async () => {
    try {
      const [p, s] = await Promise.all([api.project(id), api.settings()]);
      setProject(p);
      setSettings(s);
      setError("");
    } catch (e) {
      setError(
        e instanceof ApiError && e.status === 404
          ? "프로젝트를 찾을 수 없습니다."
          : "API 서버에 연결할 수 없습니다. 터미널에서 `python -m shorts_studio serve`가 실행 중인지 확인하세요.",
      );
    }
  }, [id]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    load();
  }, [load]);

  // Esc closes the image viewer
  useEffect(() => {
    if (open === null) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(null);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  async function runFaceCheck() {
    if (!project || faceBusy) return;
    setFaceBusy(true);
    setFaceError("");
    try {
      const result = await api.faceCheck(id);
      // remember which image each result belongs to, so a regenerated shot does not keep a stale badge
      setFaceRun({ byShot: new Map(result.checks.map((c) => [c.shot, c])), versions: new Map(project.shots.map((s) => [s.n, s.image_version])) });
    } catch (e) {
      setFaceError(e instanceof ApiError ? describe(e.detail) : "얼굴 검사를 실행하지 못했습니다");
    } finally {
      setFaceBusy(false);
    }
  }

  const replaceShot = (s: Shot) =>
    setProject((p) => (p ? { ...p, shots: p.shots.map((x) => (x.n === s.n ? s : x)) } : p));

  if (error) {
    return (
      <>
        <p><Link href="/projects">← 프로젝트 목록</Link></p>
        <div className="banner" role="alert">{error}</div>
      </>
    );
  }
  if (!project || !settings) return <p className="muted">불러오는 중…</p>;

  const speakers = Object.keys(project.voices);
  const price = settings.image_price_usd;
  const capReached = settings.spent_today_usd + price > settings.daily_cap_usd;
  const blockedReason = !settings.keys.gemini
    ? "Gemini 키가 설정되지 않아 이미지를 만들 수 없습니다"
    : capReached
      ? "오늘 예상 비용 한도에 도달했습니다"
      : "";
  const canGenerate = blockedReason === "";
  const missing = project.shots.filter((s) => !s.has_image).length;
  const errors = project.issues.filter((i) => i.level === "error").length;
  const warns = project.issues.length - errors;
  const spentPct = Math.min(100, (settings.spent_today_usd / settings.daily_cap_usd) * 100);
  const openShot = project.shots.find((s) => s.n === open);

  return (
    <>
      {settings.demo && <DemoBanner />}
      <div className="toolbar">
        <div>
          <p className="small" style={{ margin: 0 }}><Link href="/projects">← 프로젝트 목록</Link></p>
          <h1>{project.title}</h1>
          <span className="muted small">{project.logline}</span>
        </div>
        <div className="stats">
          <span className="pill">컷 {project.shots.length}</span>
          {missing > 0 && <span className="pill bad">이미지 없음 {missing}</span>}
          {errors > 0 && <span className="pill bad">오류 {errors}</span>}
          {warns > 0 && <span className="pill">경고 {warns}</span>}
          <span className="pill" title="이미지 재생성 추정 비용 누계 (실제 청구액이 아님)">
            오늘 ${settings.spent_today_usd.toFixed(2)} / ${settings.daily_cap_usd.toFixed(2)}{" "}
            <span className="meter"><i style={{ width: `${spentPct}%` }} /></span>
          </span>
          <a className="button primary" href="#render">렌더로 이동</a>
        </div>
      </div>

      {project.issues.length > 0 && (
        <section className="panel" aria-label="점검 결과">
          <h2>점검 결과</h2>
          <ul className="plain">
            {project.issues.map((i, k) => (
              <li key={k} className={i.level === "error" ? "error" : "muted"}>
                {i.shot !== null ? `컷 ${i.shot}: ` : ""}{i.message}
              </li>
            ))}
          </ul>
        </section>
      )}

      <ImagesPanel pid={id} missing={missing} price={price} canGenerate={canGenerate} blockedReason={blockedReason} onDone={load} />

      <VoicePanel pid={id} voices={project.voices} azureReady={settings.keys.azure} onChanged={load} />

      <h2>스토리보드</h2>
      <p className="muted small">
        대사를 고치고 “저장”을 누르면 바로 파일에 반영됩니다(이전 버전은 .bak로 보관). 이미지 재생성은 유료 API를 쓰므로
        예상 비용을 확인한 뒤에만 실행됩니다.
      </p>
      <div className="row" style={{ alignItems: "center", gap: 12, marginBottom: 12 }}>
        <button onClick={runFaceCheck} disabled={faceBusy} title="내 컴퓨터에서만 계산합니다. 비용 없음.">
          {faceBusy ? "검사 중…" : "얼굴 일치 검사"}
        </button>
        <span className="muted small">
          등장인물 기준 이미지와 각 컷의 얼굴을 비교합니다(무료·로컬). 옆모습·뒷모습은 낮게 나올 수 있어 눈으로 확인할 컷을 고르는 용도입니다.
        </span>
      </div>
      {faceError && <p className="error" role="alert">{faceError}</p>}
      <div className="grid">
        {project.shots.map((s) => (
          <ShotCard
            key={s.n}
            pid={id}
            shot={s}
            speakers={speakers}
            cameras={project.cameras}
            price={price}
            canGenerate={canGenerate}
            blockedReason={blockedReason}
            onSaved={replaceShot}
            onRegenerated={load}
            onOpen={setOpen}
            face={faceRun && faceRun.versions.get(s.n) === s.image_version ? faceRun.byShot.get(s.n) : undefined}
          />
        ))}
      </div>

      <RenderPanel pid={id} azureReady={settings.keys.azure} />

      {openShot && (
        <div className="lightbox" role="dialog" aria-label={`컷 ${openShot.n} 이미지`} onClick={() => setOpen(null)}>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={imageUrl(id, openShot.n, openShot.image_version, 1080)} alt={`컷 ${openShot.n}: ${openShot.scene}`} />
          <button onClick={() => setOpen(null)} aria-label="닫기">닫기 (Esc)</button>
        </div>
      )}
    </>
  );
}
