"use client";

import { useEffect, useState, useCallback } from "react";
import { DownloadSimple, X, DeviceMobile } from "@phosphor-icons/react/dist/ssr";

type BeforeInstallPromptEvent = Event & {
  prompt: () => Promise<void>;
  userChoice: Promise<{ outcome: "accepted" | "dismissed"; platform: string }>;
};

const DISMISS_KEY = "shotclassify:pwa:dismissed-at";
const DISMISS_TTL_MS = 1000 * 60 * 60 * 24 * 14; // 14 days

function isStandalone(): boolean {
  if (typeof window === "undefined") return false;
  if (window.matchMedia?.("(display-mode: standalone)").matches) return true;
  // iOS Safari
  // @ts-expect-error legacy property
  if (window.navigator.standalone) return true;
  return false;
}

function isIos(): boolean {
  if (typeof navigator === "undefined") return false;
  const ua = navigator.userAgent || "";
  const iOS = /iPad|iPhone|iPod/.test(ua) && !("MSStream" in window);
  return iOS;
}

export default function PwaInstaller() {
  const [deferred, setDeferred] = useState<BeforeInstallPromptEvent | null>(null);
  const [visible, setVisible] = useState(false);
  const [showIos, setShowIos] = useState(false);

  useEffect(() => {
    if (typeof window === "undefined") return;
    if (!("serviceWorker" in navigator)) return;
    const onLoad = () => {
      navigator.serviceWorker.register("/sw.js").catch(() => {});
    };
    if (document.readyState === "complete") onLoad();
    else window.addEventListener("load", onLoad, { once: true });
    return () => window.removeEventListener("load", onLoad);
  }, []);

  useEffect(() => {
    if (isStandalone()) return;
    const dismissedAt = Number(localStorage.getItem(DISMISS_KEY) || 0);
    if (dismissedAt && Date.now() - dismissedAt < DISMISS_TTL_MS) return;

    const handler = (e: Event) => {
      e.preventDefault();
      setDeferred(e as BeforeInstallPromptEvent);
      setVisible(true);
    };
    window.addEventListener("beforeinstallprompt", handler);

    // iOS has no beforeinstallprompt; show a hint once.
    if (isIos()) setShowIos(true);

    const installed = () => {
      setVisible(false);
      setShowIos(false);
      setDeferred(null);
    };
    window.addEventListener("appinstalled", installed);
    return () => {
      window.removeEventListener("beforeinstallprompt", handler);
      window.removeEventListener("appinstalled", installed);
    };
  }, []);

  const dismiss = useCallback(() => {
    try {
      localStorage.setItem(DISMISS_KEY, String(Date.now()));
    } catch {}
    setVisible(false);
    setShowIos(false);
  }, []);

  const install = useCallback(async () => {
    if (!deferred) return;
    try {
      await deferred.prompt();
      await deferred.userChoice;
    } finally {
      setDeferred(null);
      setVisible(false);
    }
  }, [deferred]);

  if (!visible && !showIos) return null;

  return (
    <div
      role="dialog"
      aria-label="Install ShotClassify"
      className="fixed z-50 bottom-4 left-4 right-4 sm:left-auto sm:right-4 sm:max-w-sm rounded-lg shadow-lg border"
      style={{
        background: "var(--color-chalk)",
        borderColor: "var(--color-rule)",
      }}
    >
      <div className="p-3 flex items-start gap-3">
        <div
          className="shrink-0 w-9 h-9 rounded-md flex items-center justify-center"
          style={{ background: "var(--color-felt)", color: "var(--color-chalk)" }}
          aria-hidden
        >
          <DeviceMobile size={20} weight="duotone" />
        </div>
        <div className="flex-1 min-w-0">
          <div className="text-[13px] font-medium">Install ShotClassify</div>
          {visible ? (
            <p className="text-[12px] opacity-75 mt-0.5">
              Add to your home screen for one tap launch and an offline shell.
            </p>
          ) : (
            <p className="text-[12px] opacity-75 mt-0.5">
              On iPhone, tap Share then &quot;Add to Home Screen&quot; to install.
            </p>
          )}
          <div className="mt-2 flex items-center gap-2">
            {visible && (
              <button
                type="button"
                onClick={install}
                className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded text-[12px]"
                style={{ background: "var(--color-felt)", color: "var(--color-chalk)" }}
              >
                <DownloadSimple size={14} weight="duotone" /> Install
              </button>
            )}
            <button
              type="button"
              onClick={dismiss}
              className="inline-flex items-center gap-1 px-2 py-1 rounded text-[12px] border"
              style={{ borderColor: "var(--color-rule)" }}
            >
              Not now
            </button>
          </div>
        </div>
        <button
          type="button"
          aria-label="Dismiss install prompt"
          onClick={dismiss}
          className="shrink-0 p-1 rounded hover:opacity-70"
        >
          <X size={14} weight="bold" />
        </button>
      </div>
    </div>
  );
}
