"use client";

import { useEffect, useRef, useState } from "react";
import { api, Job } from "@/lib/api";

/** Poll a background job until it finishes. Pass null to stop. */
export function useJob(jobId: string | null, onFinished?: (job: Job) => void) {
  const [job, setJob] = useState<Job | null>(null);
  const finished = useRef(onFinished);
  useEffect(() => {
    finished.current = onFinished;
  });

  useEffect(() => {
    if (!jobId) return;
    let stop = false;
    const tick = async () => {
      try {
        const j = await api.job(jobId);
        if (stop) return;
        setJob(j);
        if (j.state === "done" || j.state === "failed") {
          finished.current?.(j);
          return;
        }
      } catch {
        /* transient: keep polling */
      }
      if (!stop) timer = setTimeout(tick, 1500);
    };
    let timer = setTimeout(tick, 300);
    return () => {
      stop = true;
      clearTimeout(timer);
    };
  }, [jobId]);

  return jobId ? job : null;
}
