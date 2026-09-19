## Context

Ver `proposal.md` — Why para a motivação. O que molda o desenho técnico:

- **O repositório é o template `intersystems-iris-dev-template` praticamente intocado.** `src/` contém apenas `dc.sample`, `module.xml` ainda se chama `dc-sample`, e — apesar do que o README afirma — **nenhum dos três Dockerfiles executa `pip install`**. Nada de Python de terceiros está instalado hoje no Embedded Python. Isso é trabalho real, não detalhe.
- **`dc.omniEmbedding` expõe dois pontos de entrada** (lidos em `~/workstation/omni-embedding`):
  - `dc.omniEmbedding.Interface.Embedding(input As %String, configuration As %String) As %Vector` — o ponto de entrada do pacote **publicado** (`dc-omni-embedding` 1.0.8 no registry community), uma classe que estende `%Embedding.Interface` e delega para a Engine. Exige `dimensions` no JSON de configuração e resolve `apiKey` como **nome de credencial do IRIS**, não como chave em texto. **A classe `dc.OmniEmbedding` de nome curto existe apenas no clone local `~/workstation/omni-embedding` e não é publicada** — o pacote exporta só `dc.omniEmbedding.PKG`. Codificar o nome curto quebraria contra o pacote real.
  - `dc.omniEmbedding.Engine.Embed(input, config As %DynamicObject) As %Vector` — API interna, exige `%DynamicObject`.
  Os providers (`AzureOpenAi`, `Gemini`, `OpenAi`) constroem o resultado com `Set $Vector(vec, i, "double")` e retornam `%Vector` nativo. Credenciais e `VectorLength` já vivem em linhas de `%Embedding.Config` (ver `tests.dc.sample.Sample`), que hoje contêm chaves de API em texto no repositório de origem — motivo a mais para este projeto referenciar a config pelo nome e nunca copiar segredos para a tela da Production.
- **`intersystems_pyprod` 0.2.0** (verificado no wheel do PyPI) fornece `BusinessService`/`BusinessProcess`/`BusinessOperation`, `IRISProperty(default, datatype, description, settings)`, `IRISParameter` (com o nome especial `ADAPTER`), `IRISLog.Info/Warning/Error`, `ProductionMessage`/`JsonSerialize` com campos `Column(...)`, e `Production`/`ServiceItem`/`ProcessItem`/`OperationItem`. Classes são carregadas no IRIS pelo CLI `intersystems_pyprod <arquivo.py>`, usando as variáveis de ambiente `IRISUSERNAME`/`IRISPASSWORD`/`IRISNAMESPACE` (já definidas no `Dockerfile`).
- **Restrição do pyprod:** a documentação do pacote é explícita — definir a Production programaticamente e pela UI **não pode ser misturado** no ciclo de vida de uma mesma Production. É preciso escolher um dos dois.
- **Prazo curto:** 21/09, cinco dias a partir de 16/09/2026. O desenho prioriza um caminho de ponta a ponta demonstrável sobre otimização.

## Goals / Non-Goals

**Goals:**

- Um caminho único e observável do arquivo até a linha vetorizada, em que cada etapa aparece no Message Viewer e no log de eventos.
- Um ponto de acoplamento estreito e nomeado com `dc.omniEmbedding`, para que mudanças lá quebrem em um só lugar aqui.
- Uma estratégia de chunking defensável por escrito, não emergente do código.
- Manter `%Vector` do lado do ObjectScript, onde é tipo nativo, em vez de tentar marshalá-lo através do Embedded Python.

**Non-Goals:**

- Throughput. O pipeline é síncrono chunk a chunk por decisão (ver Decisões); paralelização fica para depois.
- Índice vetorial aproximado (HNSW). O schema fica pronto para recebê-lo, mas na escala do concurso a varredura exata basta.
- OCR de PDFs escaneados. O Docling suporta, mas isso multiplica o tamanho da imagem e o tempo de parsing; fica desligado por padrão.
- Qualquer query de busca (híbrida ou não) e qualquer UI.

## Decisions

### D1. Componentes em Python puro com `intersystems_pyprod`, Production definida programaticamente

Os três hosts ficam em `src/python/omni_ingest/`, com `iris_package_name = "dc.omniIngest"`, e a Production é declarada por uma subclasse de `Production` no mesmo módulo — `services=[ServiceItem(...)]`, `processes=[ProcessItem(...)]`, `operations=[OperationItem(...)]`, com `host_settings`/`adapter_settings` como valores iniciais.

