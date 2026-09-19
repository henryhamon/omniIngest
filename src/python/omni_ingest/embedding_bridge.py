"""Gera o vetor de cada chunk e o persiste na tabela alvo.

Onde este modulo NAO fala com provider nenhum
=============================================
A chamada de embedding sai por ``dc.omniIngest.Embedder.EmbedToCsv``, que abre a
%Embedding.Config pelo nome e despacha para a classe declarada no campo
EmbeddingClass dela -- ``dc.omniEmbedding.Interface`` no pacote publicado. Este
modulo nao monta requisicao HTTP, nao conhece provider e nao ve chave de API:
credenciais vivem na %Embedding.Config, nao em settings da Production, que
aparecem em telas e em exports.

Por que o vetor chega como CSV
------------------------------
%Vector nao tem representacao estavel do lado do Embedded Python -- um
"SELECT <coluna vector>" a partir daqui falha com "Invalid argument type". A
conversao acontece em ObjectScript, onde o vetor nasce, e volta como string
separada por virgulas que o TO_VECTOR() consome.

A forma do TO_VECTOR importa
----------------------------
``TO_VECTOR(?, ?, ?)`` NAO funciona: o tipo e palavra-chave, nao string, e nem
ele nem a dimensao aceitam parametro. Verificado na IRIS 2026.2 -- com o tipo
entre aspas ou como "?", o erro e "Invalid VECTOR field definition". Entao a
CSV viaja como parametro e o tipo e a dimensao sao interpolados no texto do SQL.
Isso e seguro porque a dimensao vem da propria coluna e o nome da tabela passa
pela validacao de identificador do dc.omniIngest.Schema antes de ser usado.
"""

import iris
from intersystems_pyprod import (BusinessOperation, IRISLog, IRISProperty, Status)

from messages import ChunkEmbedResponse, as_flag

iris_package_name = "dc.omniIngest"


