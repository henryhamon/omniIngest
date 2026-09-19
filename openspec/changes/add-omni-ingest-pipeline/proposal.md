## Why

`dc.omniEmbedding` (embeddings multi-provider) e `dc.omniReRank` (reranking multi-provider) já existem, mas o pipeline de RAG sobre IRIS ainda começa no vácuo: não há nada que transforme um PDF/DOCX/PPTX/MD/TXT em chunks vetorizados dentro de uma tabela SQL do IRIS. Hoje o usuário precisa escrever o parsing, o chunking e o `INSERT ... TO_VECTOR()` à mão antes de conseguir usar qualquer um dos dois gateways.

`dc.omniIngest` é o terceiro gateway da família e fecha o pipeline **ingest → embed → (busca híbrida) → rerank**, entregando a etapa de ingestão como uma Production de Interoperabilidade observável, configurável pela tela de configuração do IRIS e escrita inteiramente em Python via `intersystems_pyprod`. A entrega é alvo de um concurso com prazo em 21/09, e a estratégia de chunking escolhida conta como critério de avaliação — por isso ela precisa ser explícita e justificada, não implícita no código.

## What Changes

- **Nova Production `dc.omniIngest`**, definida programaticamente com `intersystems_pyprod` (`Production` + `ServiceItem`/`ProcessItem`/`OperationItem`), com três hosts em Python puro:
  - `FileWatcherService` (BusinessService sobre `EnsLib.File.InboundAdapter`): monitora uma pasta configurável, aceita PDF/DOCX/PPTX/MD/TXT e encaminha o arquivo ao Process.
  - `ParseChunkProcess` (BusinessProcess): parseia com `docling.document_converter.DocumentConverter` (CPU, sem GPU), aplica chunking estrutural com `chunk_size`/`chunk_overlap` configuráveis e envia um chunk por vez via `SendRequestSync`.
  - `EmbeddingBridgeOperation` (BusinessOperation): chama o gateway `dc.omniEmbedding` (classe declarada na `%Embedding.Config`) pelo módulo `iris` do Embedded Python para obter o vetor e persiste `chunk_text` + vetor na tabela alvo via `TO_VECTOR()`.
- **Novo schema SQL de chunks** (`dc_omniIngest.DocumentChunk` por padrão, nome da tabela configurável), com coluna `%Vector` e coluna de texto bruto dimensionadas desde já para busca híbrida (índice iFind + índice vetorial) sem remodelagem posterior.
- **Novas mensagens persistíveis** (`ProductionMessage`/`JsonSerialize` com `Column`) entre Service→Process e Process→Operation, para que cada arquivo e cada chunk apareçam no Message Viewer e sejam consultáveis por SQL.
- **Toda configuração relevante exposta como `IRISProperty` com `settings`**, portanto editável na tela Interoperability > Configure > Production: pasta de entrada, extensões aceitas, `chunk_size`, `chunk_overlap`, nome da tabela alvo e nome da `%Embedding.Config` que identifica o provider. Nenhum desses valores fica hardcoded.
- **Rastreabilidade via `IRISLog`** em cada etapa: arquivo recebido, documento parseado, número de chunks gerados, chunk embeddado, chunk falho.
- **Infraestrutura do repositório**: `requirements.txt` passa a declarar `intersystems-pyprod` e `docling`, e o `Dockerfile` passa a instalar essas dependências no site-packages do Embedded Python e a pré-baixar os modelos do Docling (hoje nenhum dos Dockerfiles faz `pip install`, apesar do README afirmar o contrário). `module.xml` deixa de se chamar `dc-sample` e passa a descrever o módulo `dc-omniIngest`.
- **Documentação da estratégia de chunking** (o quê e por quê) no README, como artefato de avaliação do concurso.

Sem mudanças breaking: o repositório é um template ainda não publicado como `dc.omniIngest`, e `dc.omniEmbedding`/`dc.omniReRank` são consumidos sem alteração.

## Capabilities

### New Capabilities
- `document-ingestion/chunk-store`: o schema SQL que guarda chunk de texto, vetor e metadados de proveniência, preparado para busca híbrida (vetor + palavra-chave) sem remodelagem.
- `document-ingestion/file-intake`: monitoramento da pasta de entrada, aceitação/rejeição por extensão e entrega do arquivo ao pipeline como mensagem persistível.
- `document-ingestion/parsing-chunking`: parsing com Docling em CPU e a estratégia de chunking (estrutural, com contextualização por cabeçalho e sobreposição configurável).
- `document-ingestion/embedding-persistence`: ponte para `dc.omniEmbedding`, conversão do vetor e persistência transacional do chunk na tabela alvo, com isolamento de falha por chunk.
- `document-ingestion/pipeline-operations`: requisitos transversais de configuração pela tela da Production (`IRISProperty`) e de rastreabilidade por `IRISLog`.

### Modified Capabilities
<!-- Nenhuma: o projeto ainda não tem specs em openspec/specs/ (openspec list --specs retorna vazio). -->

## Impact

- **Código novo**: `src/python/omni_ingest/` (hosts pyprod, mensagens, definição da Production, lógica de chunking) e `src/dc/omniIngest/` (classe ObjectScript de suporte para marshalling de `%Vector` e a DDL da tabela de chunks).
- **Dependências externas novas**: `docling` (pesado — traz `torch` CPU e modelos de layout/OCR) e `intersystems-pyprod` 0.2.0. O tempo e o tamanho do build do container crescem de forma significativa.
- **Dependência entre projetos**: declarada no `module.xml` como `dc-omni-embedding` 1.0.8 (IPM). O contrato consumido é `Embedding(input, configurationJSON) As %Vector` na classe apontada pelo `EmbeddingClass` da `%Embedding.Config` — `dc.omniEmbedding.Interface` no pacote publicado. Mudança de assinatura lá quebra o `EmbeddingBridgeOperation` aqui.
- **Infraestrutura**: `Dockerfile`, `requirements.txt`, `module.xml` e `iris.script` são alterados; a Production precisa do namespace com Interoperabilidade habilitada (`Interop=1` já está em `merge.cpf`).
- **Requisito de versão do IRIS**: o schema depende de `%Vector`/`TO_VECTOR()` e de `%iFind`, disponíveis nas imagens community 2024.3+/2025.x. O `Dockerfile` atual já aponta para `intersystems/iris-community:latest-cd`.
- **Fora de escopo**: a lógica interna de `dc.omniEmbedding`/`dc.omniReRank`, a query de busca híbrida em si e qualquer front-end ou app de demonstração do pipeline completo.
