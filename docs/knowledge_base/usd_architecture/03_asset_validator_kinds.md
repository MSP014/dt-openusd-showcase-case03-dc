# Protocol 03: Asset Validator Kinds (Hierarchy)

The **Asset Validator** in Omniverse is the overarching quality-control tool that ensures our scene will not break downstream automation or UX selection. The most common error in mechanical assemblies relates to **Kinds** (metadata tags identifying what a prim functionally represents).

## 1. Project UX Rule

To ensure a clean UI selection experience and pass project validation, we enforce the following structural guideline: **A `Component` or `Subcomponent` must live inside a `Group` or an `Assembly`.**

### Definitions for Case 03

* **Group:** A logical collection of assemblies. Example: `/World/Datacenter/Row_A`
* **Assembly:** A collection of components that form a system. Example: `/World/Datacenter/Row_A/Rack_05`
* **Component:** An indivisible piece of *primary* equipment. Example: `/World/Datacenter/Row_A/Rack_05/Server_12`
* **Subcomponent:** Critical internals requiring independent selection/inspection. Example: `/World/Datacenter/Row_A/Rack_05/Server_12/GPU_01`

### Why This Matters

Without `Subcomponent`, clicking the GPU selects the whole server. Without `Assembly`, clicking the rack might randomly select a single screw. When Kinds are configured perfectly, clicking anywhere on the rack highlights the entire `Assembly` by default.

> [!TIP]
> **Houdini Implementation:**
> Do not leave USD prims untagged. Use the `Configure Primitive` node in Solaris:
>
> 1. Select your top-level rack group -> Set Kind to `Assembly`.
> 2. Select the individual server instances -> Set Kind to `Component`.
> 3. Select internals (ConnectX-7, Blackwell VMs) -> Set Kind to `Subcomponent`.

---

## ✅ Definition of Done (DoD)

- [ ] Running the Asset Validator in Omniverse yields zero `KindChecker` errors.
* [ ] Double-clicking a server rack in the Viewport selects the `Assembly`, not an internal mesh.
* [ ] Individual GPUs or NICs are tagged as `Subcomponent` allowing focused inspection.
