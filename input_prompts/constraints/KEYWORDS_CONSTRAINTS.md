<!--
Appended to the system prompt every time `compose` calls an LLM to extract search
keywords from a request (before the candidate block catalog is narrowed for planning).
Empty by default. Add negative constraints here, e.g.:

- Don't invent keywords that aren't implied by the request -- leave a category blank
  rather than guessing.
- Prefer concrete tool/technology names over generic category words.
-->
- For the ROLE category, the maximum length of a point (a singular role) is maximum of 5 words.
- For the ENVIRONMENT category, the maximum length of a point (a singular tech) is maximum of 5 words. The bracketed subvariants should be separated into distinct points. The "/" separated technologies should be separated into distinct points. Mostly focus on environment, keep each point simple and precise, even if it is one word. Maximize the amount of ENVIRONMENT category points if relevant - this one is the most valuable out of all.
- For the RESPONSIBILITIES category, the maximum length of a point (a singular responsibility) is maximum of 3 words.
- For the DOMAIN category, the maximum length of a point (a singular domain) is maximum of 4 words.
