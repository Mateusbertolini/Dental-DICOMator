"""Mesh voxelization helpers used by the DICOMator add-on.

All voxelizers share one ray-casting core (:func:`_voxelize_objects_iter`)
that fills axis-aligned voxel columns by casting +Z rays through each mesh
and pairing entry/exit hits. The core is a generator yielding
``(processed_columns, total_columns)`` so callers (e.g. the modal export
operator) can keep the Blender UI responsive; the blocking wrappers drive
the generator to completion and forward progress to an optional callback.
"""
from __future__ import annotations

import math
from typing import Callable, Generator, Optional, Sequence, Tuple

import bpy
import numpy as np
from bpy.types import Object
from mathutils import Vector
from mathutils.bvhtree import BVHTree

from .constants import (
    AIR_DENSITY,
    DEFAULT_DENSITY,
    MAX_HU_VALUE,
    MIN_HU_VALUE,
    MODALITY_CT,
    get_material_intensity,
    resolve_positive_voxel_size,
)
from .dental import (
    depth_fraction,
    sampled_layer_fraction,
    smooth_threshold,
    textured_bone_values,
    tooth_values_from_surface,
)
from .properties import ensure_tooth_vertex_groups

VectorLike = Sequence[float]
VoxelSize = Sequence[float]
ProgressCallback = Optional[Callable[[int, int], None]]
Bounds = Tuple[float, float, float, float, float, float]
VoxelizeResult = Tuple[np.ndarray, Vector, Tuple[int, int, int]]
VoxelizeGenerator = Generator[Tuple[int, int], None, VoxelizeResult]
#: ``(bvh, world_bounds)`` pair produced by :func:`_object_geometry` /
#: :func:`prepare_object_geometry_iter`.
PreparedGeometry = Tuple[BVHTree, Bounds]


def _effective_dental_mode(obj: Object) -> str:
    """Resolve layered behavior from the preset for older saved .blend files."""

    material = str(getattr(obj, "dicomator_material", "CUSTOM"))
    if material == "BONE":
        return "UNIFORM"
    if material == "TOOTH":
        return "TOOTH"
    if material == "DENTAL_PULP":
        return "PULP"
    return str(getattr(obj, "dicomator_dental_mode", "UNIFORM"))


def _face_group_weights(obj: Object, group_name: str) -> dict[int, float]:
    """Return average named vertex-group weight for each mesh polygon."""

    if _effective_dental_mode(obj) != "TOOTH":
        return {}
    group = obj.vertex_groups.get(group_name) if group_name else None
    if group is None:
        return {}
    weights: dict[int, float] = {}
    for polygon in obj.data.polygons:
        vertex_weights = []
        for vertex_index in polygon.vertices:
            vertex = obj.data.vertices[vertex_index]
            vertex_weights.append(next(
                (float(item.weight) for item in vertex.groups if item.group == group.index),
                0.0,
            ))
        weights[int(polygon.index)] = sum(vertex_weights) / max(1, len(vertex_weights))
    return weights if any(value > 0.0 for value in weights.values()) else {}


def _painted_surface(obj: Object, group_name: str, *, use_max_weight: bool = False):
    """Build a world-space BVH containing only faces touched by a paint group."""

    group = obj.vertex_groups.get(group_name) if group_name else None
    if group is None:
        return None
    vertices = _world_vertex_array(obj.data, obj.matrix_world)
    polygons: list[list[int]] = []
    weights: dict[int, float] = {}
    for polygon in obj.data.polygons:
        values = []
        for vertex_index in polygon.vertices:
            vertex = obj.data.vertices[vertex_index]
            values.append(next(
                (float(item.weight) for item in vertex.groups if item.group == group.index),
                0.0,
            ))
        # Lesion paint is often a small brush mark crossing only one vertex of
        # a large/decimated face. Preserve that mark with the maximum weight;
        # broad anatomical layers retain smooth face-average interpolation.
        weight = max(values, default=0.0) if use_max_weight else sum(values) / max(1, len(values))
        if weight > 0.0:
            weights[len(polygons)] = weight
            polygons.append([int(index) for index in polygon.vertices])
    if not polygons:
        return None
    return BVHTree.FromPolygons(vertices.tolist(), polygons), weights


def _unpainted_surface(obj: Object, group_name: str, threshold: float):
    """Build a BVH from faces not assigned to the named paint group."""

    group = obj.vertex_groups.get(group_name) if group_name else None
    vertices = _world_vertex_array(obj.data, obj.matrix_world)
    polygons: list[list[int]] = []
    weights: dict[int, float] = {}
    for polygon in obj.data.polygons:
        values = []
        for vertex_index in polygon.vertices:
            vertex = obj.data.vertices[vertex_index]
            values.append(next(
                (float(item.weight) for item in vertex.groups if group is not None and item.group == group.index),
                0.0,
            ))
        if max(values, default=0.0) < float(threshold):
            weights[len(polygons)] = 1.0
            polygons.append([int(index) for index in polygon.vertices])
    if not polygons:
        return None
    return BVHTree.FromPolygons(vertices.tolist(), polygons), weights


