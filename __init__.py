"""Blender entry point for the DICOMator add-on."""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import bpy
from bpy.props import EnumProperty, FloatProperty, IntProperty, PointerProperty, StringProperty
from bpy.types import AddonPreferences

# Blender keeps add-on submodules alive in sys.modules across disable/enable
# cycles. Reload any that are already present (a no-op on first load) before
# the named imports below so newly added panel/operator classes are visible
# without restarting Blender.
for _module_name in (
    "constants",
    "utils",
    "artifacts",
    "dicom_export",
    "drr",
    "rtdose_export",
    "rtstruct_export",
    "dental",
    "voxelization",
    "properties",
    "operators",
    "panels",
):
    _qualified_name = f"{__name__}.{_module_name}"
    if _qualified_name in sys.modules:
        importlib.reload(sys.modules[_qualified_name])

from .artifacts import (
    add_bias_field_shading,
    add_gaussian_noise,
    add_gibbs_ringing,
    add_metal_artifacts,
    add_motion_artifact,
    add_mri_geometric_distortion,
    add_poisson_noise,
    add_rician_noise,
    add_ring_artifacts,
    apply_partial_volume_effect,
)
from .constants import DENTAL_MATERIAL_MODE_ITEMS, DICOM_OBJECT_TYPE_ITEMS, MATERIAL_ITEMS, MAX_HU_VALUE, MIN_HU_VALUE, ROI_TYPE_ITEMS
from .dicom_export import export_projection_to_dicom, export_voxel_grid_to_dicom
from .drr import generate_drr_from_hu_volume, resolve_drr_detector_size
from .operators import DICOMATOR_OT_export_dicom
from .rtdose_export import export_rtdose_to_dicom
from .rtstruct_export import export_rtstruct_to_dicom
from .panels import (
    DICOMATOR_OT_object_mode,
    DICOMATOR_OT_weight_paint_group,
    VIEW3D_PT_dicomator_artifacts,
    VIEW3D_PT_dicomator_about,
    VIEW3D_PT_dicomator_export_settings,
    VIEW3D_PT_dicomator_panel,
    VIEW3D_PT_dicomator_patient_info,
    VIEW3D_PT_dicomator_per_object_hu,
    VIEW3D_PT_dicomator_selection_info,
)
from .properties import DICOMATOR_PG_properties, update_object_material
from .voxelization import voxelize_mesh, voxelize_objects_to_dose, voxelize_objects_to_hu


class DICOMATOR_AP_preferences(AddonPreferences):
    """Extension preferences with access to Blender's official uninstall action."""

    bl_idname = __package__

    def draw(self, context) -> None:  # pragma: no cover - Blender UI code
        layout = self.layout
        layout.label(text="Dental DICOMator")
        layout.operator_context = 'INVOKE_DEFAULT'
        operator = layout.operator(
            "extensions.package_uninstall",
            text="Uninstall Dental DICOMator",
            icon='TRASH',
        )
        operator.repo_directory = str(Path(__file__).resolve().parent.parent)
        operator.repo_index = -1
        # Blender installs an extension in a directory named after its
        # manifest ID. Resolving the ID here keeps this action correct if the
        # package is renamed in a future release.
        operator.pkg_id = Path(__file__).resolve().parent.name


classes = (
    DICOMATOR_AP_preferences,
    DICOMATOR_PG_properties,
    DICOMATOR_OT_weight_paint_group,
    DICOMATOR_OT_object_mode,
    DICOMATOR_OT_export_dicom,
    VIEW3D_PT_dicomator_panel,
    VIEW3D_PT_dicomator_per_object_hu,
    VIEW3D_PT_dicomator_patient_info,
    VIEW3D_PT_dicomator_export_settings,
    VIEW3D_PT_dicomator_selection_info,
    VIEW3D_PT_dicomator_artifacts,
    VIEW3D_PT_dicomator_about,
)


