// TypeScript port of src/models/block_fields.py's parse_block_body — same regexes and
// label-alias table, so a block's body parses into the same shape client-side.
const FIELD_RE = /^\*\*(.+?):\*\*\s*(.*)$/;
const BULLET_RE = /^-\s+(.+)$/;
const HEADING_RE = /^#{1,6}\s*\S/;

const LABEL_ALIASES: Record<string, "time_period" | "role"> = {
  period: "time_period",
  "time period": "time_period",
  role: "role",
  "project roles": "role",
  author: "role",
};

export interface EditFormFields {
  name: string;
  description: string;
  role: string | null;
  timePeriod: string | null;
  environment: string[];
  otherFields: Record<string, string[] | string>;
}

function fieldText(value: string[] | string): string {
  return typeof value === "string" ? value : value.join(" ");
}

// Mirrors core/naming.py's slugify — lowercase, non-alphanumeric runs collapsed to "_".
function slugify(text: string): string {
  const raw = text
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "");
  return raw || "item";
}

// Reads the heading (if the first non-blank line is one) and the description paragraph that
// follows it, stopping at the first field line. Shared by parseBlockBody (structured parse) and
// splitBlockBody (raw-text split for the edit UI) so both agree on where metadata starts.
function extractHeadingAndDescription(lines: string[]): { name: string; description: string; nextIndex: number } {
  let i = 0;
  while (i < lines.length && !lines[i].trim()) i += 1;

  let name = "";
  if (i < lines.length && lines[i].trim().startsWith("#")) {
    name = lines[i].trim().replace(/^#+/, "").trim();
    i += 1;
  }

  const descriptionLines: string[] = [];
  while (i < lines.length) {
    const stripped = lines[i].trim();
    if (!stripped) {
      i += 1;
      continue;
    }
    if (FIELD_RE.test(stripped)) break;
    descriptionLines.push(stripped);
    i += 1;
  }

  return { name, description: descriptionLines.join(" "), nextIndex: i };
}

export function splitBlockBody(body: string): { name: string; description: string; metadata: string } {
  const lines = body.split(/\r?\n/);
  const { name, description, nextIndex } = extractHeadingAndDescription(lines);
  return { name, description, metadata: lines.slice(nextIndex).join("\n").trim() };
}

export function parseBlockBody(body: string): EditFormFields {
  const lines = body.split(/\r?\n/);
  const { name, description, nextIndex } = extractHeadingAndDescription(lines);
  let i = nextIndex;

  let role: string | null = null;
  let timePeriod: string | null = null;
  const environment: string[] = [];
  const otherFields: Record<string, string[] | string> = {};

  let currentLabel: string | null = null;
  let currentInlineValue = "";
  let currentBullets: string[] = [];

  function flush(): void {
    if (currentLabel === null) return;
    const value: string[] | string = currentBullets.length ? currentBullets : currentInlineValue.trim();
    const labelLower = currentLabel.trim().toLowerCase();
    const alias = LABEL_ALIASES[labelLower];
    if (alias === "role") {
      role = fieldText(value);
    } else if (alias === "time_period") {
      timePeriod = fieldText(value);
    } else if (labelLower === "environment") {
      environment.push(
        ...fieldText(value)
          .split(",")
          .map((entry) => entry.trim())
          .filter(Boolean)
      );
    } else {
      otherFields[slugify(currentLabel)] = value;
    }
  }

  while (i < lines.length) {
    const stripped = lines[i].trim();
    i += 1;
    if (!stripped) continue;
    const fieldMatch = stripped.match(FIELD_RE);
    if (fieldMatch) {
      flush();
      currentLabel = fieldMatch[1];
      currentInlineValue = fieldMatch[2];
      currentBullets = [];
      continue;
    }
    const bulletMatch = stripped.match(BULLET_RE);
    if (bulletMatch && currentLabel !== null) {
      currentBullets.push(bulletMatch[1].trim());
      continue;
    }
    if (currentLabel !== null && currentBullets.length === 0) {
      currentInlineValue = `${currentInlineValue} ${stripped}`.trim();
    }
  }
  flush();

  return { name, description, role, timePeriod, environment, otherFields };
}

export function titleCaseLabel(slug: string): string {
  return slug
    .split("_")
    .filter(Boolean)
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

export function reassembleBlockBody(fields: EditFormFields): string {
  const lines: string[] = [`# ${fields.name}`.trimEnd()];

  if (fields.description) lines.push("", fields.description);
  if (fields.role) lines.push("", `**Role:** ${fields.role}`);
  if (fields.timePeriod) lines.push("", `**Period:** ${fields.timePeriod}`);
  if (fields.environment.length > 0) lines.push("", `**Environment:** ${fields.environment.join(", ")}`);

  for (const [key, value] of Object.entries(fields.otherFields)) {
    const label = titleCaseLabel(key);
    if (Array.isArray(value)) {
      if (value.length === 0) continue;
      lines.push("", `**${label}:**`, ...value.map((item) => `- ${item}`));
    } else if (value) {
      lines.push("", `**${label}:** ${value}`);
    }
  }

  return lines.join("\n");
}

export function looksLikeWholeBlock(text: string): boolean {
  const trimmed = text.trim();
  if (!trimmed) return false;
  const lines = trimmed.split(/\r?\n/).map((line) => line.trim());
  const startsWithHeading = HEADING_RE.test(lines[0]);
  const hasFieldLine = lines.some((line) => FIELD_RE.test(line));
  return startsWithHeading || hasFieldLine;
}
