"""
Template Data Format Converter.

Handles conversion between different template data formats to support
legacy imports and standardization during SCORM ingestion.
"""

import json
import logging
from typing import Dict, Any, Union
from enum import Enum

logger = logging.getLogger(__name__)


class TemplateFormat(Enum):
    """Supported template data formats."""
    CANONICAL = "canonical"  # Standardized format with nested structure
    FLAT = "flat"            # Legacy flat structure (question + options at root)
    JSON_STUFFED = "json_stuffed"  # JSON string embedded in text field
    UNKNOWN = "unknown"      # Could not detect format


class FormatConversionError(Exception):
    """Raised when format conversion fails."""
    pass


class TemplateDataConverter:
    """Converter for template data formats."""

    # MCQ format indicators
    FLAT_FORMAT_INDICATORS = {"question", "options"}
    CANONICAL_FORMAT_INDICATORS = {"questions", "data"}
    JSON_STUFFED_INDICATORS = {"content", "data_json"}

    def auto_detect_format(self, template_data: Dict[str, Any]) -> TemplateFormat:
        """
        Automatically detect the format of template data.

        Args:
            template_data: Template data dictionary to analyze

        Returns:
            Detected TemplateFormat

        Example:
            >>> converter = TemplateDataConverter()
            >>> legacy = {"question": "...", "options": [...]}
            >>> converter.auto_detect_format(legacy)
            TemplateFormat.FLAT
        """
        if not isinstance(template_data, dict):
            return TemplateFormat.UNKNOWN

        keys = set(template_data.keys())

        # Check for canonical format (nested structure)
        if "questions" in template_data and isinstance(template_data.get("questions"), list):
            return TemplateFormat.CANONICAL

        # Check for flat format (direct question + options)
        if self.FLAT_FORMAT_INDICATORS.issubset(keys):
            return TemplateFormat.FLAT

        # Check for JSON-stuffed format
        if "content" in template_data:
            content = template_data["content"]
            if isinstance(content, str):
                try:
                    json.loads(content)
                    return TemplateFormat.JSON_STUFFED
                except (json.JSONDecodeError, ValueError):
                    pass

        return TemplateFormat.UNKNOWN

    def convert_to_canonical(
        self,
        template_data: Dict[str, Any],
        template_type: str = "mcq"
    ) -> Dict[str, Any]:
        """
        Convert template data to canonical format.

        The canonical format uses a normalized nested structure suitable
        for validation and export.

        Args:
            template_data: Source template data
            template_type: Type of template (for format hints)

        Returns:
            Canonical format dictionary

        Raises:
            FormatConversionError: If conversion fails

        Example:
            >>> converter = TemplateDataConverter()
            >>> legacy = {"question": "What is 2+2?", "options": [...]}
            >>> canonical = converter.convert_to_canonical(legacy, "mcq")
            >>> canonical["questions"][0]["question"]
            'What is 2+2?'
        """
        if not isinstance(template_data, dict):
            raise FormatConversionError("Template data must be a dictionary")

        if not template_data:
            return {}

        source_format = self.auto_detect_format(template_data)

        try:
            if source_format == TemplateFormat.CANONICAL:
                return template_data.copy()

            elif source_format == TemplateFormat.FLAT:
                return self._convert_flat_to_canonical(template_data)

            elif source_format == TemplateFormat.JSON_STUFFED:
                return self._convert_json_stuffed_to_canonical(template_data)

            else:
                # Unknown format - return as-is
                logger.warning(f"Unknown template format, returning as-is")
                return template_data.copy()

        except Exception as e:
            logger.error(f"Format conversion failed: {e}")
            raise FormatConversionError(f"Failed to convert to canonical: {str(e)}")

    def convert_to_export_format(
        self,
        template_data: Dict[str, Any],
        template_type: str = "mcq"
    ) -> Dict[str, Any]:
        """
        Convert template data to export-ready format.

        This ensures data is in the right shape for SCORM export,
        with all required fields present and types validated.

        Args:
            template_data: Source template data
            template_type: Type of template

        Returns:
            Export-ready dictionary

        Raises:
            FormatConversionError: If conversion fails
        """
        # First convert to canonical
        canonical = self.convert_to_canonical(template_data, template_type)

        # Then apply type validations
        return self._validate_for_export(canonical, template_type)

    def _convert_flat_to_canonical(self, flat_data: Dict[str, Any]) -> Dict[str, Any]:
        """Convert flat MCQ format to canonical."""
        canonical = {}

        # Extract common fields
        for key in ("explanation", "category", "difficulty"):
            if key in flat_data:
                canonical[key] = flat_data[key]

        # Convert question + options to questions array
        if "question" in flat_data:
            question_obj = {
                "id": flat_data.get("id", "q0"),
                "question": flat_data["question"],
                "options": []
            }

            # Add explanation if present
            if "explanation" in flat_data:
                question_obj["explanation"] = flat_data["explanation"]

            # Process options
            if "options" in flat_data and isinstance(flat_data["options"], list):
                for opt_idx, option in enumerate(flat_data["options"]):
                    if isinstance(option, dict):
                        question_obj["options"].append({
                            "id": option.get("id", f"opt_{opt_idx}"),
                            "text": option.get("text", ""),
                            "isCorrect": option.get("isCorrect", option.get("correct", False))
                        })
                    elif isinstance(option, str):
                        # Just a string option
                        question_obj["options"].append({
                            "id": f"opt_{opt_idx}",
                            "text": option,
                            "isCorrect": False
                        })

            canonical["questions"] = [question_obj]

        return canonical

    def _convert_json_stuffed_to_canonical(
        self,
        stuffed_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Convert JSON-stuffed format to canonical."""
        canonical = {}

        # Check for embedded JSON
        for key in ("content", "data_json", "json_content"):
            if key in stuffed_data:
                content = stuffed_data[key]
                if isinstance(content, str):
                    try:
                        parsed = json.loads(content)
                        if isinstance(parsed, dict):
                            # Recursively convert the parsed data
                            return self.convert_to_canonical(parsed)
                    except (json.JSONDecodeError, ValueError):
                        logger.debug(f"Could not parse {key} as JSON")
                        continue

        # If no JSON found, try flat format conversion
        return self._convert_flat_to_canonical(stuffed_data)

    def _validate_for_export(
        self,
        canonical_data: Dict[str, Any],
        template_type: str
    ) -> Dict[str, Any]:
        """Validate and prepare data for export."""
        validated = canonical_data.copy()

        # MCQ-specific validation
        if template_type == "mcq":
            if "questions" in validated and isinstance(validated["questions"], list):
                for question in validated["questions"]:
                    if "options" in question and isinstance(question["options"], list):
                        # Ensure all options have required fields
                        for option in question["options"]:
                            if "isCorrect" not in option:
                                option["isCorrect"] = False

        return validated

    def normalize_mcq_options(
        self,
        options: Union[list, dict]
    ) -> list:
        """
        Normalize MCQ options to standard format.

        Handles various option formats and returns standardized list.

        Args:
            options: Options in various formats

        Returns:
            Normalized options list

        Example:
            >>> converter = TemplateDataConverter()
            >>> opts = [{"text": "A"}, {"text": "B"}]
            >>> normalized = converter.normalize_mcq_options(opts)
            >>> normalized[0]["isCorrect"]
            False
        """
        if not isinstance(options, list):
            return []

        normalized = []
        for idx, option in enumerate(options):
            if isinstance(option, dict):
                normalized.append({
                    "id": option.get("id", f"opt_{idx}"),
                    "text": option.get("text", ""),
                    "isCorrect": option.get("isCorrect", option.get("correct", False))
                })
            elif isinstance(option, str):
                normalized.append({
                    "id": f"opt_{idx}",
                    "text": option,
                    "isCorrect": False
                })

        return normalized

    def get_format_summary(self, template_data: Dict[str, Any]) -> str:
        """
        Get a human-readable summary of the detected format.

        Args:
            template_data: Template data to analyze

        Returns:
            Format description string
        """
        fmt = self.auto_detect_format(template_data)

        summaries = {
            TemplateFormat.CANONICAL: "Canonical format (normalized structure)",
            TemplateFormat.FLAT: "Flat format (legacy question + options)",
            TemplateFormat.JSON_STUFFED: "JSON-stuffed format (embedded JSON)",
            TemplateFormat.UNKNOWN: "Unknown format"
        }

        return summaries.get(fmt, "Unknown format")
