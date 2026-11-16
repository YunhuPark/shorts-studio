"use client";

import { useState } from "react";
import { api, ApiError, describe } from "@/lib/api";
import { useJob } from "@/hooks/useJob";

type Props = {
  pid: string;
  missing: number;
  price: number;
  canGenerate: boolean;
  blockedReason: string;
  onDone: () => void;
};

/** Makes every shot that has no image yet, in story order, as one background job. */
export function ImagesPanel({ pid, missing, price, canGenerate, blockedReason, onDone }: Props) {
  const [jobId, setJobId] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [error, setError] = useState("");
  const [note, setNote] = useState("");

  const job = useJob(jobId, (j) => {
    setJobId(null);
    if (j.state === "failed") setError(j.error ?? "이미지 생성에 실패했습니다. 이미 만든 컷은 남아 있습니다.");
    onDone();
  });

  async function start() {
    setConfirming(false);
    setError("");
    setNote("");
    try {
      const j = await api.generateMissing(pid);
      if (j.skipped > 0) setNote(`오늘 예상 비용 한도 때문에 ${j.count}컷만 만듭니다. 나머지 ${j.skipped}컷은 내일 또는 한도를 올린 뒤 만들 수 있습니다.`);
      setJobId(j.id);
    } catch (e) {
      if (e instanceof ApiError && e.status === 429) setError("오늘 예상 비용 한도에 도달했습니다");
      else setError(e instanceof ApiError ? describe(e.detail) : "요청하지 못했습니다");
    }
  }

  const running = jobId !== null;
  if (missing === 0 && !running) return null;
  const total = price * missing;

  return (
    <section className="panel" aria-label="이미지 만들기">
      <h2>이미지 만들기</h2>
      <p className="muted small">
        이미지가 없는 컷 {missing}개를 이야기 순서대로 한 장씩 만듭니다. 한 인물이 처음 나오는 컷이 그 인물의 기준 이미지가 되어
        이후 컷의 얼굴과 옷을 맞춥니다. 컷당 약 ${price.toFixed(3)}(추정)이고 실제 청구액과 다를 수 있습니다. 컷 수에 따라 몇 분이 걸립니다.
      </p>
      <div className="actions">
        {!confirming ? (
          <button className="primary" onClick={() => setConfirming(true)} disabled={running || !canGenerate} title={canGenerate ? "" : blockedReason}>
            {running ? "만드는 중…" : `빈 컷 이미지 모두 만들기 (${missing}컷)`}
          </button>
        ) : (
          <span className="confirm" role="group" aria-label="비용 확인">
            <span>{missing}컷, 약 ${total.toFixed(2)} 사용 (추정)</span>
            <button className="danger" onClick={start}>만들기</button>
            <button onClick={() => setConfirming(false)}>취소</button>
          </span>
        )}
        {!canGenerate && <span className="muted small">{blockedReason}</span>}
      </div>
      {running && (
        <div className="progress-wrap" role="status">
          <progress value={job?.progress ?? 0} max={1} />
          <span>{Math.round((job?.progress ?? 0) * 100)}%</span>
          <pre className="log">{(job?.log ?? []).slice(-3).join("\n")}</pre>
        </div>
      )}
      {note && <p className="muted small">{note}</p>}
      {error && <p className="error" role="alert">{error}</p>}
    </section>
  );
}
