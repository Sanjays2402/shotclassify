export function SampleBadge({ note }: { note?: string }) {
  return (
    <span
      className="eyebrow inline-flex items-center gap-1.5 px-2 py-0.5 rounded-sm"
      style={{
        background: "var(--color-ink)",
        color: "var(--color-cue)",
        border: "1px solid var(--color-cue-deep)",
      }}
      title={note ?? "Seeded data shown because the server has no matching records."}
    >
      ⟂ Sample data
    </span>
  );
}
