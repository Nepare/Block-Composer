import { looksLikeWholeBlock, parseBlockBody, reassembleBlockBody } from "@/features/library/blockFields";

const SAMPLE_BODY = [
  "# Senior Platform Engineer",
  "",
  "Built and operated the internal deployment platform for a mid-size fintech.",
  "",
  "**Role:** Platform Lead",
  "",
  "**Period:** 03.2022 - present",
  "",
  "**Environment:** Kubernetes, Terraform, AWS",
  "",
  "**Responsibilities:**",
  "- Designed the deployment pipeline",
  "- Mentored two junior engineers",
].join("\n");

test("parse -> reassemble -> parse round trip preserves content", () => {
  const parsed = parseBlockBody(SAMPLE_BODY);

  expect(parsed).toEqual({
    name: "Senior Platform Engineer",
    description: "Built and operated the internal deployment platform for a mid-size fintech.",
    role: "Platform Lead",
    timePeriod: "03.2022 - present",
    environment: ["Kubernetes", "Terraform", "AWS"],
    otherFields: { responsibilities: ["Designed the deployment pipeline", "Mentored two junior engineers"] },
  });

  const reassembled = reassembleBlockBody(parsed);
  const reparsed = parseBlockBody(reassembled);

  expect(reparsed).toEqual(parsed);
});

test("round trip preserves an inline (non-bulleted) other field", () => {
  const body = "# Client Project\nA short summary.\n**Client:** Confidential\n**Environment:** Figma";
  const parsed = parseBlockBody(body);

  expect(parsed.otherFields).toEqual({ client: "Confidential" });

  const reparsed = parseBlockBody(reassembleBlockBody(parsed));
  expect(reparsed).toEqual(parsed);
});

test("recognizes label aliases (period/time period, role/project roles/author)", () => {
  const period = parseBlockBody("# X\n**Time Period:** 2020-2021");
  expect(period.timePeriod).toBe("2020-2021");

  const author = parseBlockBody("# X\n**Author:** Jane Doe");
  expect(author.role).toBe("Jane Doe");

  const projectRoles = parseBlockBody("# X\n**Project Roles:** Tech Lead");
  expect(projectRoles.role).toBe("Tech Lead");
});

test("looksLikeWholeBlock identifies a full block's text", () => {
  expect(looksLikeWholeBlock(SAMPLE_BODY)).toBe(true);
  expect(looksLikeWholeBlock("# Just a heading")).toBe(true);
  expect(looksLikeWholeBlock("Some intro text.\n**Role:** Engineer")).toBe(true);
});

test("looksLikeWholeBlock rejects an ordinary sentence with no heading and no field", () => {
  expect(looksLikeWholeBlock("Please fix the typo in the second bullet.")).toBe(false);
  expect(looksLikeWholeBlock("Kubernetes, Terraform, AWS")).toBe(false);
  expect(looksLikeWholeBlock("")).toBe(false);
});
