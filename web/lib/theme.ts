// Theme persistence + resolution helpers. Pure: no DOM access here so we
// can unit-test the storage / resolution logic without jsdom. The component
// in components/ThemeToggle.tsx wraps these with `localStorage` and an
// observer for the `prefers-color-scheme` media query.

export type ThemeMode = "light" | "dim" | "system";
export type ResolvedTheme = "light" | "dim";

export const STORAGE_KEY = "shotclassify.theme";

const VALID_MODES: ThemeMode[] = ["light", "dim", "system"];

// Parse whatever's currently in localStorage into a known mode. Returns
// "system" for anything unrecognised so we don't apply a corrupted value
// from a previous version of the schema.
export function parseStoredMode(raw: string | null | undefined): ThemeMode {
  if (typeof raw !== "string") return "system";
  const t = raw.trim().toLowerCase();
  if ((VALID_MODES as string[]).includes(t)) return t as ThemeMode;
  return "system";
}

// Given the user's preference + the system preference (typically the
// outcome of `matchMedia('(prefers-color-scheme: dark)').matches`),
// produce the theme we should actually paint. Default is light; system
// mode delegates to the OS; explicit modes always win.
export function resolveTheme(
  mode: ThemeMode,
  systemPrefersDark: boolean,
): ResolvedTheme {
  if (mode === "light") return "light";
  if (mode === "dim") return "dim";
  return systemPrefersDark ? "dim" : "light";
}

// Cycle through the three modes -- the toggle button cycles in this order
// so a user can quickly find every state without opening a dropdown.
export function nextMode(mode: ThemeMode): ThemeMode {
  if (mode === "light") return "dim";
  if (mode === "dim") return "system";
  return "light";
}

// Human label for the active mode, used by the toggle button.
export function labelForMode(mode: ThemeMode): string {
  if (mode === "light") return "Light";
  if (mode === "dim") return "Dim";
  return "Auto";
}

// Build the pre-paint script that runs before React hydrates. Reads the
// stored mode from localStorage and slaps the correct data-theme attribute
// onto <html> so the dim palette is in place BEFORE the first paint --
// otherwise users see a flash of chalk-cream before flipping to dim.
//
// Inlined into the layout via a <Script strategy="beforeInteractive">. We
// keep it minimal and self-contained -- no imports, no module bindings,
// pure browser globals.
export const themeInitScript = `(function(){try{var k='${STORAGE_KEY}';var m=localStorage.getItem(k);if(!m||(m!=='light'&&m!=='dim'&&m!=='system'))m='system';var dark=false;try{dark=window.matchMedia('(prefers-color-scheme: dark)').matches;}catch(e){}var t=m==='dim'?'dim':m==='light'?'light':dark?'dim':'light';document.documentElement.setAttribute('data-theme',t);document.documentElement.setAttribute('data-theme-mode',m);}catch(e){}})();`;
