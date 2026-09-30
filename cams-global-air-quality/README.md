# CAMS Global Air Quality Historical Database

Infraestrutura científica Python para um arquivo global incremental da reanálise
CAMS EAC4: ADS → originais GRIB/ZIP → QC → NetCDF4 → Zarr anual → extração,
estatísticas, mapas e atualização.

**Estado da entrega (30/09/2026):** código implementado e testado localmente;
catálogo, formulários e restrições reais consultados. Cobertura confirmada pelo
catálogo/constraints: **2003-01 a 2025-12**, 276 meses por variável.
A tentativa mínima autenticada foi bloqueada **antes de submeter o job** por
falta de API key. **Nenhum dado observacional/reanalisado foi baixado.** Não há
mapas ou resultados científicos CAMS prontos; os testes usam fixtures sintéticas.
O pipeline precisa passar pelos pilotos reais abaixo antes de ser considerado
validado em produção. Veja [relatório da primeira fase](reports/PHASE1_REPORT.md).

## Instalação no Ubuntu/Linux

Python 3.11 ou 3.12; Python 3.12 foi usado nos testes. Extraia o ZIP e entre no diretório:

```bash
cd cams-global-air-quality
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -e '.[dev,notebooks]'
pytest -q
camsaq --help
```

Os derivados são NetCDF4/HDF5 escritos por `h5netcdf` e interoperáveis com
`netCDF4`; tabelas Parquet usam `fastparquet`. Mapas Cartopy são renderizados em
um processo isolado, com confirmação de encerramento normal antes da publicação
do PNG. Essas decisões foram verificadas na suíte integrada.

Se você clonou o repositório `cams`, entre no diretório do pacote antes de instalar
ou executar os comandos deste guia:

```bash
cd cams/cams-global-air-quality
```

`requirements-lock.txt` fixa o fechamento das dependências usadas na execução,
para Python 3.12/Linux. Para repetir esse ambiente:

```bash
pip install -r requirements-lock.txt
pip install --no-deps -e .
```

Algumas plataformas precisam da biblioteca nativa ecCodes; consulte as instruções
da distribuição se as wheels não a fornecerem. Não use este ambiente globalmente;
crie um venv separado. Os arquivos de configuração ficam na raiz do checkout:
execute os exemplos a partir dele ou passe `--config /caminho/config/config.yaml`.

## Autenticação ADS — apenas na sua máquina

