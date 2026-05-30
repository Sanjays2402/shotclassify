import "./globals.css";
import type { Metadata } from "next";
import Link from "next/link";
import { Inter, Space_Grotesk, JetBrains_Mono } from "next/font/google";
import Ticker from "@/components/Ticker";

const inter = Inter({
  subsets: ["latin"],
  variable: "--font-sans",
  display: "swap",
});
const display = Space_Grotesk({
  subsets: ["latin"],
  variable: "--font-display",
  display: "swap",
  weight: ["500", "600", "700"],
});
const mono = JetBrains_Mono({
  subsets: ["latin"],
  variable: "--font-mono",
  display: "swap",
});

export const metadata: Metadata = {
  title: "ShotClassify · live screenshot classifier",
  description:
    "Real-time screenshot classification with confidence scoring, OCR, and field extraction.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${inter.variable} ${display.variable} ${mono.variable}`}>
      <body>
        <Ticker />
        <header
          className="border-b"
          style={{ borderColor: "var(--color-rule)", background: "var(--color-chalk)" }}
        >
          <div className="max-w-7xl mx-auto px-5 py-3 flex items-center gap-6">
            <Link href="/" className="flex items-center gap-2.5">
              <span
                className="inline-block w-3 h-3 rounded-full"
                style={{
                  background: "var(--color-felt)",
                  boxShadow: "inset 0 0 0 2px var(--color-chalk), 0 0 0 1.5px var(--color-felt-rail)",
                }}
                aria-hidden
              />
              <span
                className="h-display text-[18px] tracking-tight"
                style={{ letterSpacing: "-0.01em" }}
              >
                SHOTCLASSIFY
              </span>
              <span className="eyebrow ml-2">v0.1</span>
            </Link>
            <nav className="flex items-center gap-4">
              <NavLink href="/">Live</NavLink>
              <NavLink href="/shots">Shots</NavLink>
              <NavLink href="/calibration">Calibration</NavLink>
              <NavLink href="/upload">Upload</NavLink>
            </nav>
            <div className="ml-auto flex items-center gap-3">
              <span className="eyebrow hidden sm:inline">Press</span>
              <span className="kbd">U</span>
              <span className="eyebrow hidden sm:inline">to ingest</span>
            </div>
          </div>
        </header>
        <main className="max-w-7xl mx-auto px-5 py-6">{children}</main>
        <footer
          className="border-t mt-12"
          style={{ borderColor: "var(--color-rule)" }}
        >
          <div className="max-w-7xl mx-auto px-5 py-6 flex items-center justify-between text-[11px]">
            <span className="eyebrow">FastAPI · Vision LLM · Tesseract · SQLAlchemy</span>
            <span className="eyebrow">© ShotClassify</span>
          </div>
        </footer>
      </body>
    </html>
  );
}

function NavLink({ href, children }: { href: string; children: React.ReactNode }) {
  return (
    <Link
      href={href}
      className="text-[13px] font-medium hover:text-[color:var(--color-felt)] transition-colors"
    >
      {children}
    </Link>
  );
}
