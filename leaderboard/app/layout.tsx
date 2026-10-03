import type { Metadata } from "next";
import { Archivo_Black, JetBrains_Mono, Space_Grotesk } from "next/font/google";
import "./globals.css";

// the dashboard's poster look; the rest of the site keeps the system font
const display = Archivo_Black({ weight: "400", subsets: ["latin"], variable: "--f-display" });
const mono = JetBrains_Mono({ subsets: ["latin"], variable: "--f-mono" });
const grotesk = Space_Grotesk({ subsets: ["latin"], variable: "--f-body" });

export const metadata: Metadata = {
  title: "Token Leaderboard",
  description: "Who is getting the most out of Claude Code, and leaking the least.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${display.variable} ${mono.variable} ${grotesk.variable}`}>
      <body>{children}</body>
    </html>
  );
}
