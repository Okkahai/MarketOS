import type { Metadata } from "next";
import { Nav } from "@/components/Nav";
import "./globals.css";

export const metadata: Metadata = {
  title: "MarketOS",
  description: "AI market research and paper trading lab. Simulation only.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <div className="shell">
          <Nav />
          <main className="main">{children}</main>
        </div>
        <footer className="footer">
          Simulated portfolio only. No real orders are placed and nothing here is investment
          advice.
        </footer>
      </body>
    </html>
  );
}
