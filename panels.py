"""UI panel definitions for the DICOMator add-on."""
from __future__ import annotations

import math
import os

import bpy
from bpy.props import StringProperty
from bpy.types import Context, Operator, Panel
from mathutils import Vector

from .constants import (
    MAX_TOTAL_VOXELS,
    ensure_pydicom_available,
    estimate_peak_memory_bytes_for_props,
    get_pydicom_error,
    grid_limits_exceeded,
)
from .drr import resolve_drr_detector_size
from .utils import get_float_prop, get_str_prop, resolve_output_directory


def _selected_meshes(context: Context) -> list[bpy.types.Object]:
    """Return selected mesh objects, falling back to the active mesh."""

    selected = [obj for obj in context.selected_objects if obj.type == 'MESH']
    active_obj = context.active_object
    if not selected and active_obj and active_obj.type == 'MESH':
        selected = [active_obj]
    return selected


class DICOMATOR_OT_weight_paint_group(Operator):
    """Activate a managed dental group and enter Weight Paint mode."""

    bl_idname = "dicomator.weight_paint_group"
    bl_label = "Weight Paint"
    bl_options = {'REGISTER', 'UNDO'}

    group_name: StringProperty(default="")

    def execute(self, context):
        obj = context.active_object
        if obj is None or obj.type != 'MESH':
            self.report({'ERROR'}, "Select a mesh object first")
            return {'CANCELLED'}
        if obj.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        group = obj.vertex_groups.get(self.group_name)
        if group is None:
            group = obj.vertex_groups.new(name=self.group_name)
        obj.vertex_groups.active_index = group.index
        bpy.ops.object.mode_set(mode='WEIGHT_PAINT')
        return {'FINISHED'}


class DICOMATOR_OT_object_mode(Operator):
    """Return the active dental mesh to Object mode."""

    bl_idname = "dicomator.object_mode"
    bl_label = "Back to Object Mode"

    def execute(self, context):
        obj = context.active_object
        if obj is not None and obj.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        return {'FINISHED'}


def _paint_mode_buttons(layout, group_name: str) -> None:
    row = layout.row(align=True)
    split = row.split(factor=0.4, align=True)
    split.label(text="")
    controls = split.row(align=True)
    op = controls.operator("dicomator.weight_paint_group", text="Weight Paint", icon='WPAINT_HLT')
    op.group_name = group_name
    controls.operator("dicomator.object_mode", text="Object Mode", icon='OBJECT_DATA')


def _export_type_counts(objects: list[bpy.types.Object]) -> dict[str, int]:
    """Count selected meshes by their DICOM export role."""

    return {"CT": len(objects), "RTDOSE": 0, "RTSTRUCT": 0}


def _export_summary(objects: list[bpy.types.Object]) -> str:
    """Return a compact summary of selected export roles."""

    counts = _export_type_counts(objects)
    parts = []
    if counts["CT"]:
        parts.append(f"Image {counts['CT']}")
    if counts["RTDOSE"]:
        parts.append(f"Dose {counts['RTDOSE']}")
    if counts["RTSTRUCT"]:
        parts.append(f"Struct {counts['RTSTRUCT']}")
    return " | ".join(parts)


def _selection_bounds(objects: list[bpy.types.Object]) -> tuple[float, float, float]:
    """Return selected-object dimensions in millimetre Blender units."""

    bbox_corners = []
    for obj in objects:
        bbox_corners.extend([obj.matrix_world @ Vector(corner) for corner in obj.bound_box])
    min_x = min(corner.x for corner in bbox_corners)
    max_x = max(corner.x for corner in bbox_corners)
    min_y = min(corner.y for corner in bbox_corners)
    max_y = max(corner.y for corner in bbox_corners)
    min_z = min(corner.z for corner in bbox_corners)
    max_z = max(corner.z for corner in bbox_corners)
    return max_x - min_x, max_y - min_y, max_z - min_z


def _grid_estimate(
    dimensions_m: tuple[float, float, float],
    props: bpy.types.PropertyGroup,
) -> tuple[int, int, int, int] | None:
    """Estimate voxel dimensions and total voxel count for the selection."""

    obj_width, obj_height, obj_depth = dimensions_m
    lateral_mm = 0.25
    axial_mm = 0.5
    if lateral_mm <= 0.0 or axial_mm <= 0.0:
        return None

    vx = lateral_mm
    vy = lateral_mm
    vz = axial_mm
    est_width = int(math.ceil((obj_width + 2 * vx) / vx))
    est_height = int(math.ceil((obj_height + 2 * vy) / vy))
    est_depth = int(math.ceil((obj_depth + 2 * vz) / vz))
    total_voxels = est_width * est_height * est_depth
    return est_width, est_height, est_depth, total_voxels


