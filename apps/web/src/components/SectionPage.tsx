import { sectionBySlug } from "@/app/sections";
import { SectionIcon } from "@/components/shell/icons";

// A section that isn't built yet: styled like the HUD, honest about when it arrives.
export default function SectionPage({ slug }: { slug: string }) {
  const section = sectionBySlug(slug);
  return (
    <article className="section hud-panel">
      <p className="hud-label">
        <SectionIcon slug={slug} /> Arrives in Phase {section.phase}
      </p>
      <h1 className="section__title">{section.title}</h1>
      <p className="section__summary">{section.summary}</p>
      <p className="section__status" role="status">
        Not built yet. Arrives in roadmap phase {section.phase}.
      </p>
    </article>
  );
}
