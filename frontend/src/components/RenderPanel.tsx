"use client";

import { useCallback, useEffect, useState } from "react";
import { api, ApiError, BgmStyle, describe, RenderFile } from "@/lib/api";
import { useJob } from "@/hooks/useJob";

const fmtMb = (b: number) => `${(b / 1024 / 1024).toFixed(1)}MB`;
const fmtTime = (t: number) => new Date(t * 1000).toLocaleString("ko-KR");

export function RenderPanel({ pid, azureReady }: { pid: string; azureReady: boolean }) {
  const [renders, setRenders] = useState<RenderFile[]>([]);
  const [jobId, setJobId] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [styles, setStyles] = useState<BgmStyle[]>([]);
  const [style, setStyle] = useState("night_piano");
  const [aiLabel, setAiLabel] = useState(true);

  const refresh = useCallback(() => {
    api.renders(pid).then(setRenders).catch(() => {});
  }, [pid]);
  useEffect(refresh, [refresh]);
  useEffect(() => {
    api.bgmStyles().then(setStyles).catch(() => {});
  }, []);

  const job = useJob(jobId, (j) => {
    setJobId(null);
    if (j.state === "failed") setError(j.error ?? "렌더에 실패했습니다");
    refresh();
  });

  async function start() {
    setError("");
    try {
      const j = await api.render(pid, undefined, style, aiLabel);
      setJobId(j.id);
    } catch (e) {
      setError(e instanceof ApiError ? describe(e.detail) : "렌더를 시작하지 못했습니다");
    }
  }

  const running = jobId !== null;
  const latest = renders[0];

  return (
    <section className="panel" id="render" aria-label="렌더">
      <h2>영상 렌더</h2>
      <p className="muted small">
        모든 컷을 이어 붙여 영상을 만듭니다. 21~26컷 기준으로 수 분이 걸리고, 처음 읽는 대사는 Azure 음성을 새로 만듭니다
        (월 무료 한도 안의 소량).
      </p>
      <label className="field">
        <span>배경음악</span>
        <select value={style} onChange={(e) => setStyle(e.target.value)} disabled={running} aria-label="배경음악">
          {styles.map((s) => <option key={s.name} value={s.name}>{s.label}</option>)}
        </select>
      </label>
      <label className="check">
        <input type="checkbox" checked={aiLabel} onChange={(e) => setAiLabel(e.target.checked)} disabled={running} />
        <span>영상에 “AI 생성” 표시 넣기 (권장)</span>
      </label>
      <p className="muted small">
        왼쪽 위에 작은 표식을 넣고 파일 정보에도 AI 생성 사실을 적습니다. 어떤 표시가 법적으로 필요한지는 직접 확인해야 합니다.
      </p>
      <div className="actions">
        <button className="primary" onClick={start} disabled={running || !azureReady} title={azureReady ? "" : "Azure 키가 필요합니다"}>
          {running ? "렌더 중…" : "영상 렌더 시작"}
        </button>
        {!azureReady && <span className="muted small">Azure 음성 키가 설정되지 않았습니다</span>}
      </div>

      {running && (
        <div className="progress-wrap" role="status">
          <progress value={job?.progress ?? 0} max={1} />
          <span>{Math.round((job?.progress ?? 0) * 100)}%</span>
          <pre className="log">{(job?.log ?? []).slice(-6).join("\n")}</pre>
        </div>
      )}
      {error && <p className="error" role="alert">{error}</p>}

      {latest ? (
        <div className="video-block">
          <h3>최근 결과 <span className="muted small">{fmtTime(latest.created)} · {fmtMb(latest.bytes)}</span></h3>
          <video key={latest.name} controls preload="metadata" src={`/api/projects/${pid}/renders/${latest.name}`} />
          <a className="button" href={`/api/projects/${pid}/renders/${latest.name}`} download={latest.name}>다운로드</a>
          {renders.length > 1 && (
            <details>
              <summary>이전 렌더 {renders.length - 1}개</summary>
              <ul className="plain">
                {renders.slice(1).map((r) => (
                  <li key={r.name}>
                    <a href={`/api/projects/${pid}/renders/${r.name}`} target="_blank" rel="noreferrer">{r.name}</a>{" "}
                    <span className="muted small">{fmtTime(r.created)} · {fmtMb(r.bytes)}</span>
                  </li>
                ))}
              </ul>
            </details>
          )}
        </div>
      ) : (
        <p className="muted">아직 렌더한 영상이 없습니다.</p>
      )}
    </section>
  );
}
