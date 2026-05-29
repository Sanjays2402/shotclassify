"use client";

import { useCallback, useState } from "react";
import { Upload } from "@/components/icons";

export default function Dropzone({
  onFiles,
  busy,
}: {
  onFiles: (files: File[]) => void;
  busy: boolean;
}) {
  const [over, setOver] = useState(false);

  const handle = useCallback(
    (files: FileList | null) => {
      if (!files) return;
      const imgs = Array.from(files).filter((f) => f.type.startsWith("image/"));
      if (imgs.length) onFiles(imgs);
    },
    [onFiles]
  );

  return (
    <label
      htmlFor="sc-upload"
      onDragOver={(e) => {
        e.preventDefault();
        setOver(true);
      }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => {
        e.preventDefault();
        setOver(false);
        handle(e.dataTransfer.files);
      }}
      className={`dropzone glass cursor-pointer transition-all flex flex-col items-center justify-center text-center py-16 px-6 ${
        over ? "scale-[1.01] shadow-2xl" : ""
      }`}
    >
      <input
        id="sc-upload"
        type="file"
        accept="image/*"
        multiple
        className="hidden"
        onChange={(e) => handle(e.target.files)}
      />
      <Upload className="w-10 h-10 float text-indigo-500" />
      <h1 className="mt-4 text-2xl md:text-3xl font-semibold tracking-tight">
        Drop a screenshot
      </h1>
      <p className="mt-2 text-sm opacity-70 max-w-md">
        Vision LLM + Tesseract decide what it is, pull the right fields, and suggest an action.
        Receipts, code, errors, charts, memes, more.
      </p>
      <div className="mt-5 flex items-center gap-2 text-xs opacity-70">
        <span className="kbd">PNG</span>
        <span className="kbd">JPG</span>
        <span className="kbd">HEIC</span>
        <span className="kbd">batch ok</span>
        {busy && <span className="ml-3 animate-pulse">classifying…</span>}
      </div>
    </label>
  );
}
