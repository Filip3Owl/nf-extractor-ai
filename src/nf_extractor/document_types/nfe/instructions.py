"""Guidance given to the extractor about Brazilian invoices."""

INSTRUCTIONS = """\
The document is a DANFE or DANFE NFC-e, the printed representation of a Brazilian \
electronic invoice.

- chave_acesso: the 44-character access key, usually printed in groups next to the barcode. \
Return it without spaces. It may contain upper-case letters.
- documento: the CNPJ or CPF as printed. Newer CNPJs may contain letters.
- modelo: "55" for an NF-e and "65" for an NFC-e.
- Monetary values and quantities: use a dot as the decimal separator and no thousands \
separator. For example, "1.234,56" becomes "1234.56".
- totais: copy these from the "Cálculo do imposto" section. Do not compute them.
- itens: list every line of every page, in the printed order.
"""
