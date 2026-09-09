export type DisplayMode = { type: "fresh" } | { type: "history"; resultId: string };

export interface BlockSelection {
  selectedBlockIds: string[];
}