*Por que:* o pacote proíbe misturar definição programática e edição pela UI. A definição programática é a que fica versionada em git, reprodutível no build do container e revisável em code review — e é a única que sobrevive a um `docker-compose build --no-cache`. Os valores continuam editáveis na tela da Production em runtime; a definição programática apenas fixa os padrões.

*Alternativa descartada:* montar a Production pela UI e exportá-la depois. Mais rápido para um único desenvolvedor, mas o estado de verdade passa a viver dentro do IRIS e não no repositório — inaceitável para uma submissão que precisa subir do zero na máquina de um avaliador.

### D2. Estratégia de chunking: estrutural (Docling `HybridChunker`), contextualizada por cabeçalho, com sobreposição aplicada em pós-passo

Esta é a decisão avaliada pelo concurso, então está escrita por extenso.

O `DocumentConverter` do Docling não devolve só texto: devolve um `DoclingDocument`, uma árvore com cabeçalhos, parágrafos, listas, tabelas e proveniência de página. Jogar essa árvore fora e picar o Markdown resultante a cada N caracteres desperdiça exatamente a informação pela qual pagamos o custo do parsing.

O pipeline usa, nesta ordem:

1. **`HybridChunker` sobre o `DoclingDocument`.** Ele agrupa por elemento estrutural, respeita fronteiras de tabela e de seção, funde chunks vizinhos pequenos demais e divide os grandes demais usando um tokenizador — de modo que `chunk_size` é um teto real em tokens do modelo de embedding, não uma aproximação por caracteres.
2. **Contextualização por caminho de cabeçalhos.** O texto enviado ao embedding é o caminho de cabeçalhos do chunk seguido do conteúdo (`chunker.contextualize()`). O texto persistido em `chunk_text` é o conteúdo bruto. Um chunk que diz "O limite é 30 dias" vira, no espaço vetorial, "Política de Reembolso > Prazos — O limite é 30 dias"; para busca por palavra-chave e para exibição, o texto bruto é o que interessa.
3. **Sobreposição como pós-passo.** O `HybridChunker` não faz sobreposição por caractere: ele funde e divide. Como `chunk_overlap` é um requisito explícito e um botão que o avaliador vai querer girar, a sobreposição é aplicada depois, copiando as últimas ~`chunk_overlap` tokens do chunk anterior para o início do seguinte **apenas entre chunks da mesma seção** (mesmo caminho de cabeçalhos). Sobrepor através de uma fronteira de seção reintroduziria justamente a mistura de contextos que o chunking estrutural existe para evitar.

Padrões: `chunk_size = 512` tokens, `chunk_overlap = 64` tokens (12,5%). 512 cabe folgado na janela dos modelos de embedding em uso e é grande o suficiente para conter um parágrafo técnico inteiro; a sobreposição de ~12% cobre a frase de fronteira sem inflar o custo de embedding de forma relevante.

**Duas coisas que só o experimento mostrou:**

*O `HybridChunker` 2.55.1 não tem `max_tokens` — o teto vive no tokenizador,* que é um campo obrigatório. Os tokenizadores prontos (HuggingFace, OpenAI) baixam arquivos de modelo na primeira execução, o que colide com a exigência de parsing sem rede. Como `BaseTokenizer` é só um ABC de três métodos (`count_tokens`, `get_max_tokens`, `get_tokenizer`), o pipeline usa uma implementação própria que estima por contagem de caracteres, dividindo por **3** e não por 4. Um BPE típico faz ~3,5–4 caracteres por token em português; dividir por 3 conta tokens a mais que a realidade, então o chunk sai menor que o teto, nunca maior. Errar para chunks pequenos é barato; estourar a janela do modelo de embedding é erro em tempo de execução. Trocar por um tokenizador exato é uma linha, depois de pré-baixá-lo na imagem. Detalhe que custa um `TypeError` se ignorado: o chunker chama `count_tokens(text=...)` por palavra-chave, então o parâmetro precisa se chamar `text`.

