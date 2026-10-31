# Changelog

All notable changes to this project are documented in this file. The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Generic extraction pipeline, with pluggable document types and extraction backends.
- NF-e and NFC-e schema, with validation rules for access keys, CNPJ, CPF and totals.
- Support for the alphanumeric CNPJ.
- Claude extractor that uses vision and structured outputs.
- `nf-extractor` command-line interface.
- CI, pre-commit hooks, Dependabot and project documentation.
- Free local OCR backend, with image preprocessing and layout rules for DANFEs.
- Synthetic dataset generation and an evaluation harness with per-field accuracy.
- Backend for public LLM APIs in the chat completions format, with Gemini, Groq and OpenRouter presets.
