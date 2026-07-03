# ADR 004: Environment Baseline

## Status

Accepted

## Context

Different Python versions introduce subtle incompatibilities in libraries like `usd-core`, `pandas`, or `numpy`. To ensure the "NVIDIA Showreel Standard" is maintainable, we must lock the Python version across the estate.

## Decision

We anchor all Case 03 environments on a specific Python baseline:

### 1. Python Version

* **Baseline**: **Python 3.11.15**.
* **Rationale**: This version keeps Case 03 aligned with the Python 3.11.x baseline used by Houdini 21 and the CY2025 VFX Reference Platform, while avoiding Python 3.10 end-of-life risk. Omniverse Kit remains free to use its own embedded interpreter.

### 2. Base Configuration

* **Package Manager**: `conda` (Miniconda/Anaconda) for environment creation.
* **Installer**: `pip` (latest) for package installation within the activated conda environment.

## Consequences

* **Positive**: Aligns the Case 03 repository baseline, local tooling, and Houdini-side Python expectations around a maintained Python version.
* **Negative**: Requires rebuilding or upgrading environments that were created on Python 3.10 or older.
