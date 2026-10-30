import { Suspense } from "react";
import { ProjectView } from "@/components/ProjectView";

// With Cache Components, reading the dynamic `id` must happen under <Suspense>; the shell prerenders instantly.
export default function ProjectPage({ params }: { params: Promise<{ id: string }> }) {
  return (
    <Suspense fallback={<p className="muted">불러오는 중…</p>}>
      <ProjectView params={params} />
    </Suspense>
  );
}
