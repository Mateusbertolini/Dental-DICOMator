"""Dental CT material helpers independent of Blender's runtime."""
from __future__ import annotations

import numpy as np

from .constants import MAX_HU_VALUE, MIN_HU_VALUE


BONE_DENSITY_FRACTIONS = {
    "D1": 1.0,
    "D2": 2.0 / 3.0,
    "D3": 1.0 / 3.0,
    "D4": 0.0,
}


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


def bone_density_fraction(base_density: str, target_density: str, paint_weight):
    """Blend a D1-D4 density preset continuously using raw paint weights.

    D1 maps to 1.0 (densest) and D4 to 0.0 (most porous). Weight paint is
    deliberately continuous: zero retains the object-wide base preset, one
    reaches the painted target, and intermediate weights use smoothstep.
    """

    base = BONE_DENSITY_FRACTIONS.get(str(base_density), BONE_DENSITY_FRACTIONS["D2"])
    target = BONE_DENSITY_FRACTIONS.get(str(target_density), BONE_DENSITY_FRACTIONS["D1"])
    weight = np.clip(np.asarray(paint_weight, dtype=np.float64), 0.0, 1.0)
    smooth_weight = weight * weight * (3.0 - 2.0 * weight)
    return base + smooth_weight * (target - base)


def _value_noise_3d(x, y, z):
    """Vectorised, deterministic 3D value noise with smooth interpolation."""

    x = np.asarray(x, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)
    z = np.asarray(z, dtype=np.float64)
    ix = np.floor(x)
    iy = np.floor(y)
    iz = np.floor(z)
    fx = x - ix
    fy = y - iy
    fz = z - iz
    # Quintic fade produces continuous first and second derivatives and avoids
    # visible lattice boundaries in the resulting DICOM slices.
    ux = fx * fx * fx * (fx * (fx * 6.0 - 15.0) + 10.0)
    uy = fy * fy * fy * (fy * (fy * 6.0 - 15.0) + 10.0)
    uz = fz * fz * fz * (fz * (fz * 6.0 - 15.0) + 10.0)

    def hashed(dx, dy, dz):
        phase = ((ix + dx) * 127.1 + (iy + dy) * 311.7 + (iz + dz) * 74.7)
        return np.mod(np.sin(phase) * 43758.5453123, 1.0)

    def lerp(a, b, amount):
        return a + amount * (b - a)

    n000 = hashed(0.0, 0.0, 0.0)
    n100 = hashed(1.0, 0.0, 0.0)
    n010 = hashed(0.0, 1.0, 0.0)
    n110 = hashed(1.0, 1.0, 0.0)
    n001 = hashed(0.0, 0.0, 1.0)
    n101 = hashed(1.0, 0.0, 1.0)
    n011 = hashed(0.0, 1.0, 1.0)
    n111 = hashed(1.0, 1.0, 1.0)
    nx00 = lerp(n000, n100, ux)
    nx10 = lerp(n010, n110, ux)
    nx01 = lerp(n001, n101, ux)
    nx11 = lerp(n011, n111, ux)
    return lerp(lerp(nx00, nx10, uy), lerp(nx01, nx11, uy), uz)


def _noise_texture_3d(x_mm, y_mm, z_mm, scale: float):
    """Approximate Blender's 3D fBM Noise Texture for voxel coordinates.

    The default scale of 25 corresponds to roughly two-millimetre base
    features in the dental coordinate system. Three octaves reproduce a
    Detail value near 2 with Roughness 0.5 while fixed coordinate rotation
    prevents axis-aligned or grid-like repetition.
    """

    frequency = max(1.0, float(scale)) / 50.0
    x = np.asarray(x_mm, dtype=np.float64) * frequency
    y = np.asarray(y_mm, dtype=np.float64) * frequency
    z = np.asarray(z_mm, dtype=np.float64) * frequency
    # Fixed oblique transform breaks alignment between the value-noise lattice
    # and the DICOM voxel grid without introducing run-to-run randomness.
    xr = 0.819 * x + 0.401 * y + 0.407 * z
    yr = -0.512 * x + 0.843 * y + 0.167 * z
    zr = -0.263 * x - 0.356 * y + 0.897 * z
    result = np.zeros_like(xr, dtype=np.float64)
    amplitude = 1.0
    amplitude_sum = 0.0
    octave_frequency = 1.0
    for _octave in range(3):
        result += amplitude * _value_noise_3d(
            xr * octave_frequency,
            yr * octave_frequency,
            zr * octave_frequency,
        )
        amplitude_sum += amplitude
        amplitude *= 0.5
        octave_frequency *= 2.0
    return result / amplitude_sum