class EmbeddingBridgeOperation(BusinessOperation):
    """Um chunk entra, uma linha sai -- ou uma falha nomeada, e so daquele chunk."""

    target_table: str = IRISProperty(
        default="dc_omniIngest.DocumentChunk",
        description="Tabela de chunks no formato <schema>.<tabela>. Precisa existir com a dimensao de vetor da config de embedding.",
        settings="omniIngest")

    embedding_config_name: str = IRISProperty(
        default="omniingest-default",
        description="Nome da %Embedding.Config que define provider, modelo e credencial. A chave de API fica la, nunca aqui.",
        settings="omniIngest")

    # Gatilho de teste para exercitar o rollback. NAO aparece na tela da
    # Production (settings=None) e vale 0 em operacao normal. Existe porque a
    # unica forma de provar que uma falha DEPOIS do INSERT nao deixa linha
    # parcial e provocar essa falha exatamente ali.
    simular_falha_pos_insert: int = IRISProperty(
        default=0,
        description="Somente teste: 1 provoca excecao apos o INSERT, antes do commit.")

    def OnMessage(self, request):
        doc_key = getattr(request, "doc_key", "(desconhecido)")
        indice = getattr(request, "chunk_index", -1)
        try:
            tabela, esquema, nome_tabela = self._tabela_validada()
            dimensao_coluna = self._dimensao_coluna(esquema, nome_tabela, tabela)
            marco = self._marco_reingestao(doc_key, tabela, indice)

            csv, dimensao = self._embeddar(request.embedding_text)

            # A divergencia e detectada ANTES de qualquer escrita: um vetor de
            # tamanho errado nao chega a tocar a tabela.
            if dimensao != dimensao_coluna:
                raise ValueError(
                    "dimensao do vetor nao confere: a config '%s' devolveu %d, mas a coluna "
                    "chunk_vector de %s tem %d. Nenhuma linha foi gravada."
                    % (self.embedding_config_name, dimensao, tabela, dimensao_coluna))

            row_id = self._gravar(request, tabela, csv, dimensao, doc_key, marco)

            IRISLog.Info("dc.omniIngest: chunk %d de '%s' persistido na linha %d de %s."
                         % (indice, doc_key, row_id, tabela))
            return Status.OK(), ChunkEmbedResponse(success=as_flag(True), row_id=row_id, error_message="")

        except Exception as excecao:
            motivo = "%s: %s" % (type(excecao).__name__, excecao)
            IRISLog.Error("dc.omniIngest: chunk %d de '%s' falhou: %s" % (indice, doc_key, motivo))
            # Status.OK com success=0 de proposito: a falha e DESTE chunk. Um
            # Status.ERROR derrubaria o Business Process inteiro
            # (<Ens>ErrBPTerminated) e levaria junto os chunks seguintes do
            # mesmo documento. Quem chama le o campo success da resposta.
            return Status.OK(), ChunkEmbedResponse(success=as_flag(False), row_id=0, error_message=motivo)

    # -- configuracao ------------------------------------------------------

    def _tabela_validada(self):
        tabela = (self.target_table or "").strip()
        esquema_ref, nome_ref = iris.ref(""), iris.ref("")
        status = iris.cls("dc.omniIngest.Schema").ValidateTableName(tabela, esquema_ref, nome_ref)
        if not iris.cls("%SYSTEM.Status").IsOK(status):
            raise ValueError(iris.cls("%SYSTEM.Status").GetErrorText(status))
        return tabela, esquema_ref.value, nome_ref.value

    def _dimensao_coluna(self, esquema, nome_tabela, tabela):
        """Dimensao declarada da coluna chunk_vector, lida uma vez por job."""
        cache = getattr(self, "_dimensao_cache", None)
        if cache and cache[0] == tabela:
            return cache[1]
        achou = iris.ref(0)
        dimensao = iris.cls("dc.omniIngest.Schema").GetVectorDimension(esquema, nome_tabela, achou)
        if not achou.value:
            raise ValueError(
                "a tabela alvo '%s' nao existe. Rode dc.omniIngest.Schema.Create() antes de iniciar "
                "a Production, ou corrija 'target table' na tela de configuracao." % tabela)
        dimensao = int(dimensao or 0)
        if dimensao < 1:
            raise ValueError("nao foi possivel ler a dimensao da coluna chunk_vector de '%s'." % tabela)
        self._dimensao_cache = (tabela, dimensao)
        return dimensao

    # -- embedding ---------------------------------------------------------

    def _embeddar(self, texto):
        dimensao_ref = iris.ref(0)
        csv = iris.cls("dc.omniIngest.Embedder").EmbedToCsv(
            texto, self.embedding_config_name, dimensao_ref)
        if not csv:
            raise ValueError("a config '%s' devolveu um vetor vazio." % self.embedding_config_name)
        return csv, int(dimensao_ref.value or 0)

    # -- persistencia ------------------------------------------------------

    def _marco_reingestao(self, doc_key, tabela, chunk_index):
        """Maior id ja existente deste documento, capturado antes da 1a escrita.

        E o que permite a regra da reingestao: apagar a versao anterior SOMENTE
        depois que o primeiro chunk novo entrou. Guardar o id de corte, em vez
        de apagar por doc_key, evita que a limpeza leve junto a linha recem
        gravada -- ela tem id maior que o marco.

        Se o parsing falhar e nenhum chunk novo for gravado, nada e apagado e a
        versao anterior continua servindo consultas.
        """
        estado = getattr(self, "_estado_reingestao", None)
        if estado is None:
            estado = {}
            self._estado_reingestao = estado

        # O marcador e recapturado a CADA chunk_index 0, porque chunk 0 e o
        # inicio de uma ingestao -- nao de um documento. Cachear por doc_key
        # para sempre foi um bug real: na segunda ingestao do mesmo arquivo o
        # marcador ainda valia o da primeira (zero, quando a tabela estava
        # vazia), a purga nunca disparava e as duas versoes conviviam na tabela.
        #
        # O dicionario guarda so a ingestao corrente. Isso vale porque os chunks
        # de um documento chegam em sequencia, o que por sua vez depende do
        # envio sincrono e de PoolSize 1 nesta Operation. Com pool maior, dois
        # documentos se intercalariam e este estado precisaria sair da memoria
        # do job para a tabela.
        if int(chunk_index or 0) == 0:
            estado.clear()

        if doc_key not in estado:
            resultado = [list(r) for r in iris.sql.exec(
                "SELECT MAX(id) FROM %s WHERE doc_key = ?" % tabela, doc_key)]
            maximo = resultado[0][0] if resultado and resultado[0][0] is not None else 0
            estado[doc_key] = {"marco": int(maximo or 0), "purgado": False}
        return estado[doc_key]

    def _gravar(self, request, tabela, csv, dimensao, doc_key, marco):
        colunas = ("doc_key, doc_id, source_file, chunk_index, heading_path, page_numbers, "
                   "chunk_text, chunk_vector, embedding_config, vector_dimension")
        # dimensao e inteiro lido da propria coluna; tabela passou pela
        # validacao de identificador. Todo o resto vai como parametro.
        sql = ("INSERT INTO %s (%s) VALUES (?,?,?,?,?,?,?,TO_VECTOR(?,double,%d),?,?)"
               % (tabela, colunas, dimensao))

        iris.tstart()
        try:
            iris.sql.exec(sql,
                          request.doc_key, request.doc_id, request.source_file,
                          request.chunk_index, request.heading_path, request.page_numbers,
                          request.chunk_text, csv, self.embedding_config_name, dimensao)

            linha = [list(r) for r in iris.sql.exec(
                "SELECT MAX(id) FROM %s WHERE doc_key = ? AND chunk_index = ?" % tabela,
                request.doc_key, request.chunk_index)]
            row_id = int(linha[0][0]) if linha and linha[0][0] is not None else 0

            if int(self.simular_falha_pos_insert or 0):
                raise RuntimeError("falha simulada apos o INSERT, antes do commit (gatilho de teste)")

            # A purga da versao anterior entra na MESMA transacao do primeiro
            # chunk novo: ou os dois acontecem, ou nenhum.
            if not marco["purgado"] and marco["marco"] > 0:
                iris.sql.exec("DELETE FROM %s WHERE doc_key = ? AND id <= ?" % tabela,
                              request.doc_key, marco["marco"])
                marco["purgado"] = True
                IRISLog.Info("dc.omniIngest: reingestao de '%s' -- versao anterior (ids ate %d) removida."
                             % (doc_key, marco["marco"]))

            iris.tcommit()
            return row_id
        except Exception:
            # Qualquer falha daqui para tras desfaz o INSERT: a tabela nao fica
            # com linha parcial nem com a versao anterior meio apagada.
            iris.trollback()
            marco["purgado"] = False
            raise
