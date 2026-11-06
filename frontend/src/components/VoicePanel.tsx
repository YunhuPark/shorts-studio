"use client";

import { useEffect, useRef, useState } from "react";
import { api, ApiError, describe, fetchVoiceSample, Recommendation, VoiceChoice, VoiceSpec } from "@/lib/api";

const RATE = /^[+-]?\d{1,3}%$/;

function SpeakerRow({ pid, who, spec, choices, azureReady, onSaved }: {
  pid: string; who: string; spec: VoiceSpec; choices: VoiceChoice[]; azureReady: boolean; onSaved: () => void;
}) {
  const [voice, setVoice] = useState(spec.voice);
  const [rate, setRate] = useState(spec.rate);
  const [pitch, setPitch] = useState(spec.pitch);
  const [gender, setGender] = useState("male");
  const [age, setAge] = useState("senior");
  const [rec, setRec] = useState<Recommendation | null>(null);
  const [src, setSrc] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState("");
  const audio = useRef<HTMLAudioElement>(null);

  useEffect(() => setVoice(spec.voice), [spec.voice]);
  useEffect(() => setRate(spec.rate), [spec.rate]);
  useEffect(() => setPitch(spec.pitch), [spec.pitch]);
  useEffect(() => () => { if (src) URL.revokeObjectURL(src); }, [src]);

  const dirty = voice !== spec.voice || rate !== spec.rate || pitch !== spec.pitch;
  const rateOk = RATE.test(rate);

  async function listen() {
    setMsg("");
    setLoading(true);
    try {
      const url = await fetchVoiceSample(voice, rate);
      setSrc(url);
      setTimeout(() => audio.current?.play().catch(() => {}), 50);
    } catch (e) {
      setMsg(e instanceof ApiError && e.status === 503 ? "Azure 키가 설정되지 않아 들어볼 수 없습니다" : e instanceof ApiError ? describe(e.detail) : "재생하지 못했습니다");
    } finally {
      setLoading(false);
    }
  }

  async function recommend() {
    setMsg("");
    try {
      setRec(await api.recommendVoices(gender, age));
    } catch (e) {
      setMsg(e instanceof ApiError ? describe(e.detail) : "추천을 가져오지 못했습니다");
    }
  }

  function apply(name: string) {
    if (!rec) return;
    setVoice(name);
    setRate(rec.rate);
    setPitch(rec.pitch);
  }

  async function save() {
    setSaving(true);
    setMsg("");
    try {
      await api.setVoice(pid, who, { voice, rate, pitch });
      onSaved();
      setMsg("저장됨");
    } catch (e) {
      setMsg(e instanceof ApiError ? describe(e.detail) : "저장하지 못했습니다");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="speaker">
      <strong>{who}</strong>
      <label className="field">
        <span>목소리</span>
        <select value={voice} onChange={(e) => setVoice(e.target.value)}>
          {choices.map((c) => (
            <option key={c.name} value={c.name}>
              {c.name.replace("ko-KR-", "").replace("Neural", "")} ({c.gender === "male" ? "남" : "여"}){c.note ? ` · ${c.note}` : ""}
            </option>
          ))}
        </select>
      </label>
      <label className="field narrow">
        <span>속도</span>
        <input value={rate} onChange={(e) => setRate(e.target.value)} aria-invalid={!rateOk} placeholder="-10%" />
      </label>
      <button onClick={listen} disabled={loading || !rateOk || !azureReady} title={azureReady ? "같은 대사로 샘플을 들어봅니다" : "Azure 키가 필요합니다"}>
        {loading ? "만드는 중…" : "들어보기"}
      </button>
      <button className="primary" onClick={save} disabled={!dirty || !rateOk || saving}>저장</button>
      <div className="recommend" role="group" aria-label={`${who} 목소리 추천`}>
        <label className="field narrow">
          <span>성별</span>
          <select value={gender} onChange={(e) => { setGender(e.target.value); setRec(null); }} aria-label={`${who} 성별`}>
            <option value="male">남</option>
            <option value="female">여</option>
          </select>
        </label>
        <label className="field narrow">
          <span>나이대</span>
          <select value={age} onChange={(e) => { setAge(e.target.value); setRec(null); }} aria-label={`${who} 나이대`}>
            <option value="young">젊음</option>
            <option value="adult">중년</option>
            <option value="senior">노년</option>
          </select>
        </label>
        <button onClick={recommend} aria-label={`${who} 목소리 추천 받기`}>추천 받기</button>
        {rec && (
          <span className="chips" aria-label={`${who} 추천 목소리`}>
            {rec.voices.map((v) => (
              <button key={v.name} className="chip-button" onClick={() => apply(v.name)} title="이 목소리와 권장 속도·음높이를 채웁니다 (저장 전까지 반영되지 않음)">
                {v.name.replace("ko-KR-", "").replace("Neural", "")} · {v.pitch_hz}Hz
              </button>
            ))}
          </span>
        )}
      </div>
      {rec && <p className="muted small recommend-note">{rec.note} (속도 {rec.rate}, 음높이 {rec.pitch})</p>}
      {src && <audio ref={audio} src={src} controls className="sample" />}
      {msg && <span className="muted small" role="status">{msg}</span>}
    </div>
  );
}

export function VoicePanel({ pid, voices, azureReady, onChanged }: {
  pid: string; voices: Record<string, VoiceSpec>; azureReady: boolean; onChanged: () => void;
}) {
  const [choices, setChoices] = useState<VoiceChoice[]>([]);
  const [confirming, setConfirming] = useState(false);
  const [narrMsg, setNarrMsg] = useState("");
  useEffect(() => { api.voices().then(setChoices).catch(() => {}); }, []);
  const narrator = voices["narrator"];
  const others = Object.keys(voices).filter((w) => w !== "narrator");

  async function unify() {
    setConfirming(false);
    setNarrMsg("");
    try {
      for (const who of others) {
        await api.setVoice(pid, who, { voice: narrator.voice, rate: narrator.rate, pitch: narrator.pitch });
      }
      onChanged();
      setNarrMsg("모든 인물이 내레이터 목소리로 바뀌었습니다");
    } catch (e) {
      setNarrMsg(e instanceof ApiError ? describe(e.detail) : "바꾸지 못했습니다");
    }
  }

  return (
    <section className="panel" aria-label="목소리">
      <h2>목소리</h2>
      <p className="muted small">같은 대사(“오늘이 우리 결혼기념일이라서. 집사람 몫이야.”)로 들어볼 수 있습니다. 저장해도 영상은 다음 렌더부터 반영됩니다.</p>
      {narrator && others.length > 0 && (
        <div className="actions" role="group" aria-label="내레이션 모드">
          {!confirming ? (
            <button onClick={() => setConfirming(true)} title="인물마다 목소리를 구하기 어려울 때: 모든 대사를 내레이터 한 사람이 읽습니다">
              내레이션으로 통일
            </button>
          ) : (
            <span className="confirm">
              <span>{others.join(", ")}의 목소리를 내레이터({narrator.voice.replace("ko-KR-", "").replace("Neural", "")})로 바꿉니다</span>
              <button className="danger" onClick={unify}>바꾸기</button>
              <button onClick={() => setConfirming(false)}>취소</button>
            </span>
          )}
          {narrMsg && <span className="muted small" role="status">{narrMsg}</span>}
        </div>
      )}
      {Object.entries(voices).map(([who, spec]) => (
        <SpeakerRow key={who} pid={pid} who={who} spec={spec} choices={choices} azureReady={azureReady} onSaved={onChanged} />
      ))}
    </section>
  );
}