def _update_enamel_vertex_group(obj, _context) -> None:
    """Create/remove and activate the managed Enamel paint group."""

    if getattr(obj, "type", None) != 'MESH':
        return
    group_name = "Enamel"
    obj.dicomator_enamel_group = group_name
    group = obj.vertex_groups.get(group_name)
    if obj.dicomator_enable_enamel:
        if group is None:
            group = obj.vertex_groups.new(name=group_name)
        obj.vertex_groups.active_index = group.index
    elif group is not None:
        obj.vertex_groups.remove(group)


def _update_caries_vertex_group(obj, _context) -> None:
    """Create/remove the dedicated Caries paint group with the checkbox."""

    if getattr(obj, "type", None) != 'MESH':
        return
    group_name = "Caries"
    obj.dicomator_caries_group = group_name
    group = obj.vertex_groups.get(group_name)
    if obj.dicomator_enable_caries:
        if group is None:
            group = obj.vertex_groups.new(name=group_name)
        obj.vertex_groups.active_index = group.index
    elif group is not None:
        obj.vertex_groups.remove(group)


def _update_pdl_vertex_group(obj, _context) -> None:
    """Create/remove and activate the managed PDL paint group."""

    if getattr(obj, "type", None) != 'MESH':
        return
    group_name = "PDL"
    obj.dicomator_pdl_group = group_name
    group = obj.vertex_groups.get(group_name)
    if obj.dicomator_enable_pdl:
        if group is None:
            group = obj.vertex_groups.new(name=group_name)
        obj.vertex_groups.active_index = group.index
    elif group is not None:
        obj.vertex_groups.remove(group)


def _update_restoration_vertex_group(obj, _context) -> None:
    """Create/remove and activate the restorative-material paint group."""

    if getattr(obj, "type", None) != 'MESH':
        return
    group_name = "Restoration"
    obj.dicomator_restoration_group = group_name
    group = obj.vertex_groups.get(group_name)
    if obj.dicomator_enable_restoration:
        if group is None:
            group = obj.vertex_groups.new(name=group_name)
        obj.vertex_groups.active_index = group.index
    elif group is not None:
        obj.vertex_groups.remove(group)


def _update_gutta_vertex_group(obj, _context) -> None:
    """Create/remove and activate the managed GuttaPercha paint group."""

    if getattr(obj, "type", None) != 'MESH':
        return
    group_name = "GuttaPercha"
    obj.dicomator_gutta_group = group_name
    group = obj.vertex_groups.get(group_name)
    if obj.dicomator_enable_gutta:
        if group is None:
            group = obj.vertex_groups.new(name=group_name)
        obj.vertex_groups.active_index = group.index
    elif group is not None:
        obj.vertex_groups.remove(group)


