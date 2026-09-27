import Link from "next/link";
import styles from "./page.module.css";
import { SECTIONS } from "./sections";

export default function Home() {
  return (
    <section className={styles.home} aria-labelledby="home-title">
      <h1 id="home-title" className={styles.title}>
        GreenLoop
      </h1>
      <p className={styles.lead}>
        Your secure, adaptive second brain. You stay in control of every consequential action.
      </p>
      <ul className={styles.grid}>
        {SECTIONS.map((section) => (
          <li key={section.slug}>
            <Link href={`/${section.slug}`} className={styles.card}>
              <h2 className={styles.cardTitle}>{section.title}</h2>
              <p>{section.summary}</p>
              <p className={styles.phase}>Phase {section.phase}</p>
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}