*O pipeline padrão de PDF do Docling liga OCR,* e o EasyOCR baixa os próprios pesos na primeira conversão. Com `layout` e `tableformer` pré-baixados e downloads desabilitados, **nenhum PDF era parseado** — falhava com `FileNotFoundError: Missing .../EasyOcr/craft_mlt_25k.pth and downloads disabled`. O conversor agora passa `PdfPipelineOptions(do_ocr=False)`, alinhando o código ao que os Non-Goals já diziam. `do_table_structure` continua ligado: é dele que depende a promessa de não cortar tabela ao meio. Consequência aceita: PDF escaneado (imagem pura) não rende texto; PDF com camada de texto, o caso comum, funciona.

*Alternativas consideradas:*
- **Fixo por caractere, com sobreposição (`RecursiveCharacterTextSplitter` e afins).** Trivial de implementar e de explicar, mas corta tabelas ao meio, separa cabeçalho de conteúdo e trata um limite de caracteres como se fosse um limite de tokens. Descartado: seria pagar o custo do Docling e não usar o resultado.
- **Um chunk por página.** Barato e com proveniência perfeita. Descartado: tamanho de página não tem relação com unidade semântica, e Markdown/TXT não têm páginas.
- **Chunking semântico por similaridade de embeddings entre sentenças.** Qualidade potencialmente melhor, mas custa uma chamada de embedding por sentença antes mesmo de existir um chunk — inviável em latência e custo, e frágil na véspera do prazo.

### D3. O vetor é produzido e serializado em ObjectScript; o Python só faz o `INSERT`

Uma classe fina em ObjectScript, `dc.omniIngest.Embedder`, expõe:

```
ClassMethod EmbedToCsv(text As %String, configName As %String, Output dimension As %Integer) As %String
```

Ela carrega a linha de `%Embedding.Config` pelo nome e despacha para a classe declarada no campo `EmbeddingClass` dessa linha — que no pacote publicado é `dc.omniEmbedding.Interface` — convertendo o `%Vector` retornado em string separada por vírgulas e devolvendo também a dimensão.

O despacho é pelo `EmbeddingClass` da config, e não por um nome fixo no código, porque é assim que `%Embedding.Config` foi feita para funcionar — e porque o nome da classe mudou entre o clone local e o pacote publicado, o que teria quebrado um nome fixo. A classe configurada é validada (existe? expõe `Embedding()`?) antes da chamada, com mensagem explícita quando não. Efeito colateral útil: a conversão `%Vector → CSV` fica testável com um dublê, sem provider real nem credencial. O `EmbeddingBridgeOperation`, em Python, chama esse método via `iris.cls("dc.omniIngest.Embedder").EmbedToCsv(...)` e executa:

```sql
INSERT INTO <tabela> (..., chunk_vector, ...) VALUES (..., TO_VECTOR(?, double, <dim>), ...)
```

**O tipo e a dimensão não podem ser parâmetros.** Verificado na IRIS 2026.2: `TO_VECTOR(?, ?, ?)` falha com *"Invalid VECTOR field definition: Vector type must be one of DOUBLE, DECIMAL, ..."*, e `'DOUBLE'` entre aspas falha do mesmo jeito — o tipo é palavra-chave, não string. Só a CSV do vetor viaja como parâmetro `?`. A dimensão é interpolada no texto do SQL, o que é seguro porque ela é validada como inteiro positivo antes (`ValidateVectorLength`) e vem da coluna, não do usuário.

*Por que:* `%Vector` é um tipo nativo do ObjectScript sem representação estável e documentada do lado do Embedded Python. Tentar recebê-lo em Python e reconverter é o ponto mais provável de falha de todo o desenho. Manter a conversão a uma linha de ObjectScript de onde o vetor nasce elimina a incerteza, e `TO_VECTOR(string, double, dim)` é uma fronteira documentada e estável. O `INSERT` fica em Python porque é lá que o nome da tabela é configurável e onde o tratamento de erro por chunk precisa acontecer.

*Alternativa descartada:* fazer o `INSERT` inteiro em ObjectScript. Reduziria ainda mais o marshalling, mas empurraria o nome da tabela, o log e o resultado por chunk para fora do host da Production — perdendo justamente a observabilidade que motiva usar uma Production.

### D4. Provider e credenciais vêm de `%Embedding.Config`; a tela da Production guarda só o nome

`EmbeddingBridgeOperation` expõe uma `IRISProperty` `embedding_config_name` (padrão `"omniingest-default"`). Chave de API, `apiBase`, `modelName` e `VectorLength` ficam na linha de `%Embedding.Config` correspondente.

