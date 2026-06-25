import "./globals.css";
import type { Metadata } from "next";
import Link from "next/link";
import { Inter, Space_Grotesk, JetBrains_Mono } from "next/font/google";
import Ticker from "@/components/Ticker";
import HotKeys from "@/components/HotKeys";
import CommandPalette from "@/components/CommandPalette";
import CommandPaletteButton from "@/components/CommandPaletteButton";
import { QuotaMeter } from "@/components/QuotaMeter";
import OnboardingTour from "@/components/OnboardingTour";
import AuthMenu from "@/components/AuthMenu";
import PwaInstaller from "@/components/PwaInstaller";
import NotificationBell from "@/components/NotificationBell";
import ShortcutsHelp from "@/components/ShortcutsHelp";
import ShortcutsHelpButton from "@/components/ShortcutsHelpButton";
import ThemeToggle from "@/components/ThemeToggle";
import ScrollProgress from "@/components/ScrollProgress";
import Toaster from "@/components/Toaster";
import WhatsNew from "@/components/WhatsNew";
import { themeInitScript } from "@/lib/theme";

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
  manifest: "/manifest.webmanifest",
  applicationName: "ShotClassify",
  appleWebApp: {
    capable: true,
    title: "ShotClassify",
    statusBarStyle: "default",
  },
  icons: {
    icon: [
      { url: "/icon.svg", type: "image/svg+xml" },
      { url: "/icons/icon-192.png", sizes: "192x192", type: "image/png" },
      { url: "/icons/icon-512.png", sizes: "512x512", type: "image/png" },
    ],
    apple: [{ url: "/icons/icon-192.png", sizes: "192x192", type: "image/png" }],
  },
};

export const viewport = {
  themeColor: "#1f4d2b",
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover" as const,
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${inter.variable} ${display.variable} ${mono.variable}`}>
      <head>
        {/* Run before hydration so the dim palette is on <html> before the
            first paint. Avoids a chalk-cream flash for users on Dim. */}
        <script
          dangerouslySetInnerHTML={{ __html: themeInitScript }}
        />
      </head>
      <body>
        <HotKeys />
        <CommandPalette />
        <ShortcutsHelp />
        <ScrollProgress />
        <Toaster />
        <OnboardingTour />
        <PwaInstaller />
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
            </Link>
            <WhatsNew />
            <nav className="flex items-center gap-4">
              <NavLink href="/">Live</NavLink>
              <NavLink href="/demo">Demo</NavLink>
              <NavLink href="/shots">Shots</NavLink>
              <NavLink href="/stats">Stats</NavLink>
              <NavLink href="/compare">Compare</NavLink>
              <NavLink href="/calibration">Calibration</NavLink>
              <NavLink href="/upload">Upload</NavLink>
              <NavLink href="/batch">Batch</NavLink>
              <NavLink href="/keys">API keys</NavLink>
              <NavLink href="/api-docs">API docs</NavLink>
              <NavLink href="/webhooks">Webhooks</NavLink>
              <NavLink href="/notifications">Inbox</NavLink>
              <NavLink href="/digest">Digest</NavLink>
              <NavLink href="/usage">Usage</NavLink>
              <NavLink href="/pricing">Pricing</NavLink>
              <NavLink href="/account">Account</NavLink>
              <NavLink href="/settings/security">Security</NavLink>
              <NavLink href="/settings/security/privacy">Privacy</NavLink>
              <NavLink href="/settings/security/scim">SCIM</NavLink>
              <NavLink href="/settings/security/incidents">Incidents</NavLink>
              <NavLink href="/settings/security/webhook-egress">Webhook egress</NavLink>
              <NavLink href="/settings/security/rate-limits">Rate limits</NavLink>
              <NavLink href="/settings/security/api-key-access-windows">Key windows</NavLink>
              <NavLink href="/settings/mfa">MFA</NavLink>
              <NavLink href="/settings/sessions">Sessions</NavLink>
              <NavLink href="/settings/data">Data</NavLink>
              <NavLink href="/settings/teardown">Teardown</NavLink>
              <NavLink href="/settings/members">Members</NavLink>
              <NavLink href="/settings/audit">Audit</NavLink>
              <NavLink href="/admin">Admin</NavLink>
              <NavLink href="/signin">Sign in</NavLink>
              <NavLink href="/welcome">Welcome</NavLink>
            </nav>
            <div className="ml-auto flex items-center gap-3">
              <CommandPaletteButton />
              <QuotaMeter compact />
              <NotificationBell />
              <ShortcutsHelpButton />
              <ThemeToggle />
              <span className="eyebrow hidden sm:inline">Press</span>
              <span className="kbd">U</span>
              <span className="eyebrow hidden sm:inline">to ingest</span>
              <AuthMenu />
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
