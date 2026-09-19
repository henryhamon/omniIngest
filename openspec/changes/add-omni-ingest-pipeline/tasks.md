## 1. Infraestrutura e dependências

- [x] 1.1 Declarar em `requirements.txt` as dependências `intersystems-pyprod==0.2.0`, `docling` e a variante CPU-only do `torch`; verificar com `pip download --no-deps -r requirements.txt` em uma pasta temporária que todas resolvem
- [x] 1.2 Adicionar ao `Dockerfile` o passo `pip3 install --target /usr/irissys/mgr/python -r requirements.txt` (hoje nenhum Dockerfile do repositório instala nada); verificar com `docker exec iris iris session iris -U IRISAPP` executando um `ClassMethod` em Python que faz `import docling` e `import intersystems_pyprod` sem erro
- [x] 1.3 Adicionar camada separada no `Dockerfile` que pré-baixa os modelos de layout/tabela do Docling para dentro da imagem, posicionada antes do `COPY` do código-fonte; verificar que um rebuild após alterar um arquivo `.py` não refaz o download
- [x] 1.4 Renomear o módulo em `module.xml` de `dc-sample` para `dc-omniIngest`, com descrição, `Resource Name="dc.omniIngest.PKG"` e `UnitTest` apontando para `dc.omniIngest.unittests`; remover `src/dc/sample/` e `tests/dc/sample/`; verificar que `zpm "load /home/irisowner/dev"` conclui com sucesso
- [x] 1.5 Fixar a linha `ARG IMAGE` ativa em uma imagem community com suporte a `VECTOR` e `%iFind`, removendo as linhas comentadas em cascata; verificar com `SELECT $ZVERSION` e um `SELECT TO_VECTOR('1,2,3',double,3)` de fumaça (tipo sem aspas)

## 2. Schema da tabela de chunks

- [x] 2.1 Criar `src/dc/omniIngest/Schema.cls` com `ClassMethod Create(tableName, vectorLength) As %Status` emitindo `CREATE TABLE` com as colunas `doc_key`, `doc_id`, `source_file`, `chunk_index`, `heading_path`, `page_numbers`, `chunk_text VARCHAR(32000)`, `chunk_vector VECTOR(DOUBLE, <vectorLength>)`, `embedding_config`, `vector_dimension`, `created_at`; verificar com `SELECT * FROM INFORMATION_SCHEMA.COLUMNS` que todas as colunas e tipos existem
- [x] 2.2 Criar na mesma rotina o índice `%iFind.Index.Basic` sobre `chunk_text` e um índice comum sobre `doc_key`; verificar que uma consulta com o predicado `%FIND search_index(...)` executa sem erro sobre a tabela vazia
- [x] 2.3 Tornar `Create` idempotente: se a tabela existir com a dimensão vetorial esperada, retornar sucesso sem alterar dados; se a dimensão divergir, retornar erro nomeando tabela, dimensão encontrada e esperada; verificar rodando `Create` duas vezes seguidas e depois uma terceira com `vectorLength` diferente, conferindo que as linhas existentes permanecem
- [x] 2.4 Adicionar em `Create` a verificação de versão do IRIS antes do `CREATE TABLE`, falhando com mensagem explícita se `VECTOR` ou `%iFind` não estiverem disponíveis; verificar inspecionando a mensagem de erro retornada quando a checagem é forçada a falhar
- [x] 2.5 Criar `src/dc/omniIngest/Embedder.cls` com `ClassMethod EmbedToCsv(text, configName, Output dimension) As %String`, que carrega a linha de `%Embedding.Config` pelo nome, despacha para a classe do campo `EmbeddingClass` dessa linha (`dc.omniEmbedding.Interface` no pacote publicado dc-omni-embedding) e serializa o `%Vector` em string separada por vírgulas; verificar no terminal do IRIS que `EmbedToCsv("teste","<config>",.dim)` devolve uma CSV com `dim` valores numéricos
- [x] 2.6 Fazer `Embedder` falhar com mensagem clara quando a classe de embedding configurada ou a `%Embedding.Config` nomeada não existir no namespace; verificar chamando com um nome de config inexistente e conferindo a mensagem
- [x] 2.7 Verificar a ponta schema+embedder isoladamente: `INSERT` manual de uma linha usando `TO_VECTOR(<csv>, double, <dim>)` com a CSV vinda de `EmbedToCsv` e em seguida um `SELECT` ordenando por `VECTOR_COSINE(chunk_vector, TO_VECTOR(...))` que retorna a linha

