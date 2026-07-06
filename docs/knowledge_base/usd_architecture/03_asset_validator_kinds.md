# Guideline 03: Asset Validator Kinds and Hierarchy

Kinds are metadata hints that help Omniverse and USD tools understand what a
prim represents. They matter most when the scene grows from individual assets to
server, rack, and data hall assemblies.

## 1. Current Baseline

For v0.1, the main requirement is readable hierarchy and stable prim names for
runtime-addressable parts.

The CPU cooler asset already exposes meaningful structure such as:

```text
/cpu_fan/geo/render/cpu_cooler/cpu_fan/blades/blades
```

This is enough for Stage 1 asset preview and gives Stage 4 a candidate fan
blade prim for telemetry-driven rotation once pivot and axis are checked.

## 2. Future Hierarchy Target

As full server and rack scenes mature, use a clear hierarchy:

- **Group:** logical collection of assemblies, such as a row or data hall zone.
- **Assembly:** a system made of components, such as a rack.
- **Component:** a primary equipment unit, such as a server or switch.
- **Subcomponent:** an internal part that needs independent review, such as a
  GPU, NIC, PSU, fan, or CPU cooler.

## 3. Why This Matters

Good hierarchy keeps selection predictable and makes future review controls
possible. A reviewer should be able to focus a server, rack, GPU, or fan without
digging through anonymous meshes.

## 4. Houdini Implementation

Use Solaris `Configure Primitive` where appropriate:

1. Tag rack or system roots as `Assembly`.
2. Tag server or device roots as `Component`.
3. Tag important internals as `Subcomponent`.

Do this when the asset hierarchy is stable enough to justify the metadata.

For parts that Blackwell Monitoring Suite will control independently, hierarchy
matters more than labels. Fans, GPU dies, VRAM chips, PSU internals, sensors,
or other runtime-addressable pieces should not collapse into anonymous merged
meshes. Give them stable names in Houdini before export so the resulting USD
paths can be targeted by runtime code.

## Definition of Done

- Runtime-addressable parts have stable, readable prim paths.
- Full server/rack scenes eventually pass relevant Omniverse validation checks.
- Kind metadata is added deliberately where it improves selection and review.
