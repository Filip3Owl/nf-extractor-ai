# nf-extractor-ai

Pipeline de IA que transforma documentos não estruturados em dados estruturados e validados, usando OCR, análise de layout e LLMs com visão.

**Read in English:** [README.md](README.md), a versão principal e mais completa da documentação.

O primeiro documento suportado é o **DANFE**, a representação impressa da NF-e e da NFC-e. Um LLM com visão lê o PDF ou a imagem, e regras determinísticas conferem o resultado. Assim, um valor lido incorretamente é sinalizado em vez de chegar silenciosamente aos seus sistemas.

> **Status: alfa.** A extração por LLM e por OCR local, as regras de validação, a avaliação e o CLI estão implementados. Os testes simulam as APIs de LLM, então nenhum LLM foi medido ainda, e a precisão não foi medida em documentos reais.

## O que é validado

| Regra | O que ela detecta | Severidade |
|---|---|---|
| Dígito verificador da chave de acesso | Um dígito lido incorretamente na chave de 44 caracteres | Erro |
| Dígitos verificadores de CNPJ e CPF, incluindo o CNPJ alfanumérico | Identificador incorreto do emitente ou do destinatário | Erro |
| Campos impressos comparados com a chave de acesso | Número da nota diferente do que consta na chave | Erro |
| Quantidade × valor unitário comparado com o total do item | Valor de item lido incorretamente | Aviso |
| Soma dos itens comparada com o total dos produtos | Linha que ficou de fora | Aviso |
| Total da nota comparado com seus componentes | Total lido incorretamente | Aviso |

Erros indicam regras que uma nota genuína sempre cumpre. Avisos indicam regras com exceções legítimas e sugerem revisão humana.

## Como usar

Requisitos: [uv](https://docs.astral.sh/uv/) e uma [chave da API do Claude](https://platform.claude.com/).

```bash
git clone https://github.com/Filip3Owl/nf-extractor-ai.git
cd nf-extractor-ai
uv sync

cp .env.example .env   # depois preencha ANTHROPIC_API_KEY

uv run nf-extractor extract caminho/para/danfe.pdf --output resultado.json
```

Cada extração faz uma chamada paga à API, e o consumo de tokens fica registrado na saída.

### Como escolher o extrator

| `--extractor` | Custo | O documento sai da sua máquina | Configuração |
|---|---|---|---|
| `claude` (padrão) | Pago | Sim | `ANTHROPIC_API_KEY` |
| `gemini` | Camada gratuita, com limites | Sim | `GEMINI_API_KEY` e `uv sync --extra vision` |
| `groq` | Camada gratuita, com limites | Sim | `GROQ_API_KEY` e `uv sync --extra vision` |
| `openrouter` | Modelos gratuitos, com limites | Sim | `OPENROUTER_API_KEY` e `uv sync --extra vision` |
| `custom` | Depende da API | Depende da API | `NF_EXTRACTOR_LLM_BASE_URL`, `NF_EXTRACTOR_LLM_MODEL` e `uv sync --extra vision` |
| `ocr` | Grátis | Não | `uv sync --extra ocr` |

O extra `vision` só é necessário para PDFs. A disponibilidade nas camadas gratuitas varia por provedor e muda com frequência.

## Privacidade

Notas fiscais contêm dados pessoais e comerciais e podem estar sujeitas à LGPD. **Exceto com `ocr`, os documentos são enviados a uma API externa para processamento.** Confirme que você tem base legal para compartilhá-los e que isso atende aos seus requisitos de retenção de dados. Nunca faça commit de documentos reais: os testes usam apenas dados sintéticos.

**Não envie notas reais para camadas gratuitas.** Os provedores podem usar o que recebem nelas. Os [termos da API Gemini](https://ai.google.dev/gemini-api/terms), por exemplo, permitem usar esse conteúdo para melhorar produtos e permitem revisão humana, além de pedir que dados pessoais não sejam enviados. Use camadas gratuitas com documentos sintéticos e confira os termos de cada provedor.

## Documentação

- [Arquitetura](docs/architecture.md)
- [Como adicionar um tipo de documento](docs/adding-a-document-type.md)
- [Registros de decisão](docs/adr/)
- [Como contribuir](CONTRIBUTING.md)
- [Histórico de versões](CHANGELOG.md)

## Licença

[MIT](LICENSE)
