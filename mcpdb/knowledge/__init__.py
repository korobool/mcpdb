"""Pluggable knowledge augmentation — domain context for the agent pipeline."""

from __future__ import annotations

from mcpdb.knowledge.base import KnowledgeCategory, KnowledgeChunk
from mcpdb.knowledge.manager import KnowledgeManager

__all__ = ["KnowledgeCategory", "KnowledgeChunk", "KnowledgeManager"]
