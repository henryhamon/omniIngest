/// Passos de inicializacao que rodam depois das classes Python entrarem no IRIS.
///
/// Fonte em ASCII por decisao: ver dc.omniIngest.Schema.
Class dc.omniIngest.Setup Extends %RegisteredObject
{

/// Promove as propriedades de alvo para Ens.DataType.ConfigName.
///
/// POR QUE ISTO EXISTE
/// -------------------
/// O diagrama da tela da Production nao desenha as setas a partir do NOME da
/// propriedade. Ens.Host.GetPropertyConnections gera as conexoes varrendo as
/// propriedades cujo TIPO e Ens.DataType.ConfigName (ou subclasse) -- o nome
/// "TargetConfigNames" das classes de fabrica e so convencao.
///
/// O intersystems_pyprod 0.2.0 nao expoe como declarar um tipo IRIS arbitrario:
/// o parser resolve o tipo por um mapa fixo ({str, int, bool, num}) e cai em
/// %VarString para qualquer outra coisa. Sem este passo, o pipeline funciona,
/// mas a tela mostra tres caixas soltas em vez de servico -> processo ->
/// operacao.
///
/// ATENCAO: recarregar as classes Python com o CLI do pyprod regenera as
/// propriedades como %VarString e desfaz isto. Rode este metodo depois de cada
/// carga -- e o que o iris.script faz.
ClassMethod PromoverAlvosNoDiagrama() As %Status
{
    Set sc = $$$OK
    Set alvos = 2
    Set alvos(1) = $LISTBUILD("dc.omniIngest.FileWatcherService", "TargetConfigName")
    Set alvos(2) = $LISTBUILD("dc.omniIngest.ParseChunkProcess", "TargetConfigName")

    For i = 1:1:alvos {
        Set nomeClasse = $LIST(alvos(i), 1)
        Set nomePropriedade = $LIST(alvos(i), 2)
        Set sc = ..PromoverPropriedade(nomeClasse, nomePropriedade)
        If $$$ISERR(sc) Return sc
    }
    Return sc
}

ClassMethod PromoverPropriedade(pClasse As %String, pPropriedade As %String) As %Status
{
    If '##class(%Dictionary.ClassDefinition).%ExistsId(pClasse) {
        Set msg = "dc.omniIngest: classe '"_pClasse_"' nao existe. Carregue os modulos Python antes deste passo."
        Return $$$ERROR($$$GeneralError, msg)
    }

    Set definicao = ##class(%Dictionary.ClassDefinition).%OpenId(pClasse, , .sc)
    If $$$ISERR(sc) Return sc

    Set encontrada = 0
    For i = 1:1:definicao.Properties.Count() {
        Set propriedade = definicao.Properties.GetAt(i)
        If propriedade.Name = pPropriedade {
            Set encontrada = 1
            // Ja promovida: nada a fazer, o passo e idempotente.
            If propriedade.Type = "Ens.DataType.ConfigName" Return $$$OK
            Set propriedade.Type = "Ens.DataType.ConfigName"
            Quit
        }
    }

    If 'encontrada {
        Set msg = "dc.omniIngest: a classe '"_pClasse_"' nao tem a propriedade '"_pPropriedade_"'."
        Return $$$ERROR($$$GeneralError, msg)
    }

    Set sc = definicao.%Save()
    If $$$ISERR(sc) Return sc
    Return $SYSTEM.OBJ.Compile(pClasse, "ck-d")
}

/// Tudo que o container precisa fazer depois de carregar o codigo.
ClassMethod Inicializar(pTabela As %String = "", pDimensao As %Integer = "") As %Status
{
    Set sc = ##class(dc.omniIngest.Schema).Create(pTabela, pDimensao)
    If $$$ISERR(sc) Return sc
    Return ..PromoverAlvosNoDiagrama()
}

}
