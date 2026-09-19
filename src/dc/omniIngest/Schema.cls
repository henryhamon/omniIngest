/// Criacao e validacao da tabela SQL de chunks do dc.omniIngest.
/// 
/// A tabela e criada por DDL parametrizada em vez de uma classe %Persistent
/// fixa porque o nome da tabela e uma configuracao da Production, e uma classe
/// %Persistent tem nome fixo em tempo de compilacao.
/// 
/// Fonte em ASCII por decisao: mensagens de erro atravessam ObjectScript,
/// Embedded Python e o log de eventos, e acentos se corrompem nesse caminho.
Class dc.omniIngest.Schema Extends %RegisteredObject
{

/// Tabela alvo padrao, no formato <schema>.<tabela>.
Parameter DEFAULTTABLE = "dc_omniIngest.DocumentChunk";

/// Dimensao padrao do vetor (text-embedding-3-small / ada-002).
Parameter DEFAULTVECTORLENGTH = 1536;

/// Nome da coluna que guarda o vetor de embedding.
Parameter VECTORCOLUMN = "chunk_vector";

/// Cria a tabela de chunks, ou valida a que ja existe.
/// 
/// Idempotente: se a tabela ja existir com a dimensao de vetor esperada,
/// retorna sucesso sem tocar nos dados. Se existir com outra dimensao,
/// retorna erro nomeando as duas dimensoes e nao altera nada.
ClassMethod Create(pTableName As %String = "", pVectorLength As %Integer = "") As %Status
{
    Set sc = $$$OK
    Try {
        If pTableName = "" Set pTableName = ..#DEFAULTTABLE
        If pVectorLength = "" Set pVectorLength = ..#DEFAULTVECTORLENGTH

        Set sc = ..CheckPrerequisites()
        If $$$ISERR(sc) Quit

        Set sc = ..ValidateTableName(pTableName, .schema, .table)
        If $$$ISERR(sc) Quit

        Set sc = ..ValidateVectorLength(pVectorLength)
        If $$$ISERR(sc) Quit

        Set existing = ..GetVectorDimension(schema, table, .found)
        If found {
            // Tabela ja existe: idempotente se a dimensao bate, erro se nao.
            If existing = pVectorLength Quit
            Set msg = "dc.omniIngest: a tabela "_pTableName_" ja existe com vetor de dimensao "_existing
            Set msg = msg_", mas a dimensao configurada e "_pVectorLength_". Nenhum dado foi alterado."
            Set msg = msg_" Aponte a configuracao para outra tabela ou reingira os documentos numa tabela nova."
            Set sc = $$$ERROR($$$GeneralError, msg)
            Quit
        }

        Set sc = ..RunDDL(pTableName, table, pVectorLength)
    }
    Catch ex {
        Set sc = ex.AsStatus()
    }
    Return sc
}

/// Verifica que esta instancia do IRIS suporta VECTOR e %iFind antes do DDL.
/// 
/// Os nomes de classe sao argumentos para que um teste possa forcar a falha
/// passando uma classe inexistente, sem codigo de teste dentro da rotina.
ClassMethod CheckPrerequisites(pVectorClass As %String = "%Library.Vector", pIFindClass As %String = "%iFind.Index.Basic") As %Status
{
    If '##class(%Dictionary.CompiledClass).%ExistsId(pVectorClass) {
        Set msg = "dc.omniIngest: esta instancia do IRIS nao suporta colunas VECTOR (classe "_pVectorClass
        Set msg = msg_" ausente). Versao encontrada: "_$ZVERSION
        Set msg = msg_". Use uma imagem community 2024.3 ou mais recente."
        Return $$$ERROR($$$GeneralError, msg)
    }
    If '##class(%Dictionary.CompiledClass).%ExistsId(pIFindClass) {
        Set msg = "dc.omniIngest: esta instancia do IRIS nao suporta indices %iFind (classe "_pIFindClass
        Set msg = msg_" ausente), exigidos pela busca hibrida. Versao encontrada: "_$ZVERSION_"."
        Return $$$ERROR($$$GeneralError, msg)
    }
    // Checagem funcional: a classe existir nao garante que a funcao SQL exista.
    Try {
        Set sql = "SELECT VECTOR_COSINE(TO_VECTOR('1,2,3',double,3),TO_VECTOR('1,2,3',double,3)) AS c"
        Set rs = ##class(%SQL.Statement).%ExecDirect(, sql)
        If rs.%SQLCODE < 0 {
            Set msg = "dc.omniIngest: TO_VECTOR/VECTOR_COSINE indisponiveis nesta instancia (SQLCODE "
            Set msg = msg_rs.%SQLCODE_": "_rs.%Message_"). Versao encontrada: "_$ZVERSION_"."
            Return $$$ERROR($$$GeneralError, msg)
        }
    }
    Catch ex {
        Set msg = "dc.omniIngest: falha ao validar suporte a VECTOR nesta instancia: "_ex.DisplayString()
        Return $$$ERROR($$$GeneralError, msg)
    }
    Return $$$OK
}

