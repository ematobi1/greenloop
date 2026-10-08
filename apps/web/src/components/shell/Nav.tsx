"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { SECTIONS } from "@/app/sections";

import { SectionIcon } from "./icons";

function isCurrent(pathname: string, slug: string): boolean {
  return pathname === `/${slug}` || pathname.startsWith(`/${slug}/`);
}

export function Tabs() {
  const pathname = usePathname();
  return (
    <nav aria-label="Main" className="hud-tabs">
      <ul className="hud-tabs__list">
        {SECTIONS.map((section) => (
          <li key={section.slug}>
            <Link
              href={`/${section.slug}`}
              className="hud-tabs__link"
              aria-current={isCurrent(pathname, section.slug) ? "page" : undefined}
            >
              {section.title}
            </Link>
          </li>
        ))}
      </ul>
    </nav>
  );
}

export function Rail() {
  const pathname = usePathname();
  return (
    <nav aria-label="Sections" className="hud-rail">
      <ul className="hud-rail__list">
        {SECTIONS.map((section) => (
          <li key={section.slug}>
            <Link
              href={`/${section.slug}`}
              className="hud-rail__link"
              aria-current={isCurrent(pathname, section.slug) ? "page" : undefined}
              title={section.title}
            >
              <SectionIcon slug={section.slug} />
              <span className="visually-hidden">{section.title}</span>
            </Link>
          </li>
        ))}
      </ul>
    </nav>
  );
}
