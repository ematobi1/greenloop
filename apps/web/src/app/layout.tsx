import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";
import { SECTIONS } from "./sections";

export const metadata: Metadata = {
  title: "GreenLoop",
  description: "Your secure, adaptive second brain.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en">
      <body>
        <header className="site-header">
          <Link href="/" className="site-header__brand">
            GreenLoop
          </Link>
          <nav aria-label="Main" className="site-nav">
            <ul className="site-nav__list">
              {SECTIONS.map((section) => (
                <li key={section.slug}>
                  <Link href={`/${section.slug}`} className="site-nav__link">
                    {section.title}
                  </Link>
                </li>
              ))}
            </ul>
          </nav>
        </header>
        <main className="site-main">{children}</main>
      </body>
    </html>
  );
}
