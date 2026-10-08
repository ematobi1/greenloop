import type { Metadata } from "next";
import localFont from "next/font/local";

import "./globals.css";

// Bundled Orbitron (SIL OFL, src/fonts/orbitron/OFL.txt) for headings, numbers and labels.
const orbitron = localFont({
  src: [
    { path: "../fonts/orbitron/orbitron-latin-500-normal.woff2", weight: "500", style: "normal" },
    { path: "../fonts/orbitron/orbitron-latin-700-normal.woff2", weight: "700", style: "normal" },
  ],
  variable: "--font-orbitron",
  display: "swap",
});

export const metadata: Metadata = {
  title: "GreenLoop",
  description: "Your secure, adaptive second brain.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={orbitron.variable}>
      <body>{children}</body>
    </html>
  );
}