1. Crie/acesse sua conta no [ADS](https://ads.atmosphere.copernicus.eu/).
2. Aceite os termos de uso dos produtos mensal e subdiário nas páginas dos datasets.
3. Consulte [as instruções atuais](https://ads.atmosphere.copernicus.eu/how-to-api)
   e copie seu **Personal Access Token**, sem o antigo prefixo `UID:`.
4. O downloader usa o cliente oficial avançado `ecmwf-datastores-client` 0.5.3
   para persistir/reabrir jobs. Configure **`~/.ecmwfdatastoresrc`**:

```yaml
url: https://ads.atmosphere.copernicus.eu/api
key: <SEU_PERSONAL_ACCESS_TOKEN>
```

```bash
chmod 600 ~/.ecmwfdatastoresrc
```

Se você já configurou `~/.cdsapirc` para `cdsapi`, o mesmo arquivo pode ser indicado
explicitamente ao cliente avançado:

```bash
export ECMWF_DATASTORES_RC_FILE="$HOME/.cdsapirc"
```

O cliente também aceita `ECMWF_DATASTORES_KEY` por variável de ambiente. Não
coloque chaves no YAML do projeto, Git, notebooks ou mensagens. Nenhuma chave é
necessária para o catálogo público. O SDK avançado é classificado como
*incubating* pela ECMWF; sua versão está fixada e a integração isolada no downloader.

## Primeira execução real

```bash
camsaq inventory
camsaq plan --kind monthly
# Um mês global de PM2.5: download → QC → NetCDF, sem download em massa.
camsaq smoke --start 2003-01 --end 2003-01 --pollutants pm25
# Confirma também a representação vertical dos gases.
camsaq smoke --start 2003-01 --end 2003-01 --pollutants co
camsaq validate
# Os pilotos têm de passar antes de iniciar a série completa.
camsaq download-monthly
camsaq inventory
camsaq validate
```

`download-monthly` executa pilotos por tipo vertical antes dos lotes restantes.
Falha de um piloto interrompe o avanço. Arquivos bons existentes são reutilizados.
O plano mensal completo pede 1.656 arquivos originais, cerca de **0,714 GiB** de
valores float32 sem compressão (seis campos × 276 meses × 241 × 480). Reserve ao
menos **2,86 GiB + 2 GiB de margem**, além de possíveis gerações antigas de Zarr.
GRIB, ZIP, índices, filesystem e compressão alteram o tamanho efetivo.

O produto mensal solicitado é `product_type: monthly_mean`, e **não**
`monthly_mean_by_hour_of_day`. `time: [00:00]` é o valor de controle do pedido
mensal; não significa usar somente as concentrações observadas às 00 UTC.
As requests usam `data_format: grib`; a opção `netcdf_zip` é suportada. Não usamos
o antigo argumento `format: netcdf`. O formulário e as constraints atuais são
checados antes da construção dos pedidos. Uma mudança incompatível causa erro.

## Variáveis e decisão vertical

| Nome | Variável exata ADS | Representação | Original | Processada |
|---|---|---|---|---|
| pm25 | `particulate_matter_2.5um` | superfície | kg m⁻³ | µg m⁻³ |
| pm10 | `particulate_matter_10um` | superfície | kg m⁻³ | µg m⁻³ |
| co | `carbon_monoxide` | model level 60 | kg kg⁻¹ | kg kg⁻¹ |
| no2 | `nitrogen_dioxide` | model level 60 | kg kg⁻¹ | kg kg⁻¹ |
| so2 | `sulphur_dioxide` | model level 60 | kg kg⁻¹ | kg kg⁻¹ |
| o3 | `ozone` | model level 60 | kg kg⁻¹ | kg kg⁻¹ |

A EAC4 tem 60 níveis híbridos; o nível 60 é o mais baixo, não uma altitude fixa de
2 m e não o nível 137 do operacional moderno. A grade ADS é 0,75° × 0,75°; não
pedimos `grid`, não interpolamos e não confundimos grade ADS com a grade nativa
reduzida do modelo. Coordenadas e metadados GRIB de forma da Terra são preservados;
não se declara EPSG:4326 como datum garantido para o modelo esférico.

## Atualização e retomada

```bash
python -m cams_air_quality update
camsaq download-monthly --retry-failed
camsaq process
camsaq consolidate
```

A atualização consulta catálogo e constraints **ao vivo**, enumera todos os meses
válidos para cada variável/nível e compara as chaves das requests com o manifesto.
Também preenche lacunas antigas, não apenas meses posteriores ao último arquivo.
`start_date` e `end_date` nulos seguem a cobertura do catálogo; datas explícitas
são limites de seleção. Não há último ano fixado no código. Meses subdiários
incompletos não são tratados como meses completos.

O manifesto SQLite é criado automaticamente em `metadata/downloads.sqlite`.
Estados: requested → downloading → downloaded → validated → processed; `failed`
registra falhas de aquisição/QC. Erros de processamento não invalidam um original
bom. A tabela `events` mantém o histórico de transições.

Jobs remotos persistem pelo ID. Downloads parciais usam HTTP Range quando o
servidor e a identidade do asset permitem; URLs novas/expiradas ou ausência de
Range podem exigir reiniciar **aquele arquivo**. Os demais lotes permanecem.
Interrupção entre submissão e gravação do ID pode deixar um job órfão no ADS; não
se promete exatamente uma submissão em qualquer falha possível.

## Subdiários: planeje o disco antes

```bash
camsaq plan --kind subdaily
camsaq smoke --kind subdaily --start 2003-01 --end 2003-01 --pollutants pm25
camsaq download-subdaily --start 2003-01 --end 2003-12 --max-batches 12
# Em máquina com capacidade adequada:
camsaq download-subdaily
camsaq consolidate --kind subdaily
```

Para 2003–2025: 67.208 instantes (8/dia), 403.248 campos para seis variáveis,
**1.656 lotes**, **173,78 GiB** de valores float32, sem compressão. A política
conservadora de quatro cópias resulta em **695,11 GiB + margem**. Não é uma
medição do volume de transferência nem orçamento monetário. O processamento
requere um chunk por vez; o tempo depende de filas, tape, rede, compressão e CPU.
`plan` e o downloader estimam a seleção atual e recusam lotes sem reserva de disco.
`--max-batches` permite avanço por etapas sem criar pedidos gigantescos.

## Análise, séries e mapas

Depois da base mensal real estar processada e consolidada:

```bash
camsaq extract-point --pollutant pm25 --lat -23.5505 --lon -46.6333 \
  --output reports/sao_paulo_pm25.parquet
camsaq extract-region --pollutant no2 --bbox -20 -50 -26 -43 \
  --output reports/sudeste_no2.csv
camsaq map --pollutant pm25 --date 2020-07 --output reports/pm25_2020_07.png
camsaq analyze --baseline-start 2003-01 --baseline-end 2022-12
```

O período climatológico acima é uma escolha explícita de exemplo; ele pode ser
alterado. Séries globais são ponderadas por área esférica, anuais por dias do mês
(somente anos completos). Bbox seleciona centros de células, não frações de polígonos.
São Paulo usa a célula esfericamente mais próxima, com coordenadas/distância
registradas; **não é uma estação de monitoramento**. CSV/Parquet recebem sidecar
JSON com unidades e metadados. `--coastlines` pode baixar o pequeno recurso
Natural Earth do Cartopy; por padrão os mapas não fazem esse acesso adicional.

Exemplo de Python:

```python
from cams_air_quality.config import load_config
from cams_air_quality.processing import open_database
from cams_air_quality.extraction import get_timeseries, subset_bbox
from cams_air_quality.statistics import summaries, climatology

cfg = load_config()
sp = get_timeseries(cfg, pollutant="pm25", lat=-23.5505, lon=-46.6333)
with open_database(cfg) as ds:
    regional = subset_bbox(ds, north=-20, west=-50, south=-26, east=-43)
    products = summaries(regional.pm25)
    climate = climatology(ds.pm25, "2003-01", "2022-12")
    # Compute/save products while the lazy dataset remains open.
    climate.to_netcdf("reports/pm25_climatology.nc", engine=cfg["netcdf_engine"])
```

## Estrutura e limites desta fase

- `src/cams_air_quality/`: catálogo, requests, manifesto, downloader, QC, unidades,
  processamento, extração, estatísticas, mapas, análise e CLI.
- `config/`: variáveis centralizadas, diretórios, datas, chunks, retry, concorrência.
- `evidence/`: respostas oficiais preservadas para auditoria; não substituem
  consulta ao vivo em downloads. `inventory/plan --offline-evidence evidence`
  serve exclusivamente à reprodução do diagnóstico histórico.
- `tests/`: sem autenticação e sem grandes downloads; GRIB sintético com ecCodes,
  NetCDF, ZIP, Zarr, HTTP mockado, mudanças no catálogo e falhas simuladas.
- `notebooks/`: inventário, climatologia/mapas e extração de São Paulo.
- `docs/`: fontes, decisões científicas, esquema e operação.
- `reports/`: resultados verificáveis desta primeira fase.
- `data/`, `logs/`, credenciais, arquivos temporários e banco de controle não entram no Git.

O operacional é **somente inventariado/documentado** nesta versão. A API pública,
PostGIS, dashboard e serviço de agendamento não estão implementados; os módulos
foram separados para permitir essas extensões. O código não concatena produtos
heterogêneos. Adicionar um poluente requer confirmar disponibilidade **em cada
produto**, nível, aliases e unidade: não basta inventar uma entrada YAML.

Consulte [fonte científica](docs/DATA_SOURCE.md), [variáveis](docs/VARIABLES.md),
[arquitetura](docs/ARCHITECTURE.md), [dicionário](docs/DATA_DICTIONARY.md),
[operação](docs/OPERATIONS.md) e [limites conhecidos](docs/KNOWN_LIMITATIONS.md).