def register() -> None:  # pragma: no cover - Blender registration
    for cls in classes:
        bpy.utils.register_class(cls)

    # Assign unconditionally: guarding with hasattr() would keep a stale
    # definition from a previous registration (e.g. an older add-on version)
    # bound instead of the current one. Re-assignment is idempotent.
    bpy.types.Scene.dicomator_props = PointerProperty(type=DICOMATOR_PG_properties)

    bpy.types.Object.dicomator_hu = FloatProperty(
        name="HU",
        description="Assigned Hounsfield Units for this mesh",
        default=0.0,
        min=MIN_HU_VALUE,
        max=MAX_HU_VALUE,
        step=10,
        precision=0,
    )

    bpy.types.Object.dicomator_material = EnumProperty(
        name="Material",
        description="Select a predefined tissue/material",
        items=MATERIAL_ITEMS,
        default="CUSTOM",
        update=update_object_material,
    )
    bpy.types.Object.dicomator_dental_mode = EnumProperty(
        name="Dental Behavior", items=DENTAL_MATERIAL_MODE_ITEMS, default="UNIFORM"
    )
    bpy.types.Object.dicomator_cortical_thickness_mm = FloatProperty(
        name="Cortical Depth (mm)", default=2.0, min=0.0, soft_max=5.0, precision=2
    )
    bpy.types.Object.dicomator_cortical_group = StringProperty(
        name="Cortical Vertex Group", default="Cortical",
        description="Automatically contains all bone surface vertices",
    )
    bpy.types.Object.dicomator_cortical_transition_mm = FloatProperty(
        name="Shell Blend (mm)", default=0.5, min=0.0, soft_max=2.0, precision=2
    )
    bpy.types.Object.dicomator_cortical_hu = FloatProperty(
        name="Cortical HU", default=800.0, min=MIN_HU_VALUE, max=MAX_HU_VALUE
    )
    bpy.types.Object.dicomator_cancellous_hu = FloatProperty(
        name="Cancellous HU", default=350.0, min=MIN_HU_VALUE, max=MAX_HU_VALUE
    )
    bpy.types.Object.dicomator_trabecular_spacing_mm = FloatProperty(
        name="Trabecular Spacing (mm)", default=0.4, min=0.025, soft_max=1.0, precision=3,
        description="Approximate spacing of the synthetic cancellous bone struts",
    )
    bpy.types.Object.dicomator_trabecular_contrast_hu = FloatProperty(
        name="Trabecular Contrast (HU)", default=0.0, min=0.0, soft_max=1500.0,
        description="HU separation between marrow-like spaces and trabecular struts",
    )
    bpy.types.Object.dicomator_enamel_group = StringProperty(
        name="Enamel Vertex Group", default="Enamel",
        description="Vertex group painted on the tooth surface; unpainted regions remain dentin",
    )
    bpy.types.Object.dicomator_enable_enamel = bpy.props.BoolProperty(
        name="Paint Enamel", default=True,
        description="Use weight paint for the radiopaque enamel layer",
        update=_update_enamel_vertex_group,
    )
    bpy.types.Object.dicomator_enamel_hu = FloatProperty(
        name="Enamel HU", default=2000.0, min=MIN_HU_VALUE, max=MAX_HU_VALUE
    )
    bpy.types.Object.dicomator_dentin_hu = FloatProperty(
        name="Dentin HU", default=1400.0, min=MIN_HU_VALUE, max=MAX_HU_VALUE
    )
    bpy.types.Object.dicomator_pdl_hu = FloatProperty(
        name="PDL HU", default=-100.0, min=MIN_HU_VALUE, max=MAX_HU_VALUE,
        description="Radiolucent periodontal-ligament simulation on non-enamel surfaces",
    )
    bpy.types.Object.dicomator_pdl_depth_mm = FloatProperty(
        name="PDL Depth (mm)", default=0.25, min=0.0, soft_max=1.0, precision=2,
    )
    bpy.types.Object.dicomator_enable_pdl = bpy.props.BoolProperty(
        name="Paint Periodontal Ligament", default=False,
        description="Add a radiolucent PDL layer and use weight paint to double its depth",
        update=_update_pdl_vertex_group,
    )
    bpy.types.Object.dicomator_pdl_group = StringProperty(
        name="PDL Vertex Group", default="PDL",
        description="Paint areas where periodontal-ligament depth is doubled",
    )
    bpy.types.Object.dicomator_enamel_threshold = FloatProperty(
        name="Enamel Threshold", default=0.05, min=0.0, max=1.0, precision=2
    )
    bpy.types.Object.dicomator_enamel_blend_width = FloatProperty(
        name="Weight Blend", default=0.2, min=0.0, max=1.0, precision=2
    )
    bpy.types.Object.dicomator_enamel_depth_mm = FloatProperty(
        name="Enamel Depth (mm)", default=1.0, min=0.0, soft_max=3.0, precision=2
    )
    bpy.types.Object.dicomator_enable_caries = bpy.props.BoolProperty(
        name="Paint Caries / Decay", default=False,
        description="Use a vertex group to add a low-attenuation lesion to this tooth",
        update=_update_caries_vertex_group,
    )
    bpy.types.Object.dicomator_caries_group = StringProperty(
        name="Caries Vertex Group", default="Caries",
        description="Vertex group painted where decay should extend inward from the tooth surface",
    )
    bpy.types.Object.dicomator_caries_hu = FloatProperty(
        name="Caries HU", default=500.0, min=MIN_HU_VALUE, max=MAX_HU_VALUE
    )
    bpy.types.Object.dicomator_caries_depth_mm = FloatProperty(
        name="Caries Depth (mm)", default=2.0, min=1.0, max=4.5, precision=2
    )
    bpy.types.Object.dicomator_caries_threshold = FloatProperty(
        name="Caries Threshold", default=0.05, min=0.0, max=1.0, precision=2
    )
    bpy.types.Object.dicomator_caries_blend_width = FloatProperty(
        name="Caries Weight Blend", default=0.5, min=0.0, max=1.0, precision=2
    )
    bpy.types.Object.dicomator_radiolucent_smooth_margins = bpy.props.BoolProperty(
        name="Smooth Margins", default=False,
        description="Blend the radiolucent object edge into air; disable for sharply defined margins",
    )
    bpy.types.Object.dicomator_gutta_group = StringProperty(
        name="Gutta-percha Vertex Group", default="GuttaPercha",
    )
    bpy.types.Object.dicomator_enable_gutta = bpy.props.BoolProperty(
        name="Paint Gutta-percha", default=True,
        description="Use weight paint for radiopaque gutta-percha inside dental pulp",
        update=_update_gutta_vertex_group,
    )
    bpy.types.Object.dicomator_pulp_hu = FloatProperty(
        name="Dental Pulp HU", default=40.0, min=MIN_HU_VALUE, max=MAX_HU_VALUE
    )
    bpy.types.Object.dicomator_gutta_hu = FloatProperty(
        name="Gutta-percha HU", default=4000.0, min=MIN_HU_VALUE, max=MAX_HU_VALUE
    )
    bpy.types.Object.dicomator_gutta_depth_mm = FloatProperty(
        name="Gutta-percha Depth (mm)", default=3.0, min=0.0, soft_max=5.0, precision=2
    )
    bpy.types.Object.dicomator_gutta_threshold = FloatProperty(
        name="Gutta-percha Threshold", default=0.05, min=0.0, max=1.0, precision=2
    )
    bpy.types.Object.dicomator_gutta_blend_width = FloatProperty(
        name="Gutta-percha Weight Blend", default=0.2, min=0.0, max=1.0, precision=2
    )
    bpy.types.Object.dicomator_enable_restoration = bpy.props.BoolProperty(
        name="Paint Restorative Material", default=False,
        description="Use weight paint for a radiopaque restoration that overrides tooth tissues",
        update=_update_restoration_vertex_group,
    )
    bpy.types.Object.dicomator_restoration_group = StringProperty(
        name="Restoration Vertex Group", default="Restoration",
    )
    bpy.types.Object.dicomator_restoration_hu = FloatProperty(
        name="Restoration HU", default=3000.0, min=MIN_HU_VALUE, max=MAX_HU_VALUE
    )
    bpy.types.Object.dicomator_restoration_depth_mm = FloatProperty(
        name="Restoration Depth (mm)", default=1.0, min=0.0, soft_max=3.0, precision=2
    )
    bpy.types.Object.dicomator_restoration_threshold = FloatProperty(
        name="Restoration Threshold", default=0.05, min=0.0, max=1.0, precision=2
    )
    bpy.types.Object.dicomator_restoration_blend_width = FloatProperty(
        name="Restoration Weight Blend", default=0.2, min=0.0, max=1.0, precision=2
    )

    bpy.types.Object.dicomator_object_type = EnumProperty(
        name="DICOM Object Type",
        description="Specifies whether this mesh contributes to image, RT Dose, or RT Structure exports",
        items=DICOM_OBJECT_TYPE_ITEMS,
        default="CT",
    )

    bpy.types.Object.dicomator_priority = IntProperty(
        name="Overlap Priority",
        description="Higher-priority image or dose meshes overwrite lower-priority meshes in overlapping voxels",
        default=0,
        min=-1000,
        max=1000,
    )

    bpy.types.Object.dicomator_dose = FloatProperty(
        name="Dose (Gy)",
        description="Absorbed dose assigned to voxels within this mesh when exported as RT Dose",
        default=0.0,
        min=0.0,
        soft_max=80.0,
        max=200.0,
        step=10,
        precision=2,
    )

    bpy.types.Object.dicomator_roi_type = EnumProperty(
        name="ROI Type",
        description="DICOM RT ROI interpreted type (RTROIInterpretedType) for this structure",
        items=ROI_TYPE_ITEMS,
        default="OAR",
    )

    # Configure an available scene immediately, but remain safe under Blender's
    # restricted installation context where bpy.context.scene does not exist.
    scene = getattr(bpy.context, "scene", None)
    if scene is not None:
        scene.unit_settings.system = 'METRIC'
        scene.unit_settings.scale_length = 0.001
        scene.unit_settings.length_unit = 'MILLIMETERS'
        scene.dicomator_props.lateral_resolution_mm = 0.25
        scene.dicomator_props.axial_resolution_mm = 0.5


