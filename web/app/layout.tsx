import "./globals.css";
import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: "ShotClassify",
  description: "Drop a screenshot, get classification + extraction + action.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <nav className="sticky top-0 z-50 glass mx-4 my-3 px-4 py-2 flex items-center gap-6">
          <Link href="/" className="font-semibold tracking-tight">
            <span className="text-indigo-500">●</span> ShotClassify
          </Link>
          <Link href="/history" className="text-sm opacity-80 hover:opacity-100">History</Link>
          <Link href="/settings" className="text-sm opacity-80 hover:opacity-100">Settings</Link>
          <div className="ml-auto text-xs opacity-60">
            <span className="kbd">⌘</span> <span className="kbd">U</span> upload
          </div>
        </nav>
        <main className="px-4 py-6 max-w-6xl mx-auto">{children}</main>
        <footer className="px-4 py-10 text-center text-xs opacity-60">
          built with Next 15 · FastAPI · Tesseract · vision LLM
        </footer>
      </body>
    </html>
  );
}
