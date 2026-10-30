"""Brazilian electronic invoices: NF-e (model 55) and NFC-e (model 65)."""

from nf_extractor.core.document_type import DocumentType
from nf_extractor.document_types.nfe.instructions import INSTRUCTIONS
from nf_extractor.document_types.nfe.schema import NotaFiscal
from nf_extractor.document_types.nfe.validators import VALIDATORS

NFE = DocumentType[NotaFiscal](
    name="nfe",
    description="Brazilian electronic invoice (DANFE of an NF-e or NFC-e)",
    schema=NotaFiscal,
    instructions=INSTRUCTIONS,
    validators=VALIDATORS,
)

__all__ = ["NFE", "NotaFiscal"]