*Por que:* é exatamente para isso que `dc.omniEmbedding.Interface` foi escrita (ela estende `%Embedding.Interface`). Reusar isso evita um segundo lugar para configurar providers, mantém chaves fora de settings de Production que aparecem em telas e exports, e dá de graça o `VectorLength` que a validação de dimensão precisa.

### D5. A tabela é criada por DDL parametrizada, não por uma classe `%Persistent` fixa

`dc.omniIngest.Schema.Create(tableName, vectorLength)` emite `CREATE TABLE`/`CREATE INDEX` se a tabela não existir; se existir, compara a dimensão da coluna vetorial e falha explicitamente em caso de divergência. Colunas: `doc_key`, `doc_id`, `source_file`, `chunk_index`, `heading_path`, `page_numbers`, `chunk_text`, `chunk_vector`, `embedding_config`, `vector_dimension`, `created_at`. `chunk_text` é `VARCHAR(32000)`, com índice `%iFind.Index.Basic`; `chunk_vector` é `VECTOR(DOUBLE, <vectorLength>)`.

*Por que:* o nome da tabela é requisito de configuração, e uma classe `%Persistent` tem nome fixo em tempo de compilação. DDL parametrizada é a única forma de honrar o requisito. O índice iFind entra já na criação — é barato e é a prova concreta de que a afirmação "pronto para busca híbrida" não é promessa.

*Sobre `doc_key` vs `doc_id`:* `doc_key` é o nome original do arquivo e é a identidade do documento — é por ele que a reingestão substitui a versão anterior. `doc_id` é o SHA-256 do conteúdo, guardado para detectar se o arquivo realmente mudou. Usar o hash como identidade faria um arquivo editado virar um documento novo, deixando a versão obsoleta na tabela para sempre.

### D6. Adapter de arquivo **sem** `WorkPath` — o nome original é a identidade do documento

`FileWatcherService` usa `EnsLib.File.InboundAdapter` com `FilePath` e `ArchivePath` configurados, e **deixa `WorkPath` vazio de propósito**.

*Esta decisão substitui a versão anterior, que mandava usar `WorkPath`. A versão anterior estava errada, e só um experimento mostrou isso.* O plano original supunha que `WorkPath` daria ao Docling um caminho estável, e que o nome original viria de `input.Attributes("Filename")`. Sonda rodada contra IRIS 2026.2, depositando `Relatorio Anual 2025.pdf`:

| Suposição | Realidade medida |
|---|---|
| `input` é um `%Stream.FileBinary` | é um `%Library.FileCharacterStream` |
| `input.Attributes("Filename")` dá o nome original | `Attributes` **não existe** na classe; há `GetAttribute()`, cuja única chave preenchida é `Filename`, e ela repete o caminho de trabalho |
| `WorkPath` só move o arquivo | `WorkPath` **mutila o nome**: `Relatorio Anual 2025.pdf` vira `Relatorio_Anual_2025.pdf_2026-09-17_19.48.11.114` — espaços viram sublinhados e um timestamp é anexado |
| o caminho continua válido após o `OnProcessInput` | o adapter move o arquivo para `ArchivePath` **assim que o método retorna** |

O terceiro item é o que decide: a mutilação é irreversível — não há como saber se o original tinha espaço ou sublinhado. E `doc_key`, que é a identidade pela qual a reingestão substitui a versão anterior (ver D5), *é* o nome original. Com `WorkPath`, reingerir o mesmo arquivo depois de renomeá-lo levemente criaria documentos duplicados.

Sem `WorkPath`, `input.Filename` é o caminho real e intacto na pasta de entrada, e o arquivo existe em disco durante todo o `OnProcessInput` — as duas coisas verificadas.

**Isso amarra o desenho:** o parsing tem de acontecer dentro do `OnProcessInput`, porque é a única janela em que o arquivo existe. É o que torna o `SendRequestSync` de D7 obrigatório, e não apenas preferível: trocar por `SendRequestAsync` entregaria ao Docling um caminho já inexistente. Quem for paralelizar depois precisa copiar o arquivo antes.

*Alternativa considerada:* manter `WorkPath` e reconstruir o nome removendo o sufixo de timestamp. Descartado: recupera o timestamp, não os espaços.

### D7. `SendRequestSync` por chunk, com o Process aguardando cada resposta

