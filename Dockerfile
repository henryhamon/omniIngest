# dc.omniIngest - gateway de ingestão/parsing de documentos para o InterSystems IRIS
#
# A tag é fixa e não "latest-cd": o schema de chunks depende de VECTOR/TO_VECTOR
# e de %iFind, e uma tag móvel pode trocar a versão do IRIS entre dois builds.
ARG IMAGE=intersystems/iris-community:2026.2
FROM $IMAGE

WORKDIR /home/irisowner/dev

ARG TESTS=0
ARG MODULE="dc-omniIngest"
ARG NAMESPACE="IRISAPP"

## Embedded Python environment
ENV IRISUSERNAME "_SYSTEM"
ENV IRISPASSWORD "SYS"
ENV IRISNAMESPACE $NAMESPACE
ENV PYTHON_PATH=/usr/irissys/bin/
ENV PATH "/usr/irissys/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/home/irisowner/bin"

## Modelos do Docling: resolvidos localmente em runtime, sem acesso à rede.
ENV DOCLING_ARTIFACTS_PATH=/home/irisowner/.cache/docling/models

COPY .iris_init /home/irisowner/.iris_init
RUN wget https://pm.community.intersystems.com/packages/zpm/latest/installer -O /tmp/zpm.xml

USER root
RUN mkdir -p /data/IRISAPP_DATA/ /data/IRISAPP_DATA/irisapp_dataenstemp /data/IRISAPP_DATA/irisapp_datasecondary && \
    chown irisowner:irisowner /data/ -R
USER ${ISC_PACKAGE_MGRUSER}

## ---------------------------------------------------------------------------
## Dependências do Embedded Python
##
## /usr/irissys/mgr/python é o ÚNICO site-packages que o Embedded Python do IRIS
## enxerga; um "pip install" comum não seria visto de dentro do IRIS.
##
## O torch CPU-only vem pinado com sufixo +cpu no requirements.txt: em aarch64
## o torch do PyPI arrasta os wheels CUDA da NVIDIA, que esta imagem nao usa.
## Ver o comentario no proprio requirements.txt.
##
## Camada própria, ANTES do código-fonte, para que alterar um .py não refaça
## a instalação.
## ---------------------------------------------------------------------------
COPY requirements.txt /tmp/requirements.txt
RUN pip3 install --no-cache-dir \
        --target /usr/irissys/mgr/python \
        -r /tmp/requirements.txt

## ---------------------------------------------------------------------------
## Modelos de layout/tabela do Docling, pré-baixados para dentro da imagem.
##
## Sem este passo a PRIMEIRA conversão baixaria os modelos sob demanda: lenta e
## dependente de rede, o que viola o requisito de parsing sem chamadas externas.
## Camada separada da anterior e também anterior ao código-fonte.
## ---------------------------------------------------------------------------
RUN PYTHONPATH=/usr/irissys/mgr/python \
    python3 /usr/irissys/mgr/python/bin/docling-tools models download \
        --output-dir ${DOCLING_ARTIFACTS_PATH} layout tableformer

## ---------------------------------------------------------------------------
## Pastas de ingestao.
##
## Este passo fica DEPOIS das camadas de pip e de modelos de proposito: posto
## antes, qualquer mudanca aqui invalidaria as duas e o build refaria o download
## do torch e dos modelos do Docling.
##
## As pastas ficam fora de /home/irisowner/dev porque aquele volume e codigo,
## nao area de dados. Nao existe pasta "work": o adapter roda sem WorkPath,
## que mutila o nome do arquivo -- e o nome original e a identidade do
## documento (ver design D6).
## ---------------------------------------------------------------------------
USER root
RUN mkdir -p /data/omniingest/in /data/omniingest/archive && \
    chown irisowner:irisowner /data/omniingest -R
USER ${ISC_PACKAGE_MGRUSER}

## O container sobe PRONTO: codigo ObjectScript, classes Python, tabela de
## chunks e Production ja existem quando o IRIS termina de iniciar.
##
## A ordem importa e nao e arbitraria:
##   1. iris.script       -> zpm carrega as classes ObjectScript (Schema,
##                           Embedder, Setup) e resolve a dependencia
##                           dc-omni-embedding;
##   2. intersystems_pyprod -> carrega os modulos Python, um por vez e em ordem
##                           de dependencia. O CLI roda sob irispython, nao
##                           python3: com o interpretador comum ele falha com
##                           "No module named 'iris'";
##   3. Setup.Inicializar -> cria a tabela de chunks e promove as propriedades
##                           de alvo para Ens.DataType.ConfigName, o que so faz
##                           sentido depois que as classes Python existem.
##
## O passo 3 tem de vir DEPOIS do 2 e ser refeito a cada recarga do pyprod, que
## regenera as propriedades como %VarString.
RUN --mount=type=bind,src=.,dst=. \
    iris start IRIS && \
    iris merge iris ./merge.cpf && \
	iris session IRIS < iris.script && \
    /usr/irissys/bin/irispython /usr/irissys/mgr/python/bin/intersystems_pyprod ./src/python/omni_ingest/messages.py && \
    /usr/irissys/bin/irispython /usr/irissys/mgr/python/bin/intersystems_pyprod ./src/python/omni_ingest/file_watcher.py && \
    /usr/irissys/bin/irispython /usr/irissys/mgr/python/bin/intersystems_pyprod ./src/python/omni_ingest/parse_chunk.py && \
    /usr/irissys/bin/irispython /usr/irissys/mgr/python/bin/intersystems_pyprod ./src/python/omni_ingest/embedding_bridge.py && \
    /usr/irissys/bin/irispython /usr/irissys/mgr/python/bin/intersystems_pyprod ./src/python/omni_ingest/production.py && \
    iris session iris -U $NAMESPACE "##class(dc.omniIngest.Setup).Inicializar()" && \
    ([ $TESTS -eq 0 ] || iris session iris -U $NAMESPACE "##class(%ZPM.PackageManager).Shell(\"test $MODULE -v -only\",1,1)") && \
    iris stop IRIS quietly