def _face_dental_weights(obj: Object) -> dict[str, object]:
    """Collect independent dental surface geometry."""

    mode = _effective_dental_mode(obj)
    if mode == "BONE":
        # Bone uses the complete closed surface; it does not depend on a
        # painted/evaluated mesh whose topology can differ after modifiers.
        return {"cortical": None}
    if mode == "PULP":
        gutta_name = str(getattr(obj, "dicomator_gutta_group", "GuttaPercha"))
        return {
            "gutta": _painted_surface(obj, gutta_name)
            if bool(getattr(obj, "dicomator_enable_gutta", True)) else None
        }
    if mode != "TOOTH":
        return {"enamel": None, "dentin": None, "caries": None, "restoration": None}
    enamel_enabled = bool(getattr(obj, "dicomator_enable_enamel", True))
    enamel_name = (
        str(getattr(obj, "dicomator_enamel_group", "Enamel"))
        if enamel_enabled else ""
    )
    caries_name = str(getattr(obj, "dicomator_caries_group", "Caries"))
    caries_enabled = bool(getattr(obj, "dicomator_enable_caries", False))
    restoration_name = str(getattr(obj, "dicomator_restoration_group", "Restoration"))
    restoration_enabled = bool(getattr(obj, "dicomator_enable_restoration", False))
    enamel_threshold = float(getattr(obj, "dicomator_enamel_threshold", 0.05))
    return {
        "enamel": _painted_surface(obj, enamel_name) if enamel_enabled else None,
        "dentin": _unpainted_surface(obj, enamel_name, enamel_threshold),
        "caries": _painted_surface(obj, caries_name, use_max_weight=True) if caries_enabled else None,
        "restoration": _painted_surface(obj, restoration_name, use_max_weight=True) if restoration_enabled else None,
        "pdl_painted": _painted_surface(
            obj, str(getattr(obj, "dicomator_pdl_group", "PDL"))
        ) if bool(getattr(obj, "dicomator_enable_pdl", False)) else None,
    }


