// Inline Phosphor-style duotone SVG icons. No font dependency.
import * as React from "react";

type P = React.SVGProps<SVGSVGElement>;

const Base = ({ children, ...p }: P & { children: React.ReactNode }) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.6} strokeLinecap="round" strokeLinejoin="round" {...p}>
    {children}
  </svg>
);

export const Upload = (p: P) => (
  <Base {...p}><path d="M12 16V4" /><path d="M5 11l7-7 7 7" /><rect x="3" y="16" width="18" height="5" rx="2" /></Base>
);
export const Receipt = (p: P) => (
  <Base {...p}><path d="M5 3h14v18l-3-2-3 2-3-2-3 2-2-2z" /><path d="M8 8h8M8 12h8M8 16h5" /></Base>
);
export const Code = (p: P) => (
  <Base {...p}><polyline points="8 6 2 12 8 18" /><polyline points="16 6 22 12 16 18" /><line x1="14" y1="4" x2="10" y2="20" /></Base>
);
export const Bug = (p: P) => (
  <Base {...p}><rect x="7" y="9" width="10" height="11" rx="5" /><path d="M12 9V5" /><path d="M9 5l-2-2M15 5l2-2M5 12H2M22 12h-3M5 18H2M22 18h-3" /></Base>
);
export const Chat = (p: P) => (
  <Base {...p}><path d="M21 12a8 8 0 0 1-12 7l-5 1 1-5A8 8 0 1 1 21 12z" /></Base>
);
export const Image = (p: P) => (
  <Base {...p}><rect x="3" y="3" width="18" height="18" rx="3" /><circle cx="9" cy="9" r="2" /><path d="M21 16l-5-5L5 21" /></Base>
);
export const FileText = (p: P) => (
  <Base {...p}><path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z" /><polyline points="14 3 14 8 19 8" /><path d="M9 13h6M9 17h6" /></Base>
);
export const Chart = (p: P) => (
  <Base {...p}><line x1="3" y1="21" x2="21" y2="21" /><rect x="5" y="13" width="3" height="6" /><rect x="11" y="9" width="3" height="10" /><rect x="17" y="5" width="3" height="14" /></Base>
);
export const Frame = (p: P) => (
  <Base {...p}><rect x="3" y="3" width="18" height="18" rx="2" /><line x1="3" y1="9" x2="21" y2="9" /><line x1="3" y1="15" x2="21" y2="15" /><line x1="9" y1="3" x2="9" y2="21" /><line x1="15" y1="3" x2="15" y2="21" /></Base>
);
export const Question = (p: P) => (
  <Base {...p}><circle cx="12" cy="12" r="9" /><path d="M9.5 9a2.5 2.5 0 1 1 4.5 1.5c-.8.7-2 1.2-2 2.5" /><circle cx="12" cy="17" r=".6" fill="currentColor" /></Base>
);
export const CheckCircle = (p: P) => (
  <Base {...p}><circle cx="12" cy="12" r="9" /><polyline points="8 12 11 15 16 9" /></Base>
);
export const Sparkle = (p: P) => (
  <Base {...p}><path d="M12 3l2 5 5 2-5 2-2 5-2-5-5-2 5-2z" /></Base>
);
export const Search = (p: P) => (
  <Base {...p}><circle cx="11" cy="11" r="7" /><line x1="20" y1="20" x2="16.5" y2="16.5" /></Base>
);
export const Filter = (p: P) => (
  <Base {...p}><path d="M3 5h18l-7 9v6l-4-2v-4z" /></Base>
);
export const Settings = (p: P) => (
  <Base {...p}><circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 0 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3h0a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5h0a1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8v0a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z" /></Base>
);
