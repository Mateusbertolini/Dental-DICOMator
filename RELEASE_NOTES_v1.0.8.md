# Dental DICOMator 1.0.8

Release date: 3 September 2026

## Highlights

- Bone now contains an automatic cortical layer: 800 HU at the surface and
  350 HU in the cancellous interior.
- Default cortical depth is 2.0 mm with a 0.5 mm smooth transition.
- Cortical depth and shell blend are editable; HU values remain managed.
- Bone occupancy still uses the unchanged v1.0.7 closed-volume ray-pair fill.
  Only HU values inside filled voxels are changed, so the cortical layer does
  not create shell geometry, holes, or loss of volume.

## Validation focus

Before publication use, test the release with the same complex mandible that
verified v1.0.7. Compare slice count, non-air voxel count, external dimensions,
and continuity against a v1.0.7 export. Those geometry measures should remain
unchanged; only the HU distribution inside bone should differ.
