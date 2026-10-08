# Dental DICOMator 1.0.10

The cancellous pattern now uses deterministic three-dimensional fBM value
noise instead of intersecting periodic sine ridges. The default Noise Scale is
25, with Detail 2 and Roughness 0.5, producing an irregular cloud-like
trabecular distribution without a visible grid.

D1-D4 control both trabecular prevalence and trabecular radiopacity. D1 has
more numerous and brighter trabeculae, whereas D4 has fewer and less
radiopaque trabeculae. The marrow/void value remains constant across density
presets, preventing painted density regions from appearing as a uniformly
darker overlay.

The pattern continues to modify attenuation only inside the unchanged
closed-volume occupancy mask.
