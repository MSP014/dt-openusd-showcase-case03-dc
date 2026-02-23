# Guideline 05: Centralized Materials Library

We are operating with an industrial "Single Source of Truth" logic for our visual assets, strictly avoiding a scattered "game-dev" texturing approach where every asset holds its own internal folder of maps.

In large-scale Omniverse scenes, duplicating the same physical property (e.g., "Polished Black Server Rack Metal") across a multitude of individual Component USDs creates severe overhead. It makes mass-updates physically impossible without destructive bulk-edits.

## 1. The Global Library Paradigm

There is **one** master materials file for the Case 03 Datacenter: `materials_library.usda` (or `.usdc`). This strictly stores Shader Graphs in OpenUSD.

To comply with the Master USD Contract:

* All material architectures sit centrally in the `materials/` directory of the project path.
* **Every single 3D asset** generated in Houdini (from the screws to the 42U Server Racks) must reference their surface definitions *exclusively* from this target file.
* All associated bitmap textures (Albedo, Roughness, Normal) must be rigorously separated and stored exclusively in a sister `textures/` directory.
* Do not allow the material `.usda` file to become a dumping ground for `.png` files.

## 2. Omniverse Nucleus-Friendly Binding

Prefix your materials internally with `m_` within the central library (e.g., `m_PolishedSteel_Rack`, `m_MattePlastic_Fan`).

By assigning all 160 servers to `m_PolishedSteel_Rack`, we unlock global updates. If the art director requests the servers appear sleeker, adjusting the roughness parameter *once* in `materials_library.usda` instantly updates it across the entire datacenter.

> [!TIP]
> **Houdini Implementation:**
> When configuring the `Material Library` LOP and exporting from Solaris, explicitly strip local USD textures and write the **relative material path** (e.g., `../materials/materials_library.usd`). This structure guarantees seamless transport across workstations and Omniverse Nucleus servers without broken absolute `C:/` drives.

---

## ✅ Definition of Done (DoD)

* [ ] No local `materials/` folders exist nested inside individual Component asset folders.

* [ ] Material definitions (`.usda`/`.usdc`) and their raw Maps (`.png`/`.exr`) are physically split into two distinct root project folders.
* [ ] Material Bindings on Component references trace back through relative cross-directory links (e.g., `../materials/...`).
