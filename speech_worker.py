"""Standalone optional speech entry point, intentionally without Qt or hooks."""
import os

# Avoid oversized BLAS/OpenMP thread stacks on high-core-count CPUs. These
# settings affect this worker only; recording and decoding have separate threads.
for name in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ[name] = "2"
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"

if __name__ == "__main__":
    from core.speech_service import serve
    raise SystemExit(serve())
