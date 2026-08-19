# Application Boundaries

## Purpose

Digital Twin Runtime Suite remains one Kit extension, `msp.dtrs`. Its code is
split by ownership so a new feature cannot turn the extension entry point into
an application god object.

The active dependency direction is:

```text
extension.py -> ui/* and workflows/* -> app/*
```

The `app/*` layer must not depend on Kit extension, OmniUI, or window code.

## Ownership

### `extension.py`

The extension is the Kit lifecycle and composition root. It owns:

- `omni.ext.IExt` startup and shutdown;
- construction and wiring of the RuntimeController, workflows, and window;
- native Kit window title, docking, and auxiliary-window integration;
- short callback adapters only.

It does not own feature workflows, acceptance state, renderer/cache logic, or
large UI builders.

### `ui/*`

Focused UI modules own OmniUI construction and transient display state:

- frames, tabs, labels, buttons, and models;
- presentation of read-only runtime snapshots;
- collecting UI values and forwarding user intent to a workflow.

They do not own task lifecycles, acceptance state machines, cache/runtime
operations, or controller-private-state inspection.

### `workflows/*`

Focused workflow modules own application-boundary sequencing:

- async task creation, cancellation, and supersession;
- guided manual acceptance and status/progress forwarding;
- orchestration of controller calls for one coherent user action.

They do not recreate domain behavior that already belongs to `app/*`.

### `app/*`

Existing application owners retain runtime/domain responsibility, including
Streamlines snapshot playback, Flow, X-Ray, telemetry, cache validation, and
visualization transitions. Public snapshots and focused query APIs are the only
information exposed upward when a workflow needs evidence.

## Controller Access

Extension and UI/workflow code must not read `RuntimeController` private
attributes. If a caller needs evidence, expose the smallest public snapshot or
query API from the runtime owner. Do not expose a broad mutable state object
merely to avoid adding a focused query.

## Module Shape

Split on a distinct reason to change, not on a line-count target. Do not add a
monolithic `ui.py`, `workflow.py`, or application mega-facade. A module
should state its responsibility in a one-line docstring and make its task,
state, and teardown ownership explicit.

## Review Rule

Before adding substantial code to `extension.py`, explain why it belongs to
Kit lifecycle/composition rather than a focused `ui/*`, `workflows/*`, or
`app/*` owner.
