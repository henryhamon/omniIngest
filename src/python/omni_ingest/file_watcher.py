"""Entrada do pipeline: monitora uma pasta e entrega cada arquivo aceito.

O que o EnsLib.File.InboundAdapter realmente entrega (verificado, nao suposto)
======================================================================
Este bloco existe porque as suposicoes iniciais estavam erradas em tres pontos,
e a proxima pessoa nao deveria precisar repetir o experimento. Sonda rodada
contra IRIS 2026.2, depositando o arquivo ``Relatorio Anual 2025.pdf``:

1. ``input`` e um ``iris.%Library.FileCharacterStream`` -- nao um
   %Stream.FileBinary.

2. NAO existe ``input.Attributes``. Acessa-la levanta "Property Attributes not
   found". O que existe e ``GetAttribute(nome)`` / ``GetAttributeList()``, e a
   unica chave preenchida e ``Filename`` -- que repete ``input.Filename``.
   Nenhum atributo carrega o nome original do arquivo.

3. ``WorkPath`` DESTROI o nome original. Com WorkPath configurado,
   ``input.Filename`` vira::

       /data/omniingest/work/Relatorio_Anual_2025.pdf_2026-09-17_19.48.11.114

   Espacos viram sublinhados e um timestamp e anexado. A perda e irreversivel:
   nao da para saber se o original tinha espaco ou sublinhado. Sem WorkPath,
   ``input.Filename`` e o caminho real, intacto::

       /data/omniingest/in/Relatorio Anual 2025.pdf

   Por isso este servico NAO usa WorkPath. O ``doc_key`` -- a identidade do
   documento, pela qual a reingestao substitui a versao anterior -- depende do
   nome original estar correto.

4. O arquivo existe em disco DURANTE o OnProcessInput e e movido para
   ArchivePath depois que ele retorna. Verificado nos dois sentidos: durante,
   ``os.path.exists`` e True e a pasta de entrada ainda lista o arquivo; depois
   do retorno, a entrada esta vazia e o arquivo esta em archive (ai sim com o
   nome mutilado).

   CONSEQUENCIA QUE AMARRA O DESENHO: o parsing tem de acontecer DENTRO do
   OnProcessInput. E por isso que o envio ao Process e SendRequestSync e nao
   SendRequestAsync -- com envio assincrono o Docling receberia um caminho que
   ja nao existe. Nao troque por assincrono sem antes copiar o arquivo.
"""

import hashlib
import os

import iris

from intersystems_pyprod import (BusinessService, IRISLog, IRISParameter,
                                 IRISProperty, Status)

from messages import IngestFileRequest

iris_package_name = "dc.omniIngest"

# Le o arquivo em blocos para calcular o SHA-256: um PDF grande nao precisa
# caber inteiro na memoria so para ser identificado.
BLOCO_LEITURA = 1024 * 1024


class FileWatcherService(BusinessService):
    """Aceita arquivos de uma pasta e os encaminha ao parsing."""

    ADAPTER = IRISParameter("EnsLib.File.InboundAdapter")

    # Extensoes aceitas, separadas por virgula. A comparacao e insensivel a
    # maiusculas e o ponto inicial e opcional ("pdf" e ".PDF" valem o mesmo).
    accepted_extensions: str = IRISProperty(
        default="pdf,docx,pptx,md,txt",
        description="Extensoes aceitas, separadas por virgula. Arquivo fora da lista e recusado sem parsing.",
        settings="omniIngest")

    # Nome do item de configuracao do Process que faz parsing e chunking.
    target_config_name: str = IRISProperty(
        default="ParseChunkProcess",
        description="Item da Production que recebe o arquivo para parsing e chunking.",
        settings="omniIngest")

    def OnProcessInput(self, input):
        caminho = ""
        try:
            # input.Filename e o caminho real na pasta de entrada, valido apenas
            # enquanto este metodo executa (ver nota 4 no docstring do modulo).
            caminho = input.Filename
            nome_original = os.path.basename(caminho)

            if not self._extensao_aceita(nome_original):
                extensao = os.path.splitext(nome_original)[1].lstrip(".").lower() or "(sem extensao)"
                IRISLog.Warning(
                    "dc.omniIngest: arquivo '%s' recusado, extensao '%s' fora da lista aceita '%s'."
                    % (nome_original, extensao, self.accepted_extensions))
                # Status.OK de proposito: o arquivo foi recusado, mas isso nao e
                # falha do servico. Erro aqui faria o adapter tratar o arquivo
                # como problema de entrega e reprocessa-lo.
                return Status.OK()

            doc_id, tamanho = self._hash_e_tamanho(caminho)

            mensagem = IngestFileRequest(
                doc_key=nome_original,
                doc_id=doc_id,
                source_file=caminho,
                # Mesmo caminho: sem WorkPath, o arquivo e legivel onde esta.
                # O campo permanece na mensagem como "caminho que o parsing deve
                # abrir", que e o que o Process precisa saber.
                work_path=caminho,
                size_bytes=tamanho)

            IRISLog.Info("dc.omniIngest: arquivo recebido '%s' (%d bytes, sha256 %s...), encaminhando para '%s'."
                         % (nome_original, tamanho, doc_id[:12], self.target_config_name))

            resultado = self.SendRequestSync(self.target_config_name, mensagem)

            # SendRequestSync devolve STATUS DE ERRO, nao excecao, quando o alvo
            # falha ou nao existe -- verificado: um Process que levanta
            # RuntimeError volta como status ruim e nao entra no except abaixo.
            # Sem esta checagem, a falha do arquivo passaria sem nenhuma linha de
            # log nomeando qual arquivo foi.
            status = resultado[0] if isinstance(resultado, tuple) else resultado
            if not iris.cls("%SYSTEM.Status").IsOK(status):
                IRISLog.Error("dc.omniIngest: arquivo '%s' falhou no processamento: %s"
                              % (nome_original, iris.cls("%SYSTEM.Status").GetErrorText(status)))
            return status

        except Exception as excecao:
            # Isolamento por arquivo: a falha e registrada e devolvida como
            # status, nunca propagada. Propagar derrubaria o job do servico e os
            # arquivos seguintes na pasta nao seriam processados.
            nome = os.path.basename(caminho) if caminho else "(arquivo desconhecido)"
            mensagem_erro = "dc.omniIngest: falha ao processar '%s': %s: %s" % (
                nome, type(excecao).__name__, excecao)
            IRISLog.Error(mensagem_erro)
            return Status.ERROR(mensagem_erro)

    def _extensao_aceita(self, nome_arquivo: str) -> bool:
        extensao = os.path.splitext(nome_arquivo)[1].lstrip(".").lower()
        if not extensao:
            return False
        aceitas = {parte.strip().lstrip(".").lower()
                   for parte in (self.accepted_extensions or "").split(",")
                   if parte.strip()}
        return extensao in aceitas

    def _hash_e_tamanho(self, caminho: str):
        digest = hashlib.sha256()
        tamanho = 0
        with open(caminho, "rb") as arquivo:
            while True:
                bloco = arquivo.read(BLOCO_LEITURA)
                if not bloco:
                    break
                digest.update(bloco)
                tamanho += len(bloco)
        return digest.hexdigest(), tamanho
