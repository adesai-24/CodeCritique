"""
JSON schemas documenting the expected shape of each AI pipeline response.

Ollama's format=json guarantees syntactically valid JSON but not structure.
Schema enforcement is carried by the prompts in prompts.py. These dicts serve
as documentation and can be used for runtime validation if needed.
"""

from typing import Any, Dict

CRITIC_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "line": {"type": "integer"},
                    "title": {"type": "string"},
                    "explanation": {"type": "string"},
                    "severity": {"type": "string", "enum": ["FATAL", "WARNING", "INFO"]},
                },
                "required": ["line", "title", "explanation", "severity"],
            },
        }
    },
    "required": ["findings"],
}

ENRICHMENT_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "reasoning": {"type": "string"},
        "suggested_fix": {"type": "string"},
        "real_severity": {"type": "string", "enum": ["FATAL", "WARNING", "INFO"]},
    },
    "required": ["reasoning", "suggested_fix", "real_severity"],
}

BATCH_ENRICHMENT_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "enrichments": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "reasoning": {"type": "string"},
                    "suggested_fix": {"type": "string"},
                    "real_severity": {"type": "string", "enum": ["FATAL", "WARNING", "INFO"]},
                },
                "required": ["reasoning", "suggested_fix", "real_severity"],
            },
        }
    },
    "required": ["enrichments"],
}

SYNTH_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "fix_first": {"type": "integer"},
        "critical": {"type": "array", "items": {"type": "integer"}},
        "warnings": {"type": "array", "items": {"type": "integer"}},
        "suggestions": {"type": "array", "items": {"type": "integer"}},
        "whats_good": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["summary", "fix_first", "critical", "warnings", "suggestions", "whats_good"],
}
