/// Ponte entre o dc.omniIngest e o gateway de embeddings dc.omniEmbedding.
/// 
/// Existe por um motivo especifico: %Vector e um tipo nativo do ObjectScript
/// sem representacao estavel do lado do Embedded Python. Tentar receber o vetor
/// em Python e reconverte-lo e o ponto mais fragil do pipeline -- uma consulta
/// "SELECT <coluna vector>" a partir do Python falha com "Invalid argument
/// type". Entao a conversao acontece aqui, a uma linha de ObjectScript de onde
/// o vetor nasce, e o Python recebe uma string separada por virgulas que o
/// TO_VECTOR() consome.
/// 
/// Fonte em ASCII por decisao: estas mensagens de erro atravessam ObjectScript,
/// Embedded Python e o log de eventos, e acentos se corrompem nesse caminho.
Class dc.omniIngest.Embedder Extends %RegisteredObject
{

/// Classe de embedding esperada quando a %Embedding.Config nao declara uma.
///
/// E a dc.omniEmbedding.Interface, e nao dc.OmniEmbedding: o pacote publicado
/// dc-omni-embedding 1.0.8 nao tem a classe de fachada de nome curto -- ele
/// expoe Interface (que estende %Embedding.Interface) sobre a Engine.
Parameter DEFAULTEMBEDDINGCLASS = "dc.omniEmbedding.Interface";

/// Gera o embedding de um texto e devolve o vetor como CSV.
/// 
/// O provider, o modelo e as credenciais vem da linha de %Embedding.Config
/// nomeada -- nunca de settings da Production, que aparecem em telas e exports.
/// 
/// Lanca excecao com mensagem legivel em qualquer falha; quem chama, do lado
/// da Production, traduz isso em falha isolada daquele chunk.
ClassMethod EmbedToCsv(pText As %String, pConfigName As %String, Output pDimension As %Integer) As %String
{
    Set pDimension = 0

    If $GET(pConfigName) = "" {
        Set msg = "dc.omniIngest: nome da %Embedding.Config nao informado."
        Set msg = msg_" Preencha 'embedding config name' na tela de configuracao da Production."
        Throw ##class(%Exception.General).%New("omniIngestConfig", 5001, , msg)
    }

    Set config = ..OpenConfig(pConfigName, .embeddingClass, .configuration, .declaredLength)

    Set vector = $CLASSMETHOD(embeddingClass, "Embedding", pText, configuration)
    If vector = "" {
        Set msg = "dc.omniIngest: "_embeddingClass_".Embedding() retornou vazio para a config '"_pConfigName_"'."
        Throw ##class(%Exception.General).%New("omniIngestEmbed", 5001, , msg)
    }

    Set count = $VECTOROP("count", vector)
    If count < 1 {
        Set msg = "dc.omniIngest: vetor vazio devolvido por "_embeddingClass_" para a config '"_pConfigName_"'."
        Throw ##class(%Exception.General).%New("omniIngestEmbed", 5001, , msg)
    }

    // A dimensao declarada na %Embedding.Config e a fonte da verdade sobre o
    // modelo; divergencia aqui significa config apontando para outro modelo.
    If (declaredLength > 0) && (count '= declaredLength) {
        Set msg = "dc.omniIngest: a config '"_pConfigName_"' declara VectorLength "_declaredLength
        Set msg = msg_" mas o provider devolveu um vetor de dimensao "_count_"."
        Throw ##class(%Exception.General).%New("omniIngestDimension", 5001, , msg)
    }

    Set csv = ""
    For i = 1:1:count {
        Set csv = csv_$SELECT(i = 1:"", 1:",")_$Vector(vector, i)
    }
    Set pDimension = count
    Return csv
}

/// Abre a %Embedding.Config e devolve, por referencia, o que ela define.
/// 
/// O despacho e feito pela EmbeddingClass declarada na propria config, e nao
/// por um nome fixo no codigo: e assim que %Embedding.Config funciona, e e o
/// que permite trocar de gateway sem recompilar. A classe e validada antes.
ClassMethod OpenConfig(pConfigName As %String, Output pEmbeddingClass As %String, Output pConfiguration As %String, Output pDeclaredLength As %Integer) As %String
{
    Set pEmbeddingClass = "", pConfiguration = "", pDeclaredLength = 0

    Set sql = "SELECT EmbeddingClass, Configuration, VectorLength FROM %Embedding.Config WHERE Name = ?"
    Set rs = ##class(%SQL.Statement).%ExecDirect(, sql, pConfigName)
    If 'rs.%Next() {
        Set msg = "dc.omniIngest: nao existe %Embedding.Config chamada '"_pConfigName_"' neste namespace."
        Set msg = msg_" Crie a configuracao do provider antes de iniciar a Production (ver README)."
        Throw ##class(%Exception.General).%New("omniIngestConfig", 5001, , msg)
    }
    Set pEmbeddingClass = rs.%GetData(1)
    Set pConfiguration = rs.%GetData(2)
    Set pDeclaredLength = +rs.%GetData(3)

    If pEmbeddingClass = "" Set pEmbeddingClass = ..#DEFAULTEMBEDDINGCLASS

    If '##class(%Dictionary.CompiledClass).%ExistsId(pEmbeddingClass) {
        Set msg = "dc.omniIngest: a %Embedding.Config '"_pConfigName_"' aponta para a classe '"_pEmbeddingClass
        Set msg = msg_"', que nao existe neste namespace. Instale o pacote dc-omni-embedding (ver README)."
        Throw ##class(%Exception.General).%New("omniIngestConfig", 5001, , msg)
    }

    If '$$$comMemberDefined(pEmbeddingClass, $$$cCLASSmethod, "Embedding") {
        Set msg = "dc.omniIngest: a classe '"_pEmbeddingClass_"' nao expoe o metodo Embedding(texto, configuracao)."
        Set msg = msg_" Ela nao serve como EmbeddingClass da config '"_pConfigName_"'."
        Throw ##class(%Exception.General).%New("omniIngestConfig", 5001, , msg)
    }

    Return pConfigName
}

/// Dimensao declarada por uma %Embedding.Config, ou 0 se ela nao existir.
/// 
/// Usado na inicializacao para conferir a config contra a coluna da tabela
/// antes de processar o primeiro chunk.
ClassMethod DeclaredDimension(pConfigName As %String) As %Integer
{
    Set sql = "SELECT VectorLength FROM %Embedding.Config WHERE Name = ?"
    Set rs = ##class(%SQL.Statement).%ExecDirect(, sql, pConfigName)
    If 'rs.%Next() Return 0
    Return +rs.%GetData(1)
}

}
