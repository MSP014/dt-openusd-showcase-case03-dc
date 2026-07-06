# Guideline 05: Materials and Texture Portability

Material organization must support portable OpenUSD assets and future
large-scale look development without blocking the current staged runtime.

## 1. Current Baseline

For the current asset-preview stage:

- material and texture paths must be relative or explicitly configurable;
- no material binding should depend on a workstation-only absolute path;
- Houdini-exported material structure is acceptable if it renders correctly in
  Omniverse and stays portable;
- texture payloads remain under the hydrated external asset package.

## 2. Future Shared Material Library

A centralized material library becomes useful when many assets share the same
material families, such as rack metal, plastic, glass, PCB surfaces, labels, or
cooling hardware.

When that scale arrives, the target is:

- shared material definitions in a stable material layer;
- reusable material names;
- texture files separated from material graph definitions;
- relative bindings from component assets to shared materials.

This is a target architecture, not a v0.1 requirement.

## 3. Houdini Export Guidance

When using Solaris Material Library LOPs:

- prefer relative paths;
- avoid embedding workstation-local texture paths;
- keep material bindings inspectable in USD;
- test the exported asset in Omniverse before treating the material layout as
  runtime-ready.

## Definition of Done

- The asset renders in Omniverse without missing material or texture paths.
- Material and texture paths survive repo relocation and asset hydration.
- Shared material libraries are introduced only when they reduce real
  duplication or make lookdev updates easier.
