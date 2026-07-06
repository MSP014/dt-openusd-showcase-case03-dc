# Guideline 02: Payloads, References, and LODs

This guideline separates the current staged runtime baseline from the future
large-scale data center target.

Blackwell Monitoring Suite v0.1 only needs to load one configured asset from
the hydrated asset package. Payload-heavy rack composition and LOD switching
become mandatory only when the runtime reaches server, rack, and data hall
scale.

## 1. Current Baseline

- Heavy assets remain under `assets/_external/`.
- Paths must be relative or explicitly configurable.
- LOD variants should stay disabled or deferred until LOD00 is stable in
  Omniverse.
- `render`, `proxy`, and `guide` purposes may be authored, but they must be
  tested in Omniverse before they become runtime assumptions.

## 2. References

References are immediate composition arcs. Use them for lightweight structure,
metadata, layout, and explicit scene assembly where eager loading is acceptable.

For v0.1, a direct configured USD asset path is sufficient.

## 3. Payloads

Payloads are deferred-load composition arcs. They are recommended for heavy
server, rack, cabling, VDB, or data hall assets when the scene becomes too large
to load eagerly.

Payloads are not a blanket requirement for the CPU cooler asset preview.

## 4. LOD and Purpose Target

When LODs are reintroduced, use a stable project convention:

1. VariantSet name: `LOD`.
2. Variant names: `LOD0`, `LOD1`, `LOD2`.
3. Purpose metadata (`render`, `proxy`, `guide`) should be placed on geometry
   leaf prims, not on root component Xforms.
4. Each LOD variant must be validated in Omniverse before it is exposed in
   Blackwell Monitoring Suite.

## 5. Future Omniverse Workflow

At server/rack/data hall scale, the desired workflow is:

- load only the payloads needed for the current review scale;
- use proxy or simplified geometry for navigation;
- use render geometry for close inspection;
- keep invalid LOD variants out of the runtime until they are fixed upstream.

## Definition of Done

- v0.1 asset loads from config without hidden absolute paths.
- LOD variants are not exposed unless they are known to render correctly in
  Omniverse.
- Future heavy scene components use payloads only when scale makes lazy loading
  valuable.
- Purpose tags, when used, live on geometry leaf prims.
