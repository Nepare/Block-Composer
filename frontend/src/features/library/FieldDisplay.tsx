import type { ReactNode } from "react";

export function FieldRow({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-1">
      <p className="text-xs font-medium tracking-wide text-muted-foreground uppercase">{label}</p>
      {children}
    </div>
  );
}

export function FieldValue({ value }: { value: string[] | string }) {
  if (Array.isArray(value)) {
    if (value.length === 0) return <p className="text-sm text-muted-foreground">—</p>;
    return (
      <ul className="list-disc space-y-1 pl-4 text-sm text-foreground">
        {value.map((entry, index) => (
          <li key={index}>{entry}</li>
        ))}
      </ul>
    );
  }
  return <p className="text-sm whitespace-pre-wrap text-foreground">{value || "—"}</p>;
}
