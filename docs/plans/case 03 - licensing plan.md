# Case 03 - Licensing Plan

**Status**: Draft
**Last Updated**: 2026-07-11

## Purpose

This plan defines the work required to make Case 03 publicly inspectable and
testable without granting unrestricted reuse of its authored 3D assets.

It deliberately does not contain final legal language. The custom asset licence
must be reviewed by a qualified intellectual-property lawyer before it is used
for a new public Asset Pack release.

## Current State

- The public repository contains code, documentation, images, and a link to an
  externally hosted Asset Pack.
- Heavy USD assets, textures, caches, and Houdini source files are excluded from
  Git tracking.
- The Asset Pack is currently distributed through Google Drive and hydrated
  locally under `assets/_external/`.
- No repository-level code licence, asset licence, licensing scope document, or
  third-party notices file currently exists.
- The public download instructions therefore need an explicit licensing model
  before the next Asset Pack release.

## Target Model

Case 03 should use a split licensing and distribution model:

| Content | Target treatment |
| --- | --- |
| Application code and reusable project tools | Standard open-source software licence |
| Project documentation and renders | Explicitly scoped rights; decision still required |
| Maksim Pospelkov-authored runtime assets | Custom evaluation-only asset licence |
| Third-party textures, HDRIs, fonts, logos, and reference material | Their original terms or exclusion from distribution |
| Houdini source files, procedural generators, high-resolution masters, and source simulations | Private; not included in the public package |

The public repository may remain open source at the code level, but the project
as a whole must not be described as fully open source while the Asset Pack is
evaluation-only.

## Principles

1. Keep technical reproducibility and asset reuse rights separate.
2. Grant only the rights required to install, run, inspect, and evaluate Case 03.
3. Do not grant commercial production, client-work, redistribution, asset-pack,
   dataset, or machine-learning reuse rights through the public Asset Pack.
4. Do not claim rights over third-party material or manufacturer intellectual
   property.
5. Define covered files through a manifest rather than a blanket claim over
   every file in the archive.
6. Keep the original authoring sources private and distribute only the runtime
   deliverables needed to demonstrate the pipeline.
7. Treat metadata and checksums as provenance evidence, not as technical copy
   protection.
8. Avoid DRM or obfuscation that harms legitimate technical evaluation without
   meaningfully preventing extraction.

## Phase 1 - Stabilise The Existing Distribution

Before publishing another Asset Pack version:

1. Preserve a private copy of the currently distributed package.
2. Record its file list, archive hash, publication location, and approximate
   publication date.
3. Do not present a future licence as retroactively changing the terms of copies
   already downloaded; obtain legal advice on the status of the earlier package.
4. Avoid adding authored binary assets to GitHub Releases or the public Git
   repository while the licensing scope remains unresolved.
5. Keep the existing application test path working while the replacement package
   is prepared.

## Phase 2 - Build A Rights Inventory

Create an inventory covering both the repository and the external Asset Pack.
Classify every distributable file into one of these groups:

- original code authored for Case 03;
- original 3D geometry, textures, materials, simulations, and renders;
- third-party content redistributed under an explicit licence;
- third-party content that may be used locally but may not be redistributed;
- manufacturer names, logos, product designs, and other brand-related material;
- generated outputs derived from more than one rights source;
- private authoring sources that must never enter the public package.

For each item, record:

- path or package-relative pattern;
- author or source;
- copyright owner where known;
- applicable licence or permission;
- whether redistribution is allowed;
- whether modification is allowed;
- whether attribution is required;
- whether the item is safe for the public evaluation package;
- replacement or removal action where rights are unclear.

Pay particular attention to HDRIs, stock textures, fonts, logos, product
photographs, manufacturer documentation, and any source maps used to derive the
published textures.

### Asset Rights Classes

Use one base Asset Evaluation Licence for author-owned runtime assets, but
classify each asset according to the rights present in the represented object.
The classification belongs in `ASSET_MANIFEST.json` and determines the notices
and exclusions that accompany the asset.

#### Original Authored Asset

Use `original_authored` where the asset does not reproduce a specific third-party
product or include third-party brand marks.

Record:

