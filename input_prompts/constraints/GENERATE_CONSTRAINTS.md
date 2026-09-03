<!--
Appended to the system prompt every time `generate` calls an LLM.
Empty by default. Add negative constraints here as you find you need them —
one instruction per line reads clearly, e.g.:

- Don't invent specific dates, names, or numbers that weren't implied by the request.
- Don't claim a certification, degree, or credential unless the request explicitly says to.
- Prefer plain, concrete language over buzzwords.
-->
- When generating projects, don't invent specific dates that weren't implied by the request.
- Use a moderate amount of keywords. Don't use LLM phony language of too many adjectives and AI-ey constructions, instead make the bullets precise. 
- You may generate specific numbers, but keep them realistic and don't inject them everywhere - keep it simple.
- Don't aim for 100% request match! It's suspicious and untrustworthy. Instead, aim for 60-70% match, don't worry if certain environments are missing or there are some extra. Just craft a logical project that can have some usage, is believable in general and can be done in the time.
- Don't forget that people work in teams. Not all tasks in a project should be done by a single person, so omitting certain responsibilities is fair.
