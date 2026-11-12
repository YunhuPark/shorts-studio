"use client";

import { DemoBanner } from "@/components/DemoBanner";
import Link from "next/link";
import { useEffect, useState } from "react";
import { api, ApiError, ProjectSummary, Settings } from "@/lib/api";

export default function Home() {
  const [projects, setProjects] = useState<ProjectSummary[] | null>(null);
  const [settings, setSettings] = useState<Settings | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    Promise.all([api.projects(), api.settings()])
      .then(([p, s]) => {
        setProjects(p);
        setSettings(s);
      })
      .catch((e) =>
        setError(
          e instanceof ApiError
            ? `서버 오류 (${e.status})`
            : "API 서버에 연결할 수 없습니다. 터미널에서 `python -m shorts_studio serve`가 실행 중인지 확인하세요.",
        ),
      );
  }, []);

  return (
    <>
      <h1>프로젝트</h1>
      <p className="muted">스토리보드를 고치고, 목소리를 고르고, 컷 이미지를 다시 만들어 영상을 렌더합니다.</p>
      {error && <div className="banner" role="alert">{error}</div>}
      {settings?.demo && <DemoBanner />}
      {settings && !settings.demo && (
        <div className="stats">
          <span className={`pill ${settings.keys.azure ? "ok" : "bad"}`}>음성(Azure) {settings.keys.azure ? "연결됨" : "키 없음"}</span>
          <span className={`pill ${settings.keys.gemini ? "ok" : "bad"}`}>이미지(Gemini) {settings.keys.gemini ? "연결됨" : "키 없음"}</span>
          <span className="pill">오늘 예상 이미지 비용 ${settings.spent_today_usd.toFixed(2)} / ${settings.daily_cap_usd.toFixed(2)}</span>
        </div>
      )}
      {projects === null && !error && <p className="muted">불러오는 중…</p>}
      {projects && projects.length === 0 && (
        <p className="muted">프로젝트가 없습니다. <code>python -m shorts_studio import-project …</code>로 가져오세요.</p>
      )}
      <div className="projects">
        {projects?.map((p) => (
          <Link key={p.id} className="project-card" href={`/projects/${p.id}`}>
            <h2>{p.title}</h2>
            <p className="muted small">{p.logline}</p>
            <p className="small">컷 {p.shots}개 · 이미지 {p.images}/{p.shots}</p>
          </Link>
        ))}
      </div>
    </>
  );
}
