# ADR 002: QA & Security Protocols

## Status

Accepted

## Context

"Works on my machine" is unacceptable for a Digital Twin that claims to be an engineering tool. We need to respect the integrity of the Data Center simulation code.

## Decision

We enforce a strict "Shift Left" strategy using `pre-commit` hooks:

### 1. Guardrails (Pre-commit)

* **Linting:** `black` (Formatting), `flake8` (Logic), `isort` (Imports).
* **Security:**
  * `bandit`: Scans for common security issues (e.g., hardcoded credentials in connection scripts).
  * `pip-audit`: Checks `requirements.txt` for known vulnerabilities.
* **Hygiene:** `check-added-large-files` (Max 10MB) to prevent repo bloating.

### 2. Testing

* `pytest` must pass locally before push.
* **Data Validation:** Tests should verify that generated JSON data matches the expected schema for the MDL sensors.

## Consequences

* **Positive:** Higher code quality, reduced security risk.
* **Negative:** Initial setup friction; `pip-audit` requires maintenance of `requirements.txt`.
