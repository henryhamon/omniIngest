## Purpose

Requisitos transversais de operação do pipeline de ingestão: toda configuração relevante deve ser editável pela tela de configuração da Production do IRIS, e cada etapa deve deixar rastro no log de eventos para diagnóstico e auditoria.

## ADDED Requirements

### Requirement: Configuração exposta na tela da Production

Todos os parâmetros operacionais do pipeline SHALL ser expostos como configurações editáveis na tela Interoperability > Configure > Production, agrupados por categoria e com descrição legível. No mínimo MUST ser configuráveis por lá: pasta de entrada, extensões aceitas, tamanho máximo de chunk, sobreposição entre chunks, nome da tabela alvo e nome da configuração de embedding. Nenhum desses valores MUST estar embutido no código como única fonte de verdade.

#### Scenario: Operador ajusta o chunking sem tocar em código

- **WHEN** um operador altera o tamanho máximo de chunk e a sobreposição na tela de configuração e reinicia o item
- **THEN** as ingestões seguintes usam os novos valores, sem recompilação nem reimportação de código

#### Scenario: Configurações têm valores padrão utilizáveis

- **WHEN** a Production é criada sem que nenhum valor seja preenchido manualmente
- **THEN** cada configuração assume um valor padrão documentado e o pipeline é capaz de rodar de ponta a ponta com esses padrões

#### Scenario: Descrição visível para o operador

- **WHEN** o operador inspeciona uma configuração do pipeline na tela da Production
- **THEN** ele vê uma descrição que explica o efeito daquele valor

### Requirement: Rastreabilidade de cada etapa no log de eventos

O sistema SHALL registrar no log de eventos do IRIS, no mínimo: arquivo recebido (com nome e tamanho), documento parseado (com formato e tempo de parsing), quantidade de chunks gerados, cada chunk persistido com sucesso (com índice do chunk e identificador da linha) e cada chunk falho (com índice do chunk e motivo). Falhas MUST ser registradas em nível de erro e eventos normais em nível informativo.

#### Scenario: Trilha completa de um documento bem-sucedido

- **WHEN** um documento é ingerido com sucesso
- **THEN** o log de eventos contém, para aquele documento, o registro de recebimento, o de parsing, a contagem de chunks gerados e um registro por chunk persistido

#### Scenario: Falha aparece em nível de erro

- **WHEN** um chunk falha no embedding
- **THEN** existe um registro em nível de erro nomeando o documento, o índice do chunk e o motivo da falha

#### Scenario: Resumo por documento ao final

- **WHEN** o processamento de um documento termina
- **THEN** o log contém uma linha de resumo com o identificador do documento, o total de chunks gerados, o total persistido e o total falho

### Requirement: Pipeline observável pelo Message Viewer

Cada arquivo e cada chunk SHALL trafegar como mensagem persistível, de modo que todo o percurso de um documento seja reconstituível pelo Message Viewer da Production. As mensagens de chunk de um mesmo arquivo MUST pertencer à mesma sessão da mensagem de arquivo que as originou.

#### Scenario: Percurso de um documento reconstituível

- **WHEN** um operador abre no Message Viewer a mensagem de um arquivo ingerido
- **THEN** ele consegue navegar, pela mesma sessão, até as mensagens de cada chunk gerado a partir daquele arquivo e ver o status de cada uma

### Requirement: Estratégia de chunking documentada

O repositório SHALL documentar a estratégia de chunking adotada e a justificativa dela, incluindo as alternativas consideradas e descartadas e o efeito dos parâmetros configuráveis sobre a qualidade da recuperação. A documentação MUST estar no README do projeto, acessível sem leitura do código-fonte.

#### Scenario: Leitor entende a estratégia sem ler o código

- **WHEN** um avaliador lê o README do projeto
- **THEN** ele encontra qual estratégia de chunking é usada, por que ela foi escolhida sobre as alternativas, e o que acontece ao alterar tamanho e sobreposição
