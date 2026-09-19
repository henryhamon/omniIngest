"""Parsing com Docling e chunking estrutural.

Estrategia de chunking (o "porque", nao so o "como")
====================================================
O DocumentConverter nao devolve so texto: devolve um DoclingDocument, uma arvore
com cabecalhos, paragrafos, listas e tabelas. Picar o Markdown resultante a cada
N caracteres jogaria fora exatamente a informacao pela qual se pagou o custo do
parsing. Por isso, nesta ordem:

1. HybridChunker sobre a arvore -- respeita fronteira de tabela e de secao,
   funde chunks pequenos demais e divide os grandes demais por contagem de
   tokens.
2. Contextualizacao por cabecalho -- o texto que vai para o embedding leva o
   caminho de cabecalhos na frente. "O limite e 30 dias" vira, no espaco
   vetorial, "Politicas > Reembolso > O limite e 30 dias". O texto bruto, que e
   o que se exibe e o que o iFind indexa, fica sem o prefixo.
3. Sobreposicao em pos-passo, apenas entre chunks da mesma secao. O
   HybridChunker nao faz sobreposicao por caractere: ele funde e divide. Como
   chunk_overlap e um botao que o operador precisa girar, ela e aplicada depois.
   Sobrepor atraves de uma fronteira de secao reintroduziria a mistura de
   contextos que o chunking estrutural existe para evitar.

Por que o tokenizador e estimado, e nao um tokenizador de verdade
-----------------------------------------------------------------
O HybridChunker exige um tokenizador. Os prontos (HuggingFace, OpenAI) baixam
arquivos de modelo na primeira execucao, e a spec exige parsing SEM chamadas de
rede em tempo de ingestao. BaseTokenizer e apenas um ABC de tres metodos, entao
aqui vai uma implementacao que estima por contagem de caracteres.

A estimativa e DELIBERADAMENTE CONSERVADORA: divide por 3, nao por 4. Um BPE
tipico faz ~3,5 a 4 caracteres por token em portugues; dividir por 3 conta
tokens A MAIS do que a realidade, entao o chunk sai menor que o teto, nunca
maior. Errar para o lado de chunks pequenos e barato; estourar a janela do
modelo de embedding e um erro em tempo de execucao.

Para trocar por um tokenizador exato, pre-baixe-o na imagem e troque a
instancia em ``_montar_chunker``. Nada mais no modulo muda.
"""

import io
import math
import os
import time

import iris
from docling.chunking import HybridChunker
from docling.datamodel.base_models import DocumentStream, InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling_core.transforms.chunker.tokenizer.base import BaseTokenizer
from intersystems_pyprod import (BusinessProcess, IRISLog, IRISProperty, Status)

from messages import ChunkEmbedRequest

iris_package_name = "dc.omniIngest"

# Caracteres por token assumidos na estimativa. Ver docstring do modulo.
CARACTERES_POR_TOKEN = 3

# Separador do caminho de cabecalhos, o mesmo usado na coluna heading_path.
SEPARADOR_CABECALHO = " > "

# O docling 2.55.1 NAO tem formato de texto puro: InputFormat lista DOCX, PPTX,
# HTML, IMAGE, PDF, ASCIIDOC, MD, CSV, XLSX e alguns XML, mas nada de TXT.
# Entregar um .txt ao DocumentConverter levanta
# "ConversionError: File format not allowed".
#
# Como a spec promete .txt e texto puro e Markdown valido, um .txt e apresentado
# ao conversor como se fosse .md -- verificado: o mesmo conteudo que falha como
# .txt converte como MD sem perder nada. E so o nome que muda; o arquivo em
# disco fica intacto.
EXTENSOES_COMO_MARKDOWN = {".txt"}


class TokenizadorEstimado(BaseTokenizer):
    """Conta tokens por estimativa de caracteres, sem baixar modelo nenhum.

    O nome do argumento importa: o HybridChunker chama ``count_tokens(text=...)``
    por palavra-chave. Renomear o parametro quebra o chunker com TypeError.
    """

    max_tokens: int = 448

    def count_tokens(self, text: str) -> int:
        return max(1, math.ceil(len(text or "") / CARACTERES_POR_TOKEN))

    def get_max_tokens(self) -> int:
        return self.max_tokens

    def get_tokenizer(self):
        return self


