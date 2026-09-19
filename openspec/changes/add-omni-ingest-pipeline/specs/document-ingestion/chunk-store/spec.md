## Purpose

Define a tabela SQL onde cada chunk de documento ingerido é persistido junto com seu vetor de embedding e seus metadados de proveniência, de modo que busca vetorial e busca por palavra-chave possam ser combinadas sobre a mesma linha sem remodelar o schema depois.

## ADDED Requirements

### Requirement: Tabela de chunks com texto e vetor na mesma linha

O sistema SHALL persistir cada chunk em uma única linha que contém, ao mesmo tempo, o texto bruto do chunk e o vetor de embedding correspondente. O texto bruto MUST ser armazenado sem truncamento silencioso e em um tipo que aceite índice de texto completo (iFind); o vetor MUST ser armazenado em uma coluna de tipo vetorial nativo com dimensão fixa, não como string.

#### Scenario: Chunk persistido carrega texto e vetor

- **WHEN** um chunk é ingerido com sucesso
- **THEN** existe exatamente uma linha na tabela alvo cujo texto do chunk é recuperável na íntegra por `SELECT` e cujo vetor é utilizável diretamente por funções de distância vetorial do IRIS (por exemplo `VECTOR_COSINE`) sem conversão adicional

#### Scenario: Texto longo não é truncado

- **WHEN** um chunk contém mais caracteres do que o tamanho padrão de uma string curta do IRIS
- **THEN** o texto armazenado é byte a byte igual ao texto que foi embeddado

### Requirement: Metadados de proveniência por chunk

Cada linha SHALL registrar de onde o chunk veio, permitindo rastrear um resultado de busca até o documento e a posição de origem. No mínimo, cada linha MUST conter: identificador do documento de origem, nome do arquivo original, índice ordinal do chunk dentro do documento, caminho de cabeçalhos (heading path) do chunk, páginas de origem quando o formato as expõe, nome do modelo/config de embedding usado, dimensão do vetor e timestamp de criação.

#### Scenario: Resultado de busca é rastreável até a origem

- **WHEN** uma linha de chunk é lida
- **THEN** é possível determinar, apenas a partir dela, qual arquivo a originou, em que ordem ela aparece no documento e sob quais cabeçalhos ela está

#### Scenario: Página de origem ausente não bloqueia a ingestão

- **WHEN** o formato de origem não expõe numeração de página (por exemplo Markdown ou TXT)
- **THEN** a linha é persistida com o campo de página vazio e todos os demais metadados preenchidos

### Requirement: Prontidão para busca híbrida

O schema SHALL suportar busca híbrida sem alteração de estrutura. A coluna de texto MUST ter um índice iFind definido, e a coluna vetorial MUST ter dimensão declarada compatível com o modelo de embedding configurado, de modo que um índice vetorial aproximado possa ser adicionado depois sem `ALTER` destrutivo nem reingestão.

#### Scenario: Busca por palavra-chave e busca vetorial sobre a mesma tabela

- **WHEN** uma consulta filtra por termo usando o predicado iFind e ordena por distância vetorial na mesma instrução SQL
- **THEN** a consulta executa com sucesso e retorna linhas da tabela de chunks

#### Scenario: Adicionar índice vetorial depois não exige reingestão

- **WHEN** um índice vetorial aproximado é criado sobre a coluna de vetor de uma tabela já populada
- **THEN** a criação do índice conclui sem exigir alteração do tipo da coluna nem reprocessamento dos documentos já ingeridos

### Requirement: Criação idempotente do schema

O sistema SHALL fornecer uma rotina de criação de schema que pode ser executada repetidamente. Se a tabela alvo já existir com a estrutura esperada, a rotina MUST terminar com sucesso sem apagar dados. Se a tabela existir com dimensão de vetor diferente da configurada, a rotina MUST falhar com erro explícito em vez de descartar ou corromper os dados existentes.

#### Scenario: Reexecução em instalação já inicializada

- **WHEN** a rotina de criação de schema roda pela segunda vez com a mesma configuração
- **THEN** ela retorna sucesso e nenhuma linha existente é removida

#### Scenario: Conflito de dimensão de vetor

- **WHEN** a rotina roda contra uma tabela existente cuja coluna vetorial tem dimensão diferente da dimensão configurada
- **THEN** a rotina falha com uma mensagem que nomeia a tabela, a dimensão encontrada e a dimensão esperada, e nenhum dado é alterado

### Requirement: Reingestão substitui a versão anterior do documento

Quando um documento já ingerido é ingerido novamente, o sistema SHALL substituir os chunks anteriores daquele documento em vez de duplicá-los. Os chunks antigos MUST ser removidos apenas depois que os novos chunks tiverem sido gerados, de modo que uma falha de parsing não deixe a tabela sem nenhuma versão do documento.

#### Scenario: Mesmo arquivo ingerido duas vezes

- **WHEN** o mesmo documento é ingerido uma segunda vez com sucesso
- **THEN** a tabela contém somente os chunks da segunda ingestão para aquele documento, sem linhas remanescentes da primeira

#### Scenario: Falha de parsing na reingestão

- **WHEN** a segunda ingestão de um documento já presente falha durante o parsing
- **THEN** os chunks da ingestão anterior permanecem intactos na tabela
