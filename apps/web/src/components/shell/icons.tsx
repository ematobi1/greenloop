// Inline line icons for the rail. Decorative: every link carries its section name as text.
const PATHS: Record<string, string> = {
  chat: "M4 5h16v10H9l-5 4z",
  memory: "M12 3a6 6 0 0 0-6 6c0 2 1 3 1 5v3h10v-3c0-2 1-3 1-5a6 6 0 0 0-6-6zM9 20h6",
  plans: "M5 4h14v16H5zM8 8h8M8 12h8M8 16h5",
  approvals: "M12 3l7 3v5c0 5-3 8-7 10c-4-2-7-5-7-10V6zM9 12l2 2l4-4",
  agents: "M8 9a4 4 0 1 0 8 0a4 4 0 1 0-8 0M4 20c1-4 4-6 8-6s7 2 8 6",
  workflows: "M5 5h5v5H5zM14 14h5v5h-5zM10 7h4a3 3 0 0 1 3 3v4",
  audit: "M6 3h9l3 3v15H6zM9 10h6M9 14h6M9 18h4",
  settings: "M12 8a4 4 0 1 0 0 8a4 4 0 1 0 0-8M12 2v3M12 19v3M2 12h3M19 12h3M5 5l2 2M17 17l2 2M5 19l2-2M17 7l2-2",
};

export function SectionIcon({ slug }: { slug: string }) {
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <path d={PATHS[slug] ?? PATHS.chat} fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
