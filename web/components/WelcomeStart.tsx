"use client";

import { useCallback } from "react";
import { PlayCircle } from "@phosphor-icons/react/dist/ssr";
import { resetOnboarded } from "@/lib/onboarding";

export default function WelcomeStart() {
  const start = useCallback(() => {
    resetOnboarded();
    window.dispatchEvent(new CustomEvent("shotclassify:show-tour"));
  }, []);

  return (
    <button
      type="button"
      onClick={start}
      className="inline-flex items-center gap-2 text-[14px] px-4 py-2 rounded font-medium"
      style={{
        background: "var(--color-felt)",
        color: "var(--color-chalk)",
      }}
    >
      <PlayCircle weight="duotone" size={18} /> Start the tour
    </button>
  );
}
