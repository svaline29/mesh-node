"""Offline benchmarking harness.

Deterministic, seed-reproducible, round-based simulation that reuses the exact
``routing``, ``attacks`` and ``detectors`` modules from the live system (no UDP).
This is the measurement artifact: it runs trials with known ground truth and
emits CSVs and plots.
"""