def synthetic_bone_values(
    cortical_depth_mm,
    cortical_weight,
    x_mm,
    y_mm,
    z_mm,
    density_paint_weight,
    *,
    base_density: str = "D2",
    target_density: str = "D1",
    cortical_thickness_mm: float = 2.0,
    cortical_transition_mm: float = 0.5,
    cortical_weight_blend: float = 0.2,
    cortical_hu: float = 800.0,
    pattern_enabled: bool = True,
    pattern_scale_mm: float = 25.0,
    pattern_strength: float = 1.0,
    voxel_radius_mm: float = 0.0,
):
    """Return closed-volume bone HU with painted density and trabeculae.

    This function changes intensity only; it never changes the occupancy mask.
    The coordinate field is deterministic, so identical geometry and settings
    produce identical intersecting trabecular struts on every export.
    """

    density = bone_density_fraction(base_density, target_density, density_paint_weight)
    # Educational synthetic anchors, not scanner-calibrated clinical HU. They
    # are used only when the pattern is disabled or partially blended.
    uniform_hu = 50.0 + 450.0 * density

    if bool(pattern_enabled) and float(pattern_strength) > 1e-9:
        noise = _noise_texture_3d(x_mm, y_mm, z_mm, pattern_scale_mm)
        # D1 lowers the factor threshold and therefore retains more of the
        # noise field as trabeculae. D4 raises it and leaves more void/marrow.
        # The transition band makes both spatial and painted boundaries smooth.
        threshold = 0.42 + 0.24 * (1.0 - density)
        # A broad transition preserves the soft, cloud-like grayscale of a
        # Blender Noise Texture instead of turning it into a binary speckle.
        width = 0.35
        network = np.clip((noise - threshold + 0.5 * width) / width, 0.0, 1.0)
        network = network * network * (3.0 - 2.0 * network)
        # Marrow remains constant across D1-D4. Density painting changes the
        # amount and brightness of trabeculae instead of tinting a whole
        # painted region darker. Even D1 remains below the 800-HU cortex.
        marrow_hu = -100.0
        trabecular_hu = 300.0 + 450.0 * density
        textured = marrow_hu + network * (trabecular_hu - marrow_hu)
        strength = np.clip(float(pattern_strength), 0.0, 1.0)
        cancellous = uniform_hu + strength * (textured - uniform_hu)
    else:
        cancellous = uniform_hu

    raw_cortical_weight = np.asarray(cortical_weight, dtype=np.float64)
    cortical_paint = smooth_threshold(
        raw_cortical_weight, 0.05, cortical_weight_blend
    )
    cortical_paint = np.where(raw_cortical_weight > 0.0, cortical_paint, 0.0)
    cortical_shell = sampled_layer_fraction(
        cortical_depth_mm,
        cortical_thickness_mm,
        cortical_transition_mm,
        voxel_radius_mm,
    )
    cortical_fraction = cortical_paint * cortical_shell
    values = cancellous + cortical_fraction * (float(cortical_hu) - cancellous)
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
    "bone_density_fraction",
    "synthetic_bone_values",
    "textured_bone_values",
    "smooth_threshold",
    "sampled_layer_fraction",
    "tooth_values",
    "tooth_values_from_surface",
]
