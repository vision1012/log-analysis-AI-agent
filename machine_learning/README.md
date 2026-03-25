# `machine_learning/` — anomaly ML (optional path)

Training and inference helpers for **anomaly detection** (e.g. isolation forest) on log-derived features. Separate from deterministic RCA; can feed signals upstream.

| File | Purpose |
|------|---------|
| `config.py` | Paths, hyperparameters, feature flags for ML runs. |
| `__init__.py` | Package marker. |

| Subfolder | Purpose |
|-----------|---------|
| `features/` | Feature extraction: embeddings, vectorization, templates. |
| `models/` | `IsolationForest` wrapper, evaluation utilities. |
| `pipelines/` | `train_anomaly.py`, `infer_anomaly.py` batch pipelines. |
| `data/` | **Large datasets** (HDFS traces, etc.) — not all tracked; see `.gitignore`. |
| `artifacts/` | Saved models and run outputs. |

See **`features/README.md`**, **`models/README.md`**, **`pipelines/README.md`** for file-level detail.
