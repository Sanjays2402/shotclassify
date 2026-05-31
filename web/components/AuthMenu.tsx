"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { SignIn, UserCircle } from "@phosphor-icons/react/dist/ssr";

type Who = { principal: string | null };

export default function AuthMenu() {
  const [who, setWho] = useState<Who | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetch("/api/auth/whoami", { credentials: "include" })
      .then((r) => r.json())
      .then((j: Who) => {
        if (!cancelled) setWho(j);
      })
      .catch(() => {
        if (!cancelled) setWho({ principal: null });
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (who === null) {
    return (
      <div
        className="w-7 h-7 rounded-full bg-gray-200 animate-pulse"
        aria-hidden
      />
    );
  }

  if (!who.principal) {
    return (
      <Link
        href="/signin"
        className="inline-flex items-center gap-1.5 text-[12px] font-medium px-2.5 py-1.5 rounded-md border hover:bg-gray-50 transition-colors"
        style={{ borderColor: "var(--color-rule)" }}
        aria-label="Sign in"
      >
        <SignIn size={14} weight="duotone" />
        Sign in
      </Link>
    );
  }

  const initials = who.principal.slice(0, 2).toUpperCase();
  return (
    <Link
      href="/signin"
      className="inline-flex items-center gap-2 px-1.5 py-1 rounded-md hover:bg-gray-50 transition-colors"
      title={`Signed in as ${who.principal}`}
      aria-label={`Account: ${who.principal}`}
    >
      <span
        className="w-7 h-7 rounded-full flex items-center justify-center text-[10px] font-semibold"
        style={{ background: "var(--color-felt)", color: "white" }}
        aria-hidden
      >
        {initials}
      </span>
      <span className="text-[12px] hidden md:inline opacity-80">
        {who.principal}
      </span>
      <UserCircle
        size={14}
        weight="duotone"
        className="opacity-50 hidden md:inline"
      />
    </Link>
  );
}