def _dental_point_values(
    obj: Object,
    bvh: BVHTree,
    x_world: float,
    y_world: float,
    z_centres: np.ndarray,
    face_weights: dict[str, object],
    voxel_radius_mm: float,
) -> np.ndarray | None:
    """Resolve dental HU using true 3D distance to the nearest mesh face."""

    mode = _effective_dental_mode(obj)
    smooth_radiolucent = (
        getattr(obj, "dicomator_material", "CUSTOM") == "RADIOLUCENT"
        and bool(getattr(obj, "dicomator_radiolucent_smooth_margins", False))
    )
    if mode not in {"BONE", "TOOTH", "PULP"} and not smooth_radiolucent:
        return None

    depths_mm = np.empty(len(z_centres), dtype=np.float64)
    face_indices = np.full(len(z_centres), -1, dtype=np.int32)
    for index, z_world in enumerate(z_centres):
        location, _normal, face_index, distance = bvh.find_nearest(
            Vector((x_world, y_world, float(z_world)))
        )
        if location is None or face_index is None or distance is None:
            depths_mm[index] = float("inf")
        else:
            depths_mm[index] = float(distance)
            face_indices[index] = int(face_index)

    if smooth_radiolucent:
        margin_fraction = np.clip(depths_mm / 0.1, 0.0, 1.0)
        target_hu = float(getattr(obj, "dicomator_hu", -500.0))
        values = AIR_DENSITY + margin_fraction * (target_hu - AIR_DENSITY)
        return np.clip(np.rint(values), MIN_HU_VALUE, MAX_HU_VALUE).astype(np.int16)

    if mode == "BONE":
        z_mm = np.asarray(z_centres, dtype=np.float64)
        requested_thickness = float(
            getattr(obj, "dicomator_cortical_thickness_mm", 0.2)
        )
        # A fixed shell can consume thin alveolar meshes completely. Preserve
        # a cancellous centre whenever the ray contains enough sampled voxels.
        finite_depths = depths_mm[np.isfinite(depths_mm)]
        if len(finite_depths) >= 3:
            requested_thickness = min(
                requested_thickness, float(np.max(finite_depths)) * 0.60
            )
        # This changes values only for the already-filled segment supplied by
        # the original ray-pair voxelizer. No shell geometry or boolean mask
        # participates in inside/outside classification.
        return textured_bone_values(
            depths_mm,
            np.full(len(z_centres), x_world),
            np.full(len(z_centres), y_world),
            z_mm,
            requested_thickness,
            getattr(obj, "dicomator_cortical_transition_mm", 0.05),
            getattr(obj, "dicomator_cortical_hu", 800.0),
            getattr(obj, "dicomator_cancellous_hu", 350.0),
            getattr(obj, "dicomator_trabecular_spacing_mm", 0.4),
            getattr(obj, "dicomator_trabecular_contrast_hu", 0.0),
        )
    if mode == "PULP":
        gutta_surface = face_weights.get("gutta")
        gutta_depths = np.full(len(z_centres), float("inf"), dtype=np.float64)
        gutta_weights = np.zeros(len(z_centres), dtype=np.float64)
        if gutta_surface is not None:
            gutta_bvh, gutta_face_weights = gutta_surface
            for index, z_world in enumerate(z_centres):
                location, _normal, face_index, distance = gutta_bvh.find_nearest(
                    Vector((x_world, y_world, float(z_world)))
                )
                if location is not None and face_index is not None and distance is not None:
                    gutta_depths[index] = float(distance)
                    gutta_weights[index] = gutta_face_weights.get(int(face_index), 0.0)
        fraction = smooth_threshold(
            gutta_weights,
            0.05,
            getattr(obj, "dicomator_gutta_blend_width", 0.2),
        )
        gutta_depth = getattr(obj, "dicomator_gutta_depth_mm", 3.0)
        fraction *= sampled_layer_fraction(
            gutta_depths, gutta_depth, min(0.5, max(0.05, gutta_depth * 0.25)),
            voxel_radius_mm,
        )
        pulp_hu = 40.0
        gutta_hu = 4000.0
        values = pulp_hu + fraction * (gutta_hu - pulp_hu)
        return np.clip(np.rint(values), MIN_HU_VALUE, MAX_HU_VALUE).astype(np.int16)
    if mode == "TOOTH":
        enamel_surface = face_weights.get("enamel")
        dentin_surface = face_weights.get("dentin")
        caries_surface = face_weights.get("caries")
        restoration_surface = face_weights.get("restoration")
        pdl_painted_surface = face_weights.get("pdl_painted")

        def _sample(surface):
            distances = np.full(len(z_centres), float("inf"), dtype=np.float64)
            weights = np.zeros(len(z_centres), dtype=np.float64)
            if surface is None:
                return distances, weights
            surface_bvh, surface_weights = surface
            for index, z_world in enumerate(z_centres):
                location, _normal, face_index, distance = surface_bvh.find_nearest(
                    Vector((x_world, y_world, float(z_world)))
                )
                if location is not None and face_index is not None and distance is not None:
                    distances[index] = float(distance)
                    weights[index] = surface_weights.get(int(face_index), 0.0)
            return distances, weights

        enamel_depths, enamel = _sample(enamel_surface)
        pdl_depths, pdl = _sample(dentin_surface)
        caries_depths, caries = _sample(caries_surface)
        restoration_depths, restoration = _sample(restoration_surface)
        pdl_painted_depths, pdl_painted = _sample(pdl_painted_surface)
        caries_depth_mm = float(getattr(obj, "dicomator_caries_depth_mm", 2.0))
        if caries_depth_mm < 1.0 or caries_depth_mm > 4.5:
            caries_depth_mm = 2.0
        return tooth_values_from_surface(
            enamel_depths,
            enamel,
            2000.0,
            1400.0,
            0.05,
            getattr(obj, "dicomator_enamel_blend_width", 0.2),
            getattr(obj, "dicomator_enamel_depth_mm", 1.0),
            caries_weight=caries if caries_surface is not None else None,
            caries_hu=500.0,
            caries_threshold=0.05,
            caries_blend_width=getattr(obj, "dicomator_caries_blend_width", 0.5),
            caries_depth_mm=caries_depth_mm,
            caries_surface_depth_mm=caries_depths,
            pdl_weight=pdl if (
                dentin_surface is not None
                and bool(getattr(obj, "dicomator_enable_pdl", False))
            ) else None,
            pdl_hu=-100.0,
            pdl_depth_mm=getattr(obj, "dicomator_pdl_depth_mm", 0.25),
            pdl_surface_depth_mm=pdl_depths,
            pdl_painted_weight=pdl_painted if pdl_painted_surface is not None else None,
            pdl_painted_surface_depth_mm=pdl_painted_depths,
            restoration_weight=restoration if restoration_surface is not None else None,
            restoration_hu=3000.0,
            restoration_threshold=0.05,
            restoration_blend_width=getattr(obj, "dicomator_restoration_blend_width", 0.2),
            restoration_depth_mm=getattr(obj, "dicomator_restoration_depth_mm", 1.0),
            restoration_surface_depth_mm=restoration_depths,
            voxel_radius_mm=voxel_radius_mm,
        )
    return None

#: Ray hits closer together than this distance (millimetres) are merged before
#: entry/exit pairing. A ray grazing an edge shared by two faces reports the
#: same surface twice; without merging, the duplicate flips the inside/outside
#: parity and incorrectly fills the remainder of the voxel column.
_HIT_MERGE_TOLERANCE_M = 0.01

#: Number of voxel columns processed between progress yields.
_PROGRESS_CHUNK = 2048

