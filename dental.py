"""Dental CT material helpers independent of Blender's runtime."""
from __future__ import annotations

import numpy as np

from .constants import MAX_HU_VALUE, MIN_HU_VALUE


def smooth_threshold(weight, threshold: float, blend_width: float):
    """Map vertex weights to a stable 0..1 enamel fraction."""

    values = np.asarray(weight, dtype=np.float64)
    width = max(0.0, float(blend_width))
    if width <= 1e-9:
        return (values >= float(threshold)).astype(np.float64)
    lower = float(threshold) - 0.5 * width
    t = np.clip((values - lower) / width, 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def depth_fraction(depth_mm, thickness_mm: float, transition_mm: float):
    """Return a 0..1 layer fraction from true surface distance in mm."""

    depth = np.asarray(depth_mm, dtype=np.float64)
    thickness = max(0.0, float(thickness_mm))
    transition = max(0.0, float(transition_mm))
    if transition <= 1e-9:
        return (depth <= thickness).astype(np.float64)
    return np.clip(
        (thickness + 0.5 * transition - depth) / transition, 0.0, 1.0
    )


def sampled_layer_fraction(depth_mm, thickness_mm: float, transition_mm: float, voxel_radius_mm: float):
    """Estimate sub-voxel coverage for layers thinner than the voxel spacing."""

    depth = np.asarray(depth_mm, dtype=np.float64)
    thickness = max(0.0, float(thickness_mm))
    radius = max(0.0, float(voxel_radius_mm))
    if radius <= 1e-9:
        return depth_fraction(depth, thickness, transition_mm)
    inner = max(0.0, thickness - radius)
    outer = thickness + radius
    coverage = np.clip((outer - depth) / max(outer - inner, 1e-9), 0.0, 1.0)
    if float(transition_mm) > 0.0:
        coverage *= depth_fraction(depth, thickness + radius, transition_mm)
    return coverage


def layered_bone_values_from_depth(
    depth_mm,
    cortical_thickness_mm: float,
    transition_mm: float,
    cortical_hu: float,
    cancellous_hu: float,
):
    """Return bone HU from direction-independent nearest-surface distance."""

    fraction = depth_fraction(depth_mm, cortical_thickness_mm, transition_mm)
    values = float(cancellous_hu) + fraction * (
        float(cortical_hu) - float(cancellous_hu)
    )
    return np.clip(np.rint(values), MIN_HU_VALUE, MAX_HU_VALUE).astype(np.int16)


def painted_bone_values(
    surface_depth_mm,
    surface_weight,
    cortical_thickness_mm: float,
    depth_transition_mm: float,
    weight_threshold: float,
    weight_blend_width: float,
    cortical_hu: float,
    cancellous_hu: float,
    voxel_radius_mm: float = 0.0,
):
    """Return cortical HU only beneath weight-painted bone surfaces."""

    raw_weight = np.asarray(surface_weight, dtype=np.float64)
    paint = smooth_threshold(raw_weight, weight_threshold, weight_blend_width)
    # A zero vertex weight means explicitly unpainted. Keep it at exactly zero
    # even when the smoothing interval extends below the threshold.
    paint = np.where(raw_weight > 0.0, paint, 0.0)
    shell = sampled_layer_fraction(
        surface_depth_mm, cortical_thickness_mm, depth_transition_mm, voxel_radius_mm,
    )
    fraction = np.asarray(paint, dtype=np.float64) * np.asarray(shell, dtype=np.float64)
    values = float(cancellous_hu) + fraction * (float(cortical_hu) - float(cancellous_hu))
    return np.clip(np.rint(values), MIN_HU_VALUE, MAX_HU_VALUE).astype(np.int16)


def textured_bone_values(
    depth_mm,
    x_mm,
    y_mm,
    z_mm,
    cortical_thickness_mm: float,
    transition_mm: float,
    cortical_hu: float,
    cancellous_hu: float,
    trabecular_spacing_mm: float,
    trabecular_contrast_hu: float,
):
    """Return a cortical shell surrounding a deterministic trabecular pattern."""

    shell = depth_fraction(depth_mm, cortical_thickness_mm, transition_mm)
    spacing = max(0.25, float(trabecular_spacing_mm))
    x = np.asarray(x_mm, dtype=np.float64) / spacing
    y = np.asarray(y_mm, dtype=np.float64) / spacing
    z = np.asarray(z_mm, dtype=np.float64) / spacing
    # Thin, intersecting sinusoidal ridges provide repeatable trabecular-like
    # struts without making identical exports depend on a random seed.
    ridge_width = 0.24
    phases = (
        np.sin(np.pi * (x + 0.19 * y)),
        np.sin(np.pi * (y + 0.23 * z)),
        np.sin(np.pi * (z + 0.17 * x)),
        np.sin(np.pi * (0.58 * x + 0.71 * y + 0.43 * z)),
    )
    ridge = np.maximum.reduce([
        np.exp(-np.square(phase / ridge_width)) for phase in phases
    ])
    contrast = max(0.0, float(trabecular_contrast_hu))
    cancellous = float(cancellous_hu) + contrast * (ridge - 0.45)
    values = cancellous + shell * (float(cortical_hu) - cancellous)
    return np.clip(np.rint(values), MIN_HU_VALUE, MAX_HU_VALUE).astype(np.int16)


def tooth_values_from_surface(
    depth_mm,
    enamel_weight,
    enamel_hu: float,
    dentin_hu: float,
    threshold: float,
    blend_width: float,
    enamel_depth_mm: float,
    *,
    caries_weight=None,
    caries_hu: float = 500.0,
    caries_threshold: float = 0.5,
    caries_blend_width: float = 0.2,
    caries_depth_mm: float = 0.0,
    caries_surface_depth_mm=None,
    pdl_weight=None,
    pdl_hu: float = -100.0,
    pdl_depth_mm: float = 0.0,
    pdl_surface_depth_mm=None,
    pdl_painted_weight=None,
    pdl_painted_surface_depth_mm=None,
    restoration_weight=None,
    restoration_hu: float = 3000.0,
    restoration_threshold: float = 0.05,
    restoration_blend_width: float = 0.2,
    restoration_depth_mm: float = 0.0,
    restoration_surface_depth_mm=None,
    voxel_radius_mm: float = 0.0,
):
    """Return tooth HU propagated inward from independently painted surfaces."""

    depth = np.asarray(depth_mm, dtype=np.float64)
    enamel_fraction = smooth_threshold(enamel_weight, threshold, blend_width)
    enamel_fraction *= sampled_layer_fraction(
        depth,
        enamel_depth_mm,
        min(0.5, max(0.05, enamel_depth_mm * 0.25)),
        voxel_radius_mm,
    )
    values = np.full(np.shape(depth), float(dentin_hu), dtype=np.float64)
    if pdl_weight is not None and float(pdl_depth_mm) > 0.0:
        pdl_depth = np.asarray(pdl_surface_depth_mm, dtype=np.float64)
        pdl_fraction = np.asarray(pdl_weight, dtype=np.float64) * sampled_layer_fraction(
            pdl_depth,
            pdl_depth_mm,
            min(0.5, max(0.05, pdl_depth_mm * 0.25)),
            voxel_radius_mm,
        )
        values += pdl_fraction * (float(pdl_hu) - values)
        if pdl_painted_weight is not None:
            painted_depth = np.asarray(
                pdl_painted_surface_depth_mm, dtype=np.float64
            )
            doubled_fraction = smooth_threshold(
                pdl_painted_weight, 0.05, 0.2
            ) * sampled_layer_fraction(
                painted_depth,
                2.0 * float(pdl_depth_mm),
                min(0.5, max(0.05, pdl_depth_mm * 0.25)),
                voxel_radius_mm,
            )
            values += doubled_fraction * (float(pdl_hu) - values)

    # Enamel replaces the periodontal layer wherever its painted surface owns
    # the voxel, while the unpainted crown/root surface remains radiolucent.
    values += enamel_fraction * (float(enamel_hu) - values)
    if caries_weight is not None and float(caries_depth_mm) > 0.0:
        caries_paint = smooth_threshold(
            caries_weight, caries_threshold, caries_blend_width
        )
        caries_fraction = caries_paint.copy()
        caries_depth = (
            depth if caries_surface_depth_mm is None
            else np.asarray(caries_surface_depth_mm, dtype=np.float64)
        )
        # Restore the 4.4 lesion profile: weight paint is propagated inward
        # using the requested physical depth and transition.
        caries_fraction *= sampled_layer_fraction(
            caries_depth,
            caries_depth_mm,
            min(0.5, max(0.05, caries_depth_mm * 0.25)),
            voxel_radius_mm,
        )
        values += caries_fraction * (float(caries_hu) - values)
    if restoration_weight is not None and float(restoration_depth_mm) > 0.0:
        restoration_fraction = smooth_threshold(
            restoration_weight, restoration_threshold, restoration_blend_width
        )
        restoration_depth = np.asarray(
            restoration_surface_depth_mm, dtype=np.float64
        )
        restoration_fraction *= sampled_layer_fraction(
            restoration_depth,
            restoration_depth_mm,
            min(0.5, max(0.05, restoration_depth_mm * 0.25)),
            voxel_radius_mm,
        )
        # Restorative material is the final override, including where it
        # overlaps caries, enamel, or dentin.
        values += restoration_fraction * (float(restoration_hu) - values)
    return np.clip(np.rint(values), MIN_HU_VALUE, MAX_HU_VALUE).astype(np.int16)


def layered_bone_values(
    z_centres,
    lower_surface_m: float,
    upper_surface_m: float,
    cortical_thickness_mm: float,
    transition_mm: float,
    cortical_hu: float,
    cancellous_hu: float,
):
    """Return HU values for a cortical shell around a cancellous interior.

    Distance is evaluated from the paired ray-entry/ray-exit surfaces. This is
    an efficient voxel-shell approximation for the add-on's column voxelizer.
    """

    z = np.asarray(z_centres, dtype=np.float64)
    depth_mm = np.minimum(z - lower_surface_m, upper_surface_m - z)
    return layered_bone_values_from_depth(
        depth_mm,
        cortical_thickness_mm,
        transition_mm,
        cortical_hu,
        cancellous_hu,
    )


def tooth_values(
    z_centres,
    lower_surface_m: float,
    upper_surface_m: float,
    lower_weight: float,
    upper_weight: float,
    enamel_hu: float,
    dentin_hu: float,
    threshold: float,
    blend_width: float,
    enamel_depth_mm: float,
    caries_weight=None,
    caries_hu: float = 500.0,
    caries_threshold: float = 0.5,
    caries_blend_width: float = 0.2,
    caries_depth_mm: float = 0.0,
):
    """Return enamel/dentin HU values with an optional painted caries layer."""

    z = np.asarray(z_centres, dtype=np.float64)
    lower_depth = z - lower_surface_m
    upper_depth = upper_surface_m - z
    nearest_lower = lower_depth <= upper_depth
    weights = np.where(nearest_lower, float(lower_weight), float(upper_weight))
    depth_mm = np.minimum(lower_depth, upper_depth)
    return tooth_values_from_surface(
        depth_mm,
        weights,
        enamel_hu,
        dentin_hu,
        threshold,
        blend_width,
        enamel_depth_mm,
        caries_weight=caries_weight,
        caries_hu=caries_hu,
        caries_threshold=caries_threshold,
        caries_blend_width=caries_blend_width,
        caries_depth_mm=caries_depth_mm,
    )


__all__ = [
    "depth_fraction",
    "layered_bone_values",
    "layered_bone_values_from_depth",
    "painted_bone_values",
    "textured_bone_values",
    "smooth_threshold",
    "sampled_layer_fraction",
    "tooth_values",
    "tooth_values_from_surface",
]
