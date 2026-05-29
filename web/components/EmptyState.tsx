"use client";

import { Sparkle } from "@/components/icons";

export default function EmptyState() {
  return (
    <div className="glass p-10 text-center flex flex-col items-center gap-3">
      <Sparkle className="w-8 h-8 text-indigo-500 float" />
      <h3 className="text-lg font-medium">Nothing classified yet</h3>
      <p className="text-sm opacity-70 max-w-md">
        Drop a screenshot above, or pipe one in from the CLI:
        <br />
        <span className="kbd mt-2 inline-block">uv run shotclassify classify ~/Desktop/img.png</span>
      </p>
    </div>
  );
}
