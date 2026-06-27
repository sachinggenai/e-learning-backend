"""content-writer-mcp — Phase 3.1.

MCP server wrapping AGT-07 Content Generator Agent.
Independently deployable for scaling content generation with GPU instances.

Tools exposed:
    - generate_page_content: Generate full educational content for a single page
    - health: Health check with model availability and rate limit status
"""
