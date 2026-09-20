# Disposable security-review benchmark

This directory compares configured local models through the existing
`local_agent_orchestrator.services.security.run_security_review` interface. It
does not change production routing, model configuration, or AI-Assistant.

The five temporary Git fixtures cover command injection, path traversal, secret
exposure, a combined shell/path boundary, and a clean control. Each fixture has
an expected category set. The runner reports detected categories, misses, false
positives, finding titles, errors, and wall-clock latency per model/case.

Run the harness from the repository root:

```sh
uv run python -m benchmarks.security_review.runner \
  --models gpt_oss,qwen_general,devstral,bonsai2 \
  --output /tmp/security-review-benchmark.json
```

Limit a run while checking one model or one case:

```sh
uv run python -m benchmarks.security_review.runner \
  --models qwen_general \
  --cases command_injection,clean_control
```

`bonsai2` is a benchmark-only alias. It uses
`~/llama.cpp-bonsai-rocm/build/bin/llama-server` with the local
`~/Bonsai-demo/models/bonsai2-gguf/27B/Ternary-Bonsai-2-27B-PQ2_0.gguf`, full
GPU offload (`-ngl 99`), and Flash Attention (`-fa on`). It does not alter
production model routing. The binary and model must already exist; missing
resources or reviewer errors are recorded per case.

`qwen_general` remains available only as a historical benchmark alias using
its previous model ID. It is removed from active routing; omit it when testing
the current fleet.

Model startup/downloads can be expensive. Use only models available on the
machine; a missing model or server failure is recorded as an error with latency
instead of being treated as a detection.

Run the disposable harness tests with:

```sh
uv run pytest benchmarks/security_review/test_benchmark.py -q
```

Delete this directory and any JSON output when the comparison is no longer
needed.
