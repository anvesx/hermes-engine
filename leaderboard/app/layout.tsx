import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Token Leaderboard",
  description: "Who is getting the most out of Claude Code, and leaking the least.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
