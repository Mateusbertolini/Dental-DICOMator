# Contributing to Dental DICOMator

Thank you for helping improve Dental DICOMator.

## Before opening an issue

- Search existing issues and test the latest release.
- Include add-on and Blender versions, OS, object dimensions, settings, and reproduction steps.
- Use synthetic or fully de-identified files only. Never upload PHI, patient identifiers, or identifiable clinical DICOM data.
- Report vulnerabilities privately as described in SECURITY.md.

## Pull requests

Discuss large changes first. Preserve DICOM generation, unit consistency, closed-volume voxelization, Blender compatibility, and safe registration. Update documentation and the changelog.

Validate and build:

    blender --command extension validate
    blender --command extension build --output-filepath Dental-DICOMator-Blender-Extension.zip

Test installation, materials, vertex groups, weight painting, DICOM dimensions/spacing/slices, overlap, and an independent viewer. Do not commit generated DICOM, large datasets, caches, credentials, or patient data.

Contributions are distributed under GPL-3.0-or-later.

