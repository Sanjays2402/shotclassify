// Loading-state predicate for the /stats charts (F37). The Box-score page
// renders recharts only after mount (they need `window`) and fetches the
// aggregate via SWR. Before either is ready the chart canvases were blank /
// the page showed a bare "Pulling rollups..." line. This pure predicate
// decides when to show a <Skeleton> shimmer in a chart slot instead, so the
// rule is documented + unit-testable and the page stays a thin renderer.
//
// We show the skeleton when EITHER:
//   - the component hasn't mounted yet (SSR / first paint -- recharts can't
//     render, so the slot would otherwise be empty), OR
//   - the first aggregate fetch is still in flight AND no data has arrived.
// Once any data exists (real OR the seeded sample the page falls back to on
// error) we stop shimmering and render the chart, so an API outage shows the
// seeded preview rather than an indefinite skeleton.

export function chartsBusy(
  mounted: boolean,
  isLoading: boolean,
  hasData: boolean,
): boolean {
  if (!mounted) return true;
  return isLoading && !hasData;
}