*Por que:* além de ser **obrigatório** pela janela de vida do arquivo (ver D6), dá contabilidade exata por documento (gerados / persistidos / falhos, exigida pelas specs), aplica back-pressure natural contra rate limit do provider, e mantém o Message Viewer legível — uma mensagem de chunk, uma resposta, um status.

*Trade-off aceito:* a latência de um documento é a soma das latências de embedding dos seus chunks. Um PDF de 200 chunks a ~300 ms por chamada leva ~1 minuto. Aceitável na escala do concurso; o caminho de evolução é `SendRequestAsync` com `PoolSize > 1` na Operation, que é troca localizada.

### D8. Dependências Python instaladas no site-packages do Embedded Python, com modelos do Docling pré-baixados

O `Dockerfile` ganha `RUN pip3 install --target /usr/irissys/mgr/python -r requirements.txt` e, em seguida, um passo que pré-baixa os modelos de layout/tabela do Docling para dentro da imagem.

*Por que:* o Embedded Python só importa de `/usr/irissys/mgr/python`; um `pip install` comum não seria visto. E o Docling baixa seus modelos na primeira conversão — sem pré-download, a primeira ingestão do avaliador seria lenta e dependeria de rede, violando o requisito de parsing sem chamadas externas.

## Risks / Trade-offs

