# Dental DICOMator 1.0.9

Bone objects now support D1-D4 synthetic density presets, optional local
density variation through a managed `BoneDensity` weight-paint group, and a
deterministic trabecular appearance with bright intersecting struts and darker
marrow-like spaces.

The pattern changes attenuation values only within voxels already classified
as occupied by the stable closed-volume voxelizer. It does not subtract bone,
create cavities in the occupancy mask, or modify cortical surface painting.

D1-D4 are educational synthetic profiles rather than scanner-independent
clinical HU calibrations. Results should be validated for each intended
teaching or research application.