- the author-owned geometry, topology, UVs, textures, materials, and assembly;
- any separately licensed source material;
- the complete set of rights the author is able to grant.

#### Unbranded Product Representation

Use `product_representation_unbranded` where the asset closely represents a real
product but does not contain manufacturer names, logos, or other brand marks.
The absence of branding does not remove possible third-party industrial-design
or other product-appearance rights.

Record:

- `representedProduct`;
- `manufacturer`;
- `brandMarksIncluded: false`;
- the author-owned contribution, such as independently modelled geometry,
  topology, UVs, and original textures;
- `thirdPartyRightsExcluded: true`;
- the applicable no-endorsement and product-reference notice.

#### Branded Product Representation

Use `product_representation_branded` where the asset represents a real product
and includes a manufacturer name, product name, logo, word mark, or similar
brand element.

Record:

- `representedProduct`;
- `manufacturer`;
- `brandMarksIncluded: true`;
- known trademark owners and the marks present;
- the author-owned contribution;
- `thirdPartyRightsExcluded: true`;
- the applicable trademark, no-affiliation, and no-endorsement notices;
- whether the downloadable evaluation asset should retain the marks or use an
  unbranded distribution variant.

#### Third-Party Or Mixed Asset

Use `third_party` or `mixed_derived` where the asset contains material owned by
another party or combines multiple rights sources. Do not place these files
under the custom Asset Evaluation Licence unless the manifest clearly limits the
grant to the author-owned contribution and redistribution of every included
third-party element has been verified.

Example manifest fields:

```text
rightsClass
representedProduct
manufacturer
brandMarksIncluded
trademarkOwners
authorOwnedElements
thirdPartyRightsExcluded
licenceId
noticeIds
```

## Phase 3 - Resolve Third-Party Product Rights

The Case 03 assets visually represent real products and brands. Before offering
any broader licence, obtain legal guidance on:

- copyright in the original authored meshes and textures;
- registered or unregistered industrial-design rights in the represented
  products;
- trademark and logo use in a portfolio and evaluation context;
- whether logos should be removed from the downloadable package while remaining
  visible in portfolio renders;
- what commercial rights, if any, can legitimately be offered for accurate
  product representations;
- the wording required to avoid implying endorsement by NVIDIA or other
  manufacturers.

The asset licence must grant rights only to the original work owned by the
author. A third-party disclaimer does not create rights that the author does not
possess.

Do not create separate public asset licences solely because one product
representation is branded and another is unbranded. Prefer one stable evaluation
grant, class-specific manifest entries, and class-specific notices. Introduce a
separate addendum or distribution tier only when legal review identifies a
materially different permission model for a particular asset category.

## Phase 4 - Choose The Code And Documentation Licences

1. Choose a standard licence for the code, most likely MIT or Apache-2.0.
2. Keep the standard licence text unmodified.
3. Define its exact path scope in a separate `LICENSING.md` file.
4. Explicitly exclude the external Asset Pack, artistic assets, simulation
   caches, source files, and third-party content from the software licence.
5. Decide separately whether documentation and renders are all-rights-reserved,
   attribution-only, or covered by another limited licence.
6. Confirm that repository contributions, if accepted in the future, do not
   create conflicting ownership assumptions.

Recommended repository artefacts:

```text
LICENSE
ASSET-LICENCE.md
LICENSING.md
THIRD-PARTY-NOTICES.md
```

`LICENSE` should remain the conventional filename for the standard code licence.
The other files should explain the split without modifying the standard licence.

## Phase 5 - Design The Asset Evaluation Licence

Prepare a lawyer-reviewed custom licence that addresses the following points.
Do not copy an unreviewed draft directly into the release.

### Covered Assets

- Apply the licence only to files marked as author-owned in
  `ASSET_MANIFEST.json`.
- Exclude third-party files and identify their separate terms.
- State that product names, manufacturer marks, logos, industrial designs, and
  other third-party rights are not licensed by the author.
- Clarify that the grant for product representations covers only the identified
  author-owned contribution.
- Use a stable licence name, version, effective date, and contact address.

### Permitted Evaluation

