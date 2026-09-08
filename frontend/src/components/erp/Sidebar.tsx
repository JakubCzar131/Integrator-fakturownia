import { NavLink } from "react-router-dom";
import { useAuth } from "../../lib/auth";

const ITEM_GROUPS: { group: string; items: { to: string; icon: string; label: string; adminOnly?: boolean }[] }[] = [
  {
    group: "Przegląd",
    items: [
      { to: "/", icon: "▦", label: "Dashboard" },
    ],
  },
  {
    group: "Sprzedaż",
    items: [
      { to: "/invoices", icon: "▤", label: "Faktury" },
      { to: "/invoice-positions", icon: "≡", label: "Pozycje faktur" },
      { to: "/clients", icon: "◉", label: "Klienci" },
    ],
  },
  {
    group: "Produkty",
    items: [
      { to: "/products", icon: "▣", label: "Produkty" },
      { to: "/mappings", icon: "⇄", label: "Mapowania produktów" },
    ],
  },
  {
    group: "Magazyn",
    items: [
      { to: "/warehouses", icon: "⌂", label: "Magazyny" },
      { to: "/stock-balances", icon: "▥", label: "Stany magazynowe" },
      { to: "/stock-ledger", icon: "↕", label: "Ruchy magazynowe" },
    ],
  },
  {
    group: "Kontrola",
    items: [
      { to: "/validation", icon: "⚠", label: "Walidacje" },
      { to: "/reports", icon: "▧", label: "Raporty" },
      { to: "/sync", icon: "⟳", label: "Synchronizacja" },
    ],
  },
  {
    group: "System",
    items: [
      { to: "/settings", icon: "⚙", label: "Ustawienia" },
      { to: "/users", icon: "☰", label: "Użytkownicy i role", adminOnly: true },
      { to: "/audit", icon: "✎", label: "Audyt" },
    ],
  },
];

export function Sidebar() {
  const { isAdmin } = useAuth();
  return (
    <nav className="sidebar">
      {ITEM_GROUPS.map((group) => (
        <div key={group.group}>
          <div className="sidebar__group">{group.group}</div>
          {group.items
            .filter((item) => !item.adminOnly || isAdmin)
            .map((item) => (
              <NavLink key={item.to} to={item.to} end={item.to === "/"}>
                <span aria-hidden>{item.icon}</span>
                <span className="label">{item.label}</span>
              </NavLink>
            ))}
        </div>
      ))}
    </nav>
  );
}