- **Docling arrasta `torch` CPU e modelos; a imagem cresce de centenas de MB para vários GB e o build passa de minutos a dezenas de minutos.** → Aceito, com dois amortecedores: instalar a variante CPU-only do `torch` explicitamente e manter o passo de modelos em uma camada própria do Dockerfile, para que mudanças no código-fonte não invalidem o download. Se o tamanho inviabilizar a submissão, a variante de fallback é `Dockerfile_mini` sem pré-download, documentando que a primeira ingestão precisa de rede.
- **O gateway de embeddings é contrato externo e já divergiu uma vez.** O clone local expõe `dc.OmniEmbedding`; o pacote publicado 1.0.8 expõe `dc.omniEmbedding.Interface` e mais providers (Bedrock, Cohere, Jina, Mistral, Ollama, VertexAi, Voyage). Um nome fixo no código teria quebrado contra o pacote real. → Despachar pelo `EmbeddingClass` da `%Embedding.Config`, concentrar a chamada em `dc.omniIngest.Embedder`, e falhar cedo com mensagem clara nomeando a classe ausente e o pacote a instalar.
- **Dimensão do vetor é fixada no `CREATE TABLE`.** Trocar de modelo de embedding depois exige tabela nova e reingestão. → Validação de dimensão em dois pontos (criação do schema e persistência de cada chunk), com mensagens que nomeiam as duas dimensões, para que a incompatibilidade apareça como erro legível e não como corrupção silenciosa.
- **Sobreposição em pós-passo pode exceder o teto de tokens do chunk.** Colar `chunk_overlap` tokens no início de um chunk que já está no limite o empurra para além dele. → O pós-passo reserva o orçamento: o `HybridChunker` recebe `chunk_size - chunk_overlap` como teto, e a sobreposição preenche o restante. A spec exige que nenhum chunk exceda o tamanho configurado, e é assim que isso é garantido.
- **Confirmado em build: o `torch` do PyPI arrasta wheels CUDA mesmo em aarch64** (`nvidia-cufft` sozinho tem 214 MB), e `--extra-index-url` não impede isso, porque o pip escolhe a versão mais alta entre os índices. → `torch`/`torchvision` pinados com sufixo `+cpu`, que só existe no índice do PyTorch; o wheel aarch64 tem 159 MB e o build passou a não baixar nada da NVIDIA.
- **A verificação de versão do IRIS é implícita.** `VECTOR`/`TO_VECTOR` e `%iFind` não existem em imagens antigas, e o `Dockerfile` carrega sete linhas `ARG IMAGE` comentadas em cascata — trocar a linha ativa por engano derruba tudo com erro de sintaxe SQL obscuro. → A rotina de criação de schema verifica a versão do IRIS e falha com mensagem explícita antes de tentar o `CREATE TABLE`.
- **O Docling 2.55.1 não tem formato de texto puro.** `InputFormat` lista DOCX, PPTX, HTML, IMAGE, PDF, ASCIIDOC, MD, CSV, XLSX e alguns XML — nada de TXT —, e entregar um `.txt` levanta `ConversionError: File format not allowed`. A spec promete `.txt`, então isso era uma promessa quebrada que só a ingestão do corpus completo revelou. → Um `.txt` é apresentado ao conversor como `DocumentStream` renomeado para `.md`; texto puro é Markdown válido e o mesmo conteúdo converte sem perda. Nada é escrito em disco e o arquivo original não é tocado.
- **`GROUP BY doc_key` devolve o nome em MAIÚSCULAS.** É a colação `SQLUPPER` padrão do IRIS agindo no agrupamento, não corrupção: um `SELECT doc_key` simples devolve `apresentacao_politicas.pptx` corretamente. → Vale avisar no README, porque a primeira consulta que qualquer um escreve sobre esta tabela é um `GROUP BY doc_key` e o resultado assusta.
- **PPTX tem proveniência de página, PDF também; MD e TXT não.** A suposição de que só PDF traria número de página estava errada — cada slide vira uma página. O requisito da spec já está redigido como "quando o formato as expõe", então nada muda; mas a documentação não deve dizer "só PDF".
- **As setas do diagrama da Production não vêm do nome `TargetConfigNames`, e sim do tipo da propriedade.** `Ens.Host.GetPropertyConnections` varre as propriedades cujo tipo é `Ens.DataType.ConfigName` (ou subclasse); nas classes de fábrica o nome é só convenção. E o `intersystems_pyprod` 0.2.0 não sabe declarar um tipo IRIS arbitrário — o parser resolve o tipo por um mapa fixo (`str`/`int`/`bool`/`num`) e cai em `%VarString` para qualquer outra coisa. Sem tratamento, o pipeline funciona mas a tela mostra três caixas soltas. → `dc.omniIngest.Setup.PromoverAlvosNoDiagrama()` promove as propriedades de alvo depois da carga, de forma idempotente, e o `Dockerfile` a chama no boot. **Recarregar os módulos Python desfaz a promoção**, então ela tem de ser refeita a cada carga.
- **A ordem das camadas do `Dockerfile` é decisão, não arrumação.** Criar as pastas de ingestão antes das camadas de `pip` e de modelos invalidaria as duas e faria cada build refazer o download do torch e dos 500 MB de modelos do Docling. → Qualquer passo barato e que muda com frequência entra *depois* das camadas caras.
- **Bug encontrado em teste: a reingestão não substituía nada.** O marcador de corte (o maior `id` já existente do documento) era capturado uma vez por `doc_key` e guardado na memória do job para sempre. Na segunda ingestão do mesmo arquivo ele ainda valia o da primeira — zero, quando a tabela estava vazia —, a purga nunca disparava e as duas versões conviviam na tabela, com `chunk_index` repetido. → O marcador é recapturado a cada `chunk_index == 0`, que é o início de uma *ingestão*, não de um documento. Sem um teste que ingerisse o mesmo arquivo duas vezes, isso teria passado.
- **O estado da reingestão vive na memória do job, o que amarra a Operation a `PoolSize = 1`.** Com pool maior, dois documentos se intercalariam e um marcador sobrescreveria o outro. → `PoolSize = 1` na `OperationItem`, e se a paralelização vier depois, esse estado precisa sair da memória para uma tabela.
- **Uma falha de chunk não pode voltar como `Status.ERROR`.** O Business Process morre com `<Ens>ErrBPTerminated` e leva junto os chunks seguintes do mesmo documento — o oposto do isolamento por chunk que a spec exige. → A Operation devolve `Status.OK()` com `success = 0` e o motivo no corpo da resposta; quem chama lê o campo, não o status.
- **Pré-baixar modelos do Docling e desligar recursos do pipeline são a mesma decisão, tomada em dois lugares.** A lista de modelos do `Dockerfile` (`layout tableformer`) só é suficiente porque o código desliga o OCR; ligar OCR ou fórmulas depois sem acrescentar o modelo correspondente volta a quebrar em tempo de ingestão, e só para PDF. → Manter as duas pontas citadas uma na outra, e testar PDF a cada mudança de pipeline do Docling.
- **Confirmado em teste: `SendRequestSync` sinaliza falha do alvo por status de retorno, não por exceção.** Um Process que levanta `RuntimeError` volta como `<Ens>ErrBPTerminated` num `%Status`, e um `try/except` em volta da chamada nunca dispara — a falha passaria sem nenhuma linha de log nomeando o arquivo. → O serviço inspeciona o status devolvido e registra `IRISLog.Error` com o nome do arquivo antes de repassá-lo. Vale para todo host que usar `SendRequestSync`.
- **Um arquivo que o próprio adapter não consegue abrir nunca chega ao `OnProcessInput`.** Verificado com um arquivo sem permissão de leitura: nenhuma linha de log do serviço, porque o `except` do host jamais executa. Essa classe de falha é tratada pelo adapter, não pelo pipeline. → Não prometer, na documentação, que o serviço reporta *toda* falha de arquivo.
- **Confirmado em teste: um `bool` do Python não sobrevive ao marshalling para uma coluna de mensagem do pyprod.** Ele chega ao IRIS como referência de objeto e a gravação falha com *"Datatype value '5@%SYS.Python' is not a valid boolean"*; a mesma coluna aceita `1` e `0`. → O campo `success` da resposta de chunk é `int`, e `messages.as_flag()` faz a conversão no ponto de construção. Vale para qualquer campo booleano que apareça depois.
- **Latência acumulada por documento pode estourar o timeout padrão de `SendRequestSync`.** → Timeout por chunk exposto como `IRISProperty`, com padrão folgado, e falha de timeout tratada como falha de chunk isolada, não como falha de documento.
- **Prazo de cinco dias com uma dependência pesada nova.** → A ordem das tarefas é deliberadamente de baixo para cima (schema → mensagens → hosts → Production), de modo que cada nível seja verificável isoladamente por SQL ou pelo terminal do IRIS antes que o nível seguinte dependa dele. O item de maior risco (build da imagem com Docling) é a tarefa 1, não a última.

