# Changelog

## [1.0.10] - 2026-10-08

### Changed

- Replaced the periodic sinusoidal trabecular field with smooth deterministic
  3D fBM value noise using a default Noise Scale of 25, Detail 2, and
  Roughness 0.5.
- D1-D4 now alter trabecular prevalence and trabecular radiopacity while the
  marrow/void baseline remains constant. Weight painting no longer darkens an
  entire region as a uniform tint.
- D1 produces more numerous, brighter trabeculae; D4 produces fewer, less
  radiopaque trabeculae and more marrow-like space.

## [1.0.9] - 2026-10-08

### Added

- Added object-wide D1-D4 synthetic bone-density presets.
- Added an optional managed `BoneDensity` weight-paint workflow. Painted
  regions blend continuously from the base preset to a selected target preset.
- Added a deterministic trabecular pattern with intersecting radiopaque struts
  and radiolucent marrow-like spaces. Pattern scale and strength are adjustable.

### Safety and compatibility

- Density and trabecular calculations modify HU values only after the original
  closed-volume ray-pair fill; they cannot create holes or change occupancy.
- Cortical weight painting remains the final bone-layer override.

## [1.0.8] - 2026-09-03

### Added

- Added a managed Cortical vertex group and Paint Cortical Bone workflow.
- Painted bone surfaces generate an 800-HU cortical layer with 2.0 mm depth;
  unpainted surfaces and the interior remain cancellous at 350 HU.
- Added Cortical Weight Paint/Object Mode controls, Weight Blend, depth, and
  depth-transition inputs for Bone objects.

### Fixed

- Cortical HU is now applied only inside the unchanged v1.0.7 closed-volume
  occupancy mask. The layer no longer creates or modifies shell geometry and
  therefore cannot remove occupied bone voxels.

## [1.0.7] - 2026-09-02

- Titanium now has the highest overlap priority, remaining visible through bone or dental tissues.
- Updated package metadata and repository documentation.

## [1.0.6] - 2026-08-28

- Standardized geometry in millimetres with Scene Unit Scale 0.001.
- Set voxel spacing to 0.25 x 0.25 x 0.5 mm, producing two axial images per millimetre.
- Corrected dental-layer depths after the scale change.
- Preserved stable closed-volume bone voxelization.

## [1.0.0] - 2026-08-26

- Added dental presets and weight-painted enamel, caries, PDL, restoration, and pulp/gutta-percha.
- Added automatic groups, paint controls, validation, simplified UI, and dental artifacts.

Adapted from DICOMator by Michael Douglass. See NOTICE.md.

