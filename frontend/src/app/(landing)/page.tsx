import type { Metadata } from "next";
import { Landing } from "@/components/landing/Landing";

export const metadata: Metadata = {
  title: "Shorts Studio — 스토리보드 한 편이 쇼츠가 됩니다",
  description: "컷마다 이미지를 만들고, 목소리를 고르고, 자막과 BGM을 얹어 9:16 영상으로 렌더합니다. 읽기 전용 데모를 열어볼 수 있습니다.",
};

export default function HomePage() {
  return <Landing />;
}
