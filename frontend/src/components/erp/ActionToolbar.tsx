import type { ReactNode } from "react";

export function ActionToolbar({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="action-toolbar">
      <span className="action-toolbar__title">{title}</span>
      {children}
    </div>
  );
}
