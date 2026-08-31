<!--
Appended to the system prompt every time `compose` calls an LLM -- its keyword/signal
extraction call (which narrows the candidate catalog before planning), its planning call,
and its result-naming call. Empty by default. Add negative constraints here, e.g.:

- Don't generate a brand-new block if any existing block is even a loose partial match --
  prefer mutate over generate whenever there's something to adapt.
- Don't reorder pinned (--use/--generate) slots relative to each other.
- Keep result names free of superlatives ("best", "ultimate", "amazing").
-->
- When the request states a specific number of entries (e.g. "3 projects"), the retrieval
  step already narrows the candidate search to roughly that many blocks (via PROJECT_COUNT)
  before the plan is built. The planning call is still the one responsible for the actual
  count: it must assemble exactly that many final use/mutate/generate steps, no more and no
  fewer -- narrowing the candidates isn't enough on its own.
- When you get a role instead of a request, treat it as "We need a <role> for our project".
- Don't create overviews, summaries, tables of content. Only create the entries of the same level as the typical block is. The blocks folder is single-level library.