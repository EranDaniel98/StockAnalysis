import type { ReactNode } from "react";

export function PageHeader({
  title,
  description,
  actions,
}: {
  title: string;
  description?: string;
  actions?: ReactNode;
}) {
  return (
    <div className="border-border mb-6 flex items-start justify-between gap-4 border-b pb-3">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">{title}</h1>
        {description ? (
          <p className="text-muted-foreground mt-1 text-xs">{description}</p>
        ) : null}
      </div>
      {actions ? <div className="flex gap-2">{actions}</div> : null}
    </div>
  );
}
