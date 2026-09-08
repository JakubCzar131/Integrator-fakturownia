import { useState, type ReactNode } from "react";

export interface TabDef {
  key: string;
  label: string;
  content: ReactNode;
}

export function DetailTabs({ tabs, initial }: { tabs: TabDef[]; initial?: string }) {
  const [active, setActive] = useState(initial ?? tabs[0]?.key);
  const current = tabs.find((t) => t.key === active) ?? tabs[0];
  return (
    <div>
      <div className="tabs">
        {tabs.map((tab) => (
          <button
            key={tab.key}
            className={tab.key === active ? "active" : ""}
            onClick={() => setActive(tab.key)}
          >
            {tab.label}
          </button>
        ))}
      </div>
      <div>{current?.content}</div>
    </div>
  );
}
