import Link from "next/link";

// Pages arrive with the phase that produces their data. Until then they are
// listed but not linked, so the UI never shows an empty page dressed up as real.
const NAV: { label: string; href?: string; phase?: number }[] = [
  { label: "System status", href: "/" },
  { label: "Overview", href: "/overview" },
  { label: "News feed", href: "/news" },
  { label: "Events", href: "/events" },
  { label: "Market", href: "/market" },
  { label: "Portfolio", href: "/portfolio" },
  { label: "Trades", href: "/trades" },
  { label: "AI journal", href: "/journal" },
  { label: "Analytics", href: "/analytics" },
];

export function Nav() {
  return (
    <nav className="nav" aria-label="Main">
      <div className="brand">
        MarketOS
        <span className="badge badge-paper">PAPER</span>
      </div>
      <ul>
        {NAV.map((item) => (
          <li key={item.label}>
            {item.href ? (
              <Link href={item.href}>{item.label}</Link>
            ) : (
              <span className="nav-disabled" title={`Arrives in Phase ${item.phase}`}>
                {item.label}
                <small>Phase {item.phase}</small>
              </span>
            )}
          </li>
        ))}
      </ul>
    </nav>
  );
}
