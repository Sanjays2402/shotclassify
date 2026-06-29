// Tooltip formatter for the /stats class-mix bar chart (F157). The bar shows
// per-class volume but the tooltip read "12" alone -- the mean confidence was
// only in the legend list below, so hovering a bar told you count without the
// quality signal sitting right next to it. This pairs the two: count gets a
// "shots" unit, and mean confidence rides along as a second tooltip row so a
// glance answers "how many, and how sure" at once.
//
// Pure + DOM-free: recharts hands the formatter (value, name, entry) and we
// map dataKey -> [text, label]. The mean lives on the same datum, so we read
// it off the payload rather than needing a second series.

// One class-mix datum as plotted: name is the short class label, count drives
// the bar height, mean is whole-percent mean confidence (already *100).
export type ClassMixDatum = {
  name: string;
  cat: string;
  count: number;
  mean: number;
};

// Pluralised "N shots" / "1 shot" so the count tooltip reads naturally rather
// than "1 shots". Exported for the conf row + tests.
export function classMixCountText(count: number): string {
  const n = Number.isFinite(count) ? Math.max(0, Math.round(count)) : 0;
  return `${n.toLocaleString()} ${n === 1 ? "shot" : "shots"}`;
}

// The mean-conf companion line. recharts only labels the count bar, so we fold
// the confidence into the count row as a second clause -- "12 shots - 87% conf"
// -- so one tooltip carries both. Guards a missing/NaN mean to 0%.
export function classMixConfText(mean: number | null | undefined): string {
  const m = typeof mean === "number" && Number.isFinite(mean) ? mean : 0;
  return `${Math.round(m)}% conf`;
}

// recharts tooltip formatter: returns [displayValue, label]. The bar's only
// series is `count`, so we enrich its value with the trailing conf clause and
// label it "Class mix" -- "12 shots - 87% conf". The datum carries `mean`.
export function classMixTooltipFormatter(
  value: number,
  datum: { mean?: number } | undefined,
): [string, string] {
  const count = typeof value === "number" ? value : 0;
  const conf = classMixConfText(datum?.mean);
  return [`${classMixCountText(count)} \u00b7 ${conf}`, "Class mix"];
}
