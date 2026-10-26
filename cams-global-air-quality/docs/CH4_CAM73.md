# Metano CAMS73: arquivo examinado e integração

## Origem e interpretação

O exemplo `../exemplo_ch4/cams73_latest_ch4_conc_first_guess_dm_202409.nc` é do
produto ADS [CAMS global inversion-optimised greenhouse gas fluxes and
concentrations](https://ads.atmosphere.copernicus.eu/datasets/cams-global-greenhouse-gas-inversion?tab=overview),
identificador `cams-global-greenhouse-gas-inversion`. Não é o campo
`methane_chemistry` da EAC4 nem a reanálise EGG4. A seleção `first_guess` usa a
simulação a priori; não representa uma estação, um fluxo de emissão ou a solução
posterior da inversão. Veja a [descrição da cadeia de
CH4](https://confluence.ecmwf.int/spaces/CKB/pages/488281456/Description%2Bof%2Bthe%2BCH4%2Binversion%2Bproduction%2Bchain).

| Propriedade local | Valor verificado |
|---|---|
| Formato | NetCDF clássico (CDF-1), atributos CF-1.6 |
| Tamanho | 536.685.448 bytes |
| SHA-256 | `10d4b4f8d20efa3402b6df7f64ce71937db242897ac1b6b9e09bdcb3db1db9d5` |
| Modelo e versão | `TM5-MP 4D-Var`, `v25r1` |
| Campo | `CH4(time=30, level=34, latitude=180, longitude=360)` |
| Grandeza | Fração molar de CH4 em ar seco; `1e-9` mol/mol = ppb |
| Tempo | Cada dia de 2024-09-01 a 2024-09-30, 00 UTC; seleção ADS `daily_mean` |
| Grade | 1°, latitudes −89,5 a 89,5; longitudes −179,5 a 179,5 |
| Níveis | 1 é a camada mais baixa, 34 é a mais alta |

O atributo `cell_methods` do campo registra apenas `area: mean`; a média diária
é identificada pela seleção ADS e pelo sufixo `dm`, que ficam na proveniência.
O arquivo inclui `cell_area`, pressão superficial `ps`, temperatura `T`, umidade
`Q`, altitude, limites das células e coeficientes dos níveis híbridos. O
processamento conserva CH4 e as informações necessárias para localizar os níveis;
o original permanece intacto com todos os campos.

Na camada 1, a média global de setembro ponderada por `cell_area` é 1.898,9 ppb.
Os valores variam de 1.839,3 a 8.083,8 ppb; o máximo foi encontrado em
2024-09-03, −19,5°, −44,5°. A célula mais próxima de São Paulo, −23,5°, −46,5°,
tem média de 2.159,9 ppb no mês. Todos os valores de CH4 decodificados são
finitos e positivos. O máximo acima de 5.000 ppb é registrado como aviso de QC
para avaliação científica, sem recorte automático. A camada 1 não é uma medição
de superfície a altura fixa.

## Recuperar o mesmo tipo de arquivo no ADS

A página [Your requests](https://ads.atmosphere.copernicus.eu/requests?tab=all)
mostra apenas os pedidos da conta autenticada; ela não permite verificar o ID do
pedido original sem acesso a essa conta. No [formulário de
download](https://ads.atmosphere.copernicus.eu/datasets/cams-global-greenhouse-gas-inversion?tab=download),
selecione **Methane**, **Concentration**, **None (first guess)**, **Daily mean**,
**Latest**, **2024** e **September**; aceite a licença, envie o pedido e baixe o
resultado. O formulário e as constraints consultados em 26/10/2026 permitem essa
combinação, tanto com `latest` quanto com `v25r1`. A seleção `latest` poderá mudar
em atualizações futuras. Use `v25r1` para fixar a versão científica; o nome do
arquivo resultante poderá diferir. A igualdade byte a byte só pode ser verificada
comparando checksums após o download.

Pedido equivalente pelo [CDS API](https://ads.atmosphere.copernicus.eu/how-to-api):

```python
import cdsapi

cdsapi.Client().retrieve(
    "cams-global-greenhouse-gas-inversion",
    {
        "variable": ["methane"],
        "quantity": ["concentration"],
        "input_observations": ["first_guess"],
        "time_aggregation": ["daily_mean"],
        "version": ["latest"],
        "year": ["2024"],
        "month": ["09"],
    },
    "ch4_202409_download",
)
```

Se o resultado for compactado, extraia o NetCDF antes da importação local. A
credencial ADS e o aceite da licença são configurados na conta, fora do Git.

## Operar a integração

Na raiz de `cams-global-air-quality`, com o ambiente Python do projeto ativo,
comece consultando o pedido e o espaço previsto:

```bash
camsaq ch4 plan --start 2024-09 --version v25r1
```

Depois escolha **um** dos caminhos. Se você já tem o arquivo local:

```bash
camsaq ch4 import --file ../exemplo_ch4/cams73_latest_ch4_conc_first_guess_dm_202409.nc
```

O arquivo grande em `exemplo_ch4/` não acompanha o clone do GitHub. Se ele não
estiver nessa pasta, informe o caminho do seu próprio NetCDF. Se você precisa
solicitar o arquivo ao ADS, configure antes o token e aceite a licença:

```bash
camsaq ch4 download --start 2024-09 --version v25r1
```

Os dois caminhos validam, processam e indexam. Não registre o mesmo mês e
release pelos dois caminhos sem revisar os lotes: a consolidação recusará meses
duplicados. Para analisar o que já foi preparado:

```bash
camsaq ch4 analyze --version v25r1 --level 1 --output reports/ch4_inversion
```

Os comandos abaixo são úteis para **reconferir** ou **refazer** etapas locais:

```bash
camsaq ch4 validate
camsaq ch4 process
camsaq ch4 consolidate --version v25r1
```

`--level` é obrigatório na análise; não há seleção vertical silenciosa. O comando
gera séries diárias de média espacial e ponto próximo de São Paulo, médias mensais
somente para meses completos, mapas e `analysis.json` com proveniência. O recorte
opcional `--bbox N W S E` limita a média espacial e os mapas. Para uma execução
sem mapas, use `--no-maps`. A versão configurada é `v25r1`; `--version latest`
é opção explícita para o download, mas os derivados são identificados pela
versão `release` presente no arquivo.

Os dois mapas de uma execução usam a mesma escala, definida pelos percentis 2 e
98 do campo do último mês completo (ou do último dia, se nenhum mês estiver
completo). Valores fora dessa faixa aparecem nas cores extremas; os números
originais permanecem nos arquivos e o limite da escala consta em `analysis.json`.

O fluxo usa `metadata/ghg_inversion/downloads.sqlite` e caminhos sob
`data/{raw,processed}/ghg_inversion/`. Isso impede mesclar CH4 de 1°/34 níveis
com EAC4 de 0,75°/60 níveis. Originais, derivados e o arquivo de exemplo são
ignorados pelo Git. Cada mês pode ser analisado isoladamente; lacunas são
registradas e não preenchidas. A média mensal só é publicada quando todos os
dias daquele mês estão presentes.

O [guia completo](../../GUIA_COMPLETO.md#24-metano-ch4-passo-a-passo) explica
cada etapa para iniciantes; a [referência de funções](REFERENCIA_FUNCOES.md)
detalha o uso em Python.

## Verificação da implementação

O arquivo de exemplo foi importado e processado localmente sem alterar o
original. A validação registrou 30 dias, 34 níveis, grade global de 1° e
`release=v25r1`, com aviso para células acima de 5.000 ppb. O derivado NetCDF,
o índice Zarr e os produtos de análise foram gerados em `data/` e
`reports/ch4_inversion/` (diretórios locais ignorados pelo Git). A análise do
derivado retornou 1.898,9137 ppb para a média global de setembro na camada 1,
e 2.159,8999 ppb para a célula mais próxima de São Paulo, em acordo com a
leitura direta do original. O planejamento foi confirmado no catálogo ADS ao
vivo para a combinação de setembro de 2024 e `v25r1`.
