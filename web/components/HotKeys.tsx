"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

export default function HotKeys() {
  const router = useRouter();
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const target = e.target as HTMLElement | null;
      if (
        target &&
        (target.tagName === "INPUT" ||
          target.tagName === "TEXTAREA" ||
          target.isContentEditable)
      ) {
        return;
      }
      if (e.key.toLowerCase() === "u" && !e.metaKey && !e.ctrlKey && !e.altKey) {
        router.push("/upload");
      } else if (e.key.toLowerCase() === "s" && !e.metaKey && !e.ctrlKey && !e.altKey) {
        router.push("/shots");
      } else if (e.key.toLowerCase() === "c" && !e.metaKey && !e.ctrlKey && !e.altKey) {
        router.push("/calibration");
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [router]);
  return null;
}