/// Exige <schema>.<tabela> com identificadores simples.
/// 
/// O nome vem de uma configuracao da Production e e interpolado em DDL, entao
/// e validado em vez de escapado: qualquer coisa fora do formato e recusada.
ClassMethod ValidateTableName(pTableName As %String, Output pSchema As %String, Output pTable As %String) As %Status
{
    Set pSchema = "", pTable = ""
    If $LENGTH(pTableName, ".") '= 2 {
        Set msg = "dc.omniIngest: nome de tabela invalido '"_pTableName_"'."
        Set msg = msg_" Use o formato <schema>.<tabela>, por exemplo "_..#DEFAULTTABLE_"."
        Return $$$ERROR($$$GeneralError, msg)
    }
    Set pSchema = $PIECE(pTableName, ".", 1)
    Set pTable = $PIECE(pTableName, ".", 2)
    For i = 1:1:2 {
        Set part = $SELECT(i = 1:pSchema, 1:pTable)
        If '..IsValidIdentifier(part) {
            Set pSchema = "", pTable = ""
            Set msg = "dc.omniIngest: identificador invalido '"_part_"' em '"_pTableName_"'."
            Set msg = msg_" Use apenas letras, digitos e sublinhado, comecando por letra."
            Return $$$ERROR($$$GeneralError, msg)
        }
    }
    Return $$$OK
}

/// Uma letra seguida de letras, digitos ou sublinhado.
///
/// Escrito com $ASCII em vez de pattern match para nao depender de sintaxe de
/// padrao: esta e a unica barreira entre uma configuracao da Production e o DDL.
ClassMethod IsValidIdentifier(pName As %String) As %Boolean
{
    If $LENGTH(pName) = 0 Return 0
    For i = 1:1:$LENGTH(pName) {
        Set c = $ASCII($EXTRACT(pName, i))
        Set isAlpha = ((c >= 65) && (c <= 90)) || ((c >= 97) && (c <= 122))
        Set isDigit = (c >= 48) && (c <= 57)
        Set isUnderscore = (c = 95)
        If i = 1 {
            If 'isAlpha Return 0
        }
        Else {
            If 'isAlpha, 'isDigit, 'isUnderscore Return 0
        }
    }
    Return 1
}

ClassMethod ValidateVectorLength(pVectorLength As %Integer) As %Status
{
    If '$ISVALIDNUM(pVectorLength) || (pVectorLength '= (pVectorLength \ 1)) || (pVectorLength < 1) {
        Set msg = "dc.omniIngest: a dimensao do vetor deve ser um inteiro positivo, recebido '"_pVectorLength_"'."
        Return $$$ERROR($$$GeneralError, msg)
    }
    Return $$$OK
}

