# DTRS Licensing Scope

**Status:** Scope decision. This document defines the boundaries implemented by
the repository licence map and its referenced licence texts.

## Purpose

DTRS combines reusable Python software, authored visual assets, private
authoring sources, and third-party material. A repository-wide software licence
would not describe those rights accurately. This document fixes the intended
scope for the repository licence map, asset-evaluation terms, and third-party
notices.

This scope document is not legal advice. Qualified intellectual-property review
is recommended before relying on the MSP Asset & Technical Content Evaluation
License for broader commercial licensing or enforcement.

The repository's current evaluation licence is version 1.1. Version 1.0 remains
the historical licence text for prior Asset Pack releases.

## The Three Licensing Zones

| Zone | Intended licence or treatment | Scope |
| --- | --- | --- |
| Code | MIT | Author-owned reusable Python code in `src/`, `tools/`, `tests/`, and project configuration files. |
| Authored assets and documentation | MSP Asset & Technical Content Evaluation License | Author-owned runtime assets, visual media, simulation outputs, README content, and authored technical documentation. |
| Third-party material | Its own applicable terms | HDRIs, libraries, NVIDIA components, manufacturer material, fonts, and every other item whose rights belong to another party. |

The MIT licence applies only to the Code zone. It must never be
described as a licence for the whole repository, the external Asset Pack, or
the DTRS project as a whole.

## Scope Matrix

| Content | Zone | Intended treatment |
| --- | --- | --- |
| `src/` | Code | MIT. |
| `tools/` | Code | MIT. |
| `tests/` | Code | MIT. |
| Project configuration files | Code | MIT, unless a file explicitly states otherwise. |
| Author-owned `.usd`, `.usda`, and `.usdc` assets | Authored assets and documentation | MSP Asset & Technical Content Evaluation License. |
| Author-owned textures and materials | Authored assets and documentation | MSP Asset & Technical Content Evaluation License. |
| Author-owned renders and preview images | Authored assets and documentation | MSP Asset & Technical Content Evaluation License. |
| VTI and manifest files in the [DTRS Airflow Runtime Dataset](https://huggingface.co/datasets/MaxSpeLL/dt-openusd-showcase-case03-airflow) | Separate published dataset | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). This is not Author Content under the MSP Asset & Technical Content Evaluation License. |
| Other author-owned VTI files, simulation caches, and derived visualisation data | Authored assets and documentation | MSP Asset & Technical Content Evaluation License. |
| `README.md` and author-owned DTRS documentation | Authored assets and documentation | MSP Asset & Technical Content Evaluation License. |
| Houdini `.hip` files and other authoring masters | Private source | Not distributed. They are not part of any public licence grant. |
| Third-party HDRIs, libraries, NVIDIA components, manufacturer PDFs, fonts, logos, and reference material | Third-party material | Subject to their original terms; no rights are granted by the DTRS author. |

Directory placement does not override provenance. For example, an externally
published PDF stored under `docs/` remains third-party material, while an
author-owned technical note in the same directory belongs to the authored
documentation zone.

### Knowledge-Base Reference Files

The knowledge base contains authored Markdown documents and cites fourteen
third-party technical references from NVIDIA, ASUS, Noctua, Weiss
Doppelbodensysteme GmbH, and IEEE. The publisher PDF files are not distributed
by this repository. They remain in the third-party zone even when a nearby
Markdown document cites or interprets them. Their provenance, official sources,
and release treatment are recorded in
[`THIRD_PARTY_NOTICES.md`](../../THIRD_PARTY_NOTICES.md).

The authored project renders and simulation-preview images displayed from
`docs/img/` are Author Content when they are generated from the project's own
visual proxies and simulation work. That classification grants no rights in
depicted product names, marks, or product designs. An ordinary outbound link to
an external page or specification is a citation, not a relicensing or copying
of the linked work.

For a public repository snapshot or Asset Pack, a third-party PDF must remain
excluded unless its publisher's redistribution terms or a specific permission
support its inclusion. Retain an author-written citation and an official source
link instead. A notice records the boundary; it cannot create permission that
the original rights holder has not granted.

## Product Representations and Manufacturer Rights

The Blackwell Rig components are independently modelled visual proxies created
from public photographic references, not manufacturer CAD data. The author owns
only the original mesh, topology, UV, texture, material, and assembly work that
they created.

Representing products such as NVIDIA ConnectX-7 or RTX PRO 4500 Blackwell does
not transfer ownership of the manufacturers' names, trademarks, logos, product
designs, documentation, or other intellectual property. NVIDIA, ASUS, Noctua,
and other manufacturer rights remain with their respective owners. The MSP Asset
& Technical Content Evaluation License must therefore grant only rights to the identified
author-owned contribution and must include an appropriate no-affiliation and
no-endorsement notice.

## Scope Precedence

Apply these rules in order when classifying a file for a future release:

1. A third-party element always remains under its original terms, regardless of
   its path or whether it is required by the runtime.
2. Private authoring sources, including Houdini `.hip` files, are excluded from
   public distribution.
3. The published DTRS Airflow Runtime Dataset is licensed under CC BY 4.0. Its
   VTI files and manifests are not subject to the MSP Asset & Technical Content
   Evaluation License.
4. Author-owned software under `src/`, `tools/`, or `tests/`, plus project
   configuration files, belongs to the MIT code zone.
5. Other author-owned DTRS assets, media, README content, and documentation
   belong to the MSP Asset & Technical Content Evaluation License zone.

Unclassified or mixed-origin files must remain out of a public package until a
rights inventory records their provenance and distribution status.

## Implemented Boundary and Maintenance

The repository licence map, reference texts, and Asset Pack 0.5.1 implement
this decision. The package carries its matching licence, manifest, notices, and
checksums. For each future public Asset Pack release, the maintainer must:

1. inventory distributable files and record third-party provenance;
2. confirm that the MIT licence remains limited to the code zone;
3. seek qualified review of the MSP Asset & Technical Content Evaluation
   License before relying on it for broader commercial licensing or enforcement;
4. maintain `THIRD_PARTY_NOTICES.md` with provenance and release treatment,
   then confirm the relevant permissions before including third-party files;
5. state the split model beside every public Asset Pack download.

`LICENSE.md` is the repository's licensing map. Do not add a root `LICENSE`
file containing only MIT text or label DTRS as fully open source.
