"""
Heuristic Parser for extracting JSON payloads from minified JavaScript.

Uses pyjsparser for AST analysis with regex fallback for simple cases.
"""

import re
import json
import logging
from typing import Optional, Dict, Any, List
from pathlib import Path

logger = logging.getLogger(__name__)

try:
    from pyjsparser import parse as js_parse
    PYJSPARSER_AVAILABLE = True
except ImportError:
    PYJSPARSER_AVAILABLE = False
    logger.warning("pyjsparser not available; using regex fallback only")


class ParseError(Exception):
    """Raised when parsing fails."""
    pass


class HeuristicParser:
    """Parser for extracting JSON payloads from JavaScript files."""

    def __init__(self):
        self.pyjsparser_available = PYJSPARSER_AVAILABLE

    def extract_json_from_js(self, js_content: str) -> List[Dict[str, Any]]:
        """
        Extract JSON payloads from JavaScript content.

        Tries multiple strategies:
        1. AST parsing with pyjsparser (for minified code)
        2. Regex pattern matching (fallback)
        3. eval/Function extraction (safe pattern matching)

        Args:
            js_content: JavaScript source code (possibly minified)

        Returns:
            List of extracted JSON objects

        Raises:
            ParseError: If no JSON payloads can be extracted
        """
        payloads = []

        # Strategy 1: AST parsing
        if self.pyjsparser_available:
            try:
                payloads.extend(self._extract_via_ast(js_content))
                if payloads:
                    logger.info(f"AST parsing found {len(payloads)} payload(s)")
                    return payloads
            except Exception as e:
                logger.debug(f"AST parsing failed: {e}, trying regex fallback")

        # Strategy 2: Regex patterns
        try:
            payloads.extend(self._extract_via_regex(js_content))
            if payloads:
                logger.info(f"Regex parsing found {len(payloads)} payload(s)")
                return payloads
        except Exception as e:
            logger.debug(f"Regex parsing failed: {e}")

        # Strategy 3: Simple JSON object detection
        try:
            payloads.extend(self._extract_simple_objects(js_content))
            if payloads:
                logger.info(f"Simple object detection found {len(payloads)} payload(s)")
                return payloads
        except Exception as e:
            logger.debug(f"Simple object detection failed: {e}")

        if not payloads:
            raise ParseError("No JSON payloads found in JavaScript content")

        return payloads

    def _extract_via_ast(self, js_content: str) -> List[Dict[str, Any]]:
        """Extract JSON via pyjsparser AST analysis."""
        if not PYJSPARSER_AVAILABLE:
            return []

        try:
            ast = js_parse(js_content)
            payloads = []

            # Walk the AST looking for assignments
            self._walk_ast(ast, payloads)
            return payloads

        except Exception as e:
            logger.debug(f"AST parse error: {e}")
            return []

    def _walk_ast(self, node: Any, payloads: List[Dict[str, Any]]) -> None:
        """Recursively walk AST looking for object/array assignments."""
        if not isinstance(node, dict):
            return

        # Check for AssignmentExpression (var x = {...})
        if node.get("type") == "AssignmentExpression":
            right = node.get("right", {})
            if right.get("type") in ("ObjectExpression", "ArrayExpression"):
                try:
                    obj = self._ast_node_to_python(right)
                    if isinstance(obj, (dict, list)):
                        payloads.append(obj)
                except Exception as e:
                    logger.debug(f"Failed to convert AST node: {e}")

        # Recurse into child nodes
        for key, value in node.items():
            if isinstance(value, dict):
                self._walk_ast(value, payloads)
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        self._walk_ast(item, payloads)

    def _ast_node_to_python(self, node: Any) -> Any:
        """Convert pyjsparser AST node to Python object."""
        if not isinstance(node, dict):
            return node

        node_type = node.get("type")

        if node_type == "ObjectExpression":
            result = {}
            for prop in node.get("properties", []):
                key = self._get_prop_key(prop)
                value = self._ast_node_to_python(prop.get("value"))
                if key:
                    result[key] = value
            return result

        elif node_type == "ArrayExpression":
            return [
                self._ast_node_to_python(elem)
                for elem in node.get("elements", [])
            ]

        elif node_type == "Literal":
            return node.get("value")

        elif node_type == "Identifier":
            # Cannot resolve identifiers during static analysis
            return None

        else:
            return None

    def _get_prop_key(self, prop: Dict[str, Any]) -> Optional[str]:
        """Extract property key from AST property node."""
        key_node = prop.get("key", {})

        if key_node.get("type") == "Identifier":
            return key_node.get("name")
        elif key_node.get("type") == "Literal":
            return str(key_node.get("value"))

        return None

    def _extract_via_regex(self, js_content: str) -> List[Dict[str, Any]]:
        """Extract JSON via regex patterns."""
        payloads = []

        # Pattern 1: var name = {...}
        # Find variable assignments and extract complete JSON objects
        var_pattern = r"(?:var|const|let)\s+(\w+)\s*=\s*(.+?)(?=[;,]\s*(?:var|const|let|$))"
        
        for match in re.finditer(var_pattern, js_content, re.DOTALL):
            var_name = match.group(1)
            var_value = match.group(2).rstrip(';, \n\t')
            
            # Try to parse as JSON object
            if var_value.startswith('{') and var_value.endswith('}'):
                try:
                    obj = json.loads(var_value)
                    if isinstance(obj, dict):
                        payloads.append(obj)
                        logger.debug(f"Extracted object from {var_name}")
                        continue
                except json.JSONDecodeError as e:
                    logger.debug(f"Failed to parse {var_name} as object: {e}")
            
            # Try to parse as JSON array
            if var_value.startswith('[') and var_value.endswith(']'):
                try:
                    arr = json.loads(var_value)
                    if isinstance(arr, list):
                        payloads.append(arr)
                        logger.debug(f"Extracted array from {var_name}")
                        continue
                except json.JSONDecodeError as e:
                    logger.debug(f"Failed to parse {var_name} as array: {e}")

        return payloads

    def _extract_simple_objects(self, js_content: str) -> List[Dict[str, Any]]:
        """Try to find JSON strings directly in content."""
        payloads = []

        # Look for standalone JSON objects/arrays
        pattern = r"(\{[\s\S]*?\}|\[[\s\S]*?\])"
        for match in re.finditer(pattern, js_content):
            try:
                obj = json.loads(match.group(1))
                if isinstance(obj, (dict, list)):
                    # Check if it looks like course data
                    if self._looks_like_course_data(obj):
                        payloads.append(obj)
            except (json.JSONDecodeError, ValueError):
                pass

        return payloads

    def _looks_like_course_data(self, obj: Any) -> bool:
        """Heuristic check if object looks like course data."""
        if isinstance(obj, dict):
            # Check for course-like keys
            keys = obj.keys()
            course_keys = {"courseId", "title", "templates", "slides", "pages"}
            return bool(keys & course_keys)
        elif isinstance(obj, list) and obj:
            # Check if it's a list of template-like objects
            return isinstance(obj[0], dict) and any(
                key in obj[0].keys()
                for key in {"type", "id", "title", "data"}
            )
        return False

    def extract_from_file(self, file_path: Path) -> List[Dict[str, Any]]:
        """Extract JSON payloads from a JavaScript file."""
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
            return self.extract_json_from_js(content)
        except Exception as e:
            logger.error(f"Failed to parse {file_path}: {e}")
            return []
