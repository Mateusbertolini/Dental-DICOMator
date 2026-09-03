"""Property group definitions for the DICOMator add-on."""
from __future__ import annotations

import bpy

from .constants import (
    DOSE_SUMMATION_TYPE_ITEMS,
    DOSE_TYPE_ITEMS,
    IMAGING_MODALITY_ITEMS,
    MODALITY_CT,
    get_material_intensity,
)


def ensure_tooth_vertex_groups(obj: bpy.types.Object) -> None:
    """Ensure mandatory tooth paint groups exist, including in older files."""

    if getattr(obj, "type", None) != 'MESH':
        return
    material_key = str(getattr(obj, "dicomator_material", "CUSTOM"))
    dental_mode = str(getattr(obj, "dicomator_dental_mode", "UNIFORM"))
    if material_key != "TOOTH" and dental_mode != "TOOTH":
        return
    if bool(getattr(obj, "dicomator_enable_enamel", True)):
        group_name = str(getattr(obj, "dicomator_enamel_group", "Enamel")) or "Enamel"
        obj.dicomator_enamel_group = group_name
        if obj.vertex_groups.get(group_name) is None:
            obj.vertex_groups.new(name=group_name)
    for enabled_attr, name_attr, managed_name in (
        ("dicomator_enable_pdl", "dicomator_pdl_group", "PDL"),
        ("dicomator_enable_caries", "dicomator_caries_group", "Caries"),
        ("dicomator_enable_restoration", "dicomator_restoration_group", "Restoration"),
    ):
        if bool(getattr(obj, enabled_attr, False)):
            setattr(obj, name_attr, managed_name)
            if obj.vertex_groups.get(managed_name) is None:
                obj.vertex_groups.new(name=managed_name)


def apply_material_intensity(obj: bpy.types.Object, modality: str) -> None:
    """Assign the intensity for ``obj`` based on its material and modality."""

    material_key = getattr(obj, "dicomator_material", "CUSTOM")
    # Dental presets select their layered behavior automatically. Other
    # presets preserve the original uniform-per-object voxelization.
    if material_key == "BONE":
        # Retain the proven closed-volume occupancy path and vary only the HU
        # of voxels that it already classified as inside the bone.
        obj.dicomator_dental_mode = "BONE"
        if float(getattr(obj, "dicomator_cortical_hu", 1100.0)) == 1100.0:
            obj.dicomator_cortical_hu = 800.0
        if float(getattr(obj, "dicomator_cancellous_hu", -100.0)) in {-100.0, 200.0}:
            obj.dicomator_cancellous_hu = 350.0
        if float(getattr(obj, "dicomator_cortical_transition_mm", 0.5)) in {0.05, 0.15, 0.3}:
            obj.dicomator_cortical_transition_mm = 0.5
        if float(getattr(obj, "dicomator_cortical_thickness_mm", 2.0)) in {0.2, 10.0}:
            obj.dicomator_cortical_thickness_mm = 2.0
        if float(getattr(obj, "dicomator_trabecular_spacing_mm", 0.4)) == 4.0:
            obj.dicomator_trabecular_spacing_mm = 0.4
    elif material_key == "TOOTH":
        obj.dicomator_dental_mode = "TOOTH"
        if float(getattr(obj, "dicomator_enamel_hu", 2500.0)) == 2500.0:
            obj.dicomator_enamel_hu = 2000.0
        if float(getattr(obj, "dicomator_dentin_hu", 1600.0)) == 1600.0:
            obj.dicomator_dentin_hu = 1400.0
        # Migrate empirical pre-1.0.2 depths to physical millimetres. Only
        # known legacy defaults are changed, preserving intentional values.
        if float(getattr(obj, "dicomator_pdl_depth_mm", 0.25)) in {2.0, 2.5}:
            obj.dicomator_pdl_depth_mm = 0.25
        if float(getattr(obj, "dicomator_enamel_depth_mm", 1.0)) == 10.0:
            obj.dicomator_enamel_depth_mm = 1.0
        if float(getattr(obj, "dicomator_caries_depth_mm", 2.0)) == 20.0:
            obj.dicomator_caries_depth_mm = 2.0
        if float(getattr(obj, "dicomator_restoration_depth_mm", 1.0)) == 10.0:
            obj.dicomator_restoration_depth_mm = 1.0
        if getattr(obj, "type", None) == 'MESH':
            ensure_tooth_vertex_groups(obj)
            if bool(getattr(obj, "dicomator_enable_enamel", True)):
                group_name = str(getattr(obj, "dicomator_enamel_group", "Enamel")) or "Enamel"
                group = obj.vertex_groups.get(group_name)
                if group is not None:
                    obj.vertex_groups.active_index = group.index
            if bool(getattr(obj, "dicomator_enable_pdl", False)):
                pdl_group = obj.vertex_groups.get("PDL")
                if pdl_group is None:
                    obj.vertex_groups.new(name="PDL")
    elif material_key == "DENTAL_PULP":
        obj.dicomator_dental_mode = "PULP"
        if float(getattr(obj, "dicomator_gutta_depth_mm", 3.0)) == 30.0:
            obj.dicomator_gutta_depth_mm = 3.0
        if (
            getattr(obj, "type", None) == 'MESH'
            and bool(getattr(obj, "dicomator_enable_gutta", True))
        ):
            obj.dicomator_gutta_group = "GuttaPercha"
            group = obj.vertex_groups.get("GuttaPercha")
            if group is None:
                group = obj.vertex_groups.new(name="GuttaPercha")
            obj.vertex_groups.active_index = group.index
    else:
        obj.dicomator_dental_mode = "UNIFORM"

    if material_key == "CUSTOM":
        return

    value = get_material_intensity(material_key, modality)
    if value is not None:
        obj.dicomator_hu = float(value)


