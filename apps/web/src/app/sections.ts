export type Section = {
  slug: string;
  title: string;
  summary: string;
  phase: number;
};

export const SECTIONS: readonly Section[] = [
  {
    slug: "chat",
    title: "Chat",
    summary: "Talk to GreenLoop. Replies draw on your memory and can draft plans.",
    phase: 2,
  },
  {
    slug: "memory",
    title: "Memory",
    summary: "Browse, correct and delete what GreenLoop remembers, with full history.",
    phase: 2,
  },
  {
    slug: "plans",
    title: "Plans",
    summary: "Review the plans GreenLoop drafted for you. Nothing runs until you approve it.",
    phase: 2,
  },
  {
    slug: "approvals",
    title: "Approvals",
    summary: "Review and approve actions that write, send, delete or spend.",
    phase: 3,
  },
  {
    slug: "agents",
    title: "Agents",
    summary: "See the registered agents and what each one is allowed to do.",
    phase: 4,
  },
  {
    slug: "workflows",
    title: "Workflows",
    summary: "Follow multi-step plans as they run, pause and recover.",
    phase: 4,
  },
  {
    slug: "audit",
    title: "Audit",
    summary: "Every consequential decision and action, in order.",
    phase: 3,
  },
  {
    slug: "settings",
    title: "Settings",
    summary: "Account, voice and connected tools.",
    phase: 5,
  },
];

export function sectionBySlug(slug: string): Section {
  const section = SECTIONS.find((candidate) => candidate.slug === slug);
  if (!section) {
    throw new Error(`Unknown section: ${slug}`);
  }
  return section;
}
