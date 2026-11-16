import type { Metadata, Viewport } from "next";
import "@fontsource/black-han-sans/latin-400.css";
import "@fontsource/black-han-sans/korean-400.css";
import "pretendard/dist/web/variable/pretendardvariable-dynamic-subset.css";
import "./globals.css";

// Fonts are bundled from npm packages (OFL): Black Han Sans for display, Pretendard Variable for text. No request leaves the site.

export const metadata: Metadata = {
  title: "Shorts Studio",
  description: "스토리보드 한 편을 컷 이미지, 목소리, 자막, BGM이 있는 9:16 쇼츠로 만드는 도구",
};

export const viewport: Viewport = { themeColor: "#070b10", colorScheme: "dark" };

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="ko">
      <body>{children}</body>
    </html>
  );
}
