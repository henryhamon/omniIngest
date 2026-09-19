## Purpose

Define como arquivos entram no pipeline de ingestão: uma pasta monitorada, um filtro de formatos aceitos e a entrega do arquivo às etapas seguintes como mensagem persistível e rastreável.

## ADDED Requirements

### Requirement: Monitoramento de pasta configurável

O sistema SHALL monitorar continuamente uma pasta do sistema de arquivos e iniciar a ingestão de cada arquivo que aparece nela. O caminho da pasta e o intervalo de varredura MUST ser configuráveis pela tela de configuração da Production, sem recompilação.

#### Scenario: Arquivo depositado na pasta é ingerido

- **WHEN** um arquivo de formato suportado é copiado para a pasta monitorada e a Production está rodando
- **THEN** o pipeline de ingestão é iniciado para aquele arquivo dentro de um intervalo de varredura

#### Scenario: Mudança de pasta em runtime

- **WHEN** o caminho da pasta de entrada é alterado na tela de configuração e o item é reiniciado
- **THEN** o sistema passa a monitorar o novo caminho e para de monitorar o anterior, sem alteração de código

### Requirement: Filtro de formatos suportados

O sistema SHALL aceitar arquivos PDF, DOCX, PPTX, MD e TXT. A lista de extensões aceitas MUST ser configurável. Um arquivo com extensão fora da lista MUST ser rejeitado sem ser parseado e sem interromper o processamento dos demais arquivos.

#### Scenario: Extensão não suportada

- **WHEN** um arquivo com extensão fora da lista configurada aparece na pasta monitorada
- **THEN** o arquivo não é parseado, um registro de log nomeia o arquivo e a extensão rejeitada, e a ingestão dos demais arquivos continua normalmente

#### Scenario: Extensão suportada em maiúsculas

- **WHEN** um arquivo cujo nome termina em `.PDF` aparece na pasta monitorada
- **THEN** ele é aceito, pois a comparação de extensão é insensível a maiúsculas e minúsculas

### Requirement: Arquivo permanece legível durante o parsing

O sistema SHALL garantir que o conteúdo do arquivo continue acessível por caminho de sistema de arquivos durante toda a etapa de parsing.

#### Scenario: Parser abre o arquivo pelo caminho recebido

- **WHEN** a etapa de parsing abre o caminho que veio na mensagem do arquivo
- **THEN** a leitura é bem-sucedida e devolve o conteúdo do arquivo depositado

### Requirement: Nome original preservado como identidade do documento

O identificador do documento SHALL ser o nome original do arquivo exatamente como ele foi depositado, sem substituição de caracteres nem sufixos acrescentados. Um arquivo cujo nome contenha espaços MUST produzir um identificador com os mesmos espaços.

#### Scenario: Nome com espaços sobrevive à ingestão

- **WHEN** um arquivo chamado `Relatorio Anual 2025.pdf` é ingerido
- **THEN** o identificador do documento registrado é `Relatorio Anual 2025.pdf`, com os espaços intactos

### Requirement: Entrega ao pipeline como mensagem persistível

O sistema SHALL representar cada arquivo aceito como uma mensagem persistível encaminhada à etapa de parsing. A mensagem MUST conter identificador do documento, nome original do arquivo, caminho legível do arquivo e tamanho em bytes, e MUST ser visível no Message Viewer da Production e consultável por SQL.

#### Scenario: Mensagem de arquivo visível no Message Viewer

- **WHEN** um arquivo suportado é ingerido
- **THEN** existe no Message Viewer uma mensagem daquele arquivo, com nome original e identificador do documento legíveis, encadeada na mesma sessão que as mensagens de chunk subsequentes

### Requirement: Isolamento de falha por arquivo

Uma falha ao processar um arquivo SHALL NOT impedir o processamento dos arquivos seguintes. O sistema MUST registrar a falha identificando o arquivo e continuar monitorando a pasta.

#### Scenario: Arquivo corrompido não derruba o pipeline

- **WHEN** um arquivo de formato suportado mas com conteúdo corrompido é ingerido e o parsing falha
- **THEN** a falha é registrada com o nome do arquivo e o arquivo seguinte na pasta é processado normalmente
