"""Exceptions raised by the package.

Every exception derives from :class:`NFExtractorError`, so callers can handle all
expected failures with a single ``except`` clause.
"""


class NFExtractorError(Exception):
    """Base class for every expected failure in this package."""


class UnsupportedDocumentError(NFExtractorError):
    """The input file cannot be read, is too large, or has an unsupported format."""


class UnknownDocumentTypeError(NFExtractorError):
    """The requested document type is not registered."""


class ExtractionError(NFExtractorError):
    """The extraction backend failed or returned an unusable response."""


class ExtractionRefusedError(ExtractionError):
    """The model declined to process the document."""


class ExtractionTruncatedError(ExtractionError):
    """The response hit the output token limit before it was complete."""
