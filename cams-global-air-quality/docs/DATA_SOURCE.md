# Fonte e interpretação científica

## Produtos consultados

Consulta direta em 29/09/2026 (UTC), com JSON original preservado em `evidence/`:

| Produto | Identificador ADS | Intervalo do catálogo nesta consulta | Resolução |
|---|---|---|---|
| EAC4 mensal | `cams-global-reanalysis-eac4-monthly` | 2003-01–2025-12 | mensal, 0,75° |
| EAC4 subdiária | `cams-global-reanalysis-eac4` | 2003-01-01–2025-12-31 | 3 horas para a seleção, 0,75° |
| CAMS operacional | `cams-global-atmospheric-composition-forecasts` | 2015-01-01–2026-09-29 | dependente de ciclo, produto, nível e lead time; grade ADS documentada 0,4° |

Esses são os três produtos relevantes investigados, não uma listagem exaustiva de
todos os datasets CAMS. O intervalo operacional de coleção não garante a mesma
cobertura para todas as variáveis. Os limites EAC4 foram cruzados com os formulários
e as combinações permitidas nas constraints de cada poluente/nível. Uma entrada no
catálogo confirma disponibilidade anunciada; só uma recuperação + QC confirma um
arquivo realmente utilizável. Não foi possível essa segunda confirmação sem chave.

## O que é estimado

O CAMS é o serviço Copernicus dedicado à composição atmosférica. A ECMWF produz a
EAC4 usando o sistema IFS CY42R1 e assimilação 4D-Var para combinar informações de
observações com uma representação física/química da atmosfera. O resultado é uma
estimativa em células e níveis do modelo, não uma rede de observações pontuais.
A documentação descreve 60 níveis híbridos; o nível mais baixo é o 60.
A seleção neste projeto usa o campo de superfície para particulados e o nível
mais baixo para os quatro gases. Não se usam colunas totais ou 1000 hPa como
substitutos de concentrações próximas à superfície.

A grade regular disponibilizada pelo ADS tem 0,75° e é preservada. Ela já é uma
representação do modelo disponibilizada pelo provedor: "não reinterpolar" aqui
significa não adicionar uma nova transformação. Não significa recuperar a grade
nativa espectral/reduzida do IFS.

## Tempo e unidades

O produto A é a média mensal integral (`monthly_mean`), não uma climatologia de
uma hora sinótica. O produto B é amostrado de 3 em 3 horas para os poluentes
selecionados. Não se infere essa frequência para qualquer outra variável futura:
campos acumulados e meteorológicos podem exigir semântica distinta.

As unidades são verificadas no payload: PM2.5/PM10 em kg m⁻³ e gases em kg kg⁻¹.
A conversão de PM para µg m⁻³ multiplica por 10⁹. Para gases, a conversão volumétrica
não é aplicada. Se feita futuramente, deve usar densidade collocada e a mesma base
mássica. Para médias mensais, E[qρ] ≠ E[q] E[ρ] em geral; o termo de covariância
não pode ser reconstruído a partir das duas médias.

A atribuição e licença do catálogo devem acompanhar qualquer redistribuição.
A consulta atual informa CC-BY-4.0. Verifique os termos atuais antes do uso e cite
o dataset, a data de acesso e o artigo de referência. DOIs dos produtos:
EAC4: `10.24381/d58bbf47`; mensal: `10.24381/fd75fff2` (confirmar também nos JSON).

## Limitações para séries temporais e epidemiologia

Mesmo com uma versão fixa do modelo, mudanças nas observações assimiladas,
inventários de emissão e qualidade da informação podem produzir descontinuidades.
Consistência de formato não demonstra homogeneidade estatística perfeita.
Antes de interpretar tendências, avalie sazonalidade, autocorrelação, quebras e
validação externa. As inclinações OLS aqui são descritivas e não recebem p-valores
que pressuporiam erros independentes.

Uma média global por área não mede exposição humana ponderada pela população.
Uma célula de 0,75° não reproduz gradientes de rua, tráfego ou microambientes.
Model level 60 não é sinônimo de um instrumento a 2 m. Médias mensais não permitem
reconstruir máximas diárias ou médias móveis de 8 horas para comparação regulatória.
Associe dados individuais/municipais apenas após definir escala, população,
janela de exposição e validação com estações independentes. Não derive relações
causais diretamente dos mapas descritivos.

## Fontes oficiais e referência científica

- [EAC4 mensal: catálogo e formulário](https://ads.atmosphere.copernicus.eu/datasets/cams-global-reanalysis-eac4-monthly)
- [EAC4 subdiária](https://ads.atmosphere.copernicus.eu/datasets/cams-global-reanalysis-eac4)
- [CAMS Reanalysis — ECMWF](https://www.ecmwf.int/en/research/climate-reanalysis/cams-reanalysis)
- [Documentação de reanálise](https://confluence.ecmwf.int/display/CKB/CAMS%3A+Reanalysis+data+documentation)
- [CAMS operacional](https://ads.atmosphere.copernicus.eu/datasets/cams-global-atmospheric-composition-forecasts)
- [API ADS](https://ads.atmosphere.copernicus.eu/how-to-api)
- [Cliente oficial avançado](https://ecmwf.github.io/ecmwf-datastores-client/)
- Inness et al. (2019), [The CAMS reanalysis of atmospheric composition](https://doi.org/10.5194/acp-19-3515-2019).

Os snapshots têm maior valor de auditoria para esta execução do que copiar um ano
final para o código. O programa refaz a consulta para qualquer novo download.
