<!--
Appended to the system prompt every time `compose` calls an LLM -- its planning call
and its result-naming call (its target-count detection call is a bare, constraints-free
mechanical classifier and never sees this file). Empty by default. Add negative
constraints here, e.g.:

- Don't generate a brand-new block if any existing block is even a loose partial match --
  prefer mutate over generate whenever there's something to adapt.
- Don't reorder pinned (--use/--generate) slots relative to each other.
- Keep result names free of superlatives ("best", "ultimate", "amazing").
-->
- The keywords that narrow down the projects that match the request are responsibility of another model, but that model can hallucinate and make mistakes, so you are the one who makes the final decision who to pick out of the narrowed down list.
- If you are supplied with a request and it describes a role, treat it as "We need a <role> for our project".
- When you are a planner, when generating projects, don't create overviews, summaries, tables of content. Only create the entries of the same level as the typical block is. The blocks folder is single-level library.