- downloading and installing the Asset Pack;
- local execution and evaluation of Case 03;
- inspection of its OpenUSD, Houdini, and NVIDIA Omniverse workflows;
- temporary local modifications or format conversions required for testing;
- internal technical and hiring evaluation by a prospective employer;
- public screenshots or captures of the running project under defined
  attribution conditions.

### Prohibited Uses

- reuse outside the evaluation of Case 03;
- commercial production, client work, paid services, advertising, or product
  integration;
- redistribution, mirroring, sublicensing, resale, or inclusion in an asset
  pack, template, library, dataset, application, game, film, simulation product,
  or digital twin;
- extraction and reuse of individual components;
- machine-learning or generative-AI dataset construction, training,
  fine-tuning, or model evaluation;
- removal of copyright, licence, attribution, or asset-identification metadata;
- claims of authorship, ownership, endorsement, or affiliation.

### Definitions And Legal Mechanics

- Distinguish evaluation by a commercial organisation from commercial use in a
  production or revenue-generating activity.
- Define the licensee and the limited internal access allowed to employees or
  contractors performing the evaluation.
- Avoid an undefined arbitrary `revocable` grant; use clear termination on
  breach unless counsel recommends otherwise.
- Define what happens to local copies after termination.
- Include warranty and liability limitations.
- Include third-party-rights and no-endorsement clauses.
- Decide governing law, venue, notice procedure, and dispute handling with
  counsel.
- Confirm whether download, click-through acceptance, or use of the package is
  sufficient to form the intended agreement in the relevant jurisdictions.

## Phase 6 - Define The Public Evaluation Package

The public package should contain only what is necessary to run and inspect the
published Case 03 experience:

- runtime USD assets and their required composition layers;
- baked runtime textures at an appropriate evaluation resolution;
- validated material definitions;
- required LODs and collision or proxy geometry;
- the smallest useful set of simulation caches;
- package-local licensing, manifest, notices, and setup documentation.

The public package should not contain:

- Houdini `.hip` source files;
- procedural modelling or simulation generators;
- high-resolution production masters not required by the viewer;
- source Substance, Photoshop, Copernicus, or similar authoring graphs;
- intermediate bakes and source scans;
- production-resolution caches beyond the evaluation need;
- third-party material without redistribution rights.

Consider a two-tier distribution only if it improves the hiring workflow:

1. a public, sufficient evaluation package;
2. a full-fidelity evaluator package supplied on request under separate written
   terms to a prospective employer.

## Phase 7 - Add Package-Level Provenance

Create `ASSET_MANIFEST.json` with, at minimum:

- package name and semantic version;
- archive identifier and release date;
- asset-relative path;
- stable `assetId`;
- author or third-party source;
- ownership classification;
- applicable licence identifier;
- SHA-256 checksum;
- source package or derivation note where appropriate.

For author-owned USD component roots, add non-rendering metadata where practical:

```text
author
copyright
assetId
assetLicence
assetVersion
```

Keep the private evidence set separately:

- Houdini source files and production masters;
- dated WIP renders and viewport captures;
- source texture and simulation history;
- Git history and release manifests;
- package archive hashes;
- any formal registration or deposit records obtained after legal advice.

Publish the final archive hash and manifest version in a signed or otherwise
stable Git tag or release note. A checksum proves the identity of a package; it
does not by itself prove authorship of every work inside it.

## Phase 8 - Integrate The Licence Into Distribution

Update the public repository only after the legal and rights inventory work is
complete:

1. Add the repository licensing files.
2. Add a concise licensing table near the Asset Pack download instructions in
   `README.md`.
3. State explicitly that the software licence does not apply to the Asset Pack.
4. State that the complete project is not wholly open source.
5. Link to the exact version of the asset licence that accompanies the archive.
6. Place `ASSET-LICENCE.txt`, `ASSET_MANIFEST.json`, and
   `THIRD-PARTY-NOTICES.txt` at the root of the downloaded archive.
7. Display the licence notice immediately beside the download action.
8. Evaluate whether the current Google Drive flow provides adequate notice and
   acceptance; use a controlled download page or explicit click-through only if
   the additional friction is justified.
9. Test the package from a clean environment after all licensing files are
   inserted.

