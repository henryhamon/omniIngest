/// Duble de teste que imita o contrato de EmbeddingClass do %Embedding.Config.
/// 
/// Serve para exercitar a conversao %Vector -> CSV do dc.omniIngest.Embedder
/// sem chamar um provider real: a chamada HTTP e responsabilidade do
/// dc.omniEmbedding e esta explicitamente fora do escopo deste pacote.
/// 
/// O vetor e derivado do texto, entao textos diferentes geram vetores
/// diferentes e a similaridade de cosseno tem o que ordenar.
Class tests.dc.omniIngest.unittests.FakeEmbedding Extends %RegisteredObject
{

ClassMethod Embedding(input As %String, configuration As %String) As %Vector
{
    Set config = {}
    Try { Set config = {}.%FromJSON(configuration) } Catch { }
    Set dim = +config.vectorLength
    If dim < 1 Set dim = 8

    Set seed = 0
    For i = 1:1:$LENGTH(input) { Set seed = seed + $ASCII($EXTRACT(input, i)) }

    Set vec = ""
    For i = 1:1:dim {
        Set $Vector(vec, i, "double") = ((seed + i) # 97) / 97
    }
    Return vec
}

}
