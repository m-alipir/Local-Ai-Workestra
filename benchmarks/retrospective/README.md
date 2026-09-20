# Disposable retrospective benchmark

This harness compares the existing `NemotronRetrospective.run()` interface on
identical authoritative context built from a stored run. The default workload
is `runs-ai-assistant/7120a13568ea`, where the task passed on Qwen attempt 1 and
the scheduler test failure was classified as pre-existing baseline debt.

Run Nemotron and Bonsai 2:

```sh
uv run python -m benchmarks.retrospective.runner \
  --run-dir runs-ai-assistant/7120a13568ea \
  --models nemotron,bonsai2 \
  --output /tmp/retrospective-benchmark.json
```

`bonsai2` is benchmark-only. It uses the supplied ROCm binary and local GGUF
with `-ngl 99`, `-fa on`, and the adapter's `xhigh` reasoning mapping. It does
not alter production routing. The report contains both raw model text and
deterministic checks for grounding, unsupported claims, actionable suggestions,
malformed sections, and latency.

`nemotron` is retained only as a historical benchmark alias using its previous
model ID. It is no longer an active configured route; the production
retrospective route uses Bonsai 2.

Run tests with:

```sh
uv run pytest benchmarks/retrospective/test_benchmark.py -q
```
