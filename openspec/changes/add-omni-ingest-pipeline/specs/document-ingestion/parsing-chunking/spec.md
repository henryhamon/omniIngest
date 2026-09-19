## Purpose

Define como um documento binário ou textual é convertido em uma sequência de chunks de texto prontos para embedding, incluindo a estratégia de divisão e as garantias observáveis sobre os chunks produzidos.

## ADDED Requirements

### Requirement: Parsing de documentos em CPU

O sistema SHALL converter PDF, DOCX, PPTX, MD e TXT em uma representação estruturada de documento (com cabeçalhos, parágrafos, listas e tabelas) e em um texto em Markdown. O parsing MUST rodar em CPU comum, sem exigir GPU, e MUST NOT depender de chamadas de rede em tempo de ingestão.

#### Scenario: PDF com tabela é parseado em CPU

- **WHEN** um PDF contendo texto e ao menos uma tabela é ingerido em uma máquina sem GPU
- **THEN** o parsing conclui com sucesso e o conteúdo da tabela aparece no texto extraído

#### Scenario: Ingestão sem acesso à rede para o parser

- **WHEN** o parsing roda em um ambiente sem acesso a downloads externos
- **THEN** o parsing conclui com sucesso, pois os modelos necessários já estão presentes localmente

### Requirement: Chunking com consciência de estrutura

O sistema SHALL dividir o documento respeitando sua estrutura: um chunk MUST NOT cortar uma tabela ao meio nem separar um cabeçalho do primeiro bloco de conteúdo que ele introduz. A divisão MUST preferir fronteiras estruturais (seção, parágrafo, célula de tabela) a cortes por contagem cega de caracteres.

#### Scenario: Tabela preservada

- **WHEN** um documento contém uma tabela que cabe dentro do tamanho máximo de chunk configurado
- **THEN** a tabela aparece inteira em um único chunk

#### Scenario: Cabeçalho acompanha seu conteúdo

- **WHEN** uma seção começa com um cabeçalho seguido de um parágrafo
- **THEN** o cabeçalho e o início do parágrafo estão no mesmo chunk

### Requirement: Contextualização por caminho de cabeçalhos

Cada chunk SHALL carregar o caminho de cabeçalhos da seção de onde veio, e esse caminho MUST ser incluído no texto enviado para embedding, para que um trecho ambíguo isolado continue interpretável. O texto bruto persistido e o texto efetivamente embeddado MUST ser ambos determináveis a partir da linha persistida.

#### Scenario: Chunk de subseção carrega sua hierarquia

- **WHEN** um chunk é extraído de uma subseção aninhada sob dois cabeçalhos
- **THEN** o caminho de cabeçalhos registrado para esse chunk contém ambos os cabeçalhos, na ordem do documento

### Requirement: Tamanho e sobreposição configuráveis

O tamanho máximo de chunk e a sobreposição entre chunks consecutivos SHALL ser configuráveis pela tela de configuração da Production. Nenhum chunk MUST exceder o tamanho máximo configurado. Quando a sobreposição é maior que zero, chunks consecutivos da mesma seção MUST compartilhar conteúdo de fronteira; quando é zero, eles MUST NOT compartilhar conteúdo.

#### Scenario: Limite de tamanho respeitado

- **WHEN** um documento é ingerido com um tamanho máximo de chunk configurado
- **THEN** nenhum chunk gerado excede esse limite

#### Scenario: Sobreposição ativa

- **WHEN** a sobreposição está configurada com valor maior que zero e uma seção gera dois chunks consecutivos
- **THEN** o fim do primeiro chunk e o início do segundo compartilham conteúdo, na quantidade aproximada configurada

#### Scenario: Sobreposição desativada

- **WHEN** a sobreposição está configurada como zero
- **THEN** chunks consecutivos não compartilham conteúdo

#### Scenario: Configuração inválida é rejeitada

- **WHEN** a sobreposição configurada é maior ou igual ao tamanho máximo de chunk
- **THEN** a configuração é rejeitada com erro explícito na inicialização do item, em vez de gerar chunking infinito ou degenerado

### Requirement: Chunks vazios são descartados

O sistema SHALL descartar chunks cujo conteúdo, após remoção de espaços em branco, seja vazio, e MUST NOT enviá-los para embedding. Os índices ordinais dos chunks efetivamente persistidos MUST ser contíguos e começar em zero.

#### Scenario: Página em branco não gera chunk

- **WHEN** um documento contém uma página sem conteúdo textual
- **THEN** nenhum chunk é gerado para aquela página e os índices dos demais chunks permanecem contíguos

### Requirement: Um chunk por mensagem, em ordem

O sistema SHALL enviar cada chunk como uma mensagem persistível individual para a etapa de embedding, na ordem do documento, e SHALL aguardar o resultado de cada chunk antes de contabilizá-lo como bem-sucedido ou falho.

#### Scenario: Contagem final por documento

- **WHEN** um documento gera N chunks e M deles falham no embedding
- **THEN** ao final do processamento o sistema reporta N gerados, N menos M persistidos e M falhos
