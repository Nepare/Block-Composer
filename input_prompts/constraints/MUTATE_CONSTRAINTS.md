<!--
Appended to the system prompt every time `mutate` calls an LLM. Empty by default.
Add negative constraints here as you find you need them, e.g.:

- Don't change the Time period field unless the change request explicitly asks to.
- Don't invent new Environment/tech-stack entries that weren't in the original or implied
  by the change request.
- Keep the tone consistent with the original entry unless asked to change it.
-->
- You may invent new environment or responsibilities entries that weren't in the original or implied by the change request, but only if it's only logical.
- Try keeping the overall structure the same. We are mutating an existing project, not generating something from scratch, most responsibilities, most of the description and most of the environment should stay the same.
- Keep the product description that the users see largely unchanged. Your mutating scope is mostly over responsibilities and environment.
- Try to keep the responsibilities, project name, project description and environment in sync. If you mutate some responsibility to include a new technology and remove an old one, make sure it's changed in the environment too, and make sure project description aligns with it.
