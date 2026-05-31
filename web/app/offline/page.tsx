import Link from "next/link";
import { WifiSlash, ArrowClockwise } from "@phosphor-icons/react/dist/ssr";

export const metadata = {
  title: "Offline · ShotClassify",
  description: "You appear to be offline. Reconnect to classify shots.",
};

export default function OfflinePage() {
  return (
    <div className="max-w-xl mx-auto px-4 py-16 text-center">
      <div
        className="mx-auto w-14 h-14 rounded-full flex items-center justify-center mb-5"
        style={{ background: "var(--color-chalk)", border: "1px solid var(--color-rule)" }}
        aria-hidden
      >
        <WifiSlash size={28} weight="duotone" />
      </div>
      <h1 className="h-display text-[28px] tracking-tight mb-2">You are offline</h1>
      <p className="text-[14px] opacity-80 mb-6">
        ShotClassify needs a network connection to run new classifications. Cached pages and
        assets remain available while you are offline.
      </p>
      <div className="flex items-center justify-center gap-3">
        <Link
          href="/"
          className="inline-flex items-center gap-2 px-4 py-2 rounded-md text-[13px]"
          style={{ background: "var(--color-felt)", color: "var(--color-chalk)" }}
        >
          <ArrowClockwise size={16} weight="duotone" />
          Try again
        </Link>
        <Link
          href="/shots"
          className="inline-flex items-center gap-2 px-4 py-2 rounded-md text-[13px] border"
          style={{ borderColor: "var(--color-rule)" }}
        >
          Browse cached shots
        </Link>
      </div>
    </div>
  );
}
