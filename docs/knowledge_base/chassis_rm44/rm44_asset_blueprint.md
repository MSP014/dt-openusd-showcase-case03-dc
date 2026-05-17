# Asset Blueprint: SilverStone RM44 (v1.0)

## 1. Asset Identity

* **Asset Name**: `SilverStone_RM44`
* **Kind**: `component` (Main), `assembly` (Hero)
* **Up Axis**: Y
* **Meters Per Unit**: 1.0 (m) - *Standard Houdini Context*. (USD typically 0.01, but Houdini SOPs are meters).

## 2. Layers & Sources

### `geo/` (SOPs)

* `chassis_main.bgeo.sc`: Корпус, уши, передняя панель.
* `chassis_proxy_tube.bgeo.sc`: Труба для симуляции.
* `internals_high.bgeo.sc`: Материнка, GPU, кулеры.

## 3. Component Builder Structure

The asset will use a single Component Builder context with a Switch for variants.

### Variant Set: `LOD`

* **`High` (Default)**
  * Geometry: `chassis_main.bgeo.sc` (High Poly)
  * Material: `mtl_brushed_steel`, `mtl_plastic_black`
  * Purpose: default
* **`Low`**
  * Geometry: `chassis_main_proxy.bgeo.sc` (Box with textures)
  * Purpose: render (distance)

### Grill Patterns

* **Front Door**: Hex-Clustered Triangles (6 tris per hex).
  * *Feature*: Gradient scale (smaller openings near edges).
* **Inner Fan Wall**: Hexagonal Honeycomb.

### Variant Set: `Purpose` (Physics)

* **`Render`**: see LODs above.
* **`SimProxy`**:
  * Geometry: `chassis_proxy_tube.bgeo.sc`
  * Topology: Open Front/Rear, Solid Walls.
  * Purpose: guide, proxy

## 4. Hero Structure (Inheritance)

To avoid duplication, the Hero asset will be a separate USD file referencing the Main asset.

**Graph:**
`SilverStone_RM44_Hero.usd`
└── (References) `SilverStone_RM44_Main.usd`
    └── (Over) `/SilverStone_RM44/Internals` (Payload: `internals_high.usd`)

## 5. Metrics

* **Width**: 440mm
* **Height**: 176mm (4U)
* **Depth**: 468mm
* **Wall Thickness**: 1.2mm
* **Rear Panel Cutouts**:
  * **PSU (ATX/PS2)**: 150mm (W) x 86mm (H)
  * **Motherboard I/O**: 158.75mm (W) x 44.45mm (H)
  * **PCIe Slots**:
    * **Vertical Cutout**: ~120mm
    * **Slot Gap**: ~15mm (Horizontal)
    * **Standard Pitch**: 20.32mm (0.8")
  * **Rear Fans (80mm)**:
    * **Dimensions**: 80x80x25mm
    * **Hole Spacing**: 71.5mm
    * **Cutout Diameter**: ~76mm
