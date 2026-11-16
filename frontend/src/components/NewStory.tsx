"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api, ApiError, describe, Settings } from "@/lib/api";
import { DemoBanner } from "@/components/DemoBanner";

const EXAMPLES = [
  "비 오는 날, 우산이 하나뿐인 버스 정류장에서 서로 모르는 두 사람이 만난다.",
  "고양이가 매일 밤 주인 몰래 어디론가 나간다. 오늘은 몰래 따라가 봤다.",
  "퇴근길 엘리베이터에서 십 년 만에 옛 직장 상사를 만났다. 어색한 3분이 흐른다.",
];

export function NewStory() {
  const router = useRouter();
  const [settings, setSettings] = useState<Settings | null>(null);
  const [loadError, setLoadError] = useState("");
  const [prompt, setPrompt] = useState("");
  const [shots, setShots] = useState<number | null>(null);
  const [style, setStyle] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    api.settings().then(setSettings).catch(() => setLoadError("API 서버에 연결할 수 없습니다. 터미널에서 `python -m shorts_studio serve`가 실행 중인지 확인하세요."));
  }, []);

  if (loadError) return <div className="banner" role="alert">{loadError}</div>;
  const story = settings?.story;
  if (!settings || !story) return <p className="muted">불러오는 중…</p>;

  const shotChoices = [6, 8, 12, 16, 20, 24].filter((n) => n >= story.min_shots && n <= story.max_shots);
  const shotCount = shots ?? story.default_shots;
  const chosenStyle = style ?? story.default_style;
  const demo = Boolean(settings.demo);
  const noKey = !demo && !settings.keys.gemini;
  const capReached = !demo && settings.spent_today_usd + story.price_usd > settings.daily_cap_usd;
  const blocked = noKey ? "Gemini 키가 설정되지 않아 이야기를 만들 수 없습니다" : capReached ? "오늘 예상 비용 한도에 도달했습니다" : "";
  const tooShort = prompt.trim().length < 4;

  async function create() {
    setConfirming(false);
    setBusy(true);
    setError("");
    try {
      const r = await api.createStory({ prompt, shots: shotCount, style: chosenStyle });
      if (r.demo) await new Promise((done) => setTimeout(done, 900)); // the replay takes a moment, like the real thing
      router.push(`/projects/${r.id}`);
    } catch (e) {
      if (e instanceof ApiError && e.status === 429) setError("오늘 예상 비용 한도에 도달했습니다");
      else setError(e instanceof ApiError ? describe(e.detail) : "이야기를 만들지 못했습니다");
      setBusy(false);
    }
  }

  return (
    <>
      {demo && <DemoBanner />}
      <p className="small" style={{ margin: 0 }}><Link href="/projects">← 프로젝트 목록</Link></p>
      <h1>새 이야기 만들기</h1>
      <p className="muted">
        만들고 싶은 이야기를 한두 문장으로 적으면 AI가 컷별 스토리보드(대사, 장면, 목소리)를 써 줍니다. 결과는 바로 고칠 수 있고,
        이미지는 그다음 단계에서 만듭니다.
      </p>
      {demo && (
        <p className="muted small">
          데모에서는 AI를 호출하지 않습니다. 무엇을 적어도 미리 만든 예제 이야기(새벽 3시, 컵라면 두 개)가 열립니다.
        </p>
      )}

      <form className="panel" onSubmit={(e) => { e.preventDefault(); if (!tooShort && !blocked) setConfirming(true); }}>
        <label className="field">
          <span>이야기</span>
          <textarea
            rows={5}
            value={prompt}
            maxLength={story.max_prompt}
            onChange={(e) => { setPrompt(e.target.value); setConfirming(false); }}
            placeholder="예) 새벽 편의점에서 매일 컵라면 하나를 사 가던 할아버지가 오늘은 두 개를 산다. 이유는 마지막에 밝혀진다."
            disabled={busy}
            aria-label="이야기"
          />
        </label>
        <p className="muted small" style={{ margin: "4px 0 10px" }}>{prompt.length}/{story.max_prompt}자</p>
        <div className="recommend" role="group" aria-label="예시">
          <span className="muted small">예시</span>
          <span className="chips">
            {EXAMPLES.map((ex) => (
              <button key={ex} type="button" className="chip-button" disabled={busy} onClick={() => { setPrompt(ex); setConfirming(false); }}>
                {ex.length > 24 ? `${ex.slice(0, 24)}…` : ex}
              </button>
            ))}
          </span>
        </div>

        <div className="row" style={{ marginTop: 14 }}>
          <label className="field">
            <span>컷 수</span>
            <select value={shotCount} onChange={(e) => setShots(Number(e.target.value))} disabled={busy} aria-label="컷 수">
              {shotChoices.map((n) => <option key={n} value={n}>{n}컷 (약 {Math.round(n * 3.5)}초)</option>)}
            </select>
          </label>
          <label className="field">
            <span>화풍</span>
            <select value={chosenStyle} onChange={(e) => setStyle(e.target.value)} disabled={busy} aria-label="화풍">
              {story.styles.map((s) => <option key={s.name} value={s.name}>{s.label}</option>)}
            </select>
          </label>
        </div>

        <div className="actions" style={{ marginTop: 14 }}>
          {!confirming ? (
            <button className="primary" type="submit" disabled={busy || tooShort || blocked !== ""} title={blocked}>
              {busy ? "만드는 중…" : "스토리보드 만들기"}
            </button>
          ) : (
            <span className="confirm" role="group" aria-label="비용 확인">
              <span>{story.price_usd > 0 ? `약 $${story.price_usd.toFixed(3)} 사용 (추정)` : "비용 없음 (데모)"}</span>
              <button className="danger" type="button" onClick={create}>만들기</button>
              <button type="button" onClick={() => setConfirming(false)}>취소</button>
            </span>
          )}
          {blocked && <span className="muted small">{blocked}</span>}
        </div>

        {busy && (
          <div className="progress-wrap" role="status" aria-live="polite">
            <div className="spinner" aria-hidden="true" />
            <span>이야기를 쓰는 중입니다. 보통 10~30초 걸립니다. 이 창을 닫지 마세요.</span>
          </div>
        )}
        {error && <p className="error" role="alert">{error}</p>}
      </form>
      <p className="muted small">
        입력한 내용은 먼저 단어·패턴 검수를 거치고, AI가 쓴 결과도 같은 검수를 통과해야 저장됩니다. 이미지와 영상은 이 단계에서 만들어지지 않습니다.
      </p>
    </>
  );
}
