"""Mensagens persistiveis que trafegam pelo pipeline de ingestao do dc.omniIngest.

Cada arquivo e cada chunk viram uma mensagem persistivel. Isso nao e detalhe de
implementacao: e o que torna o percurso de um documento reconstituivel pelo
Message Viewer da Production e consultavel por SQL.

Contrato de nomes
-----------------
Os campos de chunk repetem, um a um, os nomes das colunas criadas por
``dc.omniIngest.Schema``: doc_key, doc_id, source_file, chunk_index,
heading_path, page_numbers, chunk_text. Divergir aqui significaria traduzir
nomes no meio do caminho, que e onde esse tipo de bug se esconde.

Como o pyprod projeta isso no IRIS
----------------------------------
Uma subclasse de ``JsonSerialize`` guarda TODOS os campos declarados como JSON
num stream. Os campos declarados com ``Column(...)`` viram, alem disso,
propriedades IRIS de verdade -- logo, colunas SQL consultaveis e indexaveis.

Duas regras do pyprod moldam o codigo abaixo:

1. O tipo da coluna sai da anotacao, via um mapa que so conhece
   ``str``/``int``/``bool``/``num`` (-> %VarString, %Integer, %Boolean,
   %Numeric). Qualquer outra coisa vira %VarString silenciosamente. Por isso as
   anotacoes aqui sao sempre um desses quatro.

2. O nome da propriedade IRIS vem de ``snake_to_pascal``, que so converte se
   houver sublinhado: ``doc_key`` -> ``DocKey``, mas ``success`` -> ``success``,
   sem inicial maiuscula. Nao e erro, e o comportamento da biblioteca.

3. Um ``bool`` do Python NAO sobrevive ao marshalling para uma coluna: ele chega
   no IRIS como referencia de objeto e a gravacao falha com "Datatype value
   '5@%SYS.Python' is not a valid boolean". Verificado: a mesma coluna aceita
   ``1`` e ``0``. Por isso campos de verdadeiro/falso aqui sao ``int``, e existe
   ``as_flag()`` abaixo para converter no ponto de construcao.
"""

from intersystems_pyprod import Column, JsonSerialize

iris_package_name = "dc.omniIngest"


def as_flag(value) -> int:
    """Converte qualquer coisa para o 1/0 que as colunas do pyprod aceitam.

    Existe porque ``True``/``False`` do Python quebram a gravacao da mensagem
    (ver nota 3 no docstring do modulo). Use sempre isto ao montar um campo de
    verdadeiro/falso, em vez de passar o bool direto.
    """
    return 1 if value else 0


class IngestFileRequest(JsonSerialize):
    """Um arquivo aceito pela pasta monitorada, a caminho do parsing.

    ``work_path`` e o caminho no diretorio de trabalho do adapter, e nao o
    caminho na pasta de entrada: quando o parsing roda, o arquivo ja saiu da
    entrada. E esse caminho que o Docling abre.
    """

    # Identidade do documento: o nome original do arquivo. E por ele que a
    # reingestao substitui a versao anterior. Deliberadamente NAO e o hash --
    # um arquivo editado tem hash novo e deixaria a versao velha orfa na tabela.
    doc_key: str = Column(default="", description="Identidade do documento (nome original do arquivo)", index=True)

    # SHA-256 do conteudo, em hexadecimal minusculo (64 caracteres). Serve para
    # saber se o arquivo realmente mudou, nao para identificar o documento.
    doc_id: str = Column(default="", description="SHA-256 do conteudo do arquivo")

    source_file: str = Column(default="", description="Caminho do arquivo como ele chegou na pasta de entrada")
    work_path: str = Column(default="", description="Caminho legivel do arquivo durante o parsing (WorkPath do adapter)")
    size_bytes: int = Column(default=0, description="Tamanho do arquivo em bytes")


class ChunkEmbedRequest(JsonSerialize):
    """Um chunk pronto para virar vetor e linha na tabela alvo.

    ``chunk_text`` e o texto bruto, que vai para a coluna ``chunk_text`` e para
    o indice iFind. ``embedding_text`` e o texto contextualizado (caminho de
    cabecalhos + conteudo), que e o que de fato vai para o embedding. Os dois
    viajam juntos porque sao diferentes de proposito: quem le um resultado de
    busca quer o bruto; o espaco vetorial precisa do contextualizado.
    """

    doc_key: str = Column(default="", description="Identidade do documento (nome original do arquivo)", index=True)
    doc_id: str = Column(default="", description="SHA-256 do conteudo do arquivo")
    source_file: str = Column(default="", description="Caminho do arquivo como ele chegou na pasta de entrada")

    # Ordinal do chunk dentro do documento, comecando em zero e contiguo:
    # chunks vazios sao descartados antes da numeracao, nao depois.
    chunk_index: int = Column(default=0, description="Ordinal do chunk dentro do documento, base zero", index=True)

    # Caminho de cabecalhos ate a secao do chunk, do mais externo para o mais
    # interno, separado por " > ". Vazio quando o chunk nao esta sob cabecalho.
    heading_path: str = Column(default="", description="Caminho de cabecalhos da secao, separado por ' > '")

    # FORMATO: string de numeros de pagina em ordem crescente, separados por
    # virgula, sem espacos -- por exemplo "3,4". Vazio quando o formato de
    # origem nao tem paginas (Markdown, TXT).
    #
    # Escolhido como string, e nao lista, porque a coluna page_numbers criada
    # por dc.omniIngest.Schema e VARCHAR(256). Serializar uma lista aqui e
    # desserializar na Operation seria uma traducao a mais entre a mensagem e a
    # tabela, sem ganho nenhum: ninguem faz aritmetica com esse campo, so
    # exibe. O valor vai para a coluna exatamente como esta aqui.
    page_numbers: str = Column(default="", description="Paginas de origem, separadas por virgula (vazio se o formato nao tem paginas)")

    chunk_text: str = Column(default="", description="Texto bruto do chunk, como vai para a coluna chunk_text e para o indice iFind")
    embedding_text: str = Column(default="", description="Texto contextualizado (cabecalhos + conteudo) que vai para o embedding")


class ChunkEmbedResponse(JsonSerialize):
    """Resultado de um chunk: ou virou linha, ou falhou com motivo.

    Os tres campos sao Column para que a contagem de sucesso e falha por
    documento saia de uma consulta SQL, sem precisar abrir mensagem por
    mensagem no Message Viewer.

    Atencao ao nome: ``success`` nao tem sublinhado, entao o pyprod o projeta
    como propriedade ``success`` mesmo, em minuscula -- diferente de
    ``row_id`` -> ``RowId``.
    """

    # int, e nao bool, de proposito: um bool do Python nao sobrevive ao
    # marshalling para a coluna (ver nota 3 no docstring do modulo). Monte este
    # campo com as_flag(), nunca com True/False direto.
    success: int = Column(default=0, description="1 se o chunk foi persistido, 0 se falhou")

    # Id da linha criada na tabela alvo. 0 quando o chunk falhou.
    row_id: int = Column(default=0, description="Id da linha persistida na tabela alvo, ou 0 em caso de falha")

    # Mensagem de erro legivel, nomeando os valores envolvidos. Vazia em sucesso.
    error_message: str = Column(default="", description="Motivo da falha, vazio em caso de sucesso")
