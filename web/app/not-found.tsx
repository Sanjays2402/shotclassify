import Link from "next/link";

export default function NotFound() {
  return (
    <div className="panel p-10 text-center max-w-[640px] mx-auto mt-12">
      <div className="eyebrow">No call on the field</div>
      <h1 className="h-display text-[40px] mt-2">404</h1>
      <p className="text-[13px] opacity-70 mt-2">
        That route is not on the card. Head back to the live feed.
      </p>
      <div className="mt-4 flex justify-center gap-3">
        <Link href="/" className="btn btn-cue">Live feed</Link>
        <Link href="/shots" className="btn btn-ghost">Box score</Link>
      </div>
    </div>
  );
}
