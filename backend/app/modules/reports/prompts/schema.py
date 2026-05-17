"""JSON Schema for the Anthropic `submit_report` tool.

The schema mirrors (a subset of) ``ReportPayload`` — only the LLM-generated
sections. Deterministic metrics (funnel, heatmap, response_time, benchmarks)
are computed outside the LLM and merged at assembly time.
"""
from __future__ import annotations

LLM_TOOL_SCHEMA: dict = {
    "type": "object",
    "required": ["diagnostic_summary", "opportunities", "objections", "faqs", "sentiment"],
    "properties": {
        "diagnostic_summary": {
            "type": "string",
            "minLength": 50,
            "maxLength": 1500,
            "description": "3-5 sentences PT-BR, consultive tone, critical point first.",
        },
        "opportunities": {
            "type": "array",
            "minItems": 0,
            "maxItems": 5,
            "items": {
                "type": "object",
                "required": ["tag", "context", "reason", "value_brl", "when"],
                "properties": {
                    "tag": {"type": "string", "description": "P-XXXX style id."},
                    "context": {"type": "string", "description": "Short summary of the lead's request."},
                    "reason": {"type": "string"},
                    "value_brl": {"type": "number", "minimum": 0},
                    "when": {"type": "string", "description": "'X dias', 'Última semana', etc."},
                },
            },
        },
        "objections": {
            "type": "array",
            "minItems": 0,
            "maxItems": 3,
            "items": {
                "type": "object",
                "required": ["label", "pct", "count", "color"],
                "properties": {
                    "label": {"type": "string"},
                    "pct": {"type": "number", "minimum": 0, "maximum": 100},
                    "count": {"type": "integer", "minimum": 0},
                    "color": {"type": "string", "description": "Hex color #RRGGBB."},
                },
            },
        },
        "faqs": {
            "type": "array",
            "minItems": 0,
            "maxItems": 5,
            "items": {
                "type": "object",
                "required": ["q", "count"],
                "properties": {
                    "q": {"type": "string"},
                    "count": {"type": "integer", "minimum": 0},
                },
            },
        },
        "sentiment": {
            "type": "array",
            "minItems": 3,
            "maxItems": 3,
            "items": {
                "type": "object",
                "required": ["name", "value", "color"],
                "properties": {
                    "name": {"type": "string", "enum": ["Positivo", "Neutro", "Negativo"]},
                    "value": {"type": "integer", "minimum": 0, "maximum": 100},
                    "color": {"type": "string"},
                },
            },
        },
    },
}
