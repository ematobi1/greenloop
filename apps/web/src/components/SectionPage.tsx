import { sectionBySlug } from "@/app/sections";

export default function SectionPage({ slug }: { slug: string }) {
  const section = sectionBySlug(slug);
  return (
    <article className="section">
      <h1 className="section__title">{section.title}</h1>
      <p className="section__summary">{section.summary}</p>
      <p className="section__status" role="status">
        Not built yet. Arrives in roadmap phase {section.phase}.
      </p>
    </article>
  );
}
