# Disposable coding-model benchmark

This benchmark compares Devstral and benchmark-only Bonsai 2 through the
existing `execute_coding_task()` semantic-edit path, followed by the existing
baseline/post-change verification comparison. It uses three temporary Git
repositories and identical deterministic repository evidence for both models:

- `normalize_source_name`: grounded existing-file replacement plus tests
- `reject_url_credentials`: security-focused existing-file replacement
- `create_safe_identifier`: legitimate new-file creation plus tests

These cases target historical failure classes including invalid schemas,
ungrounded paths, exact no-match/no-op edits, and verification failures. The
benchmark reports task success, schema-valid operation generation, applied
edits, failure classes, verification, changed-path scope, unnecessary changes,
and latency.

Run it with:

```sh
uv run python -m benchmarks.coding.runner \
  --models devstral,bonsai2 \
  --output /tmp/coding-model-benchmark.json
```

`bonsai2` uses the supplied ROCm binary/local GGUF with `-ngl 99` and `-fa on`
only inside this benchmark. Production routing and AI-Assistant are unchanged.

Run focused tests with:

```sh
uv run pytest benchmarks/coding/test_benchmark.py -q
```
