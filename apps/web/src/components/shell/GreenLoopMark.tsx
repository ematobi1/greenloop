// GreenLoop's own mark: a loop around a leaf-like core. Decorative; the name is text.
export default function GreenLoopMark({ size = 32 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden="true" focusable="false">
      <circle cx="16" cy="16" r="13" fill="none" stroke="var(--hud-accent)" strokeWidth="2" opacity="0.9" />
      <circle cx="16" cy="16" r="8.5" fill="none" stroke="var(--hud-accent-2)" strokeWidth="1.5" strokeDasharray="4 3" />
      <path d="M16 9c3.5 2.5 3.5 11.5 0 14c-3.5-2.5-3.5-11.5 0-14z" fill="var(--hud-ok)" opacity="0.85" />
    </svg>
  );
}
