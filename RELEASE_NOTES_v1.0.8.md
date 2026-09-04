# Dental DICOMator 1.0.8 corrected cortical workflow

Bone retains the established closed-volume ray-pair fill. Enabling Paint
Cortical Bone creates a managed Cortical vertex group; only painted surfaces
propagate 800-HU cortical behavior inward. Unpainted surfaces and the remaining
volume stay cancellous at 350 HU. Defaults are 2.0 mm depth, 0.5 mm depth
transition, and 0.2 Weight Blend.

This correction prevents unintended internal mesh surfaces from automatically
receiving cortical behavior. It changes voxel values only and never modifies
the occupancy mask or mesh geometry.