def unregister() -> None:  # pragma: no cover - Blender registration
    if hasattr(bpy.types.Scene, "dicomator_props"):
        del bpy.types.Scene.dicomator_props

    for attr in (
        "dicomator_gutta_blend_width", "dicomator_gutta_threshold",
        "dicomator_gutta_depth_mm", "dicomator_gutta_hu", "dicomator_pulp_hu",
        "dicomator_gutta_group", "dicomator_enable_gutta",
        "dicomator_pdl_group", "dicomator_enable_pdl",
        "dicomator_radiolucent_smooth_margins",
        "dicomator_restoration_blend_width", "dicomator_restoration_threshold",
        "dicomator_restoration_depth_mm", "dicomator_restoration_hu",
        "dicomator_restoration_group", "dicomator_enable_restoration",
        "dicomator_caries_blend_width", "dicomator_caries_threshold",
        "dicomator_caries_depth_mm", "dicomator_caries_hu",
        "dicomator_caries_group", "dicomator_enable_caries",
        "dicomator_enamel_depth_mm", "dicomator_enamel_blend_width",
        "dicomator_enamel_threshold", "dicomator_pdl_depth_mm", "dicomator_pdl_hu",
        "dicomator_dentin_hu", "dicomator_enamel_hu",
        "dicomator_enamel_group", "dicomator_enable_enamel",
        "dicomator_cancellous_hu", "dicomator_cortical_hu",
        "dicomator_trabecular_contrast_hu", "dicomator_trabecular_spacing_mm",
        "dicomator_cortical_group", "dicomator_cortical_transition_mm", "dicomator_cortical_thickness_mm",
        "dicomator_dental_mode",
    ):
        if hasattr(bpy.types.Object, attr):
            delattr(bpy.types.Object, attr)

    if hasattr(bpy.types.Object, "dicomator_roi_type"):
        del bpy.types.Object.dicomator_roi_type

    if hasattr(bpy.types.Object, "dicomator_dose"):
        del bpy.types.Object.dicomator_dose

    if hasattr(bpy.types.Object, "dicomator_object_type"):
        del bpy.types.Object.dicomator_object_type

    if hasattr(bpy.types.Object, "dicomator_priority"):
        del bpy.types.Object.dicomator_priority

    if hasattr(bpy.types.Object, "dicomator_material"):
        del bpy.types.Object.dicomator_material

    if hasattr(bpy.types.Object, "dicomator_hu"):
        del bpy.types.Object.dicomator_hu

    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)


__all__ = [
    "add_bias_field_shading",
    "add_gaussian_noise",
    "add_gibbs_ringing",
    "add_metal_artifacts",
    "add_motion_artifact",
    "add_mri_geometric_distortion",
    "add_poisson_noise",
    "add_rician_noise",
    "add_ring_artifacts",
    "apply_partial_volume_effect",
    "export_projection_to_dicom",
    "export_rtdose_to_dicom",
    "export_rtstruct_to_dicom",
    "export_voxel_grid_to_dicom",
    "generate_drr_from_hu_volume",
    "voxelize_mesh",
    "voxelize_objects_to_dose",
    "voxelize_objects_to_hu",
    "resolve_drr_detector_size",
    "register",
    "unregister",
]
