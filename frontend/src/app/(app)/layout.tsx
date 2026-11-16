import Link from "next/link";

// The working part of the site: the project list and the editor. The landing page (outside this group) has its own header.
export default function AppLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <>
      <header className="topbar">
        <Link href="/" className="brand">Shorts Studio</Link>
        <nav aria-label="주 메뉴" className="topnav">
          <Link href="/projects">프로젝트</Link>
        </nav>
      </header>
      <main className="shell">{children}</main>
    </>
  );
}