def _draw_export_action(layout: bpy.types.UILayout, context: Context) -> None:
    """Draw the primary export action and blocking status."""

    props = context.scene.dicomator_props
    button_text = "Export DICOM"

    if not ensure_pydicom_available():
        layout.label(text="pydicom unavailable", icon='ERROR')
        error_detail = get_pydicom_error()
        if error_detail:
            layout.label(text=error_detail[:120], icon='INFO')
        return

    export_dir = resolve_output_directory(get_str_prop(props, "export_directory", ""))
    if not export_dir or not export_dir.strip():
        layout.label(text="Choose an export folder", icon='FILE_FOLDER')
        return
    if os.path.exists(export_dir) and not os.path.isdir(export_dir):
        layout.label(text="Export path must be a folder", icon='ERROR')
        return
    if os.path.isdir(export_dir):
        try:
            output_has_files = bool(os.listdir(export_dir))
        except OSError:
            layout.label(text="Cannot inspect export folder", icon='ERROR')
            return
        if output_has_files:
            layout.label(text="Choose a new or empty export folder", icon='ERROR')
            return

    unit_scale = float(
        getattr(getattr(context.scene, "unit_settings", None), "scale_length", 1.0) or 1.0
    )
    if not math.isclose(unit_scale, 0.001, rel_tol=0.0, abs_tol=1e-8):
        layout.label(text="Export will set Unit Scale to 0.001 (millimetres)", icon='INFO')

    if not (context.active_object and context.active_object.type == 'MESH'):
        layout.label(text="Select a mesh", icon='INFO')
        return

    selected_meshes = _selected_meshes(context)
    counts = _export_type_counts(selected_meshes)
    if not counts["CT"]:
        layout.label(text="No image mesh selected", icon='ERROR')
        return

    estimate = _grid_estimate(_selection_bounds(selected_meshes), props)
    # The estimated peak memory has to be part of this check: the export
    # operator aborts on it too, so leaving it out let the button look clear
    # for a grid that would be rejected the moment it was pressed.
    if estimate is not None and grid_limits_exceeded(
        *estimate[:3], estimate_peak_memory_bytes_for_props(estimate[3], props)
    ):
        if getattr(props, "allow_oversized_grids", False):
            layout.label(text="Oversized grid allowed", icon='ERROR')
        else:
            layout.label(text="Grid too large - export will abort", icon='ERROR')
    layout.operator("dicomator.export_dicom", text=button_text, icon='EXPORT')


class VIEW3D_PT_dicomator_panel(Panel):
    """Root panel that hosts the add-on UI."""

    bl_label = "DICOMator"
    bl_idname = "VIEW3D_PT_dicomator_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Dental DICOMator"

    def draw(self, context: Context) -> None:  # pragma: no cover - Blender UI code
        layout = self.layout
        scene = context.scene
        props = scene.dicomator_props
        # Blender 5.2 forbids modifying ID data while a panel is being drawn.
        # Scene-unit migration is performed by registration and export instead.
        layout.label(text="Pixels: 0.25 mm | slices every 0.5 mm | 1 BU = 1 mm", icon='DRIVER_DISTANCE')
        layout.label(text="Synthetic research data only - not clinical", icon='ERROR')
        if not (context.active_object and context.active_object.type == 'MESH'):
            layout.label(text="Select a mesh object to export", icon='INFO')
            return
        else:
            selected_meshes = _selected_meshes(context)
            layout.label(text=_export_summary(selected_meshes), icon='MESH_DATA')

        layout.label(text="Dental CT image-series export", icon='IMAGE_DATA')


