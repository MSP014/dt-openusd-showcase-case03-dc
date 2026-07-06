# Guideline 01: Scale and Axis Setup

## 1. Current Standard

Case 03 authored USD assets should use Houdini-native project units:

- **Meters Per Unit:** `1.0`
- **Up Axis:** `Y`

This keeps Houdini procedural authoring predictable and makes exported layers
self-describing for downstream OpenUSD and Omniverse tools.

## 2. Omniverse Behavior

OpenUSD layers carry `metersPerUnit` and `upAxis` metadata. When those values
are authored correctly, Omniverse and other compliant consumers can resolve the
asset scale and orientation without manual rotation or scale fixes.

If a runtime scene uses a different world convention, the conversion must be
explicit and documented. It must not be hidden as a local workstation transform.

## 3. Houdini Export Rule

Use a `Configure Layer` LOP before writing USD:

1. Set **Up Axis** to `Y`.
2. Set **Meters Per Unit** to `1.0`.
3. Confirm the exported root layer contains the expected metadata.

Place this rule before the final `usd_rop`, `usdrender_rop`, or Component
Builder output layer. The exported USD should be self-describing; importing it
into Omniverse must not require a manual rotation, scale correction, or
workstation-only transform.

## 4. External Asset Ingest

Purchased or library assets may use different conventions, especially Z-up or
centimeter scale.

External assets should be inspected before they enter the Case 03 package. If
they differ, either bake the correction into the asset or apply a documented
root `Xform` correction as part of ingest.

## Definition of Done

- Root USD layers expose `metersPerUnit = 1.0` and `upAxis = "Y"` unless an
  explicit ingest exception exists.
- Omniverse loading requires no manual rotation or scale correction.
- Any non-native external asset has a documented conversion.
