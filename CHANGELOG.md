# Changelog

## [1.0.8] - 2026-09-03

### Added

- Reintroduced cortical/cancellous bone layering with a 2.0 mm cortical depth
  and a 0.5 mm transition.
- Added cortical depth and shell-blend controls for Bone objects.

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

