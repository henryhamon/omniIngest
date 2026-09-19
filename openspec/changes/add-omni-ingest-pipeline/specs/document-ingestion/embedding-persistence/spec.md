## Purpose

Define como o texto de cada chunk é transformado em vetor pelo gateway de embeddings existente e persistido na tabela de chunks, incluindo o comportamento sob falha de provider e as garantias de consistência por chunk.

## ADDED Requirements

### Requirement: Reuso do gateway de embeddings existente

O sistema SHALL obter o vetor de cada chunk chamando o gateway `dc.omniEmbedding` já instalado no namespace, e SHALL NOT implementar cliente HTTP próprio para provedores de embedding. A escolha de provider e modelo MUST vir da configuração nomeada referenciada na tela da Production, e não de valores embutidos no código.

#### Scenario: Vetor gerado pelo gateway

- **WHEN** um chunk é enviado para embedding com uma configuração de embedding válida
- **THEN** o vetor persistido é o retornado pelo gateway `dc.omniEmbedding` para aquele texto e aquela configuração

#### Scenario: Troca de provider sem alterar código

- **WHEN** a configuração de embedding referenciada na tela da Production é trocada por outra que usa provider diferente
- **THEN** as ingestões seguintes usam o novo provider, sem recompilação do pipeline

### Requirement: Segredos não ficam na configuração da Production

Chaves de API e endpoints de provedores SHALL ser lidos da configuração de embedding nomeada existente no namespace. A tela de configuração da Production MUST expor apenas o nome dessa configuração, e MUST NOT conter campos de chave de API.

#### Scenario: Tela da Production não expõe chave

- **WHEN** um operador abre a configuração do item de embedding na tela da Production
- **THEN** ele vê o nome da configuração de embedding a ser usada e nenhum campo contendo chave de API

### Requirement: Persistência do vetor em coluna vetorial nativa

O sistema SHALL persistir o vetor retornado na coluna vetorial da tabela alvo como vetor nativo, e MUST NOT armazená-lo como texto, JSON ou blob. O nome da tabela alvo MUST ser configurável pela tela da Production.

#### Scenario: Vetor utilizável por função de distância

- **WHEN** um chunk é persistido e uma consulta calcula a similaridade de cosseno entre a coluna vetorial e um vetor de consulta
- **THEN** a consulta retorna um valor de similaridade, sem conversão explícita da coluna

#### Scenario: Tabela alvo trocada por configuração

- **WHEN** o nome da tabela alvo é alterado na tela da Production para outra tabela com o mesmo schema e o item é reiniciado
- **THEN** as ingestões seguintes gravam na nova tabela

### Requirement: Validação de dimensão do vetor

O sistema SHALL verificar que a dimensão do vetor retornado corresponde à dimensão declarada da coluna vetorial antes de persistir. Em caso de divergência, o chunk MUST ser marcado como falho com mensagem que nomeia a dimensão esperada e a recebida, e MUST NOT ser gravado parcialmente.

#### Scenario: Modelo com dimensão diferente da tabela

- **WHEN** a configuração de embedding é trocada por um modelo cuja dimensão de saída difere da dimensão da coluna vetorial
- **THEN** o chunk é reportado como falho com as duas dimensões na mensagem e nenhuma linha é inserida

### Requirement: Isolamento de falha por chunk

A falha de um chunk SHALL NOT abortar o restante do documento. Cada chunk MUST ser persistido de forma atômica: ou a linha completa (texto, vetor e metadados) é gravada, ou nada daquele chunk é gravado.

#### Scenario: Provider indisponível para um chunk

- **WHEN** a chamada de embedding falha para um chunk específico enquanto os demais têm sucesso
- **THEN** os demais chunks do documento são persistidos, o chunk falho não gera linha, e a falha é reportada identificando documento e índice do chunk

#### Scenario: Falha entre o embedding e o INSERT

- **WHEN** a gravação falha depois de o vetor ter sido obtido
- **THEN** nenhuma linha parcial permanece na tabela para aquele chunk

### Requirement: Resultado por chunk reportado ao chamador

Cada operação de embedding e persistência SHALL retornar ao chamador um resultado que indica sucesso ou falha, o identificador da linha criada em caso de sucesso, e a mensagem de erro em caso de falha.

#### Scenario: Resposta de sucesso

- **WHEN** um chunk é embeddado e persistido com sucesso
- **THEN** a resposta indica sucesso e contém o identificador da linha persistida

#### Scenario: Resposta de falha

- **WHEN** um chunk falha no embedding ou na persistência
- **THEN** a resposta indica falha e contém uma mensagem de erro não vazia