class ParseChunkProcess(BusinessProcess):
    """Converte um arquivo em chunks e os envia, um a um, para embedding."""

    chunk_size: int = IRISProperty(
        default=512,
        description="Teto de tokens por chunk, incluindo a sobreposicao herdada do chunk anterior.",
        settings="omniIngest")

    chunk_overlap: int = IRISProperty(
        default=64,
        description="Tokens do fim do chunk anterior repetidos no inicio do seguinte, dentro da mesma secao. Zero desliga.",
        settings="omniIngest")

    target_config_name: str = IRISProperty(
        default="EmbeddingBridgeOperation",
        description="Item da Production que gera o embedding e persiste o chunk.",
        settings="omniIngest")

    embedding_timeout: int = IRISProperty(
        default=30,
        description="Segundos de espera pelo embedding de um chunk. Estouro conta como falha daquele chunk, nao do documento.",
        settings="omniIngest")

    def OnRequest(self, request):
        doc_key = getattr(request, "doc_key", "(desconhecido)")
        try:
            tamanho, sobreposicao = self._configuracao_validada()

            documento, formato, duracao_ms = self._parsear(request.work_path)
            IRISLog.Info("dc.omniIngest: '%s' parseado como %s em %d ms." % (doc_key, formato, duracao_ms))

            chunks = self._chunkear(documento, tamanho, sobreposicao)
            IRISLog.Info("dc.omniIngest: '%s' gerou %d chunks (chunk_size=%d, chunk_overlap=%d)."
                         % (doc_key, len(chunks), tamanho, sobreposicao))

            return self._enviar(request, chunks, doc_key)

        except Exception as excecao:
            mensagem = "dc.omniIngest: falha ao processar '%s': %s: %s" % (
                doc_key, type(excecao).__name__, excecao)
            IRISLog.Error(mensagem)
            return Status.ERROR(mensagem)

    # -- configuracao ------------------------------------------------------

    def _configuracao_validada(self):
        tamanho = int(self.chunk_size or 0)
        sobreposicao = int(self.chunk_overlap or 0)

        if tamanho < 1:
            raise ValueError("chunk_size deve ser um inteiro positivo, configurado '%s'." % self.chunk_size)
        if sobreposicao < 0:
            raise ValueError("chunk_overlap nao pode ser negativo, configurado '%s'." % self.chunk_overlap)
        # Sem esta barreira, o teto do chunker seria zero ou negativo e o
        # chunking degeneraria -- cada chunk carregaria so a sobreposicao.
        if sobreposicao >= tamanho:
            raise ValueError(
                "chunk_overlap (%d) deve ser MENOR que chunk_size (%d). Com sobreposicao maior ou "
                "igual ao tamanho, cada chunk seria composto so pela repeticao do anterior. "
                "Ajuste os valores na tela de configuracao da Production." % (sobreposicao, tamanho))
        return tamanho, sobreposicao

    # -- parsing -----------------------------------------------------------

    def _parsear(self, caminho: str):
        if not caminho or not os.path.exists(caminho):
            # O adapter arquiva o arquivo assim que o OnProcessInput do servico
            # retorna. Se o caminho sumiu aqui, o envio deixou de ser sincrono.
            raise FileNotFoundError(
                "caminho '%s' nao existe. O arquivo so e legivel enquanto o FileWatcherService "
                "esta no OnProcessInput -- o envio ao Process precisa ser SendRequestSync." % caminho)

        inicio = time.monotonic()
        resultado = self._conversor().convert(self._origem(caminho))
        duracao_ms = int((time.monotonic() - inicio) * 1000)
        formato = getattr(getattr(resultado, "input", None), "format", None)
        return resultado.document, getattr(formato, "name", str(formato)), duracao_ms

    def _origem(self, caminho: str):
        """O que entregar ao DocumentConverter: o caminho, ou um stream renomeado.

        Formatos que o docling nao reconhece pela extensao, mas cujo conteudo ele
        sabe ler, viajam como DocumentStream com o nome trocado. Nada e escrito
        em disco e o arquivo original nao e tocado.
        """
        extensao = os.path.splitext(caminho)[1].lower()
        if extensao not in EXTENSOES_COMO_MARKDOWN:
            return caminho
        with open(caminho, "rb") as arquivo:
            conteudo = arquivo.read()
        nome = os.path.splitext(os.path.basename(caminho))[0] + ".md"
        return DocumentStream(name=nome, stream=io.BytesIO(conteudo))

    def _conversor(self):
        """DocumentConverter configurado para CPU e sem rede.

        OCR DESLIGADO DE PROPOSITO. O pipeline padrao do Docling liga OCR, e o
        EasyOCR baixa os proprios pesos na primeira conversao de PDF. Numa
        imagem que so pre-baixou layout e tableformer, e com downloads
        desabilitados, isso falha com::

            FileNotFoundError: Missing .../EasyOcr/craft_mlt_25k.pth
            and downloads disabled

        Verificado: com do_ocr ligado, nenhum PDF era parseado. Desligar alinha
        o codigo ao que o desenho ja dizia (OCR de PDF escaneado esta fora de
        escopo) e mantem a exigencia de parsing sem chamadas de rede.

        Consequencia aceita: PDF escaneado (imagem pura) nao rende texto. PDF
        com camada de texto, que e o caso comum, funciona normalmente.

        A estrutura de tabela continua LIGADA -- e dela que depende a promessa
        de nao cortar tabela ao meio.
        """
        conversor = getattr(self, "_conversor_cache", None)
        if conversor is None:
            opcoes_pdf = PdfPipelineOptions()
            opcoes_pdf.do_ocr = False
            opcoes_pdf.do_table_structure = True
            # Construir o DocumentConverter e caro (carrega os modelos de
            # layout), entao ele e criado uma vez por job e reaproveitado.
            conversor = DocumentConverter(
                format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=opcoes_pdf)})
            self._conversor_cache = conversor
        return conversor

    # -- chunking ----------------------------------------------------------

    def _montar_chunker(self, tamanho: int, sobreposicao: int) -> HybridChunker:
        # O teto entregue ao chunker desconta a sobreposicao: o pos-passo vai
        # colar ate `sobreposicao` tokens no inicio de cada chunk, e o total
        # precisa continuar dentro de chunk_size.
        return HybridChunker(tokenizer=TokenizadorEstimado(max_tokens=tamanho - sobreposicao))

    def _chunkear(self, documento, tamanho: int, sobreposicao: int):
        chunker = self._montar_chunker(tamanho, sobreposicao)
        preparados = []

        for chunk in chunker.chunk(dl_doc=documento):
            bruto = (chunk.text or "").strip()
            # Chunk vazio nao vira linha nem consome uma chamada de embedding.
            # O descarte acontece ANTES da numeracao, para que os indices
            # persistidos fiquem contiguos a partir de zero.
            if not bruto:
                continue
            preparados.append({
                "texto": bruto,
                "cabecalhos": self._caminho_cabecalhos(chunk),
                "paginas": self._paginas(chunk),
                "prefixo": self._prefixo_contexto(chunker, chunk),
            })

        self._aplicar_sobreposicao(preparados, sobreposicao)

        for indice, preparado in enumerate(preparados):
            preparado["indice"] = indice
        return preparados

    def _caminho_cabecalhos(self, chunk) -> str:
        cabecalhos = getattr(chunk.meta, "headings", None) or []
        return SEPARADOR_CABECALHO.join(str(c) for c in cabecalhos if c)

    def _paginas(self, chunk) -> str:
        # FORMATO: numeros crescentes separados por virgula, sem espacos, igual
        # ao que a coluna page_numbers espera. Vazio quando o formato de origem
        # nao tem paginas -- Markdown e TXT nao tem, PDF tem.
        paginas = set()
        for item in getattr(chunk.meta, "doc_items", None) or []:
            for proveniencia in getattr(item, "prov", None) or []:
                numero = getattr(proveniencia, "page_no", None)
                if numero is not None:
                    paginas.add(int(numero))
        return ",".join(str(p) for p in sorted(paginas))

    def _prefixo_contexto(self, chunker, chunk) -> str:
        """O que contextualize() poe na frente do texto, isolado.

        O prefixo e extraido em vez de usar o contextualize() inteiro porque a
        sobreposicao e colada depois: e preciso montar
        prefixo + texto_com_sobreposicao, nao contextualizar de novo.
        """
        try:
            contextualizado = chunker.contextualize(chunk)
        except Exception:
            contextualizado = ""
        bruto = chunk.text or ""
        if bruto and contextualizado.endswith(bruto):
            return contextualizado[:len(contextualizado) - len(bruto)]
        cabecalhos = self._caminho_cabecalhos(chunk)
        return (cabecalhos + "\n") if cabecalhos else ""

    def _aplicar_sobreposicao(self, preparados, sobreposicao: int):
        if sobreposicao <= 0 or len(preparados) < 2:
            return
        limite_caracteres = sobreposicao * CARACTERES_POR_TOKEN
        # De tras para frente: cada chunk herda a cauda do anterior ORIGINAL,
        # nao do anterior ja modificado, senao a sobreposicao se acumularia em
        # cascata ao longo do documento.
        for posicao in range(len(preparados) - 1, 0, -1):
            atual, anterior = preparados[posicao], preparados[posicao - 1]
            if atual["cabecalhos"] != anterior["cabecalhos"]:
                continue
            cauda = self._cauda(anterior["texto"], limite_caracteres)
            if cauda:
                atual["texto"] = cauda + "\n" + atual["texto"]

    def _cauda(self, texto: str, limite_caracteres: int) -> str:
        if limite_caracteres <= 0 or not texto:
            return ""
        if len(texto) <= limite_caracteres:
            return texto
        recorte = texto[-limite_caracteres:]
        # Corta na fronteira de palavra para nao herdar meia palavra.
        espaco = recorte.find(" ")
        return recorte[espaco + 1:] if espaco != -1 else recorte

    # -- envio -------------------------------------------------------------

    def _enviar(self, request, chunks, doc_key: str):
        persistidos = 0
        falhos = 0
        tempo_limite = int(self.embedding_timeout or 30)

        for preparado in chunks:
            mensagem = ChunkEmbedRequest(
                doc_key=request.doc_key,
                doc_id=request.doc_id,
                source_file=request.source_file,
                chunk_index=preparado["indice"],
                heading_path=preparado["cabecalhos"],
                page_numbers=preparado["paginas"],
                chunk_text=preparado["texto"],
                embedding_text=preparado["prefixo"] + preparado["texto"])

            try:
                resultado = self.SendRequestSync(self.target_config_name, mensagem, tempo_limite)
                status = resultado[0] if isinstance(resultado, tuple) else resultado
                resposta = resultado[1] if isinstance(resultado, tuple) and len(resultado) > 1 else None

                # SendRequestSync sinaliza falha do alvo por status de retorno,
                # nao por excecao -- inclusive o estouro do tempo limite.
                if not iris.cls("%SYSTEM.Status").IsOK(status):
                    falhos += 1
                    IRISLog.Error("dc.omniIngest: chunk %d de '%s' falhou: %s"
                                  % (preparado["indice"], doc_key,
                                     iris.cls("%SYSTEM.Status").GetErrorText(status)))
                    continue

                if resposta is not None and not int(getattr(resposta, "success", 1) or 0):
                    falhos += 1
                    IRISLog.Error("dc.omniIngest: chunk %d de '%s' falhou: %s"
                                  % (preparado["indice"], doc_key,
                                     getattr(resposta, "error_message", "(sem motivo informado)")))
                    continue

                persistidos += 1

            except Exception as excecao:
                # Falha isolada do chunk: o documento continua.
                falhos += 1
                IRISLog.Error("dc.omniIngest: chunk %d de '%s' falhou: %s: %s"
                              % (preparado["indice"], doc_key, type(excecao).__name__, excecao))

        IRISLog.Info("dc.omniIngest: resumo de '%s' -- %d chunks gerados, %d persistidos, %d falhos."
                     % (doc_key, len(chunks), persistidos, falhos))

        if falhos and not persistidos:
            return Status.ERROR("dc.omniIngest: nenhum chunk de '%s' foi persistido (%d falhas)." % (doc_key, falhos))
        return Status.OK()
