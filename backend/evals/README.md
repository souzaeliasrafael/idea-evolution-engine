# Local agent specialization experiments

These evaluations compare agent configurations without mutating a project or
depending on a provider-hosted eval product.

The first experiment performs a blind A/B comparison between the active Critic
prompt and a financial-systems specialist prompt. It reuses distinct historical
Critic inputs, runs both prompts against the configured Critic model, randomizes
the A/B positions, and asks the configured Judge model to score both outputs on
a fixed 100-point rubric. Tokens, latency, and estimated cost are recorded.

Run it from the backend directory:

```powershell
.\.venv\Scripts\python.exe tools\run_specialization_experiment.py `
  --project-id <PROJECT_UUID> `
  --cases 3
```

Reports are written to `work/specialization-experiments/`. Generated criticisms
are not inserted into `agent_runs` or any project table.

This is a prompt-specialization pilot, not a fine-tuning claim. Before promoting
a candidate prompt or model, repeat the evaluation on more projects and add
human or domain-expert review.
