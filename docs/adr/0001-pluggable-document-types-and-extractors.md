# 0001. Pluggable document types and extractors

**Status:** Accepted

## Context

The project starts with Brazilian invoices but should support related projects later, including other documents and other extraction technologies such as OCR.

## Decision

Keep a generic `core` that depends on two abstractions:

- `DocumentType`: a schema, instructions and validators for one kind of document.
- `Extractor`: a `typing.Protocol` that turns a document into data matching a schema.

Everything else plugs in from the outside. The project stays in a single package for now.

## Consequences

- A new document type or backend needs no changes to the core.
- The pipeline can be tested without an LLM, by using a fake extractor.
- The approaches can be compared on the same documents, which the evaluation harness on the roadmap requires.
- `Extractor` assumes one document produces one result. Splitting a file that holds several documents will require extending it.
- The `nf_extractor` name will be narrower than the package's scope if it grows beyond fiscal documents. `core` can be moved to its own package at that point, since it has no dependency on the rest.
