"""Template Marking System — Deterministic marker parser for DOCX annotations.

Parses plain-text template markers ([PAGE:], [COMPONENT:], [ITEM:],
[QUESTION:], etc.) from extracted DOCX paragraphs and builds a structured
MarkedDocument tree. When markers are absent, returns MarkedDocument with
has_markers=False so the existing heuristic/LLM pipeline runs unchanged.

Architecture:
    Stack-based, single-pass parser. O(n) over paragraphs, O(d) stack depth
    (d = nesting depth, default max 3). Pure stdlib (re, dataclasses).

Usage:
    parser = MarkedDocumentParser()
    if parser.has_markers(paragraphs):
        doc = parser.parse(paragraphs)
        if doc.parse_errors:
            # report errors to user
        else:
            # use doc.pages for deterministic page plan
    else:
        # existing pipeline — no markers found

TRD: Template Marking System v1.0
FRD: FRD-TMS-001
Branch: agentic-ai-architecture
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, ClassVar, Literal

logger = logging.getLogger("ai_authoring")


# ═══════════════════════════════════════════════════════════════════════════
# Data Structures
# ═══════════════════════════════════════════════════════════════════════════


@dataclass
class ParseLocation:
    """Identifies where in the document a parse event occurred.

    Attributes:
        paragraph_index: Zero-based index into the source paragraphs list.
        marker_type: The marker type being parsed ("PAGE", "COMPONENT",
                     "ITEM", "QUESTION", "OPTION", etc.).
        context_preview: The first 120 chars of the marker line for
                         user-facing error messages.
    """
    paragraph_index: int = 0
    marker_type: str = ""
    context_preview: str = ""


@dataclass
class ParseError:
    """A structured error or warning from marker parsing.

    Attributes:
        code: Machine-readable error code (e.g. "UNCLOSED_MARKER").
        message: Human-readable error description.
        location: Where the error occurred.
        severity: "error" blocks pipeline; "warning" is informational.
        suggestion: Optional suggested fix text for user feedback.
    """
    code: str
    message: str
    location: ParseLocation
    severity: Literal["error", "warning"]
    suggestion: str = ""


@dataclass
class MarkedItem:
    """One item inside a component.

    Examples:
      - A tab in a tabs component
      - An accordion panel in an accordion
      - A reveal item in click-reveal
      - A question in an assessment
      - An option in a question

    Attributes:
        title: The item's display title (from [ITEM: title] or [QUESTION: type]).
        content: The item's body text (paragraphs between open and close markers).
        item_type: Semantic type discriminator.
        order_index: Position within the parent component (0-based).
        metadata: Extra key-value pairs from marker attributes.
        source_paragraph_indices: Which source paragraphs produced this item.
    """
    title: str = ""
    content: str = ""
    item_type: str = "tab"  # tab, accordion-item, reveal-item, question, option, feedback
    order_index: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)
    source_paragraph_indices: list[int] = field(default_factory=list)


@dataclass
class MarkedComponent:
    """A single component within a page.

    Components are the structural building blocks of pages. Each has a
    component_type (tabs, accordion, mcq, etc.), items (tabs, accordion
    panels, questions), and optional children (nested components).

    Attributes:
        component_type: The type slug (must be in VALID_COMPONENT_TYPES).
        order_index: Position within the parent page (0-based).
        items: Direct child items (tabs, accordion panels, questions, etc.).
        children: Nested MarkedComponents (for hierarchical content).
        raw_content: Unstructured text between open/close that didn't
                     match item markers.
        source_paragraph_indices: Which source paragraphs produced this component.
        attributes: Key-value pairs from marker attributes.
        parent_page_index: Index of the containing page, or -1 if not yet assigned.
    """
    component_type: str = "content-text"
    order_index: int = 0
    items: list[MarkedItem] = field(default_factory=list)
    children: list[MarkedComponent] = field(default_factory=list)
    raw_content: str = ""
    source_paragraph_indices: list[int] = field(default_factory=list)
    attributes: dict[str, str] = field(default_factory=dict)
    parent_page_index: int = -1


@dataclass
class MarkedPage:
    """A single page defined by [PAGE: ...] ... [/PAGE] markers.

    Attributes:
        title: The page title (from the `title` attribute).
        template_type: The page-level template (must be in VALID_TEMPLATE_TYPES).
        order: The page order (from `order` attribute, or auto-assigned).
        components: All components on this page.
        source_paragraph_indices: Which source paragraphs produced this page.
        raw_content: Full unstripped content text for the page.
        attributes: All key-value pairs from the PAGE marker.
    """
    title: str = ""
    template_type: str = "content-text"
    order: int = 0
    components: list[MarkedComponent] = field(default_factory=list)
    source_paragraph_indices: list[int] = field(default_factory=list)
    raw_content: str = ""
    attributes: dict[str, str] = field(default_factory=dict)


@dataclass
class MarkedDocument:
    """The complete result of parsing a document for markers.

    Attributes:
        has_markers: True if any markers were found. When False, the
                     existing pipeline runs unchanged.
        source_filename: The original document filename.
        pages: All parsed pages (empty if has_markers=False).
        unmarked_paragraphs: Paragraphs that came before/after/between
                             marker blocks (for hybrid content).
        parse_errors: All errors and warnings from parsing.
        warnings: Flat list of warning strings.
        metadata: Arbitrary metadata about the parse (timing, version, etc.).
    """
    has_markers: bool = False
    source_filename: str = ""
    pages: list[MarkedPage] = field(default_factory=list)
    unmarked_paragraphs: list[dict] = field(default_factory=list)
    parse_errors: list[ParseError] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    # ── Serialization ────────────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dict for storage in source_metadata."""
        return {
            "has_markers": self.has_markers,
            "source_filename": self.source_filename,
            "pages": [_page_to_dict(p) for p in self.pages],
            "unmarked_paragraph_count": len(self.unmarked_paragraphs),
            "parse_error_count": len(self.parse_errors),
            "parse_errors": [
                {
                    "code": e.code,
                    "message": e.message,
                    "paragraph_index": e.location.paragraph_index,
                    "marker_type": e.location.marker_type,
                    "context_preview": e.location.context_preview,
                    "severity": e.severity,
                    "suggestion": e.suggestion,
                }
                for e in self.parse_errors
            ],
            "warnings": self.warnings,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MarkedDocument:
        """Deserialize from a dict (inverse of to_dict)."""
        if not data or not data.get("has_markers"):
            return cls(has_markers=False)

        doc = cls(
            has_markers=True,
            source_filename=data.get("source_filename", ""),
            warnings=list(data.get("warnings", [])),
            metadata=dict(data.get("metadata", {})),
        )

        # Rebuild parse errors
        for e_data in data.get("parse_errors", []):
            doc.parse_errors.append(ParseError(
                code=e_data.get("code", ""),
                message=e_data.get("message", ""),
                location=ParseLocation(
                    paragraph_index=e_data.get("paragraph_index", 0),
                    marker_type=e_data.get("marker_type", ""),
                    context_preview=e_data.get("context_preview", ""),
                ),
                severity=e_data.get("severity", "error"),
                suggestion=e_data.get("suggestion", ""),
            ))

        # Rebuild pages
        for p_data in data.get("pages", []):
            page = MarkedPage(
                title=p_data.get("title", "Untitled"),
                template_type=p_data.get("template_type", "content-text"),
                order=p_data.get("order", 0),
                source_paragraph_indices=list(p_data.get("source_paragraph_indices", [])),
                attributes=dict(p_data.get("attributes", {})),
            )
            for c_data in p_data.get("components", []):
                page.components.append(_component_from_dict(c_data))
            doc.pages.append(page)

        return doc


# ── Serialization helpers ───────────────────────────────────────────────


def _page_to_dict(p: MarkedPage) -> dict[str, Any]:
    return {
        "title": p.title,
        "template_type": p.template_type,
        "order": p.order,
        "components": [_component_to_dict(c) for c in p.components],
        "source_paragraph_indices": list(p.source_paragraph_indices),
        "raw_content": p.raw_content,
        "attributes": dict(p.attributes),
    }


def _component_to_dict(c: MarkedComponent) -> dict[str, Any]:
    return {
        "component_type": c.component_type,
        "order_index": c.order_index,
        "items": [
            _item_to_dict(i)
            for i in c.items
        ],
        "children": [_component_to_dict(ch) for ch in c.children],
        "raw_content": c.raw_content,
        "source_paragraph_indices": list(c.source_paragraph_indices),
        "attributes": dict(c.attributes),
        "parent_page_index": c.parent_page_index,
    }


def _item_to_dict(i: MarkedItem) -> dict[str, Any]:
    """Serialize a MarkedItem, including any _children in metadata.

    Places is_correct at the TOP level of each child dict (not nested in
    child's metadata) so that from_dict() can read it consistently.
    """
    result = {
        "title": i.title,
        "content": i.content,
        "item_type": i.item_type,
        "order_index": i.order_index,
        "metadata": _item_metadata_to_dict(i.metadata),
        "source_paragraph_indices": list(i.source_paragraph_indices),
    }
    return result


def _component_from_dict(d: dict[str, Any]) -> MarkedComponent:
    c = MarkedComponent(
        component_type=d.get("component_type", "content-text"),
        order_index=d.get("order_index", 0),
        raw_content=d.get("raw_content", ""),
        source_paragraph_indices=list(d.get("source_paragraph_indices", [])),
        attributes=dict(d.get("attributes", {})),
        parent_page_index=d.get("parent_page_index", -1),
    )
    for i_data in d.get("items", []):
        item = MarkedItem(
            title=i_data.get("title", ""),
            content=i_data.get("content", ""),
            item_type=i_data.get("item_type", "tab"),
            order_index=i_data.get("order_index", 0),
            metadata=dict(i_data.get("metadata", {})),
        )
        # Reconstruct _children from serialized form
        children_data = i_data.get("metadata", {}).get("_children", [])
        if children_data:
            reconstructed = []
            for ch_data in children_data:
                # is_correct is at the TOP level of the serialized child dict
                is_correct_val = ch_data.get("is_correct", False)
                ch_item = MarkedItem(
                    title=ch_data.get("title", ""),
                    content=ch_data.get("content", ""),
                    item_type=ch_data.get("item_type", "option"),
                    order_index=ch_data.get("order_index", 0),
                    metadata={"is_correct": is_correct_val},
                )
                reconstructed.append(ch_item)
            item.metadata["_children"] = reconstructed
        c.items.append(item)
    for ch_data in d.get("children", []):
        c.children.append(_component_from_dict(ch_data))
    return c


def _item_metadata_to_dict(meta: dict[str, Any]) -> dict[str, Any]:
    """Serialize item metadata, handling _children with MarkedItem objects."""
    result = {}
    for key, value in meta.items():
        if key == "_children" and isinstance(value, list):
            result[key] = []
            for child in value:
                if isinstance(child, MarkedItem):
                    child_dict = {
                        "title": child.title,
                        "content": child.content,
                        "item_type": child.item_type,
                        "order_index": child.order_index,
                        "is_correct": child.metadata.get("is_correct", False)
                            if isinstance(child.metadata, dict) else False,
                        "metadata": _item_metadata_to_dict(child.metadata)
                            if isinstance(child.metadata, dict) else {},
                        "source_paragraph_indices": list(child.source_paragraph_indices),
                    }
                    result[key].append(child_dict)
        else:
            result[key] = value
    return result


# ═══════════════════════════════════════════════════════════════════════════
# MarkedDocumentParser
# ═══════════════════════════════════════════════════════════════════════════


class MarkedDocumentParser:
    """Parses [PAGE:...], [COMPONENT:...], [ITEM:...], [QUESTION:...] markers
    from a list of paragraph dicts (the output of DocumentExtractor).

    Stack-based, single-pass parser. When markers are absent, returns
    MarkedDocument(has_markers=False) so the existing pipeline runs unchanged.
    Thread-safe: all state is local to parse().
    """

    # ── Compiled regex patterns (class-level, compiled once) ────────────

    # Open markers: [TYPE: positional_arg | key: val | key2: val2]
    # Uses negative lookahead to NOT match [/ inside the attribute string
    _MARKER_OPEN: ClassVar[re.Pattern] = re.compile(
        r'^\[(PAGE|COMPONENT|ITEM|QUESTION|OPTION|FEEDBACK|'
        r'LEARNING_OBJECTIVE|KEY_TAKEAWAY|CALLOUT):'
        r'\s*((?:(?!\[/).)*?)\]'
    )

    # Close markers: [/TYPE]
    _MARKER_CLOSE: ClassVar[re.Pattern] = re.compile(
        r'^\[/(PAGE|COMPONENT|ITEM|QUESTION|OPTION|FEEDBACK|'
        r'LEARNING_OBJECTIVE|KEY_TAKEAWAY|CALLOUT)\]$'
    )

    # Attribute parser: key: value (handles pipes between key:value pairs)
    _ATTRIBUTE_PAT: ClassVar[re.Pattern] = re.compile(
        r'(\w+)\s*:\s*([^|]+?)(?:\s*\||\s*$)'
    )

    # Comment markers (GitHub-style): [//]: # (comment text)
    _COMMENT_PAT: ClassVar[re.Pattern] = re.compile(
        r'^\[//\]:\s*#\s*\(.*\)$'
    )

    # Escaped marker detection: backslash before bracket
    _ESCAPE_PAT: ClassVar[re.Pattern] = re.compile(
        r'\\(\[(?:PAGE|COMPONENT|ITEM|QUESTION|OPTION|FEEDBACK|CALLOUT)[:\]])'
    )

    # Quick pre-scan: look for any [PAGE: marker
    _HAS_MARKERS_PAT: ClassVar[re.Pattern] = re.compile(
        r'^\[PAGE:\s*\w+', re.MULTILINE
    )

    # Simple markers without attributes: [FEEDBACK], [LEARNING_OBJECTIVE], [KEY_TAKEAWAY]
    # No $ anchor — suffix after ] is handled by inline close processing
    _SIMPLE_MARKER_OPEN: ClassVar[re.Pattern] = re.compile(
        r'^\[(FEEDBACK|LEARNING_OBJECTIVE|KEY_TAKEAWAY)\]'
    )

    # Inline close detection: find close marker anywhere in text (not at start)
    _INLINE_CLOSE_PAT: ClassVar[re.Pattern] = re.compile(
        r'(\[/(?:PAGE|COMPONENT|ITEM|QUESTION|OPTION|FEEDBACK|'
        r'LEARNING_OBJECTIVE|KEY_TAKEAWAY|CALLOUT)\])'
    )

    # ── Valid value whitelists (frozen sets for O(1) membership) ────────

    VALID_TEMPLATE_TYPES: ClassVar[frozenset] = frozenset({
        "content-text", "tabs", "accordion", "click-reveal",
        "final-assessment", "welcome", "summary",
    })

    VALID_COMPONENT_TYPES: ClassVar[frozenset] = frozenset({
        "content-text", "tabs", "accordion", "click-reveal",
        "final-assessment", "mcq", "multi-select", "true-false",
        "image", "video", "callout",
    })

    VALID_QUESTION_TYPES: ClassVar[frozenset] = frozenset({
        "mcq", "true-false", "multi-select",
    })

    VALID_CALLOUT_TYPES: ClassVar[frozenset] = frozenset({
        "tip", "warning", "note", "important",
    })

    # ── Nesting rules: which marker types can contain which ─────────────
    _NESTING_RULES: ClassVar[dict[str, frozenset]] = {
        "PAGE": frozenset({"PAGE", "COMPONENT", "LEARNING_OBJECTIVE",
                           "KEY_TAKEAWAY", "CALLOUT"}),
        "COMPONENT": frozenset({"COMPONENT", "ITEM", "QUESTION",
                                "LEARNING_OBJECTIVE", "KEY_TAKEAWAY",
                                "CALLOUT"}),
        "ITEM": frozenset({"COMPONENT", "LEARNING_OBJECTIVE", "KEY_TAKEAWAY",
                           "CALLOUT"}),
        "QUESTION": frozenset({"OPTION", "FEEDBACK"}),
        "OPTION": frozenset(),
        "FEEDBACK": frozenset(),
        "LEARNING_OBJECTIVE": frozenset(),
        "KEY_TAKEAWAY": frozenset(),
        "CALLOUT": frozenset(),
    }

    # ── Maximum nesting depth ───────────────────────────────────────────
    _MAX_NESTING: int = 4  # PAGE > COMPONENT > QUESTION > OPTION (4 levels)

    # ── Item type mapping by parent component type ──────────────────────
    _ITEM_TYPE_MAP: ClassVar[dict[str, str]] = {
        "tabs": "tab",
        "accordion": "accordion-item",
        "click-reveal": "reveal-item",
    }

    def __init__(
        self,
        component_registry: Any = None,
        max_pages: int = 50,
        strict_mode: bool = False,
    ):
        """Initialize the parser.

        Args:
            component_registry: Optional ComponentTypeRegistry for
                                additional validation against DB types.
            max_pages: Maximum pages allowed in a single document.
            strict_mode: When True, parse errors become blocking.
        """
        self._component_registry = component_registry
        self._max_pages = max_pages
        self._strict_mode = strict_mode

    # ══════════════════════════════════════════════════════════════════
    # Public API
    # ══════════════════════════════════════════════════════════════════

    def has_markers(self, paragraphs: list[dict]) -> bool:
        """Fast pre-scan: does this document contain PAGE markers?

        Scans each paragraph's text. Returns True if any [PAGE: ...]
        marker is found. O(n) but early-exits on first match.

        Performance: <5ms for 500 paragraphs.
        """
        if not paragraphs:
            return False
        for para in paragraphs:
            text = para.get("text", "")
            if self._HAS_MARKERS_PAT.search(text):
                return True
        return False

    def parse(self, paragraphs: list[dict]) -> MarkedDocument:
        """Parse paragraphs into a MarkedDocument.

        This is the main entry point. Performs:
        1. Pre-scan via has_markers() (returns early if none)
        2. Single-pass stack-based parse
        3. Post-parse validation
        4. Error collection

        Args:
            paragraphs: List of dicts from DocumentExtractor, each
                        with at minimum a "text" key.

        Returns:
            MarkedDocument with pages, errors, and metadata populated.
        """
        doc = MarkedDocument(has_markers=True)

        if not paragraphs:
            doc.has_markers = False
            return doc

        if not self.has_markers(paragraphs):
            doc.has_markers = False
            doc.unmarked_paragraphs = list(paragraphs)
            return doc

        # ── Single-pass stack parse ──────────────────────────────────
        stack: list[dict] = []
        # Each frame: {"type": str, "data": object, "lines": list[str],
        #               "start_idx": int, "attr_string": str}

        page_counter = 0
        seen_page_titles: set[str] = set()
        seen_page_orders: set[int] = set()

        for para_idx, para in enumerate(paragraphs):
            text = para.get("text", "").strip()
            if not text:
                # Preserve blank lines for content accumulation
                if stack:
                    stack[-1]["lines"].append("")
                continue

            # 1. Handle comments (consume silently)
            if self._COMMENT_PAT.match(text):
                continue

            # 2. Handle escaped markers
            if text.startswith("\\[") and self._ESCAPE_PAT.match(text):
                unescaped = self._unescape(text)
                if stack:
                    stack[-1]["lines"].append(unescaped)
                continue

            # 2b. Try SIMPLE marker (no colon): [FEEDBACK], [LEARNING_OBJECTIVE], [KEY_TAKEAWAY]
            simple_match = self._SIMPLE_MARKER_OPEN.match(text)
            if simple_match:
                marker_type = simple_match.group(1)

                # Validate nesting
                if stack:
                    top_type = stack[-1]["type"]
                    allowed = self._NESTING_RULES.get(top_type, frozenset())
                    if marker_type not in allowed:
                        doc.parse_errors.append(ParseError(
                            code="NESTING_VIOLATION",
                            message=(
                                f"Cannot open '{marker_type}' inside "
                                f"'{top_type}' at paragraph {para_idx}"
                            ),
                            location=ParseLocation(
                                paragraph_index=para_idx,
                                marker_type=marker_type,
                                context_preview=text[:120],
                            ),
                            severity="error",
                            suggestion=f"Move [{marker_type}] outside [{top_type}].",
                        ))
                        continue

                item_type = marker_type.lower().replace("_", "-")
                stack.append({
                    "type": marker_type,
                    "data": MarkedItem(
                        title="",
                        content="",
                        item_type=item_type,
                        order_index=0,
                    ),
                    "lines": [],
                    "start_idx": para_idx,
                    "attr_string": "",
                })

                # Check for inline close suffix
                suffix_simple = text[simple_match.end():].strip()
                if suffix_simple:
                    close_tag = f"[/{marker_type}]"
                    close_idx = suffix_simple.find(close_tag)
                    if close_idx >= 0:
                        inline_content = suffix_simple[:close_idx].strip()
                        if inline_content and stack:
                            stack[-1]["lines"].append(inline_content)
                        self._handle_close_marker(
                            marker_type, text, para_idx, stack, doc, paragraphs,
                        )
                continue

            # 3. Try OPEN marker (with colon): [TYPE: ...]
            open_match = self._MARKER_OPEN.match(text)
            if open_match:
                marker_type = open_match.group(1)
                attr_string = open_match.group(2).strip()
                suffix = text[open_match.end():].strip()

                # Validate nesting against stack top
                if stack:
                    top_type = stack[-1]["type"]
                    allowed = self._NESTING_RULES.get(top_type, frozenset())
                    if marker_type not in allowed:
                        doc.parse_errors.append(ParseError(
                            code="NESTING_VIOLATION",
                            message=(
                                f"Cannot open '{marker_type}' inside "
                                f"'{top_type}' at paragraph {para_idx}"
                            ),
                            location=ParseLocation(
                                paragraph_index=para_idx,
                                marker_type=marker_type,
                                context_preview=text[:120],
                            ),
                            severity="error",
                            suggestion=(
                                f"Move the [{marker_type}:...] marker "
                                f"outside the [{top_type}:...] block."
                            ),
                        ))
                        continue

                # Check nesting depth
                current_depth = len(stack) + 1
                if current_depth > self._MAX_NESTING:
                    doc.parse_errors.append(ParseError(
                        code="MAX_NESTING_EXCEEDED",
                        message=(
                            f"Nesting depth {current_depth} exceeds "
                            f"maximum {self._MAX_NESTING} at paragraph {para_idx}"
                        ),
                        location=ParseLocation(
                            paragraph_index=para_idx,
                            marker_type=marker_type,
                            context_preview=text[:120],
                        ),
                        severity="error",
                        suggestion=f"Reduce nesting to {self._MAX_NESTING} levels or less.",
                    ))
                    continue

                # Dispatch to type-specific handler
                self._handle_open_marker(
                    marker_type, attr_string, text, para_idx,
                    stack, doc, page_counter, seen_page_titles,
                )

                if marker_type == "PAGE":
                    page_counter += 1

                # Handle inline close suffix (e.g., [OPTION: a]content[/OPTION])
                if suffix:
                    # Check if suffix starts with inline content ending with close
                    close_tag = f"[/{marker_type}]"
                    close_idx = suffix.find(close_tag)
                    if close_idx >= 0:
                        inline_content = suffix[:close_idx].strip()
                        if inline_content and stack:
                            stack[-1]["lines"].append(inline_content)
                        # Process the close inline
                        self._handle_close_marker(
                            marker_type, text, para_idx, stack, doc, paragraphs,
                        )
                continue

            # 4. Try CLOSE marker (at start or mid-text)
            close_match = self._MARKER_CLOSE.match(text)
            if close_match:
                close_type = close_match.group(1)
                self._handle_close_marker(
                    close_type, text, para_idx, stack, doc, paragraphs,
                )
                continue

            # 4b. Check for mid-text close: content followed by [/TYPE]
            inline_close = self._INLINE_CLOSE_PAT.search(text)
            if inline_close:
                close_type_inline = inline_close.group(1).strip("[/").rstrip("]")
                # Content before the close
                prefix = text[:inline_close.start()].strip()
                if prefix and stack:
                    stack[-1]["lines"].append(prefix)
                # Validate close type matches stack top
                if stack and stack[-1]["type"] == close_type_inline:
                    frame = stack.pop()
                    obj = frame["data"]
                    content_lines = frame.get("lines", [])
                    if hasattr(obj, "raw_content"):
                        obj.raw_content = "\n".join(content_lines)
                    if hasattr(obj, "content"):
                        obj.content = "\n".join(content_lines).strip()
                    if isinstance(obj, (MarkedPage, MarkedComponent)):
                        start_idx = frame.get("start_idx", para_idx)
                        obj.source_paragraph_indices = list(range(start_idx, para_idx + 1))
                    self._attach_to_parent(obj, close_type_inline, stack, doc, para_idx)
                elif stack:
                    doc.parse_errors.append(ParseError(
                        code="MISMATCHED_CLOSE",
                        message=(
                            f"Mismatched close: [/{close_type_inline}] does not match "
                            f"open [{stack[-1]['type']}:...] at paragraph {para_idx}"
                        ),
                        location=ParseLocation(
                            paragraph_index=para_idx,
                            marker_type=close_type_inline,
                            context_preview=text[:120],
                        ),
                        severity="error",
                        suggestion=f"Use [/{stack[-1]['type']}] instead.",
                    ))
                else:
                    doc.parse_errors.append(ParseError(
                        code="UNEXPECTED_CLOSE",
                        message=(
                            f"Unexpected [/{close_type_inline}] at paragraph "
                            f"{para_idx} — no matching open marker"
                        ),
                        location=ParseLocation(
                            paragraph_index=para_idx,
                            marker_type=close_type_inline,
                            context_preview=text[:120],
                        ),
                        severity="error",
                        suggestion=f"Remove the unmatched [/{close_type_inline}] marker.",
                    ))
                continue

            # 5. Regular text — accumulate into current stack frame
            if stack:
                stack[-1]["lines"].append(text)
            else:
                # Text outside any marker → unmarked
                doc.unmarked_paragraphs.append(para)

        # ── End of document: auto-close remaining open markers ──────
        while stack:
            frame = stack.pop()
            obj = frame["data"]
            content_lines = frame.get("lines", [])

            if hasattr(obj, "raw_content"):
                obj.raw_content = "\n".join(content_lines)
            if hasattr(obj, "content"):
                obj.content = "\n".join(content_lines).strip()

            start_idx = frame.get("start_idx", 0)
            ctx = ""
            if start_idx < len(paragraphs):
                ctx = paragraphs[start_idx].get("text", "")[:120]

            doc.parse_errors.append(ParseError(
                code="UNCLOSED_MARKER",
                message=(
                    f"Unclosed [{frame['type']}:...] opened at "
                    f"paragraph {start_idx}. Auto-closed at end of document."
                ),
                location=ParseLocation(
                    paragraph_index=start_idx,
                    marker_type=frame["type"],
                    context_preview=ctx,
                ),
                severity="error",
                suggestion=f"Add [/{frame['type']}] at the end of this block.",
            ))

            # Attach to parent if any parent remains
            self._attach_to_parent(obj, frame["type"], stack, doc, -1)

        # ── Post-parse validation ─────────────────────────────────────
        doc.parse_errors.extend(self.validate(doc))

        # Sort pages by order, preserving explicit marker orders
        doc.pages.sort(key=lambda p: (p.order, p.title))

        # Collect flat warnings
        doc.warnings = [
            e.message for e in doc.parse_errors
            if e.severity == "warning"
        ]

        # Build metadata
        doc.metadata = {
            "page_count": len(doc.pages),
            "component_count": sum(len(p.components) for p in doc.pages),
            "item_count": sum(
                sum(len(c.items) for c in p.components)
                for p in doc.pages
            ),
            "error_count": len([e for e in doc.parse_errors if e.severity == "error"]),
            "warning_count": len(doc.warnings),
            "parser_version": "1.0",
        }

        logger.info(
            "Parsed %d pages, %d components, %d errors, %d warnings",
            doc.metadata["page_count"],
            doc.metadata["component_count"],
            doc.metadata["error_count"],
            doc.metadata["warning_count"],
        )

        return doc

    def validate(self, doc: MarkedDocument) -> list[ParseError]:
        """Post-parse validation of a completed MarkedDocument.

        Runs structural checks that are easier to perform after the
        full document tree is built.

        Checks:
        - Assessment components must have at least 3 questions
        - Each question must have at least 2 options
        - Each question with "correct" attribute must have one correct option
        - Component item counts within BUSINESS_RULES limits
        - No empty pages (warning)
        - No duplicate page orders

        Returns:
            List of new ParseError objects.
        """
        errors: list[ParseError] = []
        seen_orders: set[int] = set()

        for page_idx, page in enumerate(doc.pages):
            # Check for empty page
            if not page.components:
                errors.append(ParseError(
                    code="EMPTY_PAGE",
                    message=f"Page '{page.title}' has no components.",
                    location=ParseLocation(
                        paragraph_index=page_idx,
                        marker_type="PAGE",
                        context_preview=page.title[:120],
                    ),
                    severity="warning",
                    suggestion="Add at least one [COMPONENT:...] to the page.",
                ))

            # Check for duplicate page order
            if page.order in seen_orders:
                errors.append(ParseError(
                    code="DUPLICATE_PAGE_ORDER",
                    message=(
                        f"Duplicate order {page.order} on page "
                        f"'{page.title}'."
                    ),
                    location=ParseLocation(
                        paragraph_index=page_idx,
                        marker_type="PAGE",
                        context_preview=page.title[:120],
                    ),
                    severity="warning",
                    suggestion=f"Change the order of '{page.title}' to a unique value.",
                ))
            seen_orders.add(page.order)

            # Validate each component
            for comp in page.components:
                errors.extend(self._validate_component(comp, page, page_idx))

        return errors

    # ══════════════════════════════════════════════════════════════════
    # Private: Open marker handlers
    # ══════════════════════════════════════════════════════════════════

    def _handle_open_marker(
        self,
        marker_type: str,
        attr_string: str,
        text: str,
        para_idx: int,
        stack: list[dict],
        doc: MarkedDocument,
        page_counter: int,
        seen_page_titles: set[str],
    ) -> None:
        """Create the appropriate object and push onto the stack."""
        attrs = self._parse_attributes(attr_string)

        if marker_type == "PAGE":
            template_type = self._extract_positional_type(attr_string, attrs)
            title = attrs.get("title", f"Page {page_counter + 1}")
            order = int(attrs.get("order", page_counter))

            # Validate template type
            if template_type not in self.VALID_TEMPLATE_TYPES:
                doc.parse_errors.append(ParseError(
                    code="INVALID_TEMPLATE_TYPE",
                    message=(
                        f"Unknown template type '{template_type}'. "
                        f"Valid: {sorted(self.VALID_TEMPLATE_TYPES)}"
                    ),
                    location=ParseLocation(
                        paragraph_index=para_idx,
                        marker_type="PAGE",
                        context_preview=text[:120],
                    ),
                    severity="error",
                    suggestion=f"Replace '{template_type}' with a valid template type.",
                ))

            # Check for duplicate page title (warning)
            title_lower = title.lower()
            if title_lower in seen_page_titles:
                doc.parse_errors.append(ParseError(
                    code="DUPLICATE_PAGE_TITLE",
                    message=f"Duplicate page title: '{title}' at paragraph {para_idx}",
                    location=ParseLocation(
                        paragraph_index=para_idx,
                        marker_type="PAGE",
                        context_preview=text[:120],
                    ),
                    severity="warning",
                    suggestion="Rename the page to a unique title.",
                ))
            seen_page_titles.add(title_lower)

            page_obj = MarkedPage(
                title=title,
                template_type=template_type,
                order=order,
                attributes=attrs,
            )
            stack.append({
                "type": "PAGE",
                "data": page_obj,
                "lines": [],
                "start_idx": para_idx,
                "attr_string": attr_string,
            })

        elif marker_type == "COMPONENT":
            comp_type = self._extract_positional_type(attr_string, attrs)

            # Validate component type
            if comp_type not in self.VALID_COMPONENT_TYPES:
                doc.parse_errors.append(ParseError(
                    code="INVALID_COMPONENT_TYPE",
                    message=(
                        f"Unknown component type '{comp_type}'. "
                        f"Valid: {sorted(self.VALID_COMPONENT_TYPES)}"
                    ),
                    location=ParseLocation(
                        paragraph_index=para_idx,
                        marker_type="COMPONENT",
                        context_preview=text[:120],
                    ),
                    severity="error",
                    suggestion=f"Replace '{comp_type}' with a valid component type.",
                ))

            comp_obj = MarkedComponent(
                component_type=comp_type,
                order_index=int(attrs.get("order", 0)),
                attributes=attrs,
            )
            stack.append({
                "type": "COMPONENT",
                "data": comp_obj,
                "lines": [],
                "start_idx": para_idx,
                "attr_string": attr_string,
            })

        elif marker_type == "ITEM":
            item_title = attr_string.strip()
            # Remove leading | if present
            if item_title.startswith("|"):
                item_title = item_title[1:].strip()
            # Parse attributes from the item title string (may contain | key: val)
            item_attrs = self._parse_attributes(item_title)
            # The item title is everything before the first key:value pair
            first_attr_match = self._ATTRIBUTE_PAT.search(item_title)
            if first_attr_match:
                clean_title = item_title[:first_attr_match.start()].strip()
            else:
                clean_title = item_title

            stack.append({
                "type": "ITEM",
                "data": MarkedItem(
                    title=clean_title,
                    content="",
                    item_type="tab",  # Refined in close handler
                    order_index=int(item_attrs.get("order", 0)),
                    metadata=item_attrs,
                ),
                "lines": [],
                "start_idx": para_idx,
                "attr_string": attr_string,
            })

        elif marker_type == "QUESTION":
            q_type = self._extract_positional_type(attr_string, attrs)

            if q_type and q_type not in self.VALID_QUESTION_TYPES:
                doc.parse_errors.append(ParseError(
                    code="INVALID_QUESTION_TYPE",
                    message=(
                        f"Unknown question type '{q_type}'. "
                        f"Valid: {sorted(self.VALID_QUESTION_TYPES)}"
                    ),
                    location=ParseLocation(
                        paragraph_index=para_idx,
                        marker_type="QUESTION",
                        context_preview=text[:120],
                    ),
                    severity="error",
                    suggestion=f"Replace '{q_type}' with mcq, true-false, or multi-select.",
                ))

            stack.append({
                "type": "QUESTION",
                "data": MarkedItem(
                    title=q_type or "mcq",
                    content="",
                    item_type="question",
                    order_index=int(attrs.get("order", 0)),
                    metadata=attrs,
                ),
                "lines": [],
                "start_idx": para_idx,
                "attr_string": attr_string,
            })

        elif marker_type == "OPTION":
            opt_id = self._extract_positional_type(attr_string, attrs)
            is_correct = attrs.get("correct", "false").lower() in ("true", "1", "yes")

            stack.append({
                "type": "OPTION",
                "data": MarkedItem(
                    title=opt_id or "",
                    content="",
                    item_type="option",
                    order_index=int(attrs.get("order", 0)),
                    metadata={**attrs, "is_correct": is_correct},
                ),
                "lines": [],
                "start_idx": para_idx,
                "attr_string": attr_string,
            })

        elif marker_type == "FEEDBACK":
            stack.append({
                "type": "FEEDBACK",
                "data": MarkedItem(
                    title="",
                    content="",
                    item_type="feedback",
                    order_index=0,
                ),
                "lines": [],
                "start_idx": para_idx,
                "attr_string": attr_string,
            })

        elif marker_type in ("LEARNING_OBJECTIVE", "KEY_TAKEAWAY", "CALLOUT"):
            item_type = marker_type.lower().replace("_", "-")
            stack.append({
                "type": marker_type,
                "data": MarkedItem(
                    title=attr_string.strip().lstrip("|").strip(),
                    content="",
                    item_type=item_type,
                    order_index=0,
                ),
                "lines": [],
                "start_idx": para_idx,
                "attr_string": attr_string,
            })

        else:
            doc.parse_errors.append(ParseError(
                code="UNKNOWN_MARKER",
                message=f"Unknown marker type '{marker_type}' at paragraph {para_idx}",
                location=ParseLocation(
                    paragraph_index=para_idx,
                    marker_type=marker_type,
                    context_preview=text[:120],
                ),
                severity="warning",
                suggestion="Check marker syntax. Use PAGE, COMPONENT, ITEM, QUESTION, OPTION, or FEEDBACK.",
            ))

    # ══════════════════════════════════════════════════════════════════
    # Private: Close marker handler
    # ══════════════════════════════════════════════════════════════════

    def _handle_close_marker(
        self,
        close_type: str,
        text: str,
        para_idx: int,
        stack: list[dict],
        doc: MarkedDocument,
        paragraphs: list[dict],
    ) -> None:
        """Pop the stack frame and attach to parent."""
        if not stack:
            doc.parse_errors.append(ParseError(
                code="UNEXPECTED_CLOSE",
                message=(
                    f"Unexpected [/{close_type}] at paragraph {para_idx} — "
                    f"no matching open marker"
                ),
                location=ParseLocation(
                    paragraph_index=para_idx,
                    marker_type=close_type,
                    context_preview=text[:120],
                ),
                severity="error",
                suggestion=f"Remove the unmatched [/{close_type}] marker.",
            ))
            return

        top = stack[-1]
        if top["type"] != close_type:
            doc.parse_errors.append(ParseError(
                code="MISMATCHED_CLOSE",
                message=(
                    f"Mismatched close: [/{close_type}] does not match "
                    f"open [{top['type']}:...] at paragraph {para_idx}"
                ),
                location=ParseLocation(
                    paragraph_index=para_idx,
                    marker_type=close_type,
                    context_preview=text[:120],
                ),
                severity="error",
                suggestion=f"Use [/{top['type']}] instead of [/{close_type}].",
            ))
            # Don't pop — preserve the stack
            return

        # Pop and finalize
        frame = stack.pop()
        obj = frame["data"]
        content_lines = frame.get("lines", [])

        if hasattr(obj, "raw_content"):
            obj.raw_content = "\n".join(content_lines)
        if hasattr(obj, "content"):
            obj.content = "\n".join(content_lines).strip()

        # Record source paragraph indices
        start_idx = frame.get("start_idx", para_idx)
        if isinstance(obj, (MarkedPage, MarkedComponent)):
            obj.source_paragraph_indices = list(range(start_idx, para_idx + 1))

        # Attach to parent
        self._attach_to_parent(obj, close_type, stack, doc, para_idx)

    # ══════════════════════════════════════════════════════════════════
    # Private: Helpers
    # ══════════════════════════════════════════════════════════════════

    def _parse_attributes(self, attr_string: str) -> dict[str, str]:
        """Parse a marker's attribute string into key-value pairs.

        Input: "content-text | title: My Page | order: 1"
        Returns: {"title": "My Page", "order": "1"}
        """
        if not attr_string:
            return {}
        attrs: dict[str, str] = {}
        for match in self._ATTRIBUTE_PAT.finditer(attr_string):
            key = match.group(1).strip()
            value = match.group(2).strip()
            if key and value is not None:
                attrs[key] = value
        return attrs

    def _extract_positional_type(
        self, attr_string: str, attrs: dict[str, str]
    ) -> str:
        """Extract the positional first argument from a marker.

        [PAGE: tabs | title: ...]
        The "tabs" is positional — it appears before any key:value pairs.
        """
        stripped = attr_string.strip()
        if not stripped:
            return ""

        # Remove leading pipe if present
        if stripped.startswith("|"):
            stripped = stripped[1:].strip()

        # Find the first key:value pair boundary
        first_attr = self._ATTRIBUTE_PAT.search(stripped)
        if first_attr:
            pos_type = stripped[:first_attr.start()].strip()
        else:
            pos_type = stripped

        # Strip trailing pipes and whitespace
        pos_type = pos_type.rstrip("| \t")
        return pos_type

    def _unescape(self, text: str) -> str:
        """Remove backslash escaping from marker syntax."""
        return text.lstrip("\\")

    def _attach_to_parent(
        self,
        obj: Any,
        marker_type: str,
        stack: list[dict],
        doc: MarkedDocument,
        para_idx: int,
    ) -> None:
        """Attach a completed object to its parent in the stack."""
        if not stack:
            # Top-level PAGE — add directly to document
            if isinstance(obj, MarkedPage):
                doc.pages.append(obj)
            return

        parent_frame = stack[-1]
        parent_obj = parent_frame["data"]

        if marker_type == "COMPONENT":
            if isinstance(parent_obj, MarkedPage):
                obj.parent_page_index = len(parent_obj.components)
                obj.order_index = len(parent_obj.components)
                parent_obj.components.append(obj)
            elif isinstance(parent_obj, MarkedComponent):
                parent_obj.children.append(obj)

        elif marker_type == "ITEM":
            if isinstance(parent_obj, MarkedComponent):
                # Determine item type from parent component type
                ptype = parent_obj.component_type
                obj.item_type = self._ITEM_TYPE_MAP.get(ptype, "tab")
                obj.order_index = len(parent_obj.items)
                parent_obj.items.append(obj)

        elif marker_type == "QUESTION":
            if isinstance(parent_obj, MarkedComponent):
                obj.order_index = len(parent_obj.items)
                parent_obj.items.append(obj)

        elif marker_type in ("OPTION", "FEEDBACK"):
            if isinstance(parent_obj, MarkedItem) and parent_obj.item_type == "question":
                children = parent_obj.metadata.setdefault("_children", [])
                children.append(obj)
            elif isinstance(parent_obj, MarkedComponent):
                obj.order_index = len(parent_obj.items)
                parent_obj.items.append(obj)

        elif marker_type in ("LEARNING_OBJECTIVE", "KEY_TAKEAWAY", "CALLOUT"):
            if isinstance(parent_obj, (MarkedPage, MarkedComponent)):
                if isinstance(parent_obj, MarkedComponent):
                    obj.order_index = len(parent_obj.items)
                    parent_obj.items.append(obj)

    def _validate_component(
        self,
        comp: MarkedComponent,
        page: MarkedPage,
        page_idx: int,
    ) -> list[ParseError]:
        """Validate a single component. Returns list of errors."""
        errors: list[ParseError] = []

        # Check empty component (warning)
        if not comp.items and not comp.children and not comp.raw_content.strip():
            errors.append(ParseError(
                code="EMPTY_COMPONENT",
                message=(
                    f"Empty {comp.component_type} component "
                    f"(order {comp.order_index}) on page '{page.title}'."
                ),
                location=ParseLocation(
                    paragraph_index=page_idx,
                    marker_type="COMPONENT",
                    context_preview=comp.component_type,
                ),
                severity="warning",
                suggestion=f"Add items or content to the {comp.component_type} component, or remove it.",
            ))

        # Assessment-specific validation
        if comp.component_type in ("final-assessment",):
            questions = [it for it in comp.items if it.item_type == "question"]
            if len(questions) < 3:
                errors.append(ParseError(
                    code="TOO_FEW_QUESTIONS",
                    message=(
                        f"Assessment has only {len(questions)} questions "
                        f"(minimum 3)."
                    ),
                    location=ParseLocation(
                        paragraph_index=page_idx,
                        marker_type="COMPONENT",
                        context_preview=comp.component_type,
                    ),
                    severity="warning",
                    suggestion=f"Add {3 - len(questions)} more questions to the assessment.",
                ))

            # Validate each question
            for q in questions:
                q_children = q.metadata.get("_children", [])
                options = [ch for ch in q_children if ch.item_type == "option"]

                if len(options) < 2:
                    errors.append(ParseError(
                        code="TOO_FEW_OPTIONS",
                        message=(
                            f"Question '{q.title}' has only "
                            f"{len(options)} options (minimum 2)."
                        ),
                        location=ParseLocation(
                            paragraph_index=page_idx,
                            marker_type="QUESTION",
                            context_preview=q.title,
                        ),
                        severity="warning",
                        suggestion=f"Add {2 - len(options)} more options to the question.",
                    ))

                correct_count = sum(
                    1 for o in options
                    if o.metadata.get("is_correct", False)
                )
                if correct_count == 0 and options:
                    errors.append(ParseError(
                        code="MISSING_CORRECT_ANSWER",
                        message=f"Question '{q.title}' has no correct option.",
                        location=ParseLocation(
                            paragraph_index=page_idx,
                            marker_type="QUESTION",
                            context_preview=q.title,
                        ),
                        severity="error",
                        suggestion="Add 'correct: true' to at least one option.",
                    ))

        # Component item count limits
        item_count = len(comp.items)
        if comp.component_type == "tabs" and item_count > 6:
            errors.append(ParseError(
                code="TOO_MANY_ITEMS",
                message=f"Tabs component has {item_count} tabs (maximum 6).",
                location=ParseLocation(
                    paragraph_index=page_idx,
                    marker_type="COMPONENT",
                    context_preview=comp.component_type,
                ),
                severity="warning",
                suggestion="Reduce to 6 tabs or split into multiple tab components.",
            ))

        if comp.component_type == "accordion" and item_count > 20:
            errors.append(ParseError(
                code="TOO_MANY_ITEMS",
                message=f"Accordion component has {item_count} items (maximum 20).",
                location=ParseLocation(
                    paragraph_index=page_idx,
                    marker_type="COMPONENT",
                    context_preview=comp.component_type,
                ),
                severity="warning",
                suggestion="Reduce to 20 items or split into multiple accordion components.",
            ))

        if comp.component_type == "click-reveal" and item_count > 10:
            errors.append(ParseError(
                code="TOO_MANY_ITEMS",
                message=f"Click-reveal component has {item_count} items (maximum 10).",
                location=ParseLocation(
                    paragraph_index=page_idx,
                    marker_type="COMPONENT",
                    context_preview=comp.component_type,
                ),
                severity="warning",
                suggestion="Reduce to 10 items or split into multiple click-reveal components.",
            ))

        # Recursively validate nested components
        for child in comp.children:
            errors.extend(self._validate_component(child, page, page_idx))

        return errors


# ═══════════════════════════════════════════════════════════════════════════
# Error Code Registry
# ═══════════════════════════════════════════════════════════════════════════

ERROR_CODES: dict[str, dict] = {
    "UNCLOSED_MARKER": {
        "severity": "error",
        "description": "A marker was opened but not closed before end of document.",
        "suggestion": "Add the corresponding close marker [/TYPE].",
    },
    "INVALID_TEMPLATE_TYPE": {
        "severity": "error",
        "description": "The template type in a [PAGE:] marker is not recognized.",
        "suggestion": "Use one of: content-text, tabs, accordion, click-reveal, final-assessment, welcome, summary.",
    },
    "INVALID_COMPONENT_TYPE": {
        "severity": "error",
        "description": "The component type in a [COMPONENT:] marker is not recognized.",
        "suggestion": "Use one of: content-text, tabs, accordion, click-reveal, final-assessment, mcq, image, video, callout.",
    },
    "INVALID_QUESTION_TYPE": {
        "severity": "error",
        "description": "The question type in a [QUESTION:] marker is not recognized.",
        "suggestion": "Use one of: mcq, true-false, multi-select.",
    },
    "NESTING_VIOLATION": {
        "severity": "error",
        "description": "A marker type was placed inside another type that cannot contain it.",
        "suggestion": "Check the nesting rules: PAGEs can contain COMPONENTs; COMPONENTs can contain ITEMs, QUESTIONs, and special markers.",
    },
    "MISSING_REQUIRED_ATTRIBUTE": {
        "severity": "error",
        "description": "A required attribute is missing from the marker.",
        "suggestion": "Add the required attribute to the marker.",
    },
    "DUPLICATE_PAGE_TITLE": {
        "severity": "warning",
        "description": "Two or more pages have the same title.",
        "suggestion": "Rename the page to a unique title.",
    },
    "EMPTY_COMPONENT": {
        "severity": "warning",
        "description": "A component has no content and no items.",
        "suggestion": "Add content or items to the component, or remove it.",
    },
    "UNKNOWN_MARKER": {
        "severity": "warning",
        "description": "An unrecognized marker type was encountered.",
        "suggestion": "Check marker syntax. Supported types: PAGE, COMPONENT, ITEM, QUESTION, OPTION, FEEDBACK, CALLOUT, LEARNING_OBJECTIVE, KEY_TAKEAWAY.",
    },
    "MAX_NESTING_EXCEEDED": {
        "severity": "error",
        "description": "Marker nesting depth exceeds the maximum allowed.",
        "suggestion": "Reduce nesting to 3 levels or less.",
    },
    "INVALID_ATTRIBUTE_VALUE": {
        "severity": "error",
        "description": "An attribute value failed validation.",
        "suggestion": "Check the attribute values for correctness.",
    },
    "MISSING_CORRECT_ANSWER": {
        "severity": "error",
        "description": "A question has no option marked correct.",
        "suggestion": "Add 'correct: true' to at least one option.",
    },
    "TOO_FEW_QUESTIONS": {
        "severity": "warning",
        "description": "An assessment has fewer than the minimum 3 questions.",
        "suggestion": "Add more questions to the assessment.",
    },
    "TOO_FEW_OPTIONS": {
        "severity": "warning",
        "description": "A question has fewer than the minimum 2 options.",
        "suggestion": "Add more options to the question.",
    },
    "TOO_MANY_ITEMS": {
        "severity": "warning",
        "description": "A component has more items than the maximum allowed.",
        "suggestion": "Reduce the number of items or split into multiple components.",
    },
    "EMPTY_PAGE": {
        "severity": "warning",
        "description": "A page has no components.",
        "suggestion": "Add at least one [COMPONENT:...] to the page.",
    },
    "UNEXPECTED_CLOSE": {
        "severity": "error",
        "description": "A close marker was found without a matching open marker.",
        "suggestion": "Remove the unmatched close marker.",
    },
    "MISMATCHED_CLOSE": {
        "severity": "error",
        "description": "A close marker does not match the most recent open marker.",
        "suggestion": "Match the close marker to its corresponding open marker.",
    },
    "MAX_PAGES_EXCEEDED": {
        "severity": "error",
        "description": "The document exceeds the maximum number of pages.",
        "suggestion": "Reduce the number of pages or increase the limit.",
    },
    "DUPLICATE_PAGE_ORDER": {
        "severity": "warning",
        "description": "Two or more pages have the same order value.",
        "suggestion": "Change the order of one of the pages.",
    },
}