## Migration Plan

Não há dados nem usuários a migrar — é a primeira versão do pacote. A implantação é: rebuild da imagem, `intersystems_pyprod` carrega as classes, `dc.omniIngest.Schema.Create()` cria a tabela, e a Production é iniciada. Rollback é parar a Production; a tabela de chunks pode permanecer, já que nada mais a consome ainda.

A remoção do código de exemplo do template (`dc.sample`, os testes de amostra e o nome `dc-sample` em `module.xml`) faz parte desta change, para que o pacote publicado não carregue o andaime do template.

## Open Questions

- ~~**Qual `%Embedding.Config` será a padrão na submissão do concurso?**~~ **Resolvido, com medição.** O provider é Cohere (`embed-multilingual-v3.0`, dimensão 1024). A escolha do modelo foi medida sobre o corpus de demonstração, comparando três perguntas em português com o critério objetivo "o chunk retornado em primeiro lugar contém a resposta":

  | | híbrida | só vetor |
  |---|---|---|
  | `embed-multilingual-v3.0` | 3/3 | 2/3 |
  | `embed-english-v3.0` | 3/3 | 2/3 |

  As duas acertam o mesmo — o corpus tem 11 chunks e 3 perguntas, pequeno demais para separar acurácia. O que separa os modelos é a **calibração**: o multilingual pontua 0,79 / 0,82 / 0,65 contra 0,59 / 0,46 / 0,37 do de inglês, sobre um corpus em português. Margem maior importa para decidir limiar de corte e para o rerank a jusante. Daí a escolha do multilingual.

  O que a medição mostrou dos dois lados: **híbrida ganha de vetor puro em 1 das 3 perguntas, com os dois modelos.** Na pergunta *"Qual a taxa para devolver roupas?"* o vetor puro devolve um chunk com similaridade **mais alta** e que não contém a resposta; o filtro iFind é o que traz o chunk da tabela de preços. É o argumento da busca híbrida medido, e não afirmado.

- **A dimensão do vetor do projeto continua 1536, e a da instalação é 1024.** Decisão deliberada: 1536 é o padrão dos modelos OpenAI mais comuns e permanece como padrão do pacote; quem usa outro provider cria a tabela com a dimensão dele, que é justamente por isso que o nome da tabela é configurável. Documentado no README com uma tabela de modelo × dimensão.
- **Vale pré-criar o índice HNSW no `CREATE TABLE`?** Depende do volume do corpus de demonstração, que ainda não foi escolhido. O schema aceita adicioná-lo depois sem reingestão (ver spec de `chunk-store`), então a decisão pode esperar.