## 3. Mensagens persistíveis

- [x] 3.1 Criar `src/python/omni_ingest/messages.py` com `iris_package_name = "dc.omniIngest"` e a mensagem de arquivo (`doc_key`, `doc_id`, `source_file`, `work_path`, `size_bytes`) como `JsonSerialize` com campos `Column(...)`; verificar carregando com `intersystems_pyprod` e conferindo que a classe compila no IRIS
- [x] 3.2 Criar a mensagem de requisição de chunk (`doc_key`, `doc_id`, `source_file`, `chunk_index`, `heading_path`, `page_numbers`, `chunk_text`, `embedding_text`) e a de resposta (`success`, `row_id`, `error_message`), com `Column(index=True)` em `doc_key` e `chunk_index`; verificar com `SELECT` SQL sobre a tabela da classe de mensagem gerada
- [x] 3.3 Verificar que as mensagens são persistíveis e legíveis: instanciar uma de cada no terminal Python do IRIS, salvar, reabrir e conferir que os campos sobrevivem à ida e volta

## 4. FileWatcherService

- [x] 4.1 Criar `src/python/omni_ingest/file_watcher.py` com a classe `FileWatcherService(BusinessService)` declarando `ADAPTER = IRISParameter("EnsLib.File.InboundAdapter")` e implementando `OnProcessInput`; verificar que a classe carrega e aparece como Business Service disponível na UI do IRIS
- [x] 4.2 Expor `accepted_extensions` e `target_config_name` como `IRISProperty` com `settings` e descrição; verificar que ambos aparecem na tela de configuração da Production com os padrões documentados
- [x] 4.3 Implementar o filtro de extensão insensível a maiúsculas, rejeitando arquivos fora da lista sem parseá-los e registrando o motivo via `IRISLog.Warning`; verificar depositando um `.xlsx` e um `.PDF` na pasta e conferindo log e comportamento
- [x] 4.4 Calcular `doc_key` (nome original do arquivo, com espacos intactos) e `doc_id` (SHA-256 do conteudo) e montar a mensagem de arquivo apontando para o caminho legivel do arquivo; verificar que o `doc_key` gravado e o nome original e que o `doc_id` bate com o sha256 calculado por fora, e que o caminho da mensagem e legivel durante o Process (o adapter arquiva o arquivo assim que o OnProcessInput retorna, entao o caminho NAO sobrevive depois disso -- ver design D6)
- [x] 4.5 Encaminhar a mensagem ao Process alvo e registrar recebimento com nome e tamanho via `IRISLog.Info`; verificar no Message Viewer que a mensagem de arquivo aparece com os campos preenchidos
- [x] 4.6 Garantir isolamento de falha por arquivo: capturar exceções em `OnProcessInput`, registrar via `IRISLog.Error` com o nome do arquivo e retornar status de erro sem derrubar o serviço; verificar depositando um arquivo corrompido seguido de um válido e conferindo que o segundo é processado

## 5. ParseChunkProcess

