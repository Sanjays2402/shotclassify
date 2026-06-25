"use client";

// useChartTheme: a small client hook that resolves the theme-aware recharts
// token set (see lib/chart-theme.ts) from the live `data-theme` attribute
// that lib/theme.ts writes onto <html>. It re-resolves when the attribute
// changes -- so flipping Light <-> Dim from the header toggle re-themes
// every chart on the page without a reload -- via a MutationObserver scoped
// to that single attribute.

import { useEffect, useState } from "react";
import { chartTheme, type ChartTheme } from "@/lib/chart-theme";
import type { ResolvedTheme } from "@/lib/theme";

function readResolvedTheme(): ResolvedTheme {
  if (typeof document === "undefined") return "light";
  const attr = document.documentElement.getAttribute("data-theme");
  return attr === "dim" ? "dim" : "light";
}

export function useChartTheme(): ChartTheme {
  // SSR + first paint default to light to match the historical hard-coded
  // look; the effect corrects to the real value right after mount.
  const [resolved, setResolved] = useState<ResolvedTheme>("light");

  useEffect(() => {
    setResolved(readResolvedTheme());

    if (typeof MutationObserver === "undefined") return;
    const el = document.documentElement;
    const obs = new MutationObserver(() => {
      setResolved((cur) => {
        const next = readResolvedTheme();
        return cur === next ? cur : next;
      });
    });
    obs.observe(el, { attributes: true, attributeFilter: ["data-theme"] });
    return () => obs.disconnect();
  }, []);

  return chartTheme(resolved);
}

export default useChartTheme;
