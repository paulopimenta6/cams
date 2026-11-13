# Dicionário de dados

## Dataset analítico

| Campo | Tipo/dimensão | Significado |
|---|---|---|
| time | datetime64, time | UTC; início do mês nos derivados mensais |
| time_bnds | datetime64, time × bnds | início inclusivo, fim exclusivo do mês |
| latitude | float, latitude | graus norte, ordem original preservada |
| longitude | float, longitude | graus leste, convenção original preservada |
| pm25, pm10 | float32, time × latitude × longitude | concentração µg m⁻³ |
| co, no2, so2, o3 | float32, time × latitude × longitude | razão mássica kg kg⁻¹ no nível 60 |
| source | atributo | EAC4, nunca operacional implícito |
| source_level_type / source_level | atributo por variável | representação vertical original |
| original_units / units | atributo por variável | antes/depois do processamento |
| conversion_equation / assumptions | atributo por variável | transformação aplicada e hipóteses |
| cell_methods | atributo por variável | time: mean mensal; time: point subdiário |
| raw_file / raw_sha256 | atributo da partição NetCDF | rastreabilidade ao original |
| api_request / dataset / catalog_sha256 | atributos | identificação exata do pedido e catálogo |
| code_version / history / processed_at | atributos | versão Git e processamento |
| provenance_manifest | atributo Zarr | lista das partições e checksums de origem |

Os payloads podem usar `valid_time`, `hybrid`, `go3` etc. O adaptador normaliza
somente após verificar significado e valor. Dimensões inesperadas (`expver`,
ensemble, forecasts 2D) são recusadas; não se faz média ou seleção silenciosa.

O produto CAMS73 usa manifesto e índice próprios. Sua partição diária contém
`ch4(time, level, latitude, longitude)` em ppb de fração molar seca, níveis 1–34,
`cell_area`, `ps`, altitude e coeficientes híbridos. A origem `first_guess` e a
versão efetiva são metadados obrigatórios; consulte [CH4_CAM73.md](CH4_CAM73.md).

| Campo CAMS73 processado | Dimensões | Unidade e uso |
|---|---|---|
| `ch4` | dia × nível × latitude × longitude | ppb; fração molar em ar seco, não concentração em massa |
| `cell_area` | latitude × longitude | m²; ponderação da média espacial |
| `ps` | dia × latitude × longitude | Pa; pressão superficial do modelo |
| `hyam`, `hyai` | nível ou interface | Pa; parcela de pressão dos níveis híbridos |
| `hybm`, `hybi` | nível ou interface | sem dimensão; outra parcela dos níveis híbridos |
| `altitude` | dia × interface × latitude × longitude | m; altitude das interfaces, não altitude fixa da camada inteira |
| `latitude_bounds`, `longitude_bounds` | coordenada × limite | contornos das células |

`hlevel` identifica interfaces entre camadas. Temperatura `T` e umidade `Q`
continuam no **arquivo original**, que é preservado; não aparecem no derivado
CH4 atual. O relatório `analysis.json` registra release, nível, arquivos e
checksums. `area_daily.csv` e `area_monthly.csv` são médias ponderadas pela área
das células; `point_daily.csv` representa apenas a célula mais próxima do ponto
pedido. Os arquivos `.metadata.json` ao lado dos CSV guardam seus parâmetros.

## Manifesto SQLite: downloads

| Campo | Tipo | Definição |
|---|---|---|
| key | TEXT PK | SHA256 de dataset + request canônica |
| dataset, variable | TEXT | coleção ADS e nome interno |
| year, month | INTEGER | lote calendário |
| temporal_resolution | TEXT | monthly, subdaily ou daily_mean (CAMS73) |
| level_type, level | TEXT, INTEGER/null | surface, model, pressure ou model_profile (CAMS73) e nível |
| request_date, download_date | TEXT ISO8601 | planejamento/submissão local e download |
| filename, filepath | TEXT | nome e caminho absoluto no ambiente |
| filesize | INTEGER | bytes do payload original |
| status | TEXT | requested/downloading/downloaded/validated/failed/processed/cleaned |
| checksum | TEXT | SHA256 original validado |
| error | TEXT/null | falha sanitizada de aquisição/QC |
| api_request | TEXT JSON | parâmetros enviados, sem chave de acesso |
| remote_id | TEXT/null | job ADS para retomar sem nova submissão |
| catalog_sha256 | TEXT | snapshot usado no pedido |
| qc_json | TEXT JSON | resultados e métricas QC |
| processed_path, processed_checksum | TEXT | partição NetCDF derivada |
| processing_error | TEXT/null | falha do derivado, original preservado |
| updated_at | TEXT ISO8601 | última transição |