- [x] 5.1 Criar `src/python/omni_ingest/parse_chunk.py` com `ParseChunkProcess(BusinessProcess)` e `OnRequest` recebendo a mensagem de arquivo; verificar que a classe carrega e o item aparece na UI
- [x] 5.2 Expor `chunk_size`, `chunk_overlap`, `target_config_name` e `embedding_timeout` como `IRISProperty` com descrição e `settings`, com os padrões 512 e 64; verificar que aparecem editáveis na tela de configuração da Production
- [x] 5.3 Validar a configuração na entrada do processamento, rejeitando com erro explícito quando `chunk_overlap >= chunk_size`; verificar configurando overlap igual ao chunk size e conferindo a mensagem de erro
- [x] 5.4 Implementar o parsing com `docling.document_converter.DocumentConverter` a partir do caminho da mensagem, medindo o tempo e registrando formato e duração via `IRISLog.Info`; verificar com um PDF contendo tabela, conferindo no log e que o conteúdo da tabela aparece no texto extraído
- [x] 5.5 Implementar o chunking estrutural com `HybridChunker` sobre o `DoclingDocument`, com teto de `chunk_size - chunk_overlap` tokens, extraindo por chunk o caminho de cabeçalhos e as páginas de proveniência; verificar que uma tabela que cabe no teto sai inteira em um único chunk
- [x] 5.6 Implementar a contextualização: `embedding_text` recebe o caminho de cabeçalhos mais o conteúdo (via `contextualize()`), enquanto `chunk_text` guarda o conteúdo bruto; verificar em um documento com duas seções que o `heading_path` de um chunk de subseção contém ambos os cabeçalhos
- [x] 5.7 Implementar a sobreposição em pós-passo, copiando as últimas `chunk_overlap` tokens do chunk anterior apenas entre chunks de mesmo `heading_path`; verificar com `chunk_overlap` em 64 que chunks consecutivos da mesma seção compartilham conteúdo e que chunks de seções diferentes não compartilham
- [x] 5.8 Descartar chunks vazios após remoção de espaços e renumerar `chunk_index` de forma contígua a partir de zero; verificar com um documento contendo página em branco que os índices persistidos não têm lacunas
- [x] 5.9 Enviar cada chunk por `SendRequestSync` na ordem do documento, respeitando `embedding_timeout`, e tratar timeout como falha isolada daquele chunk; verificar no Message Viewer que os chunks aparecem em ordem e na mesma sessão da mensagem de arquivo
- [x] 5.10 Registrar a contagem de chunks gerados e, ao final, a linha de resumo com gerados/persistidos/falhos por documento via `IRISLog.Info`; verificar no log de eventos após ingerir um documento com ao menos um chunk falho forçado

## 6. EmbeddingBridgeOperation

- [x] 6.1 Criar `src/python/omni_ingest/embedding_bridge.py` com `EmbeddingBridgeOperation(BusinessOperation)` e o método de tratamento da mensagem de chunk; verificar que a classe carrega e o item aparece na UI
- [x] 6.2 Expor `target_table` e `embedding_config_name` como `IRISProperty` com descrição e `settings`, sem nenhum campo de chave de API; verificar abrindo a tela de configuração do item e conferindo que só o nome da config aparece
- [x] 6.3 Chamar `dc.omniIngest.Embedder.EmbedToCsv` via `iris.cls(...)` para obter a CSV do vetor e a dimensão; verificar que uma mensagem de chunk de teste produz CSV não vazia com a dimensão esperada
- [x] 6.4 Validar a dimensão recebida contra a dimensão declarada da coluna vetorial, marcando o chunk como falho com as duas dimensões na mensagem quando divergir e sem inserir nada; verificar apontando `embedding_config_name` para uma config de dimensão diferente
- [x] 6.5 Executar o `INSERT` na tabela configurada usando `TO_VECTOR(?, double, <dim>)` (o tipo e a dimensao nao podem ser parametros `?`), dentro de transação, gravando texto, vetor e todos os metadados de proveniência; verificar com `SELECT` que a linha inserida tem `chunk_text` idêntico ao enviado e vetor utilizável por `VECTOR_COSINE`
- [x] 6.6 Garantir atomicidade por chunk: rollback em qualquer falha após o embedding, de modo que nenhuma linha parcial permaneça; verificar forçando erro entre o embedding e o commit e conferindo que a tabela não ganhou linha
- [x] 6.7 Implementar a substituição na reingestão: apagar as linhas anteriores de `doc_key` somente após o primeiro chunk novo do documento ser gravado com sucesso; verificar ingerindo o mesmo arquivo duas vezes e conferindo que só os chunks da segunda ingestão permanecem, e que uma segunda ingestão que falha no parsing deixa a primeira intacta
- [x] 6.8 Retornar a mensagem de resposta com sucesso e `row_id`, ou falha com mensagem de erro não vazia, e registrar cada chunk persistido via `IRISLog.Info` e cada falho via `IRISLog.Error` com documento e índice; verificar no log de eventos e nas respostas visíveis no Message Viewer

## 7. Classe da Production

