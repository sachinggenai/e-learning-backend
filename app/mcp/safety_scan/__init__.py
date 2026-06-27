"""safety-scan-mcp — Phase 3.2.

MCP server wrapping SafetyService for input/output/PII scanning.
Enables independent update of safety models without redeploying the main app.
Future: integration point for NeMo Guardrails.

Tools exposed:
    - scan_input: Scan user input for injection, jailbreak, PII, policy violations
    - scan_output: Scan AI-generated output for PII leaks, blocked terms
    - health: Health check with safety pattern status
"""
