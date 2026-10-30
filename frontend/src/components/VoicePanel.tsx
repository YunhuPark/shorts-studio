"use client";

import { useEffect, useRef, useState } from "react";
import { api, ApiError, describe, fetchVoiceSample, VoiceChoice, VoiceSpec } from "@/lib/api";

const RATE = /^[+-]?\d{1,3}%$/;

function SpeakerRow({ pid, who, spec, choices, azureReady, onSaved }: {
  pid: string; who: string; spec: VoiceSpec; choices: VoiceChoice[]; azureReady: boolean; onSaved: () => void;
}) {
  const [voice, setVoice] = useState(spec.voice);
  const [rate, setRate] = useState(spec.rate);
  const [src, setSrc] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState("");
  const audio = useRef<HTMLAudioElement>(null);

  useEffect(() => setVoice(spec.voice), [spec.voice]);
  useEffect(() => setRate(spec.rate), [spec.rate]);
  useEffect(() => () => { if (src) URL.revokeObjectURL(src); }, [src]);

  const dirty = voice !== spec.voice || rate !== spec.rate;
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

  async function save() {
    setSaving(true);
    setMsg("");
    try {
      await api.setVoice(pid, who, { voice, rate, pitch: spec.pitch });
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
      {src && <audio ref={audio} src={src} controls className="sample" />}
      {msg && <span className="muted small" role="status">{msg}</span>}
    </div>
  );
}

export function VoicePanel({ pid, voices, azureReady, onChanged }: {
  pid: string; voices: Record<string, VoiceSpec>; azureReady: boolean; onChanged: () => void;
}) {
  const [choices, setChoices] = useState<VoiceChoice[]>([]);
  useEffect(() => { api.voices().then(setChoices).catch(() => {}); }, []);
  return (
    <section className="panel" aria-label="목소리">
      <h2>목소리</h2>
      <p className="muted small">같은 대사(“오늘이 우리 결혼기념일이라서. 집사람 몫이야.”)로 들어볼 수 있습니다. 저장해도 영상은 다음 렌더부터 반영됩니다.</p>
      {Object.entries(voices).map(([who, spec]) => (
        <SpeakerRow key={who} pid={pid} who={who} spec={spec} choices={choices} azureReady={azureReady} onSaved={onChanged} />
      ))}
    </section>
  );
}
