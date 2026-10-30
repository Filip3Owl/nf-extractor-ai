# Adding a document type

A document type needs no changes to the pipeline or the extractors. This guide uses a simplified boleto as an example.

## 1. Create the subpackage

```text
src/nf_extractor/document_types/boleto/
├── __init__.py
├── instructions.py
├── schema.py
└── validators.py
```

## 2. Define the schema

Make fields nullable so the model can report an unreadable value instead of inventing one. Keep identifiers as plain strings and check them in validators, so that one bad value does not discard the whole extraction.

```python
# schema.py
from pydantic import BaseModel, ConfigDict

from nf_extractor.document_types.nfe.schema import BrDecimal


class Boleto(BaseModel):
    """A Brazilian bank payment slip. Use null for any value that is absent or unreadable."""

    model_config = ConfigDict(extra="forbid")

    linha_digitavel: str | None
    beneficiario_documento: str | None
    valor: BrDecimal | None
```

## 3. Write the instructions

Describe only what is specific to this document. The extractor's system prompt already covers general behavior, such as using null for unreadable values.

```python
# instructions.py
INSTRUCTIONS = """\
The document is a Brazilian bank payment slip (boleto).

- linha_digitavel: the numeric line above the barcode, without spaces or punctuation.
"""
```

## 4. Write the validators

A validator takes the extracted data and yields issues. Use `Severity.ERROR` for rules that a genuine document always satisfies, and `Severity.WARNING` for rules with legitimate exceptions.

```python
# validators.py
from collections.abc import Iterator

from nf_extractor.core.result import Severity, ValidationIssue
from nf_extractor.document_types.boleto.schema import Boleto
from nf_extractor.validators.br_identifiers import is_valid_cnpj


def check_beneficiary(boleto: Boleto) -> Iterator[ValidationIssue]:
    """Verify the beneficiary's CNPJ."""
    document = boleto.beneficiario_documento
    if document is not None and not is_valid_cnpj(document):
        yield ValidationIssue(
            code="beneficiario.invalid",
            message="The CNPJ has an invalid format or check digits.",
            severity=Severity.ERROR,
            field="beneficiario_documento",
        )
```

Rules that other document types could use belong in `nf_extractor/validators/`.

## 5. Declare and register the type

```python
# __init__.py
from nf_extractor.core.document_type import DocumentType
from nf_extractor.document_types.boleto.instructions import INSTRUCTIONS
from nf_extractor.document_types.boleto.schema import Boleto
from nf_extractor.document_types.boleto.validators import check_beneficiary

BOLETO = DocumentType[Boleto](
    name="boleto",
    description="Brazilian bank payment slip",
    schema=Boleto,
    instructions=INSTRUCTIONS,
    validators=(check_beneficiary,),
)
```

Then add it to `default_registry()` in `document_types/__init__.py`:

```python
registry.register(BOLETO)
```

It is now available from the command line:

```bash
uv run nf-extractor extract boleto.pdf --type boleto
```

## 6. Test it

Add tests for every validator, with synthetic data only, covering both the passing and failing cases. See `tests/test_nfe.py` for an example.