#: Hard cap on surface crossings recorded for one voxel column. A closed mesh
#: produces a handful; a runaway count means the marching ray stopped making
#: progress, so the column is abandoned rather than looping forever.
_MAX_COLUMN_HITS = 4096

#: Smallest absolute distance (millimetres) a restarted ray is pushed past the face
#: it just hit.
_RAY_RESTART_EPSILON_M = 0.001


def restart_z_past_hit(hit_z: float) -> float:
    """Return a Z just past ``hit_z`` so a restarted +Z ray clears that face.

    ``mathutils.Vector`` stores single-precision floats, whose spacing already
    can swallow very small fixed nudges at large coordinates. A 0.001 mm minimum
    keeps the restarted ray beyond the face for dental-sized geometry while
    remaining far below the configured dental voxel spacing.
    """

    return hit_z + max(_RAY_RESTART_EPSILON_M, abs(hit_z) * 1e-6)


def _resolve_voxel_size(voxel_size: VoxelSize | float) -> Tuple[float, float, float]:
    """Return ``(vx, vy, vz)`` in millimetre Blender units."""
    return resolve_positive_voxel_size(voxel_size)


def _object_priority_key(obj: Object) -> tuple[int, int, str, str]:
    """Sort low-priority objects first so higher priorities overwrite them.

    Dental presets use a fixed material tier ahead of the legacy hidden
    priority. Titanium is deliberately processed last so an implant or metal
    restoration cannot be hidden by overlapping bone, tooth, pulp, or other
    image meshes. Pulp remains above ordinary meshes for its guarded
    dentin-only replacement, but below titanium.
    """

    material = str(getattr(obj, "dicomator_material", "CUSTOM"))
    material_tier = 2 if material == "TITANIUM" else (
        1 if _effective_dental_mode(obj) == "PULP" else 0
    )
    return (
        material_tier,
        int(getattr(obj, "dicomator_priority", 0)),
        obj.name.casefold(),
        obj.name,
    )


def _world_vertex_array(mesh: bpy.types.Mesh, matrix_world) -> np.ndarray:
    """Return the mesh vertices as an ``(N, 3)`` world-space float64 array.

    Uses ``foreach_get`` plus one NumPy matrix multiply instead of a Python
    loop over vertices, which is dramatically faster on dense meshes. The
    returned buffer is caller-owned, so it stays valid after
    ``to_mesh_clear()``.
    """
    count = len(mesh.vertices)
    coords = np.empty(count * 3, dtype=np.float64)
    mesh.vertices.foreach_get("co", coords)
    matrix = np.array(matrix_world, dtype=np.float64)
    return coords.reshape(count, 3) @ matrix[:3, :3].T + matrix[:3, 3]


def _mesh_polygon_indices(mesh: bpy.types.Mesh) -> list[list[int]]:
    """Return per-polygon vertex index lists via ``foreach_get`` batch reads."""
    poly_count = len(mesh.polygons)
    if poly_count == 0:
        return []
    loop_start = np.empty(poly_count, dtype=np.int32)
    mesh.polygons.foreach_get("loop_start", loop_start)
    loop_verts = np.empty(len(mesh.loops), dtype=np.int32)
    mesh.loops.foreach_get("vertex_index", loop_verts)
    return [segment.tolist() for segment in np.split(loop_verts, loop_start[1:])]


def _object_geometry(
    obj: Object,
    depsgraph: Optional[bpy.types.Depsgraph] = None,
    *,
    apply_modifiers: bool = False,
) -> Optional[PreparedGeometry]:
    """Build a world-space BVH for ``obj`` plus its world-space bounds.

    Returns ``(bvh, (min_x, max_x, min_y, max_y, min_z, max_z))``, or ``None``
    when the (evaluated) mesh has no vertices or faces.
    """
    if apply_modifiers and depsgraph is not None:
        obj_eval = obj.evaluated_get(depsgraph)
        mesh = obj_eval.to_mesh(preserve_all_data_layers=False, depsgraph=depsgraph)
        try:
            verts_world = _world_vertex_array(mesh, obj_eval.matrix_world)
            polygons = _mesh_polygon_indices(mesh)
        finally:
            obj_eval.to_mesh_clear()
    else:
        mesh = obj.data
        verts_world = _world_vertex_array(mesh, obj.matrix_world)
        polygons = _mesh_polygon_indices(mesh)
    if verts_world.size == 0 or not polygons:
        return None
    mins = verts_world.min(axis=0)
    maxs = verts_world.max(axis=0)
    bounds: Bounds = (
        float(mins[0]), float(maxs[0]),
        float(mins[1]), float(maxs[1]),
        float(mins[2]), float(maxs[2]),
    )
    return BVHTree.FromPolygons(verts_world.tolist(), polygons), bounds