def update_imaging_modality(self, context: bpy.types.Context) -> None:
    """Refresh material-derived intensities when the modality changes."""

    if context is None or context.scene is None:
        return

    for obj in context.scene.objects:
        if obj.type != 'MESH':
            continue
        apply_material_intensity(obj, self.imaging_modality)


def update_object_material(self, context: bpy.types.Context) -> None:
    """Update an object's intensity when its material preset changes."""

    if context is None or context.scene is None:
        return

    props = getattr(context.scene, "dicomator_props", None)
    if props is None:
        return

    apply_material_intensity(self, MODALITY_CT)


class DICOMATOR_PG_properties(bpy.types.PropertyGroup):
    """Properties exposed in the DICOMator UI."""

    export_image_series: bpy.props.BoolProperty(
        name="Image Series",
        description="Export image-type meshes as a CT or MR DICOM image series",
        default=True,
    )
    export_drr: bpy.props.BoolProperty(
        name="DRR",
        description="Export image-type meshes as a digitally reconstructed radiograph from the active camera",
        default=False,
    )
    export_rtdose: bpy.props.BoolProperty(
        name="RT Dose",
        description="Export dose-type meshes as an RT Dose DICOM object",
        default=False,
    )
    export_rtstruct: bpy.props.BoolProperty(
        name="RT Structure",
        description="Export structure-type meshes as an RT Structure Set DICOM object",
        default=False,
    )

    patient_name: bpy.props.StringProperty(
        name="Patient Name",
        description="Name of the patient",
        default="Anonymous",
    )
    patient_id: bpy.props.StringProperty(
        name="MRN",
        description="Medical Record Number (Patient ID)",
        default="12345678",
    )
    patient_birth_date: bpy.props.StringProperty(
        name="Birth Date",
        description="Patient birth date as YYYYMMDD (8 digits); left empty when unset or invalid",
        default="",
        maxlen=16,
    )
    study_id: bpy.props.StringProperty(
        name="Study ID",
        description="DICOM Study ID written to every exported object (max 16 characters)",
        default="1",
        maxlen=16,
    )
    accession_number: bpy.props.StringProperty(
        name="Accession Number",
        description="DICOM Accession Number written to every exported object (max 16 characters)",
        default="1",
        maxlen=16,
    )
    patient_sex: bpy.props.EnumProperty(
        name="Patient Sex",
        description="Patient sex",
        items=[
            ('M', 'Male', 'Male'),
            ('F', 'Female', 'Female'),
            ('O', 'Other', 'Other'),
        ],
        default='M',
    )
    patient_position: bpy.props.EnumProperty(
        name="Patient Position",
        description="DICOM Patient Position (image orientation context)",
        items=[
            ('HFS', 'Head First Supine', 'Head First Supine'),
            ('FFS', 'Feet First Supine', 'Feet First Supine'),
            ('HFP', 'Head First Prone', 'Head First Prone'),
            ('FFP', 'Feet First Prone', 'Feet First Prone'),
            ('HFDR', 'Head First Decubitus Right', 'Head First Decubitus Right'),
            ('HFDL', 'Head First Decubitus Left', 'Head First Decubitus Left'),
            ('FFDR', 'Feet First Decubitus Right', 'Feet First Decubitus Right'),
            ('FFDL', 'Feet First Decubitus Left', 'Feet First Decubitus Left'),
        ],
        default='HFS',
    )
    imaging_modality: bpy.props.EnumProperty(
        name="Imaging Modality",
        description="Select the imaging modality used for material presets",
        items=IMAGING_MODALITY_ITEMS,
        default=IMAGING_MODALITY_ITEMS[0][0],
        update=update_imaging_modality,
    )
    export_4d: bpy.props.BoolProperty(
        name="Export 4D/Time Series",
        description="Export each selected animation frame as a separate phase or projection",
        default=False,
    )
    use_timeline_range: bpy.props.BoolProperty(
        name="Use Timeline Range",
        description="Use the scene's timeline start/end as the frame range",
        default=True,
    )
    frame_start: bpy.props.IntProperty(
        name="Start Frame",
        description="First frame to export (when not using timeline range)",
        default=1,
        min=0,
    )
    frame_end: bpy.props.IntProperty(
        name="End Frame",
        description="Last frame to export (when not using timeline range)",
        default=250,
        min=0,
    )
    frame_step: bpy.props.IntProperty(
        name="Frame Step",
        description="Step between frames to export",
        default=1,
        min=1,
    )
    lateral_resolution_mm: bpy.props.FloatProperty(
        name="Lateral Resolution (mm)",
        description="Voxel size in X/Y (mm)",
        default=0.25,
        min=0.1,
        max=10.0,
        step=10,
        precision=2,
    )
    axial_resolution_mm: bpy.props.FloatProperty(
        name="Axial Resolution (mm)",
        description="Voxel size in Z (mm)",
        default=0.5,
        min=0.1,
        max=10.0,
        step=10,
        precision=2,
    )
    apply_modifiers: bpy.props.BoolProperty(
        name="Apply Modifiers/Deformations",
        description="Evaluate modifiers/shape keys/armatures/lattices when voxelizing",
        default=True,
    )
    allow_oversized_grids: bpy.props.BoolProperty(
        name="Allow Oversized Grids",
        description=(
            "Permit voxel grids beyond 2000 voxels per dimension or 100 million "
            "total voxels. Oversized exports may be very slow or run out of memory"
        ),
        default=False,
    )
    drr_resolution_scale: bpy.props.FloatProperty(
        name="DRR Resolution Scale",
        description="Scale factor applied to the scene render resolution when generating the DRR detector image",
        default=1.0,
        min=0.1,
        max=2.0,
        precision=2,
    )
    drr_water_attenuation_m_inv: bpy.props.FloatProperty(
        name="Water Attenuation (1/m)",
        description=(
            "Effective linear attenuation coefficient of water used by the "
            "monoenergetic Beer-Lambert DRR approximation"
        ),
        default=20.0,
        min=0.01,
        soft_max=50.0,
        precision=3,
    )
    export_directory: bpy.props.StringProperty(
        name="Export Directory",
        description="Directory to save DICOM files",
        subtype='DIR_PATH',
        default="//DICOM_Export",
    )
    series_description: bpy.props.StringProperty(
        name="Series Description",
        description="Description for the DICOM series",
        default="DICOMator Export",
    )
    artifact_seed: bpy.props.IntProperty(
        name="Artifact Seed",
        description="Seed used to reproduce random artifacts; each 4D phase receives a deterministic sub-seed",
        default=0,
        min=0,
    )
    enable_noise: bpy.props.BoolProperty(
        name="Add Gaussian Noise",
        description="Add zero-mean Gaussian noise to exported HU images",
        default=False,
    )
    noise_std_dev_hu: bpy.props.FloatProperty(
        name="Noise Std. Dev. (HU)",
        description="Standard deviation of Gaussian noise in Hounsfield Units",
        default=20.0,
        min=0.0,
        soft_max=500.0,
        step=10,
        precision=1,
    )
    enable_bias_field: bpy.props.BoolProperty(
        name="Add Bias Field Shading",
        description="Apply low-frequency coil shading variations (MRI)",
        default=False,
    )
    bias_field_strength: bpy.props.FloatProperty(
        name="Bias Strength",
        description="Fractional amplitude of the multiplicative bias field",
        default=0.25,
        min=0.0,
        max=1.0,
        subtype='FACTOR',
    )
    bias_field_scale: bpy.props.FloatProperty(
        name="Bias Scale",
        description="Relative smoothing window controlling how quickly the bias varies",
        default=0.3,
        min=0.05,
        max=1.0,
        precision=2,
    )
    enable_geometric_distortion: bpy.props.BoolProperty(
        name="Add Geometric Distortion",
        description="Warp MR images with gradient non-linearity and B0 off-resonance distortion",
        default=False,
    )
    geometric_gradient_strength: bpy.props.FloatProperty(
        name="Gradient Non-linearity",
        description="Radial warp from gradient non-linearity (>0 pincushion, <0 barrel); "
        "approx. fractional displacement at the FOV corner",
        default=0.05,
        min=-0.5,
        max=0.5,
        precision=3,
    )
    geometric_b0_shift: bpy.props.FloatProperty(
        name="B0 Shift (voxels)",
        description="Peak off-resonance displacement (voxels) along the readout axis",
        default=3.0,
        min=0.0,
        soft_max=15.0,
        precision=2,
    )
    geometric_b0_scale: bpy.props.FloatProperty(
        name="B0 Field Scale",
        description="Relative smoothness of the off-resonance field (larger = slower spatial variation)",
        default=0.35,
        min=0.05,
        max=1.0,
        precision=2,
    )
    geometric_readout_axis: bpy.props.EnumProperty(
        name="Readout Axis",
        description="Frequency-encode (readout) direction along which B0 distortion shifts voxels",
        items=[
            ('X', 'X Axis', 'Readout along the X axis'),
            ('Y', 'Y Axis', 'Readout along the Y axis'),
        ],
        default='Y',
    )
    enable_gibbs_ringing: bpy.props.BoolProperty(
        name="Add Gibbs Ringing",
        description="Add truncation (Gibbs) ringing from finite k-space sampling (MRI)",
        default=False,
    )
    gibbs_strength: bpy.props.FloatProperty(
        name="Ringing Strength",
        description="Blend factor between the original and k-space-truncated reconstruction",
        default=0.6,
        min=0.0,
        max=1.0,
        subtype='FACTOR',
    )
    gibbs_truncation: bpy.props.FloatProperty(
        name="k-space Truncation",
        description="Fraction of k-space removed from each in-plane edge (larger = coarser ringing)",
        default=0.2,
        min=0.0,
        max=0.49,
        precision=3,
    )
    enable_partial_volume: bpy.props.BoolProperty(
        name="Add Partial Volume Blur",
        description="Blend materials at boundaries using a volumetric blur",
        default=False,
    )
    partial_volume_kernel: bpy.props.IntProperty(
        name="Kernel Size",
        description="Size of the averaging kernel (odd integer)",
        default=3,
        min=1,
        soft_max=11,
    )
    partial_volume_iterations: bpy.props.IntProperty(
        name="Iterations",
        description="Number of smoothing passes to apply",
        default=1,
        min=1,
        soft_max=5,
    )
    partial_volume_mix: bpy.props.FloatProperty(
        name="Blend",
        description="Blend factor between blurred and original data",
        default=1.0,
        min=0.0,
        max=1.0,
        subtype='FACTOR',
    )
    enable_metal_artifacts: bpy.props.BoolProperty(
        name="Add Metal Streaks",
        description="Simulate streak artifacts originating from dense materials",
        default=False,
    )
    metal_intensity: bpy.props.FloatProperty(
        name="Streak Intensity (HU)",
        description="Base amplitude in HU for generated streaks",
        default=400.0,
        min=0.0,
        soft_max=2000.0,
        step=10,
    )
    metal_density_threshold: bpy.props.FloatProperty(
        name="Metal Threshold (HU)",
        description="HU value above which voxels count as metal",
        default=2000.0,
        min=0.0,
        soft_max=4000.0,
        step=10,
    )
    metal_num_streaks: bpy.props.IntProperty(
        name="Streak Count",
        description="Number of streaks per slice (0 = automatic)",
        default=10,
        min=0,
        soft_max=32,
    )
    metal_falloff: bpy.props.FloatProperty(
        name="Falloff",
        description="Spatial decay of streaks away from the streak axis",
        default=6.0,
        min=0.1,
        soft_max=12.0,
        step=10,
        precision=2,
    )
    enable_ring_artifacts: bpy.props.BoolProperty(
        name="Add Ring Artifacts",
        description="Introduce concentric banding similar to detector gain errors",
        default=False,
    )
    ring_intensity: bpy.props.FloatProperty(
        name="Ring Intensity (HU)",
        description="Amplitude of the generated rings in HU",
        default=80.0,
        min=0.0,
        soft_max=500.0,
        step=10,
    )
    ring_random_radius: bpy.props.BoolProperty(
        name="Random Radius",
        description="Choose a random ring radius for each export",
        default=False,
    )
    ring_radius: bpy.props.FloatProperty(
        name="Ring Radius (rel)",
        description="Relative radius of the ring (0=center, 1=edge) when random radius is disabled",
        default=0.5,
        min=0.0,
        max=1.0,
        precision=3,
    )
    ring_thickness: bpy.props.FloatProperty(
        name="Ring Thickness (rel)",
        description="Relative radial thickness of the ring (typical ~0.01-0.05)",
        default=0.02,
        min=0.0,
        soft_max=0.1,
        precision=3,
    )
    ring_jitter: bpy.props.FloatProperty(
        name="Jitter",
        description="Noise mixed with rings to avoid smooth bands",
        default=0.02,
        min=0.0,
        soft_max=0.2,
        precision=3,
    )
    enable_motion_artifact: bpy.props.BoolProperty(
        name="Add Motion Blur",
        description="Simulate in-plane patient motion during acquisition",
        default=False,
    )
    motion_blur_size: bpy.props.IntProperty(
        name="Blur Length",
        description="Length of the motion blur kernel (odd integer)",
        default=7,
        min=1,
        soft_max=21,
    )
    motion_severity: bpy.props.FloatProperty(
        name="Severity",
        description="Blend factor between original and blurred slice",
        default=0.05,
        min=0.0,
        max=1.0,
        subtype='FACTOR',
    )
    motion_axis: bpy.props.EnumProperty(
        name="Blur Axis",
        description="Direction of motion blur within each slice",
        items=[
            ('X', 'X Axis', 'Blur along the X axis (left/right)'),
            ('Y', 'Y Axis', 'Blur along the Y axis (anterior/posterior)'),
        ],
        default='X',
    )
    enable_poisson_noise: bpy.props.BoolProperty(
        name="Add Poisson Noise",
        description="Approximate photon counting noise via a Poisson process",
        default=False,
    )
    poisson_scale: bpy.props.FloatProperty(
        name="Photon Scale",
        description="Higher values reduce noise by increasing simulated counts",
        default=250.0,
        min=1.0,
        soft_max=1000.0,
        step=10,
    )

    # ------------------------------------------------------------------
    # RT Dose export settings
    # ------------------------------------------------------------------

    dose_type: bpy.props.EnumProperty(
        name="Dose Type",
        description="Physical dose (Gy) or radiobiologically weighted effective dose",
        items=DOSE_TYPE_ITEMS,
        default="PHYSICAL",
    )
    dose_summation_type: bpy.props.EnumProperty(
        name="Dose Summation Type",
        description="Synthetic dose is exported only as a plan total until full fraction and beam modules are supported",
        items=DOSE_SUMMATION_TYPE_ITEMS,
        default="PLAN",
    )
    dose_accumulation: bpy.props.EnumProperty(
        name="Dose Overlap",
        description="How overlapping RT Dose meshes combine in the exported grid",
        items=[
            ("SUM", "Sum", "Overlapping dose volumes accumulate, matching how physical dose combines"),
            ("OVERWRITE", "Overwrite", "The mesh with the highest overlap priority wins; names break ties"),
        ],
        default="SUM",
    )


__all__ = [
    "DICOMATOR_PG_properties",
    "apply_material_intensity",
    "ensure_tooth_vertex_groups",
    "update_imaging_modality",
    "update_object_material",
]
