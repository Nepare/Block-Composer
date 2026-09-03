<!--
Appended to the system prompt every time `naming` calls an LLM to label a variant
or a compose result. Empty by default. Add negative constraints here, e.g.:

- Never use words like "new", "updated", or "final" as a label -- they don't age well.
- Avoid single-letter or purely numeric labels.
-->
- Never use words like "new", "updated", or "final" as a label - they don't age well.
- Avoid single-letter or purely numeric labels.
- Try to limit the variant naming appendix to 5 words or less.
- Don't lazily name mutated variants with _mut_variant appendix, add actual semantically informative suffixes. "_mut_variant" suffix is a fallback that applies when you fail to generate a coherent suffix.
