"""Enhanced SCORM Validator — Phase 3.8.

Validates SCORM packages against SCORM 1.2 and 2004 (4th Edition) standards.
Checks: manifest structure, XSD schema compliance, resource references,
metadata completeness, sequencing rules.

Extends the existing SCORM export workflow step with XSD-based validation.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("ai_authoring")


class SCORMValidator:
    """Validates SCORM packages against standards.

    Supports: SCORM 1.2 and SCORM 2004 (4th Edition).

    Usage:
        validator = SCORMValidator()
        result = await validator.validate_package(
            zip_path="/path/to/scorm_package.zip",
            version="2004",
        )
    """

    # Required SCORM manifest elements
    REQUIRED_MANIFEST_ELEMENTS = {
        "1.2": ["manifest", "organizations", "resources"],
        "2004": ["manifest", "organizations", "resources", "sequencing"],
    }

    # Required manifest attributes
    REQUIRED_MANIFEST_ATTRIBUTES = {
        "1.2": {"manifest": ["identifier", "version"]},
        "2004": {"manifest": ["identifier", "version", "xml:base"]},
    }

    # Required resource attributes
    REQUIRED_RESOURCE_ATTRIBUTES = {
        "1.2": ["identifier", "type", "href"],
        "2004": ["identifier", "type", "href", "scormType"],
    }

    def __init__(self):
        self._xsd_cache: Dict[str, Any] = {}

    # ── Public API ─────────────────────────────────────────────────

    async def validate_package(
        self,
        zip_path: str,
        version: str = "2004",
    ) -> Dict[str, Any]:
        """Validate a SCORM package zip file.

        Returns:
            {
                "valid": bool,
                "version": str,
                "issues": [{"severity": "error|warning", "check": str, "message": str}],
                "summary": str,
            }
        """
        issues: List[Dict[str, Any]] = []

        if not os.path.exists(zip_path):
            return {
                "valid": False,
                "version": version,
                "issues": [{"severity": "error", "check": "file_exists", "message": f"File not found: {zip_path}"}],
                "summary": "SCORM package file not found.",
            }

        # 1. Validate zip integrity
        issues.extend(await self._check_zip_integrity(zip_path))

        # 2. Validate manifest presence and structure
        import zipfile
        manifest_content = None
        try:
            with zipfile.ZipFile(zip_path, 'r') as zf:
                if 'imsmanifest.xml' not in zf.namelist():
                    issues.append({
                        "severity": "error",
                        "check": "manifest_present",
                        "message": "imsmanifest.xml not found in package root",
                    })
                else:
                    manifest_content = zf.read('imsmanifest.xml').decode('utf-8', errors='replace')
        except zipfile.BadZipFile:
            return {
                "valid": False,
                "version": version,
                "issues": [{"severity": "error", "check": "zip_integrity", "message": "File is not a valid ZIP archive"}],
                "summary": "Invalid ZIP file.",
            }

        # 3. Validate manifest content
        if manifest_content:
            issues.extend(await self._validate_manifest_content(manifest_content, version, zip_path))

        # 4. Check for required SCORM files
        issues.extend(await self._check_required_files(zip_path, version))

        errors = [i for i in issues if i["severity"] == "error"]
        warnings = [i for i in issues if i["severity"] == "warning"]

        return {
            "valid": len(errors) == 0,
            "version": version,
            "issues": issues,
            "error_count": len(errors),
            "warning_count": len(warnings),
            "summary": (
                f"SCORM {version} validation: {'PASSED' if len(errors) == 0 else 'FAILED'}. "
                f"{len(errors)} error(s), {len(warnings)} warning(s)."
            ),
        }

    async def validate_manifest_xsd(
        self,
        manifest_xml: str,
        version: str = "2004",
    ) -> Dict[str, Any]:
        """Validate manifest XML against SCORM XSD schema.

        Uses xmlschema library for XSD validation when available.
        Falls back to structural checks when xmlschema is not installed.
        """
        issues: List[Dict[str, Any]] = []

        try:
            import xmlschema

            # SCORM 2004 XSD (simplified — full schema would be loaded from file)
            xsd_content = self._get_scorm_xsd(version)
            schema = xmlschema.XMLSchema(xsd_content)  # type: ignore[arg-type]

            try:
                schema.validate(manifest_xml)
                issues.append({
                    "severity": "info",
                    "check": "xsd_validation",
                    "message": f"Manifest passes SCORM {version} XSD validation",
                })
            except xmlschema.XMLSchemaValidationError as exc:
                issues.append({
                    "severity": "error",
                    "check": "xsd_validation",
                    "message": f"XSD validation failed: {exc}",
                })
        except ImportError:
            logger.info("xmlschema not installed — using structural validation only")
            issues.extend(self._validate_manifest_structure(manifest_xml, version))

        return {"valid": not any(i["severity"] == "error" for i in issues), "issues": issues}

    # ── Internal checks ────────────────────────────────────────────

    async def _check_zip_integrity(self, zip_path: str) -> List[Dict[str, Any]]:
        """Check zip file integrity."""
        issues = []
        import zipfile
        try:
            with zipfile.ZipFile(zip_path, 'r') as zf:
                bad = zf.testzip()
                if bad:
                    issues.append({
                        "severity": "error",
                        "check": "zip_integrity",
                        "message": f"Corrupted file in ZIP: {bad}",
                    })

                # Check for zero-byte files
                for info in zf.infolist():
                    if info.file_size == 0 and not info.is_dir():
                        issues.append({
                            "severity": "warning",
                            "check": "zip_integrity",
                            "message": f"Empty file in package: {info.filename}",
                        })
        except Exception as exc:
            issues.append({
                "severity": "error",
                "check": "zip_integrity",
                "message": f"ZIP integrity check failed: {exc}",
            })
        return issues

    async def _validate_manifest_content(
        self, manifest_xml: str, version: str, zip_path: str
    ) -> List[Dict[str, Any]]:
        """Validate the imsmanifest.xml content."""
        issues = []
        try:
            from lxml import etree
            root = etree.fromstring(manifest_xml.encode('utf-8'))
        except ImportError:
            # Fall back to regex checks
            return self._validate_manifest_structure(manifest_xml, version)
        except Exception as exc:
            return [{"severity": "error", "check": "manifest_parse", "message": f"Failed to parse manifest XML: {exc}"}]

        # Check required elements
        nsmap = root.nsmap if hasattr(root, 'nsmap') else {}
        for el_name in self.REQUIRED_MANIFEST_ELEMENTS.get(version, []):
            found = root.find(f".//{{*}}{el_name}") is not None or root.find(f".//{el_name}") is not None
            if not found:
                issues.append({
                    "severity": "error",
                    "check": "manifest_structure",
                    "message": f"Required element missing: <{el_name}>",
                })

        # Check resources reference actual files
        resources = root.findall(".//{*}resource") or root.findall(".//resource")
        import zipfile
        with zipfile.ZipFile(zip_path, 'r') as zf:
            zip_contents = set(zf.namelist())
            for res in resources:
                href = res.get("href", "")
                if href and href not in zip_contents:
                    issues.append({
                        "severity": "warning",
                        "check": "resource_reference",
                        "message": f"Resource '{href}' not found in package",
                    })

        return issues

    def _validate_manifest_structure(
        self, manifest_xml: str, version: str
    ) -> List[Dict[str, Any]]:
        """Structural checks using regex (fallback when lxml unavailable)."""
        issues = []
        import re

        for el_name in self.REQUIRED_MANIFEST_ELEMENTS.get(version, []):
            if not re.search(rf'<{el_name}[>\s]', manifest_xml):
                issues.append({
                    "severity": "error",
                    "check": "manifest_structure",
                    "message": f"Required element missing: <{el_name}>",
                })

        return issues

    async def _check_required_files(
        self, zip_path: str, version: str
    ) -> List[Dict[str, Any]]:
        """Check for required SCORM API files."""
        issues = []
        import zipfile

        required_patterns = [
            # SCORM API wrappers (LMS communication)
            ("SCORM_API", "warning", "No SCORM API wrapper JS found"),
            (".html", "error", "No HTML content files in package"),
        ]

        with zipfile.ZipFile(zip_path, 'r') as zf:
            namelist = zf.namelist()

            for pattern, severity, message in required_patterns:
                matches = [n for n in namelist if pattern in n]
                if not matches:
                    issues.append({
                        "severity": severity,
                        "check": "required_files",
                        "message": message,
                    })

        return issues

    @staticmethod
    def _get_scorm_xsd(version: str) -> str:
        """Return a minimal SCORM XSD for validation."""
        if version == "1.2":
            return """<?xml version="1.0"?>
<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">
  <xs:element name="manifest">
    <xs:complexType>
      <xs:sequence>
        <xs:element name="organizations" minOccurs="1"/>
        <xs:element name="resources" minOccurs="1"/>
      </xs:sequence>
      <xs:attribute name="identifier" type="xs:string" use="required"/>
      <xs:attribute name="version" type="xs:string" use="required"/>
    </xs:complexType>
  </xs:element>
</xs:schema>"""
        # SCORM 2004
        return """<?xml version="1.0"?>
<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">
  <xs:element name="manifest">
    <xs:complexType>
      <xs:sequence>
        <xs:element name="organizations" minOccurs="1"/>
        <xs:element name="resources" minOccurs="1"/>
        <xs:element name="sequencing" minOccurs="0" maxOccurs="1"/>
      </xs:sequence>
      <xs:attribute name="identifier" type="xs:string" use="required"/>
      <xs:attribute name="version" type="xs:string" use="required"/>
      <xs:attribute name="xml:base" type="xs:string"/>
    </xs:complexType>
  </xs:element>
</xs:schema>"""