class VIEW3D_PT_dicomator_selection_info(Panel):
    bl_label = "3.1 Export Estimate"
    bl_idname = "VIEW3D_PT_dicomator_selection_info"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Dental DICOMator"
    bl_parent_id = "VIEW3D_PT_dicomator_export_settings"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context: Context) -> None:  # pragma: no cover - Blender UI code
        layout = self.layout
        props = context.scene.dicomator_props
        if not (context.active_object and context.active_object.type == 'MESH'):
            layout.label(text="No mesh selected", icon='INFO')
            return

        selected_meshes = _selected_meshes(context)
        active_obj = context.active_object
        selection_count = len(selected_meshes)
        if selection_count > 1:
            layout.label(text=f"Selected: {selection_count} meshes (Active: {active_obj.name})", icon='MESH_DATA')
        else:
            layout.label(text=f"Selected: {active_obj.name}", icon='MESH_DATA')

        obj_width, obj_height, obj_depth = _selection_bounds(selected_meshes)

        col = layout.column(align=True)
        col.label(text=f"Size: {obj_width:.2f} x {obj_height:.2f} x {obj_depth:.2f} m")

        estimate = _grid_estimate((obj_width, obj_height, obj_depth), props)
        if estimate is not None:
            est_width, est_height, est_depth, total_voxels = estimate

            col.label(text=f"Est. Grid: {est_width} x {est_height} x {est_depth}")
            col.label(text=f"Total Voxels: {total_voxels:,}")

            memory_bytes = estimate_peak_memory_bytes_for_props(total_voxels, props)
            memory_mb = memory_bytes / (1024 * 1024)
            col.label(text=f"Conservative Peak Memory: {memory_mb:.1f} MB")

            if grid_limits_exceeded(est_width, est_height, est_depth, memory_bytes):
                if getattr(props, "allow_oversized_grids", False):
                    col.label(text="Oversized grid allowed - may exhaust memory", icon='ERROR')
                else:
                    col.label(text="Grid too large - export blocked", icon='CANCEL')
            elif total_voxels > MAX_TOTAL_VOXELS // 2:
                col.label(text="Large grid - may be slow", icon='ERROR')

        if False:  # Legacy DRR estimate intentionally hidden in the dental UI.
            camera_obj = context.scene.camera
            detector_box = layout.column(align=True)
            if camera_obj and camera_obj.type == 'CAMERA':
                detector_box.label(text=f"Active Camera: {camera_obj.name}", icon='CAMERA_DATA')
                detector_width, detector_height = resolve_drr_detector_size(
                    context.scene,
                    resolution_scale=get_float_prop(props, "drr_resolution_scale", 1.0),
                )
                detector_box.label(text=f"Detector: {detector_width} x {detector_height} px", icon='IMAGE_DATA')
            else:
                detector_box.label(text="Set an active scene camera for DRR export", icon='ERROR')


class VIEW3D_PT_dicomator_per_object_hu(Panel):
    bl_label = "1. Select Objects and Set Materials"
    bl_idname = "VIEW3D_PT_dicomator_per_object_hu"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Dental DICOMator"
    bl_parent_id = "VIEW3D_PT_dicomator_panel"

    def draw(self, context: Context) -> None:  # pragma: no cover - Blender UI code
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        if not (context.active_object and context.active_object.type == 'MESH'):
            layout.label(text="No mesh selected", icon='INFO')
            return
        selected_meshes = _selected_meshes(context)
        props = context.scene.dicomator_props

        for obj in selected_meshes:
            object_box = layout.box()
            col = object_box.column(align=True)
            col.label(text=obj.name, icon='MESH_DATA')
            col.separator(factor=0.5)

            # DICOM object type selector determines which pipeline this mesh
            # feeds into when exported.
            obj_type = "CT"

            if obj_type == "CT":
                col.prop(obj, "dicomator_material", text="Material")
                material_key = getattr(obj, "dicomator_material", "CUSTOM")
                dental_mode = getattr(obj, "dicomator_dental_mode", "UNIFORM")
                if dental_mode == "BONE" or material_key == "BONE":
                    col.prop(obj, "dicomator_enable_cortical")
                    if getattr(obj, "dicomator_enable_cortical", True):
                        bone = col.column(align=True)
                        _paint_mode_buttons(bone, "Cortical")
                        bone.prop(obj, "dicomator_cortical_blend_width")
                        bone.prop(obj, "dicomator_cortical_thickness_mm")
                        bone.prop(obj, "dicomator_cortical_transition_mm", text="Depth Transition (mm)")
                elif dental_mode == "TOOTH" or material_key == "TOOTH":
                    col.prop(obj, "dicomator_enable_enamel")
                    if getattr(obj, "dicomator_enable_enamel", True):
                        enamel = col.column(align=True)
                        _paint_mode_buttons(enamel, "Enamel")
                        enamel.prop(obj, "dicomator_enamel_blend_width")
                        enamel.prop(obj, "dicomator_enamel_depth_mm")

                    col.separator()
                    col.prop(obj, "dicomator_enable_pdl")
                    if getattr(obj, "dicomator_enable_pdl", False):
                        pdl = col.column(align=True)
                        _paint_mode_buttons(pdl, "PDL")
                        pdl.prop(obj, "dicomator_pdl_depth_mm")

                    col.separator()
                    col.prop(obj, "dicomator_enable_caries")
                    if getattr(obj, "dicomator_enable_caries", False):
                        caries_ui = col.column(align=True)
                        _paint_mode_buttons(caries_ui, "Caries")
                        caries_ui.prop(obj, "dicomator_caries_depth_mm")
                        caries_ui.prop(obj, "dicomator_caries_blend_width")

                    col.separator()
                    col.prop(obj, "dicomator_enable_restoration")
                    if getattr(obj, "dicomator_enable_restoration", False):
                        restoration = col.column(align=True)
                        _paint_mode_buttons(restoration, "Restoration")
                        restoration.prop(obj, "dicomator_restoration_depth_mm")
                        restoration.prop(obj, "dicomator_restoration_blend_width")
                elif dental_mode == "PULP" or material_key == "DENTAL_PULP":
                    col.prop(obj, "dicomator_enable_gutta")
                    if getattr(obj, "dicomator_enable_gutta", True):
                        _paint_mode_buttons(col, "GuttaPercha")
                else:
                    if getattr(obj, "dicomator_material", "CUSTOM") == "RADIOLUCENT":
                        col.prop(obj, "dicomator_radiolucent_smooth_margins")

            elif obj_type == "RTDOSE":
                col.prop(obj, "dicomator_dose", text="Dose (Gy)")

            elif obj_type == "RTSTRUCT":
                col.prop(obj, "dicomator_roi_type", text="ROI Type")


