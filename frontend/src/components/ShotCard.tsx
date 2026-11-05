"use client";

import { useEffect, useState } from "react";
import { api, ApiError, CAMERA_LABELS, describe, FaceCheck, FaceStatus, imageUrl, Shot } from "@/lib/api";
import { useJob } from "@/hooks/useJob";

type Props = {
  pid: string;
  shot: Shot;
  speakers: string[];
  cameras: string[];
  price: number;
  canGenerate: boolean;
  blockedReason: string;
  onSaved: (s: Shot) => void;
  onRegenerated: () => void;
  onOpen: (n: number) => void;
  face?: FaceCheck;
};

const FACE_LABEL: Record<FaceStatus, string> = {
  ok: "얼굴 일치",
  "drift?": "얼굴 확인 필요",
  small: "얼굴 작아 판정 불가",
  "no face": "얼굴 안 보임",
};

const splitHighlight = (s: string) => s.split(",").map((x) => x.trim()).filter(Boolean);

export function ShotCard({ pid, shot, speakers, cameras, price, canGenerate, blockedReason, onSaved, onRegenerated, onOpen, face }: Props) {
  const [text, setText] = useState(shot.text);
  const [who, setWho] = useState(shot.who);
  const [camera, setCamera] = useState(shot.camera);
  const [highlight, setHighlight] = useState(shot.highlight.join(", "));
  const [scene, setScene] = useState(shot.scene);
  const [phrases, setPhrases] = useState(shot.phrases);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState("");
  const [confirming, setConfirming] = useState(false);
  const [jobId, setJobId] = useState<string | null>(null);

  // follow the server copy when it changes (after save or reload), without clobbering unsaved edits elsewhere
  useEffect(() => setText(shot.text), [shot.text]);
  useEffect(() => setWho(shot.who), [shot.who]);
  useEffect(() => setCamera(shot.camera), [shot.camera]);
  useEffect(() => setHighlight(shot.highlight.join(", ")), [shot.highlight]);
  useEffect(() => setScene(shot.scene), [shot.scene]);
  useEffect(() => setPhrases(shot.phrases), [shot.phrases]);

  const dirty =
    text !== shot.text || who !== shot.who || camera !== shot.camera || scene !== shot.scene ||
    highlight !== shot.highlight.join(", ");

  // live subtitle preview while typing
  useEffect(() => {
    if (text === shot.text) return;
    const t = setTimeout(() => {
      api.preview(text).then((r) => setPhrases(r.phrases)).catch(() => {});
    }, 300);
    return () => clearTimeout(t);
  }, [text, shot.text]);

  const job = useJob(jobId, (j) => {
    setJobId(null);
    if (j.state === "failed") setError(j.error ?? "이미지 생성에 실패했습니다");
    else onRegenerated();
  });

  async function save() {
    if (!dirty || saving) return;
    setSaving(true);
    setError("");
    try {
      const updated = await api.patchShot(pid, shot.n, { text, who, camera, scene, highlight: splitHighlight(highlight) });
      onSaved(updated);
      setSaved(true);
      setTimeout(() => setSaved(false), 1800);
    } catch (e) {
      setError(e instanceof ApiError ? describe(e.detail) : "저장하지 못했습니다");
    } finally {
      setSaving(false);
    }
  }

  async function regenerate() {
    setConfirming(false);
    setError("");
    try {
      const j = await api.regenerate(pid, shot.n);
      setJobId(j.id);
    } catch (e) {
      if (e instanceof ApiError && e.status === 429) setError("오늘 예상 비용 한도에 도달했습니다");
      else setError(e instanceof ApiError ? describe(e.detail) : "요청하지 못했습니다");
    }
  }

  const busy = jobId !== null;
  const hasPhrases = phrases.length > 0;

  return (
    <article className="card" aria-label={`컷 ${shot.n}`}>
      <div className="card-media">
        {shot.has_image ? (
          <button className="thumb" onClick={() => onOpen(shot.n)} aria-label={`컷 ${shot.n} 이미지 크게 보기`}>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={imageUrl(pid, shot.n, shot.image_version, 360)} alt={`컷 ${shot.n}: ${shot.scene}`} loading="lazy" />
          </button>
        ) : (
          <div className="thumb empty">이미지 없음</div>
        )}
        <span className="badge">컷 {shot.n}</span>
        {face && (
          <span
            className={`badge face ${face.status === "ok" ? "ok" : "warn"}`}
            title={face.faces.map((f) => `${f.closest} ${f.similarity.toFixed(2)}${f.small ? " (작음)" : ""}`).join(" / ") || "감지된 얼굴 없음"}
          >
            {FACE_LABEL[face.status]}
          </span>
        )}
        {busy && (
          <div className="overlay" role="status">
            <div className="spinner" />
            <span>이미지 생성 중… {Math.round((job?.progress ?? 0) * 100)}%</span>
          </div>
        )}
      </div>

      <div className="card-body">
        <label className="field">
          <span>대사</span>
          <textarea
            value={text}
            rows={3}
            maxLength={300}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if ((e.ctrlKey || e.metaKey) && e.key === "Enter") save();
            }}
            placeholder="이 컷에서 읽을 대사 (비워두면 무음 컷)"
          />
        </label>

        <div className="phrases" aria-label="자막 미리보기">
          {hasPhrases ? phrases.map((p, i) => <span key={i} className="chip">{p}</span>) : <span className="muted">자막 없음</span>}
        </div>

        <div className="row">
          <label className="field">
            <span>화자</span>
            <select value={who} onChange={(e) => setWho(e.target.value)}>
              <option value="">(없음)</option>
              {speakers.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          </label>
          <label className="field">
            <span>카메라</span>
            <select value={camera} onChange={(e) => setCamera(e.target.value)}>
              {cameras.map((c) => <option key={c} value={c}>{CAMERA_LABELS[c] ?? c}</option>)}
            </select>
          </label>
        </div>

        <label className="field">
          <span>강조 단어 (쉼표로 구분)</span>
          <input value={highlight} onChange={(e) => setHighlight(e.target.value)} placeholder="예: 두 개, 결혼기념일" />
        </label>

        <details>
          <summary>이미지 설명 (재생성에 사용)</summary>
          <textarea value={scene} rows={4} maxLength={1500} onChange={(e) => setScene(e.target.value)} aria-label="이미지 설명" />
        </details>

        {error && <p className="error" role="alert">{error}</p>}

        <div className="actions">
          <button className="primary" onClick={save} disabled={!dirty || saving}>
            {saving ? "저장 중…" : saved ? "저장됨 ✓" : dirty ? "저장" : "저장할 변경 없음"}
          </button>

          {!confirming ? (
            <button
              onClick={() => setConfirming(true)}
              disabled={busy || !canGenerate}
              title={canGenerate ? "이 컷의 이미지를 새로 만듭니다 (유료)" : blockedReason}
            >
              이미지 다시 생성
            </button>
          ) : (
            <span className="confirm" role="group" aria-label="비용 확인">
              <span>약 ${price.toFixed(3)} 사용 (추정)</span>
              <button className="danger" onClick={regenerate}>생성</button>
              <button onClick={() => setConfirming(false)}>취소</button>
            </span>
          )}
        </div>
        {!canGenerate && <p className="muted small">{blockedReason}</p>}
      </div>
    </article>
  );
}