def _objects_world_bounds(
    objects: Sequence[Object],
    depsgraph: Optional[bpy.types.Depsgraph],
    *,
    apply_modifiers: bool,
) -> Bounds:
    """Return the combined world-space bounds of ``objects``."""
    min_x = min_y = min_z = float('inf')
    max_x = max_y = max_z = float('-inf')
    for obj in objects:
        if apply_modifiers and depsgraph is not None:
            obj_eval = obj.evaluated_get(depsgraph)
            mesh = obj_eval.to_mesh(preserve_all_data_layers=False, depsgraph=depsgraph)
            try:
                verts_world = _world_vertex_array(mesh, obj_eval.matrix_world)
            finally:
                obj_eval.to_mesh_clear()
            if verts_world.size:
                mins = verts_world.min(axis=0)
                maxs = verts_world.max(axis=0)
                min_x = min(min_x, float(mins[0]))
                max_x = max(max_x, float(maxs[0]))
                min_y = min(min_y, float(mins[1]))
                max_y = max(max_y, float(maxs[1]))
                min_z = min(min_z, float(mins[2]))
                max_z = max(max_z, float(maxs[2]))
        else:
            for corner in obj.bound_box:
                world_corner = obj.matrix_world @ Vector(corner)
                min_x = min(min_x, world_corner.x)
                max_x = max(max_x, world_corner.x)
                min_y = min(min_y, world_corner.y)
                max_y = max(max_y, world_corner.y)
                min_z = min(min_z, world_corner.z)
                max_z = max(max_z, world_corner.z)
    return min_x, max_x, min_y, max_y, min_z, max_z


