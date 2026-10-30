import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: "Shorts Studio",
  description: "스토리보드 편집, 목소리 선택, 컷별 이미지 재생성, 쇼츠 렌더",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="ko">
      <body>
        <header className="topbar">
          <Link href="/" className="brand">Shorts Studio</Link>
          <span className="muted small">로컬 대시보드</span>
        </header>
        <main>{children}</main>
      </body>
    </html>
  );
}
