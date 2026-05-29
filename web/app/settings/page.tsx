"use client";

import { useEffect, useState } from "react";

export default function SettingsPage() {
  const [yaml, setYaml] = useState("");
  const [path, setPath] = useState("");
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  useEffect(() => {
    fetch("/api/settings")
      .then((r) => r.json())
      .then((d) => {
        setYaml(d.yaml ?? "");
        setPath(d.path ?? "");
      });
  }, []);

  async function save() {
    setSaving(true);
    setMsg(null);
    const r = await fetch("/api/settings", {
      method: "PUT",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ yaml }),
    });
    setSaving(false);
    setMsg(r.ok ? "saved" : "failed: " + (await r.text()));
  }

  return (
    <div className="flex flex-col gap-4">
      <header className="glass p-4">
        <h1 className="text-xl font-semibold">Routing rules</h1>
        <p className="text-xs opacity-70 mt-1">
          YAML file at <span className="kbd">{path}</span>. Edits take effect immediately.
        </p>
      </header>

      <textarea
        spellCheck={false}
        className="glass p-4 font-mono text-xs min-h-[420px] outline-none"
        value={yaml}
        onChange={(e) => setYaml(e.target.value)}
      />

      <div className="flex items-center gap-3">
        <button
          onClick={save}
          disabled={saving}
          className="cat-badge px-4 py-1.5 cursor-pointer disabled:opacity-50"
        >
          {saving ? "saving…" : "save"}
        </button>
        {msg && <span className="text-xs opacity-70">{msg}</span>}
      </div>
    </div>
  );
}