def _voxelize_objects_iter(
    objects: Sequence[Object],
    voxel_size: VoxelSize | float,
    padding: int,
    bbox_override: Optional[Bounds],
    *,
    apply_modifiers: bool,
    depsgraph: Optional[bpy.types.Depsgraph],
    value_for_object: Callable[[Object], float],
    dtype: np.dtype,
    background_value: float,
    accumulate: bool,
    label: str,
    messages: Optional[list[str]] = None,
    prepared: Optional[dict[str, PreparedGeometry]] = None,
) -> VoxelizeGenerator:
    """Shared ray-casting voxelizer.

    Fills a ``(width, height, depth)`` grid of ``dtype`` initialized to
    ``background_value``. Meshes are processed by ``dicomator_priority`` then
    name; when ``accumulate`` is False the highest-priority mesh wins any
    overlapping voxels, when True the per-object values are summed.

    When ``messages`` is provided, human-readable warnings about skipped
    objects are appended to it so callers can surface them in the UI.

    ``prepared`` optionally supplies pre-built world-space geometry (from
    :func:`prepare_object_geometry_iter`) keyed by object name, avoiding a
    second mesh evaluation and BVH build; objects missing from the cache are
    treated as skipped (they had no usable geometry when prepared).
    """
    if not objects:
        raise ValueError(f"No objects provided for {label} voxelization")

    if apply_modifiers and depsgraph is None:
        depsgraph = bpy.context.evaluated_depsgraph_get()

    vx, vy, vz = _resolve_voxel_size(voxel_size)

    if bbox_override is not None:
        min_x, max_x, min_y, max_y, min_z, max_z = bbox_override
    else:
        min_x, max_x, min_y, max_y, min_z, max_z = _objects_world_bounds(
            objects, depsgraph, apply_modifiers=apply_modifiers
        )
        min_x -= padding * vx
        max_x += padding * vx
        min_y -= padding * vy
        max_y += padding * vy
        min_z -= padding * vz
        max_z += padding * vz

    width = max(1, int(math.ceil((max_x - min_x) / vx)))
    height = max(1, int(math.ceil((max_y - min_y) / vy)))
    depth = max(1, int(math.ceil((max_z - min_z) / vz)))
    origin = Vector((min_x, min_y, min_z))

    grid = np.full((width, height, depth), background_value, dtype=dtype)

    sorted_objects = sorted(objects, key=_object_priority_key)
    dentin_values = {
        int(round(float(getattr(item, "dicomator_dentin_hu", 1400.0))))
        for item in sorted_objects
        if _effective_dental_mode(item) == "TOOTH"
    }
    def _skip(reason: str) -> None:
        print(reason)
        if messages is not None:
            messages.append(reason)

    skipped_names: list[str] = []
    object_data: list[tuple[Object, BVHTree, float, int, int, int, int, dict[str, object]]] = []
    for obj in sorted_objects:
        # Final export-time safeguard for files loaded before this version or
        # objects whose material was assigned through a script without a UI
        # update callback.
        ensure_tooth_vertex_groups(obj)
        if (
            _effective_dental_mode(obj) == "PULP"
            and bool(getattr(obj, "dicomator_enable_gutta", True))
        ):
            obj.dicomator_gutta_group = "GuttaPercha"
            if obj.vertex_groups.get("GuttaPercha") is None:
                obj.vertex_groups.new(name="GuttaPercha")
        if prepared is not None:
            geometry = prepared.get(obj.name)
        else:
            geometry = _object_geometry(obj, depsgraph=depsgraph, apply_modifiers=apply_modifiers)
        if geometry is None:
            skipped_names.append(obj.name)
            _skip(f"Skipped '{obj.name}' during {label} voxelization: mesh has no faces")
            continue
        bvh, (obj_min_x, obj_max_x, obj_min_y, obj_max_y, _obj_min_z, _obj_max_z) = geometry
        # Rays outside the object's XY footprint cannot intersect it, so only
        # the covered column range (plus one voxel of slack) is visited. For
        # small objects inside a large grid this skips almost all columns.
        ix0 = max(0, int(math.floor((obj_min_x - min_x) / vx)) - 1)
        ix1 = min(width - 1, int(math.ceil((obj_max_x - min_x) / vx)) + 1)
        iy0 = max(0, int(math.floor((obj_min_y - min_y) / vy)) - 1)
        iy1 = min(height - 1, int(math.ceil((obj_max_y - min_y) / vy)) + 1)
        if ix1 < ix0 or iy1 < iy0:
            skipped_names.append(obj.name)
            _skip(f"Skipped '{obj.name}' during {label} voxelization: outside the voxel grid")
            continue
        face_weights = _face_dental_weights(obj)
        if (
            _effective_dental_mode(obj) == "TOOTH"
            and bool(getattr(obj, "dicomator_enable_enamel", True))
            and not face_weights["enamel"]
        ):
            _skip(
                f"'{obj.name}' has no usable enamel vertex-group weights; "
                "the tooth will voxelize as dentin"
            )
        if (
            _effective_dental_mode(obj) == "TOOTH"
            and getattr(obj, "dicomator_enable_caries", False)
            and not face_weights["caries"]
        ):
            _skip(
                f"'{obj.name}' has caries enabled but no usable caries "
                "vertex-group weights; no decay layer will be added"
            )
        if (
            _effective_dental_mode(obj) == "TOOTH"
            and getattr(obj, "dicomator_enable_restoration", False)
            and not face_weights["restoration"]
        ):
            _skip(
                f"'{obj.name}' has restorative material enabled but no usable "
                "Restoration weights; no restorative layer will be added"
            )
        object_data.append((obj, bvh, float(value_for_object(obj)), ix0, ix1, iy0, iy1, face_weights))

    if not object_data:
        raise ValueError(
            f"No voxelizable {label} objects: all selected meshes were skipped "
            f"({', '.join(skipped_names)})"
        )

    print(f"Voxelizing {len(object_data)} object(s) into {width}x{height}x{depth} {label} grid...")

    xs = [float(min_x + (index + 0.5) * vx) for index in range(width)]
    ys = [float(min_y + (index + 0.5) * vy) for index in range(height)]
    z0_center = min_z + 0.5 * vz
    inv_dz = 1.0 / vz
    ray_dir = Vector((0.0, 0.0, 1.0))
    ray_start_z = min_z - 2.0 * vz
    max_dist = (max_z - min_z) + 4.0 * vz

    total_columns = max(
        1,
        sum(
            (ix1 - ix0 + 1) * (iy1 - iy0 + 1)
            for _obj, _bvh, _value, ix0, ix1, iy0, iy1, _weights in object_data
        ),
    )
    processed = 0

    for obj, bvh, value, ix0, ix1, iy0, iy1, face_weights in object_data:
        object_name = obj.name
        ray_cast = bvh.ray_cast
        odd_columns = 0
        recovered_columns = 0
        stalled_rays = 0

        def _merged_hits(x_world: float, y_world: float) -> list[tuple[float, int]]:
            nonlocal stalled_rays
            origin_ray = Vector((x_world, y_world, ray_start_z))
            hits: list[tuple[float, int]] = []
            while True:
                location, _normal, _face_index, _distance = ray_cast(
                    origin_ray, ray_dir, max_dist
                )
                if location is None:
                    break
                hits.append((float(location.z), int(_face_index)))
                if len(hits) >= _MAX_COLUMN_HITS:
                    stalled_rays += 1
                    break
                next_origin = Vector(
                    (location.x, location.y, restart_z_past_hit(float(location.z)))
                )
                if next_origin.z <= origin_ray.z:
                    # The restart point rounded back onto the face just hit, so
                    # the next cast would report the same crossing forever.
                    stalled_rays += 1
                    break
                origin_ray = next_origin
            hits.sort(key=lambda item: item[0])
            merged: list[tuple[float, int]] = []
            for hit_z, face_index in hits:
                if not merged or (hit_z - merged[-1][0]) > _HIT_MERGE_TOLERANCE_M:
                    merged.append((hit_z, face_index))
            return merged

        for ix in range(ix0, ix1 + 1):
            x_world = xs[ix]
            for iy in range(iy0, iy1 + 1):
                y_world = ys[iy]
                merged = _merged_hits(x_world, y_world)
                if len(merged) % 2:
                    odd_columns += 1
                    # Retry edge/vertex-grazing rays with a small deterministic
                    # sub-voxel offset. The first even result preserves stable
                    # output while avoiding arbitrary unpaired surface loss.
                    jittered_hits = None
                    for x_fraction, y_fraction in (
                        (0.173, 0.271),
                        (-0.173, 0.271),
                        (0.173, -0.271),
                        (-0.173, -0.271),
                    ):
                        candidate = _merged_hits(
                            x_world + x_fraction * vx,
                            y_world + y_fraction * vy,
                        )
                        if candidate and len(candidate) % 2 == 0:
                            jittered_hits = candidate
                            break
                    if jittered_hits is not None:
                        merged = jittered_hits
                        recovered_columns += 1

                if merged:
                    for start in range(0, len(merged) - 1, 2):
                        lower, lower_face = merged[start]
                        upper, upper_face = merged[start + 1]
                        start_idx = int(math.ceil((lower - z0_center) * inv_dz))
                        end_idx = int(math.floor((upper - z0_center) * inv_dz))
                        if end_idx >= start_idx:
                            s = max(0, start_idx)
                            e = min(depth - 1, end_idx)
                            if e >= s:
                                if accumulate:
                                    grid[ix, iy, s:e + 1] += value
                                else:
                                    z_centres = z0_center + np.arange(s, e + 1) * vz
                                    dental_values = _dental_point_values(
                                        obj, bvh, x_world, y_world, z_centres,
                                        face_weights,
                                        0.5 * math.sqrt(vx * vx + vy * vy + vz * vz),
                                    )
                                    target = grid[ix, iy, s:e + 1]
                                    if (
                                        _effective_dental_mode(obj) == "PULP"
                                        and dentin_values
                                        and dental_values is not None
                                    ):
                                        # Pulp/gutta replaces only unmodified dentin.
                                        # Enamel, caries, restoration and their blended
                                        # margins remain protected.
                                        replace = np.isin(target, tuple(dentin_values))
                                        target[replace] = dental_values[replace]
                                    else:
                                        target[:] = value if dental_values is None else dental_values

                processed += 1
                if processed % _PROGRESS_CHUNK == 0:
                    yield processed, total_columns

        if stalled_rays:
            _skip(
                f"'{object_name}' abandoned {stalled_rays} ray(s) during {label} "
                "voxelization after they stopped advancing past a surface; the "
                "affected columns may be incompletely filled (check for "
                "coincident faces or geometry far from the world origin)"
            )

        if odd_columns:
            unresolved = odd_columns - recovered_columns
            warning = (
                f"'{object_name}' produced {odd_columns} odd ray-intersection "
                f"column(s) during {label} voxelization; {recovered_columns} "
                f"recovered with deterministic sub-voxel rays"
            )
            if unresolved:
                warning += f", {unresolved} remained ambiguous and may need mesh repair"
            _skip(warning)

    print(f"Voxelization complete ({label} grid).")
    yield total_columns, total_columns
    return grid, origin, (width, height, depth)