class VIEW3D_PT_dicomator_patient_info(Panel):
    bl_label = "2. Patient Information"
    bl_idname = "VIEW3D_PT_dicomator_patient_info"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Dental DICOMator"
    bl_parent_id = "VIEW3D_PT_dicomator_panel"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context: Context) -> None:  # pragma: no cover - Blender UI code
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        props = context.scene.dicomator_props
        layout.prop(props, "series_description", text="Description")
        layout.prop(props, "patient_name")
        layout.prop(props, "patient_birth_date", text="Birth Date")
        layout.prop(props, "patient_sex")
        layout.prop(props, "study_id")


class VIEW3D_PT_dicomator_export_settings(Panel):
    bl_label = "3. Export DICOM"
    bl_idname = "VIEW3D_PT_dicomator_export_settings"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Dental DICOMator"
    bl_parent_id = "VIEW3D_PT_dicomator_panel"

    def draw(self, context: Context) -> None:  # pragma: no cover - Blender UI code
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        props = context.scene.dicomator_props
        layout.prop(props, "export_directory")
        _draw_export_action(layout, context)


class VIEW3D_PT_dicomator_artifacts(Panel):
    bl_label = "3.2 Optional Artifacts"
    bl_idname = "VIEW3D_PT_dicomator_artifacts"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Dental DICOMator"
    bl_parent_id = "VIEW3D_PT_dicomator_export_settings"
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context: Context) -> bool:  # pragma: no cover - Blender UI code
        props = getattr(context.scene, "dicomator_props", None)
        return props is not None and bool(getattr(props, "export_image_series", True))

    def draw(self, context: Context) -> None:  # pragma: no cover - Blender UI code
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        props = context.scene.dicomator_props
        layout.prop(props, "enable_noise", text="Gaussian Noise")
        layout.prop(props, "enable_poisson_noise", text="Quantum Noise")
        layout.prop(props, "enable_motion_artifact", text="Motion")
        layout.prop(props, "enable_metal_artifacts", text="Titanium Metal Artifacts")


class VIEW3D_PT_dicomator_about(Panel):
    bl_label = "4. About"
    bl_idname = "VIEW3D_PT_dicomator_about"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Dental DICOMator"
    bl_parent_id = "VIEW3D_PT_dicomator_panel"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context: Context) -> None:  # pragma: no cover - Blender UI code
        layout = self.layout
        layout.label(text="Dental Developer: Mateus Bertolini")
        layout.label(text="DICOMATOR developer: Michael Douglass")


__all__ = [
    "VIEW3D_PT_dicomator_panel",
    "VIEW3D_PT_dicomator_selection_info",
    "VIEW3D_PT_dicomator_per_object_hu",
    "VIEW3D_PT_dicomator_patient_info",
    "VIEW3D_PT_dicomator_export_settings",
    "VIEW3D_PT_dicomator_artifacts",
    "VIEW3D_PT_dicomator_about",
]
