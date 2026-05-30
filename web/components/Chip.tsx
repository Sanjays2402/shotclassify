import type { Category } from "@/lib/categories";
import { SHORT } from "@/lib/categories";

export function Chip({
  cat,
  size = "md",
  label,
}: {
  cat: Category;
  size?: "md" | "lg";
  label?: string;
}) {
  return (
    <span className={size === "lg" ? "chip lg" : "chip"} data-cat={cat}>
      <span className="bar" />
      <span className="label">{label ?? SHORT[cat]}</span>
    </span>
  );
}
