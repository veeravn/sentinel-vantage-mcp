"""Scheduler process — alert-rule evaluation and scheduled briefings.

Runs outside the interactive MCP request lifecycle so alerts and briefs operate with
no MCP client connected. Phase 0 is a lifecycle stub; the rule engine lands in Phase 5.
"""