def prepare_object_geometry_iter(
    objects: Sequence[Object],
    depsgraph: Optional[bpy.types.Depsgraph],
    *,
    apply_modifiers: bool,
) -> Generator[Tuple[int, int], None, dict[str, PreparedGeometry]]:
    """Evaluate each object's world-space BVH and bounds exactly once.

    Yields ``(objects_done, total_objects)`` and returns a dict keyed by
    object name; objects without usable geometry are omitted. The cache is
    only valid for the frame/depsgraph it was built with — callers must not
    reuse it across animation frames.
    """
    prepared: dict[str, PreparedGeometry] = {}
    total = max(1, len(objects))
    for index, obj in enumerate(objects, start=1):
        geometry = _object_geometry(obj, depsgraph=depsgraph, apply_modifiers=apply_modifiers)
        if geometry is not None:
            prepared[obj.name] = geometry
        yield index, total
    return prepared


def _drive(generator: VoxelizeGenerator, progress_callback: ProgressCallback) -> VoxelizeResult:
    """Run a voxelize generator to completion, forwarding progress."""
    while True:
        try:
            current, total = next(generator)
        except StopIteration as stop:
            return stop.value
        if progress_callback:
            progress_callback(current, total)


def voxelize_objects_to_hu_iter(
    objects: Sequence[Object],
    voxel_size: VoxelSize | float = 1.0,
    padding: int = 1,
    bbox_override: Optional[Bounds] = None,
    *,
    apply_modifiers: bool = False,
    depsgraph: Optional[bpy.types.Depsgraph] = None,
    background_value: float = AIR_DENSITY,
    messages: Optional[list[str]] = None,
    prepared: Optional[dict[str, PreparedGeometry]] = None,
) -> VoxelizeGenerator:
    """Generator variant of :func:`voxelize_objects_to_hu`.

    ``background_value`` fills voxels not covered by any mesh. CT exports use
    air (-1000 HU); MR exports should pass 0 (signal void) instead.
    ``messages`` collects skipped-object warnings for the caller's UI;
    ``prepared`` reuses geometry from :func:`prepare_object_geometry_iter`.
    """
    def hu_for_object(obj: Object) -> float:
        material = str(getattr(obj, "dicomator_material", "CUSTOM"))
        preset_value = get_material_intensity(material, MODALITY_CT)
        hu_value = float(
            getattr(obj, "dicomator_hu", DEFAULT_DENSITY)
            if preset_value is None
            else preset_value
        )
        return max(MIN_HU_VALUE, min(MAX_HU_VALUE, hu_value))

    return _voxelize_objects_iter(
        objects,
        voxel_size,
        padding,
        bbox_override,
        apply_modifiers=apply_modifiers,
        depsgraph=depsgraph,
        value_for_object=hu_for_object,
        dtype=np.int16,
        background_value=float(background_value),
        accumulate=False,
        label="HU",
        messages=messages,
        prepared=prepared,
    )