/// Dimensao declarada da coluna de vetor de uma tabela existente.
/// 
/// INFORMATION_SCHEMA.COLUMNS reporta VECTOR como 'varchar' e nao expoe a
/// dimensao, entao ela e lida do parametro LEN da propriedade compilada.
ClassMethod GetVectorDimension(pSchema As %String, pTable As %String, Output pFound As %Boolean) As %Integer
{
    Set pFound = 0
    Set sql = "SELECT CLASSNAME FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ?"
    Set rs = ##class(%SQL.Statement).%ExecDirect(, sql, pSchema, pTable)
    If 'rs.%Next() Return ""
    Set className = rs.%GetData(1)
    If className = "" Return ""
    Set pFound = 1

    Set psql = "SELECT Name FROM %Dictionary.CompiledProperty WHERE parent = ? AND SqlFieldName = ?"
    Set prs = ##class(%SQL.Statement).%ExecDirect(, psql, className, ..#VECTORCOLUMN)
    If 'prs.%Next() Return ""
    Set propName = prs.%GetData(1)

    Set prop = ##class(%Dictionary.CompiledProperty).%OpenId(className_"||"_propName)
    If '$ISOBJECT(prop) Return ""
    Return prop.Parameters.GetAt("LEN")
}

/// Emite o CREATE TABLE e os indices. Chamado so quando a tabela nao existe.
ClassMethod RunDDL(pTableName As %String, pTable As %String, pVectorLength As %Integer) As %Status
{
    // chunk_text e VARCHAR(32000) e nao um tipo curto: chunks nao podem ser
    // truncados, e %iFind.Index.Basic indexa esse tipo diretamente.
    Set ddl = "CREATE TABLE "_pTableName_" ("
    Set ddl = ddl_"id BIGINT IDENTITY PRIMARY KEY, "
    Set ddl = ddl_"doc_key VARCHAR(512) NOT NULL, "
    Set ddl = ddl_"doc_id VARCHAR(64) NOT NULL, "
    Set ddl = ddl_"source_file VARCHAR(1024) NOT NULL, "
    Set ddl = ddl_"chunk_index INTEGER NOT NULL, "
    Set ddl = ddl_"heading_path VARCHAR(2048), "
    Set ddl = ddl_"page_numbers VARCHAR(256), "
    Set ddl = ddl_"chunk_text VARCHAR(32000) NOT NULL, "
    Set ddl = ddl_"chunk_vector VECTOR(DOUBLE, "_pVectorLength_") NOT NULL, "
    Set ddl = ddl_"embedding_config VARCHAR(128) NOT NULL, "
    Set ddl = ddl_"vector_dimension INTEGER NOT NULL, "
    Set ddl = ddl_"created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
    Set sc = ..Exec(ddl)
    If $$$ISERR(sc) Return sc

    Set sc = ..Exec("CREATE INDEX "_..DocKeyIndexName(pTable)_" ON "_pTableName_" (doc_key)")
    If $$$ISERR(sc) Return sc

    // O indice iFind entra ja na criacao: e o que sustenta a busca por
    // palavra-chave do lado hibrido, sem remodelar o schema depois.
    Set idx = "CREATE INDEX "_..IFindIndexName(pTable)_" ON "_pTableName_" (chunk_text) AS %iFind.Index.Basic"
    Return ..Exec(idx)
}

/// Nome do indice iFind sobre chunk_text, usado em %FIND search_index(...).
ClassMethod IFindIndexName(pTable As %String) As %String [ CodeMode = expression ]
{
pTable_"IFindText"
}

ClassMethod DocKeyIndexName(pTable As %String) As %String [ CodeMode = expression ]
{
pTable_"IdxDocKey"
}

ClassMethod Exec(pSql As %String) As %Status
{
    Set rs = ##class(%SQL.Statement).%ExecDirect(, pSql)
    If rs.%SQLCODE < 0 {
        Set msg = "dc.omniIngest: falha ao executar DDL (SQLCODE "_rs.%SQLCODE_"): "_rs.%Message
        Set msg = msg_" | SQL: "_pSql
        Return $$$ERROR($$$GeneralError, msg)
    }
    Return $$$OK
}

}
