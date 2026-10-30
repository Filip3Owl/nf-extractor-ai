"""Document types shipped with the package."""

from nf_extractor.core.document_type import DocumentTypeRegistry
from nf_extractor.document_types.nfe import NFE


def default_registry() -> DocumentTypeRegistry:
    """Build a registry containing every built-in document type."""
    registry = DocumentTypeRegistry()
    registry.register(NFE)
    return registry