def voxelize_objects_to_hu(
    objects: Sequence[Object],
    voxel_size: VoxelSize | float = 1.0,
    padding: int = 1,
    progress_callback: ProgressCallback = None,
    bbox_override: Optional[Bounds] = None,
    *,
    apply_modifiers: bool = False,
    depsgraph: Optional[bpy.types.Depsgraph] = None,
    background_value: float = AIR_DENSITY,
) -> VoxelizeResult:
    """Voxelize multiple objects into a single intensity grid.

    Overlapping solids resolve deterministically: meshes are processed by
    ``dicomator_priority`` and then by name, so the highest-priority mesh wins
    conflicting voxels and names break ties.
    """
    return _drive(
        voxelize_objects_to_hu_iter(
            objects,
            voxel_size,
            padding,
            bbox_override,
            apply_modifiers=apply_modifiers,
            depsgraph=depsgraph,
            background_value=background_value,
        ),
        progress_callback,
    )


def voxelize_objects_to_dose_iter(
    objects: Sequence[Object],
    voxel_size: VoxelSize | float = 1.0,
    padding: int = 1,
    bbox_override: Optional[Bounds] = None,
    *,
    apply_modifiers: bool = False,
    depsgraph: Optional[bpy.types.Depsgraph] = None,
    accumulate: bool = True,
    messages: Optional[list[str]] = None,
    prepared: Optional[dict[str, PreparedGeometry]] = None,
) -> VoxelizeGenerator:
    """Generator variant of :func:`voxelize_objects_to_dose`."""
    def dose_for_object(obj: Object) -> float:
        # Clamp dose to non-negative values; negative dose has no physical meaning.
        return max(0.0, float(getattr(obj, "dicomator_dose", 0.0)))

    return _voxelize_objects_iter(
        objects,
        voxel_size,
        padding,
        bbox_override,
        apply_modifiers=apply_modifiers,
        depsgraph=depsgraph,
        value_for_object=dose_for_object,
        dtype=np.float32,
        background_value=0.0,
        accumulate=accumulate,
        label="dose",
        messages=messages,
        prepared=prepared,
    )


def voxelize_objects_to_dose(
    objects: Sequence[Object],
    voxel_size: VoxelSize | float = 1.0,
    padding: int = 1,
    progress_callback: ProgressCallback = None,
    bbox_override: Optional[Bounds] = None,
    *,
    apply_modifiers: bool = False,
    depsgraph: Optional[bpy.types.Depsgraph] = None,
    accumulate: bool = True,
) -> VoxelizeResult:
    """Voxelize multiple objects into a dose grid (Gy).

    Reads ``obj.dicomator_dose`` (float, Gy) per object and returns a
    ``float32`` array (background = 0.0 Gy). When ``accumulate`` is True
    (default) overlapping dose volumes sum, which matches how physical dose
    from multiple sources combines; when False the highest-priority mesh
    overwrites earlier assignments wherever voxels overlap, with names used
    to break equal-priority ties.
    """
    return _drive(
        voxelize_objects_to_dose_iter(
            objects,
            voxel_size,
            padding,
            bbox_override,
            apply_modifiers=apply_modifiers,
            depsgraph=depsgraph,
            accumulate=accumulate,
        ),
        progress_callback,
    )


def voxelize_mesh(
    obj: Object,
    voxel_size: VectorLike | float = 1.0,
    padding: int = 1,
) -> VoxelizeResult:
    """Voxelize a single object's base mesh into a binary occupancy grid."""
    return _drive(
        _voxelize_objects_iter(
            [obj],
            voxel_size,
            padding,
            None,
            apply_modifiers=False,
            depsgraph=None,
            value_for_object=lambda _obj: 1.0,
            dtype=np.uint8,
            background_value=0.0,
            accumulate=False,
            label="occupancy",
        ),
        None,
    )


__all__ = [
    "prepare_object_geometry_iter",
    "restart_z_past_hit",
    "voxelize_mesh",
    "voxelize_objects_to_hu",
    "voxelize_objects_to_hu_iter",
    "voxelize_objects_to_dose",
    "voxelize_objects_to_dose_iter",
]
