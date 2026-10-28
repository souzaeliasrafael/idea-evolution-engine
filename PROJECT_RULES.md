# PROJECT RULES

1. Agents never call LLM APIs directly.

2. Every LLM call must use LLMProvider.

3. Every agent output must use a typed schema.

4. All important enums must be explicit.

5. Every AgentRun must be persisted.

6. Idea versions are immutable.

7. Prompts must be versioned.

8. Never use infinite agent loops.

9. Every run must respect a maximum round limit.

10. Every run must respect a cost limit when configured.

11. Facts, assumptions and inferences must not be silently mixed.

12. Evidence must remain traceable to its source.

13. New features must not break existing tests.

14. Do not rewrite unrelated files.

15. Prefer small, composable components.

16. Domain logic must remain independent of specific LLM vendors.

17. Every schema change must use a migration.

18. Secrets must never be committed.

19. Use environment variables for API credentials.

20. A task is only complete when relevant tests pass.

