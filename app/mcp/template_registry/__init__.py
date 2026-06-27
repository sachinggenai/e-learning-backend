"""template-registry-mcp — Phase 3.3.

MCP server wrapping AITemplateContractsService for template schema management.
Enables independent template updates without app restart.

Tools exposed:
    - list_templates: List all available template types with descriptions
    - get_template_schema: Get JSON Schema for a specific template type
    - validate_against_template: Validate data against a template schema
    - search_templates: Semantic/keyword search for template discovery
    - health: Health check with template count
"""
