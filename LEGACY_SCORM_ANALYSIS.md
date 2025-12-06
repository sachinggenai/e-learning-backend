# Legacy SCORM 1.2 Import Analysis

## Executive Summary
This document details the technical requirements and implementation strategy for supporting the import of legacy SCORM 1.2 packages, specifically modeled after the `RuntimeMinimumCalls_SCORM12.zip` sample. These packages differ significantly from the application's native JSON-based format, relying on `imsmanifest.xml` for structure and procedural JavaScript for interaction data.

## Artifact Analysis: `RuntimeMinimumCalls_SCORM12.zip`

### 1. Structure
The package follows the standard SCORM 1.2 Content Aggregation Model (CAM):
*   **Manifest**: `imsmanifest.xml` at the root.
*   **Resources**: HTML files (SCOs) and Assets (images, JS, CSS).
*   **Organization**: Hierarchical structure defined in `<organization>`.

### 2. Manifest (`imsmanifest.xml`)
*   **Namespace**: `http://www.imsproject.org/xsd/imscp_rootv1p1p2` (and ADL/IMS MD namespaces).
*   **Organization**:
    *   `<organization>` element defines the course title.
    *   Nested `<item>` elements define the table of contents (modules/slides).
    *   Leaf `<item>` elements reference `<resource>` elements via `identifierref`.
    *   **Parameters**: Some items have query parameters, e.g., `parameters="?questions=Etiquette"`. This is critical for linking quizzes to data files.
*   **Resources**:
    *   Define the physical file paths (`href`).
    *   `adlcp:scormtype="sco"` indicates a launchable content object.
    *   `adlcp:scormtype="asset"` indicates a passive resource.

### 3. Content Types
The sample contains two primary content patterns:

#### A. Static HTML Content (SCO)
*   **Example**: `Playing/Playing.html`
*   **Structure**: Standard HTML with `<body>` containing `<h1>`, `<img>`, and `<p>` tags.
*   **Dependencies**: Links to `../shared/style.css` and `../shared/scormfunctions.js`.
*   **Import Strategy**:
    *   **Option 1 (Ideal)**: Parse the HTML, extract the body content (excluding scripts), and convert to a `content-text` template.
    *   **Option 2 (Fallback)**: Serve the HTML file as-is via an `iframe` template (requires new template type).
    *   **Decision**: For this implementation, we will attempt **Option 1** (Extraction) to maintain consistency with the authoring tool's native format.

#### B. JavaScript-based Quizzes
*   **Example**: `Etiquette/questions.js`
*   **Invocation**: The manifest item points to `shared/assessmenttemplate.html` with parameter `?questions=Etiquette`.
*   **Data Format**: Procedural JavaScript calls to `test.AddQuestion()`.
    ```javascript
    test.AddQuestion( new Question (
        "id",
        "Question Text",
        QUESTION_TYPE_CHOICE,
        new Array("Opt1", "Opt2"),
        "CorrectOpt",
        "objective_id"
    ));
    ```
*   **Import Strategy**:
    *   Parse the `questions.js` file using Regex.
    *   Map `QUESTION_TYPE_CHOICE` to `mcq`.
    *   Map `QUESTION_TYPE_TF` to `mcq` (True/False).
    *   Construct `Question` and `QuestionOption` objects.

## Data Mapping

| SCORM Element | App Model | Mapping Logic |
| :--- | :--- | :--- |
| `<organization><title>` | `Course.title` | Direct mapping. |
| `<item>` (Leaf) | `Template` | Each leaf item becomes a slide. |
| `<item><title>` | `Template.title` | Direct mapping. |
| Item Order | `Template.order` | Sequential index (0-based). |
| HTML Content (`<body>`) | `Template.data.content` | Sanitize and extract HTML body. |
| `questions.js` | `Template.data.questions` | Parse JS calls to `Question` objects. |
| `QUESTION_TYPE_CHOICE` | `Template.type="mcq"` | Standard MCQ. |
| `QUESTION_TYPE_TF` | `Template.type="mcq"` | MCQ with "True"/"False" options. |

## Technical Specification

### 1. Manifest Parsing
*   Use `xml.etree.ElementTree`.
*   Handle namespaces (strip them or register them).
*   Traverse `<organization>` recursively to flatten the structure into a linear list of templates.
*   Resolve `identifierref` to `href` in `<resources>`.

### 2. Question Parsing (Regex)
The parser must handle the specific signature of the `Question` constructor in the sample.

**Regex Pattern**:
```python
r'new\s+Question\s*\(\s*"(?P<id>[^"]+)"\s*,\s*"(?P<text>[^"]+)"\s*,\s*(?P<type>\w+)\s*,\s*(?P<answers>new\s+Array\([^)]+\)|null)\s*,\s*(?P<correct>[^,]+),\s*"(?P<obj_id>[^"]+)"\s*\)'
```
*Note: This regex needs refinement to handle escaped quotes and varying whitespace.*

### 3. HTML Extraction
*   Use `BeautifulSoup` (if available) or Regex to extract content between `<body>` and `</body>`.
*   Remove `<script>` tags.
*   Rewrite image `src` attributes if necessary (though if we keep the zip structure, relative paths might break unless we flatten assets). **Critical**: The import service currently extracts to a temp dir. We need to ensure assets are handled.
    *   *Current App Logic*: `AssetRewriter` handles this. We need to ensure the extracted HTML is passed to it.

## Implementation Plan

### Phase 1: Infrastructure
1.  **Modify `ImportService._discover_payloads`**: Add fallback to check for `imsmanifest.xml` if no JSON is found.
2.  **Create `LegacyScormImporter` class**: Encapsulate the logic.

### Phase 2: Parsing Logic
3.  **Implement `parse_manifest`**: Extract course structure.
4.  **Implement `parse_html_content`**: Extract text/images for `content-text` templates.
5.  **Implement `parse_js_questions`**: Extract MCQ data.

### Phase 3: Integration
6.  **Model Conversion**: Convert parsed data to `Course`, `Template`, `TemplateData`.
7.  **Asset Handling**: Ensure images referenced in HTML are accessible.

## Detailed Regex Logic for Questions

The `questions.js` format:
1.  **ID**: String literal.
2.  **Text**: String literal.
3.  **Type**: Variable (`QUESTION_TYPE_CHOICE`, `QUESTION_TYPE_TF`).
4.  **Answers**: `new Array("A", "B")` OR `null`.
5.  **Correct Answer**: String literal OR Boolean (`true`/`false`).
6.  **Objective**: String literal.

**Parsing Algorithm**:
1.  Find all `test.AddQuestion(...)` blocks.
2.  Inside the block, match `new Question(...)`.
3.  Split arguments carefully (respecting quoted strings containing commas).
4.  **If Type == CHOICE**:
    *   Parse `new Array(...)` to get options.
    *   Find `CorrectAnswer` in the options list to mark `isCorrect=True`.
5.  **If Type == TF**:
    *   Create options "True" and "False".
    *   If `CorrectAnswer` is `true`, mark "True" as correct.

## Limitations & Assumptions
*   **Assumption**: The JS format strictly follows the `test.AddQuestion(new Question(...))` pattern found in the sample.
*   **Assumption**: HTML content is simple enough to be embedded in a `content-text` template. Complex layouts will be lost.
*   **Limitation**: Nested items in the manifest will be flattened to a linear sequence.