The licensing notice must not obstruct a recruiter from viewing the portfolio,
README, screenshots, or demo video. Download acceptance should apply only when
the evaluator requests the underlying Asset Pack.

## Phase 9 - Release And Maintenance

### Licence Stability Rule

Adding, replacing, or recalculating author-owned content does not require a new
asset-licence version while the legal permissions and restrictions remain
unchanged. This includes:

- additional server, rack, or data-hall simulation cache sets;
- new Idle, Nominal, Surge, or Critical cache variants;
- corrected geometry, topology, materials, or textures;
- additional author-owned runtime assets;
- optimisation or compatibility updates to existing package content.

For these content-only changes, increment the Asset Pack version, update
`ASSET_MANIFEST.json`, recalculate the affected file and archive checksums, and
update the package documentation. Continue to include the same asset-licence
version in the archive.

A new asset-licence version is required only when the legal grant changes, such
as the permitted evaluation scope, prohibited uses, attribution requirements,
termination terms, governing law, AI or dataset restrictions, or commercial
licensing model. New third-party content always requires a rights and notices
review, but does not by itself require a new asset-licence version when the
author-owned asset terms remain unchanged.

For every future Asset Pack release:

1. Increment the package version.
2. Re-run the rights and third-party-content audit.
3. Generate a fresh manifest and checksums.
4. Confirm that the archive contains the matching licence version.
5. Run the technical hydration and BMS smoke checks.
6. Publish an immutable archive rather than silently replacing an existing
   version.
7. Record the archive URL, version, hash, licence version, and publication date.
8. Preserve the previous release and evidence set privately.

Any material change to the licence should produce a new licence and package
version. Do not imply that new terms automatically replace permissions already
granted for older package versions.

## Phase 10 - Prepare An Infringement Response

Prepare a private response checklist without publishing legal threats in the
repository:

1. Preserve the allegedly infringing URL, listing, screenshots, date, seller,
   product, and downloadable files.
2. Compare the files, topology, textures, identifiers, and package hashes.
3. Preserve the relevant source and release evidence.
4. Determine whether the use is actually prohibited and whether an exception
   may apply.
5. Obtain legal advice before making material legal claims.
6. Send a proportionate removal or commercial-licensing request where
   appropriate.
7. Use the relevant hosting provider's copyright or trademark process only with
   accurate ownership and infringement details.

## Decisions Required Before Drafting

- MIT or Apache-2.0 for application code.
- Rights granted for documentation and renders.
- Public package fidelity and texture resolution.
- Whether a second evaluator-only package is useful.
- Whether manufacturer logos remain in downloadable assets.
- Governing law and dispute venue.
- Public contact address for licensing and infringement notices.
- Attribution wording for public screenshots and captures.
- Download notice, click-through, or request-based distribution.
- Whether formal registration or deposit is worthwhile in the chosen
  jurisdictions.

## Acceptance Criteria

Licensing preparation is complete when:

- every distributable file has an ownership and licence classification;
- every authored asset has an explicit `rightsClass` and matching notices;
- third-party redistribution rights have been verified or the files removed;
- the code, documentation, and asset scopes are unambiguous;
- the custom asset licence has been reviewed by qualified counsel;
- the public archive contains its matching licence, manifest, and notices;
- the README presents the split licensing model clearly near the download link;
- the package remains installable and testable from a clean environment;
- production masters and source files remain private;
- package hashes and version records have been preserved;
- a reviewer can determine the permitted evaluation use without guessing.

## Reference Sources

- [WIPO Copyright FAQ](https://www.wipo.int/en/web/copyright/faq-copyright)
- [WIPO Industrial Designs FAQ](https://www.wipo.int/en/web/designs/faq-industrial-designs)
- [WIPO Trademarks](https://www.wipo.int/en/web/trademarks)
- [Creative Commons BY-NC-ND 4.0 Legal Code](https://creativecommons.org/licenses/by-nc-nd/4.0/legalcode.en)
- [GitHub Terms of Service](https://docs.github.com/en/site-policy/github-terms/github-terms-of-service)
- [GitHub Repository Licensing Guidance](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/licensing-a-repository)