A tabela `events` registra chave, timestamp, status e detalhes das transições.
O evento `raw_removed` não muda o status `processed` se o derivado ainda estiver
íntegro. `cleaned` indica que o derivado foi removido e não há bruto verificado
para reconstrução; `validate` mostra essa linha como `SKIPPED`.
`downloads.sqlite` incluído no ZIP registra somente a tentativa real bloqueada,
sem observações. O banco é ignorado por Git e não deve ser publicado com dados
sensíveis de diretórios locais. Ao mover o arquivo para outra máquina, lotes sem payload são reposicionados automaticamente; arquivos movidos só são
reconhecidos no novo caminho após checksum idêntico. Para outras situações, ajuste
cuidadosamente os caminhos absolutos; não marque arquivos
como válidos sem QC/checksum.

## Inventário

`pollutant`, `expected_first`, `expected_last`, `first_date`, `last_date`,
`months_expected`, `months_available`, `missing`, `missing_months`, `files`,
`bytes`, `status`. As datas first/last referem-se **a arquivos locais válidos**;
quando não existem dados elas são vazias, não copiadas do catálogo. Meses
intermediários faltantes são listados, ainda que first/last pareçam contínuos.

## QC

PASS: todos os critérios atendidos. WARNING: por exemplo valores negativos
(não truncados) ou faltantes dentro de tolerância configurada. FAIL: arquivo
ilegível, nível/variável/unidade incorreto, timestamps inconsistentes, infinidade,
campos inteiramente ausentes, grade inesperada ou ausência acima do limite.
O padrão aceita fração faltante 0,0. Alterações dessa política precisam ser
documentadas na análise; warnings não equivalem a confirmação de acurácia física.

## Tabelas e relatório CH4 da análise

Todos os CSVs usam `ch4_ppb`: fração molar de metano em ar seco, em ppb. O
arquivo vizinho `<nome>.csv.metadata.json` guarda release, nível, recorte,
arquivos e checksums. A coluna `time` identifica o dia ou o primeiro dia do mês;
`year` identifica um ano completo; `month` é o mês calendário 1–12.

| Arquivo | Colunas principais | Quando aparece |
|---|---|---|
| `area_daily.csv` | `time`, `ch4_ppb` | Sempre; média espacial diária ponderada por `cell_area`. |
| `point_daily.csv` | `time`, `ch4_ppb` | Sempre; célula mais próxima do ponto escolhido. |
| `area_monthly.csv` | `time`, `ch4_ppb`, `days` | Sempre; somente meses diários completos. |
| `area_annual.csv` | `year`, `ch4_ppb`, `days` | Quando há ano com 12 meses completos. |
| `area_climatology.csv` | `month`, `ch4_ppb`, `n_years` | Quando há pelo menos dois anos completos de referência. |
| `area_anomaly_monthly.csv` | `time`, `ch4_ppb`, `days` | Com referência válida; diferença em ppb. |
| `area_anomaly_annual.csv` | `year`, `ch4_ppb`, `days` | Com referência válida e ano analisado completo. |

`analysis.json` versão 2 mantém `first_day`, `last_day`, `complete_months`,
`files`, `interpretation` e `map_color_scale` do formato anterior. Acrescenta
`schema_version`, `requested_start`, `requested_end`, `requested_date`,
`selected_months`, `selected_years`, `complete_years`, `reference_years`,
`baseline`, `maps`, `skipped`, `map_scales` e `coverage`.

`baseline` registra limites, anos completos, anos usados na referência,
checksums e a ponderação anual; é `null` sem baseline explícito. Cada entrada de
`maps` informa `file`, `family`, `period`, `vmin`, `vmax` e `scale_method`.
`map_scales` indexa as mesmas escalas pelo nome do PNG e inclui `method`.
`skipped` informa
`family`, `period` e `reason`. `coverage` registra `days_available`,
`days_expected` e `missing_days`, sem inventar valores para lacunas.

O notebook `04_ch4_inventory` grava `inventory.csv` com `year`, `month`,
`release`, `status`, `path`, `checksum`, `complete`, `days`, `n_levels`,
`first_time` e `last_time`; `coverage.json` lista meses e anos completos e o
que falta para uma média anual. Os notebooks 05 e 06 usam pastas de execução
próprias e não alteram o manifesto.
