# O3, CH4 e formaldeído no CAMS

**Atualização sobre CH4 CAMS73:** o projeto agora possui um fluxo próprio para o
arquivo de metano da inversão de gases de efeito estufa. Use `camsaq ch4` e o
[guia do arquivo](../docs/CH4_CAM73.md). O texto abaixo descreve as opções de
variáveis **EAC4** e **EGG4** examinadas para os notebooks; esses produtos não
são intercambiáveis com CAMS73. Os notebooks 01–03 continuam restritos à EAC4.

Fontes oficiais consultadas nesta atualização:
- https://ads.atmosphere.copernicus.eu/datasets/cams-global-reanalysis-eac4-monthly?tab=overview
- https://confluence.ecmwf.int/spaces/CKB/pages/83395896/CAMS+Reanalysis+data+documentation
- https://ads.atmosphere.copernicus.eu/datasets/cams-global-ghg-reanalysis-egg4-monthly?tab=overview

A EAC4 mensal lista Ozone, Methane (chemistry) e Formaldehyde em kg/kg.
A documentação identifica os nomes ADS `ozone`, `methane_chemistry` e
`formaldehyde`. Para os campos mensais em níveis de modelo, a documentação
identifica o nível 60; não confundir com uma medida em altura fixa de estação.
Total column é outra variável, em kg/m², e não equivale à concentração perto do solo.

O3 já consta do registro EAC4 original do projeto. `methane_chemistry` e HCHO
não estão ativos nesse registro de seis poluentes. Os notebooks EAC4 poderão
reconhecer seus arquivos quando forem cadastrados, baixados, validados e
processados **como EAC4**. Essa atualização dos notebooks não os baixa nem
altera o registro; a integração CAMS73 usa outros comandos e outros arquivos.
Antes de ampliar o downloader, valide os nomes e níveis no formulário vivo e nas
restrições do ADS e execute pilotos reais para cada variável.

Para investigar o metano como gás de efeito estufa, avalie também EGG4, produto
específico para CH4/CO2. A página consultada indica 2003–2020 e oferece methane
em kg/kg e CH4 column-mean molar fraction em ppb. A coluna média é distinta de
um valor próximo à superfície. EAC4 methane_chemistry e EGG4 methane não devem
ser misturados ou tratados como produtos intercambiáveis. A integração EGG4
precisa de fonte separada no pipeline; os novos notebooks filtram EAC4.

## Concentração em massa por volume

kg/kg é razão de mistura em massa, não µg/m³. Para uma razão definida por massa
do ar úmido, w = massa do gás / massa do ar:

    concentração_ug_m3 = w_kg_kg * densidade_ar_kg_m3 * 1e9

A densidade do ar deve corresponder ao mesmo local, instante e nível. Sob a
aproximação de gás ideal para ar úmido:

    densidade_ar = p / (Rd * Tv)

Tv é temperatura virtual, derivada de temperatura e umidade específica. Se a
razão estiver definida em relação ao ar seco, use a densidade de ar seco. Não
substitua pressão de superfície e temperatura a 2 m automaticamente pelos
campos do nível de modelo 60. Para ppm/ppb, a conversão é molar e também exige
convenção explícita de ar seco/úmido e massas molares.

Além disso, média(w * densidade) não é em geral igual a
média(w) * média(densidade). Para médias mensais de concentração com rigor,
converta campos subdiários compatíveis antes de agregar. Esta atualização conserva
as unidades originais dos gases e não implementa aproximações silenciosas.