- [x] 7.1 Criar `src/python/omni_ingest/production.py` com a subclasse de `Production` declarando `ServiceItem`, `ProcessItem` e `OperationItem` (a Operation precisa de `PoolSize = 1` -- ver design), com `host_settings` e `adapter_settings` fixando os padrões documentados; verificar que `intersystems_pyprod` carrega o arquivo sem avisos de propriedade inexistente
- [x] 7.2 Configurar no `adapter_settings` do serviço `FilePath`, `ArchivePath` (sem `WorkPath` -- ver design D6) e o intervalo de varredura, e criar essas pastas no `Dockerfile`; verificar que o Docling consegue abrir o arquivo pelo caminho recebido na mensagem
- [x] 7.3 Encadear os alvos (`TargetConfigNames` do serviço apontando para o processo, alvo do processo apontando para a operação); verificar na tela da Production que o diagrama mostra serviço → processo → operação
- [x] 7.4 Fazer o container subir pronto: `iris.script` carrega o ObjectScript via zpm, o `Dockerfile` chama o CLI do `intersystems_pyprod` para cada modulo Python (e um CLI de shell, nao roda de dentro do iris.script) e depois `dc.omniIngest.Setup.Inicializar()`, que cria a tabela e promove os tipos de alvo; verificar com `docker-compose build` seguido de `docker-compose up -d --force-recreate` que classes, tabela e Production existem sem passo manual
- [x] 7.5 Verificar que trocar pasta de entrada, `chunk_size`, `chunk_overlap`, `target_table` e `embedding_config_name` pela tela da Production e reiniciar os itens muda o comportamento das ingestões seguintes, sem recompilar código

## 8. Testes manuais de ponta a ponta

- [x] 8.1 Preparar um corpus de demonstração com ao menos um arquivo de cada formato suportado (PDF com tabela, DOCX, PPTX, MD, TXT) em `tests/fixtures/`; verificar que cada arquivo abre corretamente fora do IRIS
- [x] 8.2 Ingerir o corpus completo pela pasta monitorada com a Production rodando; verificar por `SELECT count(*), doc_key ... GROUP BY doc_key` que todos os documentos produziram chunks e que os índices são contíguos por documento
- [x] 8.3 Verificar a trilha de observabilidade de um documento: no Message Viewer, partir da mensagem de arquivo e alcançar cada mensagem de chunk na mesma sessão; no log de eventos, encontrar recebimento, parsing, contagem de chunks, um registro por chunk persistido e a linha de resumo
- [x] 8.4 Verificar a busca híbrida sobre a tabela populada: uma única instrução SQL que filtra por termo com o predicado iFind e ordena por `VECTOR_COSINE`, retornando linhas com texto e proveniência legíveis
- [x] 8.5 Verificar os caminhos de falha: arquivo de extensão não suportada (rejeitado com log, sem parar o pipeline), arquivo corrompido (falha isolada, próximo arquivo processado), e config de embedding inválida (chunks falhos com erro legível, sem linhas parciais na tabela)
- [x] 8.6 Verificar a reingestão de ponta a ponta: reingerir um documento já presente com conteúdo alterado e confirmar que a tabela contém apenas a versão nova para aquele `doc_key`
- [x] 8.7 Verificar a ingestão sem rede para o parser: desconectar o container da rede externa e confirmar que o parsing de um PDF ainda conclui com sucesso usando os modelos pré-baixados

## 9. Documentação

- [x] 9.1 Reescrever o `README.md` descrevendo `dc.omniIngest` e seu lugar no pipeline `ingest → embed → busca híbrida → rerank`, substituindo o conteúdo herdado do template; verificar que nenhuma menção a `dc-sample` ou ao template permanece
- [x] 9.2 Documentar no README a estratégia de chunking: o que é feito (chunking estrutural com contextualização por cabeçalho e sobreposição intra-seção), por que foi escolhida sobre chunking fixo por caractere, por página e semântico, e qual o efeito de alterar `chunk_size` e `chunk_overlap` na recuperação; verificar que um leitor consegue responder às três perguntas sem abrir o código
- [x] 9.3 Documentar a tabela de configurações da Production (nome, categoria, padrão, efeito) e o schema da tabela de chunks coluna a coluna; verificar conferindo cada entrada contra as `IRISProperty` declaradas e contra o `CREATE TABLE`
- [x] 9.4 Documentar o pré-requisito de ter `dc.omniEmbedding` instalado e uma `%Embedding.Config` criada, com um exemplo de criação sem chave de API real no repositório; verificar seguindo as instruções do zero em um container limpo
