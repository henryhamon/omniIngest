"""Definicao da Production do dc.omniIngest.

A Production e declarada em codigo, e nao montada pela tela, porque o
intersystems_pyprod e explicito: as duas abordagens nao podem ser misturadas no
ciclo de vida de uma mesma Production. Em codigo, ela fica versionada em git,
sobe identica num container novo e passa por code review.

Os valores aqui sao apenas os PADROES iniciais. Todos continuam editaveis na
tela Interoperability > Configure > Production em tempo de execucao -- e e assim
que o operador ajusta pasta de entrada, chunking e tabela alvo sem recompilar.
"""

from intersystems_pyprod import (OperationItem, ProcessItem, Production, ServiceItem)

iris_package_name = "dc.omniIngest"

# As pastas sao criadas no Dockerfile. Ficam fora de /home/irisowner/dev de
# proposito: o volume do repositorio e codigo, nao area de dados.
PASTA_ENTRADA = "/data/omniingest/in"
PASTA_ARQUIVADOS = "/data/omniingest/archive"


class OmniIngestProduction(Production):
    """pasta -> parsing/chunking -> embedding -> tabela pronta para busca hibrida."""

    services = [
        ServiceItem(
            "FileWatcherService",
            "dc.omniIngest.FileWatcherService",
            host_settings={
                "TargetConfigName": "ParseChunkProcess",
                "AcceptedExtensions": "pdf,docx,pptx,md,txt",
            },
            adapter_settings={
                "FilePath": PASTA_ENTRADA,
                # SEM WorkPath de proposito: ele mutila o nome do arquivo
                # (espacos viram sublinhados, timestamp anexado) e o nome
                # original E a identidade do documento. Ver design D6.
                "ArchivePath": PASTA_ARQUIVADOS,
                "FileSpec": "*",
                "CallInterval": 5,
            },
            comment="Monitora a pasta de entrada e entrega cada arquivo aceito ao parsing.",
        )
    ]

    processes = [
        ProcessItem(
            "ParseChunkProcess",
            "dc.omniIngest.ParseChunkProcess",
            host_settings={
                "TargetConfigName": "EmbeddingBridgeOperation",
                "ChunkSize": 512,
                "ChunkOverlap": 64,
                "EmbeddingTimeout": 30,
            },
            comment="Parseia com Docling e divide em chunks estruturais contextualizados.",
        )
    ]

    operations = [
        OperationItem(
            "EmbeddingBridgeOperation",
            "dc.omniIngest.EmbeddingBridgeOperation",
            host_settings={
                "TargetTable": "dc_omniIngest.DocumentChunk",
                "EmbeddingConfigName": "omniingest-default",
            },
            # PoolSize 1 NAO e detalhe de desempenho. O controle de reingestao
            # (qual versao anterior apagar) vive na memoria do job e supoe que
            # os chunks de um documento cheguem em sequencia. Com pool maior,
            # dois documentos se intercalariam e um marcador sobrescreveria o
            # outro. Ver design.
            pool_size=1,
            comment="Gera o vetor via dc.omniEmbedding e grava o chunk na tabela alvo.",
        )
    ]
