<!--
Appended to the system prompt every time `compose` calls an LLM -- both its planning
call and its result-naming call. Empty by default. Add negative constraints here, e.g.:

- Don't generate a brand-new block if any existing block is even a loose partial match --
  prefer mutate over generate whenever there's something to adapt.
- Don't reorder pinned (--use/--generate) slots relative to each other.
- Keep result names free of superlatives ("best", "ultimate", "amazing").
-->
- When a specific number requirement is present in the request (for example, creating a list of N projects), exactly N projects should be created.
- Don't create overviews, summaries, tables of content. Only create the entries of the same level as the typical block is. The blocks folder is single-level library.