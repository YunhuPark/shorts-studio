import type { Metadata } from "next";
import { NewStory } from "@/components/NewStory";

export const metadata: Metadata = { title: "새 이야기 만들기 — Shorts Studio" };

export default function NewStoryPage() {
  return <NewStory />;
}
