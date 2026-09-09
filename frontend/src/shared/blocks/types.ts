import type { BlockOrigin } from "@/shared/icons/OriginIcon";

export type BlockViewMode = "list" | "grid-2" | "grid-3";

export interface LibraryBlockRecord {
  id: string;
  name: string;
  created_at: string | null;
  created_by: string;
  environment: string[];
  preserved: boolean;
}

export function originFromCreatedBy(createdBy: string): BlockOrigin {
  if (createdBy === "dissected" || createdBy === "mutated" || createdBy === "generated") {
    return createdBy;
  }
  return "manual";
}

const FIELD_RE = /^\*\*(.+?):\*\*\s*(.*)$/;
const BULLET_RE = /^-\s+(.+)$/;

// Display-only extraction of the "**Environment:**" field from a block's body —
// not a full port of block_fields.py's parser (that lands with the Edit dialog).
export function extractEnvironment(body: string): string[] {
  const lines = body.split("\n");
  let capturing = false;
  let inline = "";
  const bullets: string[] = [];

  for (const raw of lines) {
    const line = raw.trim();
    if (!line) continue;
    const fieldMatch = line.match(FIELD_RE);
    if (fieldMatch) {
      if (capturing) break;
      if (fieldMatch[1].trim().toLowerCase() === "environment") {
        capturing = true;
        inline = fieldMatch[2];
      }
      continue;
    }
    if (!capturing) continue;
    const bulletMatch = line.match(BULLET_RE);
    if (bulletMatch) {
      bullets.push(bulletMatch[1].trim());
    } else {
      inline = `${inline} ${line}`.trim();
    }
  }

  const text = bullets.length ? bullets.join(" ") : inline;
  return text
    .split(",")
    .map((entry) => entry.trim())
    .filter(Boolean);
}
