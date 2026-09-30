# EAC4 e operacional: produtos distintos

A coleção operacional investigada é `cams-global-atmospheric-composition-forecasts`.
Seu snapshot tem cobertura de coleção 2015-01-01 até 2026-09-29. Não existe
continuação automática EAC4 → operacional no downloader atual.

| Aspecto | EAC4 | Operacional |
|---|---|---|
| Objetivo | reconstrução histórica consistente | análises e previsões em tempo hábil |
| Grade regular ADS documentada | 0,75° | 0,4° |
| Versão do modelo | CY42R1 | ciclos IFS mudam ao longo do arquivo |
| Vertical | 60 níveis; menor nível 60 | historicamente 60 e depois 137 |
| Tempo | mensal ou 3h na seleção | inicialização, validade e lead time precisam ser definidos |
| Mistura neste projeto | fonte EAC4 | não implementada; namespace reservado |

A documentação ECMWF registra transição para 137 níveis no ciclo 46r1 em julho
de 2019 e melhorias químicas/aerossóis, incluindo nitrato e amônio. Outras trocas
de ciclo modificam física, química, emissões e assimilação. As datas exatas de
transição devem ser verificadas contra o changelog e os metadados do arquivo:
a descrição resumida da coleção e a tabela de implementação nem sempre usam a
mesma data de delimitação.

Não basta recortar o operacional após o fim da EAC4: é necessário escolher análise
ou lead time fixo, evitar múltiplas previsões para a mesma validade, comparar o
período sobreposto, harmonizar unidades, documentar remapeamento de grades, avaliar
quebras e incerteza. Uma curva visualmente contínua pode não ser homogênea.

Uma futura tabela combinada deverá carregar pelo menos `source`, `dataset`,
`ifs_cycle`, `grid_id`, `vertical_definition`, `forecast_reference_time`,
`valid_time`, `leadtime_hour`, `processing_version`, `transition_date`,
`harmonization_method` e os checksums originais. O índice nunca deve substituir
uma versão EAC4 por uma previsão sem essa indicação. Reanálise e operacional
devem também estar disponíveis separadamente para análises de sensibilidade.

Fontes: [coleção oficial](https://ads.atmosphere.copernicus.eu/datasets/cams-global-atmospheric-composition-forecasts),
[documentação operacional](https://confluence.ecmwf.int/pages/viewpage.action?pageId=673323626),
[descrição técnica e grade](https://confluence.ecmwf.int/pages/viewpage.action?pageId=304241849).
