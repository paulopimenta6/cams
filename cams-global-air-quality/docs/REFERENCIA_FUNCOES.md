# Referência das funções Python

Este documento explica **o que cada função faz**, quando usá-la e o que ela
devolve. Se você está começando, use primeiro os comandos `camsaq` do
[guia completo](../../GUIA_COMPLETO.md): eles organizam as chamadas abaixo na
ordem correta. As funções com nome iniciado por `_` são **internas**; aparecem
aqui para permitir auditoria, mas podem mudar sem aviso em uma versão futura.
Os módulos ficam em `src/cams_air_quality/`, salvo quando outro caminho é
indicado.

## Antes de chamar uma função

`cfg` é um dicionário criado por `load_config()`. `batch` é um pedido para **um
mês e uma variável**, representado por `Batch`. `snap` é a resposta do catálogo
ADS. `ds` e `da` são, respectivamente, `xarray.Dataset` e `xarray.DataArray`.
Datas de mês usam `AAAA-MM`; coordenadas são graus decimais. `bbox` é a lista
`[norte, oeste, sul, leste]`. A origem EAC4 e a origem CAMS73 usam manifests
e caminhos diferentes.

Um `DataArray` do xarray costuma ser **preguiçoso**: a conta só se realiza ao
usar `.compute()`, `.to_netcdf()` ou função equivalente. Quando a função abre
dados por meio de `with`, faça o cálculo e salve o resultado **dentro** desse
bloco, antes de o arquivo ser fechado.

### Exemplo curto: ler a base EAC4 já consolidada

```python
from cams_air_quality.config import load_config
from cams_air_quality.processing import open_database
from cams_air_quality.extraction import area_mean

cfg = load_config("config/config.yaml")
with open_database(cfg, kind="monthly") as ds:
    serie = area_mean(ds.pm25).compute()
    print(serie.to_dataframe().head())
```

Esse exemplo só funciona depois de baixar, processar e consolidar dados EAC4.
O PM2.5 processado está em µg/m³. Se houver meses faltantes entre o primeiro e o
último, `open_database()` recusa a série por padrão; `allow_gaps=True` permite
**abrir** os dados para inspeção, mas não preenche as lacunas.

### Exemplo curto: ler o metano importado

```python
from cams_air_quality.config import load_config
from cams_air_quality.ghg_inversion import open_processed

cfg = load_config("config/config.yaml")
with open_processed(cfg, version="v25r1") as (ds, rows):
    primeiro_dia = ds.ch4.sel(level=1).isel(time=0).compute()
    print(primeiro_dia.attrs["units"], primeiro_dia.shape)
```

`open_processed()` abre os NetCDF CH4 cujos checksums constam do manifesto. O
valor está em **ppb de fração molar em ar seco**. O nível precisa ser escolhido
explicitamente para a maior parte das análises. `rows` contém os registros de
proveniência dos meses abertos.

## Configuração, catálogo e pedidos

| Módulo e função | Papel e resultado |
|---|---|
| `config.load_config(path="config/config.yaml")` | Lê YAML, resolve caminhos, cria pastas locais e valida opções básicas; devolve `cfg`. Chame a partir da pasta do pacote ou passe um caminho explícito. |
| `catalog.CatalogError` | Exceção para formulário, restrições ou disponibilidade ADS incompatíveis com o pedido. |
| `catalog._session()` | **Interna:** prepara sessão HTTP com tentativas limitadas para erros transitórios do catálogo. |
| `catalog.fetch_catalog(cfg, kind, source="EAC4")` | Consulta coleção, formulário e restrições **ao vivo**; salva uma cópia datada por hash em `metadata/catalog/`; devolve `snap`. `kind` é `monthly`/`subdaily` na EAC4 ou `daily_mean` na fonte CH4. |
| `catalog.load_snapshot(directory, kind)` | Lê os três arquivos locais `kind.collection.json`, `kind.form.json` e `kind.constraints.json`; serve para diagnóstico histórico, não para autorizar um download novo. |
| `catalog.choices(snap, field)` | Devolve os valores exibidos por um campo do formulário ADS. |
| `catalog.matching_rows(snap, spec, kind)` | Seleciona linhas de restrições compatíveis com a variável e o tipo de produto EAC4. |
| `catalog.available_months(snap, spec, kind)` | Devolve meses EAC4 completos confirmados pelo catálogo, para uma variável e uma resolução. |
| `catalog.validate_request(snap, spec, kind, request)` | Recusa pedido EAC4 com opção ou mês não confirmado; não envia o pedido. |
| `requests.Batch` | Registro imutável de um lote: dataset, variável, ano, mês, representação vertical, pedido, destino e chave SHA-256. `Batch.to_dict()` fornece um dicionário para exibição/JSON. |
| `requests.build_batch(cfg, snap, pollutant, period, kind)` | Cria **um** lote EAC4 após validar a seleção no catálogo. Não baixa dados. |
| `requests.plan_batches(cfg, snap, kind, start=None, end=None, pollutants=None)` | Cria a lista ordenada de lotes EAC4 para o intervalo e as variáveis escolhidas. Datas omitidas seguem `cfg`; sem limites explícitos, usa a cobertura confirmada ao vivo. |
| `requests.estimate(cfg, batches)` | Estima campos e espaço de disco EAC4 com float32 e multiplicador de cópias. É orçamento de planejamento, não tamanho exato do arquivo baixado. |
| `inventory.inventory(cfg, batches)` | Compara lotes esperados com originais íntegros do manifesto EAC4; devolve `pandas.DataFrame` com meses disponíveis, faltantes, bytes e estado. |

## Download, manifesto e validação EAC4

| Módulo e função | Papel e resultado |
|---|---|
| `downloader.make_client(cfg)` | Cria o cliente oficial ECMWF/ADS com URL e tempos de espera configurados. Para submeter jobs, requer token e licença aceitos na conta. |
| `downloader.safe_error(exc)` | Reduz uma exceção a mensagem adequada ao log, evitando persistir token, URL assinada ou corpo HTTP. |
| `downloader.download_range(url, target, expected, timeout)` | Baixa o asset em blocos; retoma por HTTP Range apenas quando identidade e tamanho conferem. Guarda somente hash da URL assinada. Erro deixa parcial para tentativa posterior. |
| `downloader.download_batch(cfg, batch, client=None, validator=None)` | Registra, solicita ou retoma **um** lote, confere bytes e QC, grava o original atomicamente e devolve dicionário com estado. `validator` escolhe QC EAC4 (padrão) ou CH4; `client` permite testes sem rede. |
| `storage.now()` | Produz data/hora UTC em ISO 8601 para registros. |
| `storage.sha256(path)` | Calcula SHA-256 dos bytes de um arquivo, lendo em blocos. |
| `storage.Manifest(path)` | Cria/abre SQLite com tabelas `downloads` e `events`. Use o manifesto EAC4 em `metadata/downloads.sqlite` e o CH4 em `metadata/ghg_inversion/downloads.sqlite`. |
| `Manifest.__init__(path)` | Construtor chamado por `Manifest(path)`; cria a pasta e o esquema SQLite quando necessário. |
| `Manifest.connect()` | Contexto de conexão SQLite: confirma a transação se terminar bem, desfaz em caso de erro e fecha a conexão. |
| `Manifest.add(batch)` | Insere lote ainda não registrado. Se o caminho mudou, exige arquivo com mesmo checksum ou lote anterior sem payload. |
| `Manifest.get(key)` | Devolve registro do lote como dicionário, ou `None`. |
| `Manifest.set(key, status, **fields)` | Atualiza estado/campos permitidos e grava evento. Estados: `requested`, `downloading`, `downloaded`, `validated`, `processed`, `failed`. |
| `Manifest.rows()` | Devolve registros ordenados por ano, mês e variável. |
| `Manifest.intact(row)` | Retorna `True` somente para original validado/processado cujo caminho, tamanho e SHA-256 conferem. Recebe um registro existente. |
| `validation.open_raw(path, interim, chunks=None, netcdf_engine="h5netcdf")` | Contexto de leitura de GRIB, NetCDF ou ZIP seguro; preserva o original e fecha recursos ao sair. |
| `validation.normalize(ds, spec)` | Encontra exatamente a variável EAC4 pedida, confirma representação vertical, renomeia coordenadas compatíveis e devolve `DataArray(time, latitude, longitude)`. Recusa ambiguidades. |
| `validation.inspect_array(da, batch, cfg)` | Confere unidade, tempo, grade, cobertura, valores ausentes/infinidade e devolve dicionário de QC (`PASS`, `WARNING` ou `FAIL`). |
| `validation.validate_file(path, batch, cfg)` | Abre e valida um original EAC4; devolve QC, inclusive `FAIL` se o arquivo não puder ser lido. |

`PASS` significa que o arquivo passou **os testes implementados**, não que sua
estimativa seja cientificamente adequada para qualquer pergunta. `WARNING`
exige inspeção; `FAIL` impede o processamento normal. O inventário mostra
cobertura, enquanto a validação examina conteúdo e integridade.

## Conversões e metadados

| Módulo e função | Papel e resultado |
|---|---|
| `units.canonical(unit)` | Normaliza grafias conhecidas de kg/m³, kg/kg, µg/m³, Pa e K para comparação de unidades. |
| `units.standardize(da, spec)` | Aplica a conversão cadastrada EAC4: PM em kg/m³ → µg/m³ (×10⁹) ou identidade para gases em kg/kg; registra equação e hipóteses. Recusa conversão desconhecida. |
| `units.mixing_ratio_to_concentration(q, density)` | Função **opcional** para campos instantâneos alinhados: kg/kg × densidade kg/m³ ×10⁹ → µg/m³. Recusa médias mensais e coordenadas diferentes. Não é usada automaticamente no pipeline. |
| `units.moist_air_density(pressure, temperature, specific_humidity)` | Função **opcional** de densidade por mistura ideal, com pressão em Pa, temperatura em K e umidade específica kg/kg, todos no mesmo nível/tempo/grade. Não é usada automaticamente. |
| `metadata.code_version(root)` | Obtém commit Git e indicador de alterações locais; se Git não estiver disponível, usa a versão do pacote. |
| `metadata.provenance(batch, row, cfg)` | Monta atributos de origem EAC4: dataset, pedido, checksum, código, unidades/nível e processamento. |

Não aplique a conversão opcional de gases a médias mensais: em geral,
`média(q × densidade)` difere de `média(q) × média(densidade)`. CH4 CAMS73 já é
fração molar em ppb; não usa essas conversões EAC4.

## Processamento, consulta e estatísticas EAC4

| Módulo e função | Papel e resultado |
|---|---|
| `processing.batch_from_row(row)` | Reconstrói um `Batch` a partir do manifesto. |
| `processing.process_batch(cfg, batch)` | Exige original íntegro, normaliza dimensão/unidade e publica uma partição NetCDF4 imutável; devolve seu caminho. Um checksum válido permite reaproveitá-la. |
| `processing.product_root(cfg, kind="monthly")` | Calcula pasta Zarr EAC4 para resolução, área e conjunto de variáveis configurados. |
| `processing.consolidate(cfg, kind="monthly")` | Combina partições em Zarr anuais e publica `index.json`; requer mesma cobertura mensal entre as variáveis configuradas em cada ano. Devolve caminho do índice. |
| `processing.open_database(cfg, kind="monthly", allow_gaps=False)` | Abre Zarr anuais em `Dataset` com `with`. Recusa datas duplicadas e, por padrão, lacunas entre extremos. `allow_gaps=True` abre sem preencher. |
| `extraction.check_bbox(bbox)` | Confere quatro coordenadas geográficas no formato norte/oeste/sul/leste. |
| `extraction.subset_bbox(ds, north, west, south, east)` | Seleciona centros de células no retângulo; aceita cruzar o antimeridiano. Não calcula fração de área dentro de fronteiras. |
| `extraction.extract_point(ds, lat, lon)` | Escolhe centro de célula mais próximo pela distância esférica e registra coordenadas/distância. Não interpola nem lê estação. |
| `extraction.area_weights(ds)` | Produz pesos de área esférica a partir das latitudes da grade regular. |
| `extraction.area_mean(da)` | Faz média espacial ponderada por área de células; não é média por população. |
| `extraction.get_timeseries(cfg, pollutant, lat, lon)` | Abre a base EAC4 e devolve `DataFrame` da célula mais próxima. |
| `extraction.get_region_timeseries(cfg, pollutant, bbox)` | Abre a base EAC4 e devolve `DataFrame` da média por área no retângulo. |
| `extraction.save_table(frame, path)` | Salva CSV ou Parquet e um arquivo `.metadata.json` com proveniência. |
| `statistics.check_monthly(da)` | Exige meses contínuos, ordenados e sem duplicatas, com datas no início do mês. |
| `statistics.annual_mean(da, require_complete=True)` | Média anual ponderada pelos dias de cada mês; com padrão `True`, publica somente anos com 12 meses. |
| `statistics.climatology(da, start, end)` | Média por mês do calendário no período de referência escolhido; exige pelo menos 12 meses e todos os meses do ano representados. |
| `statistics.anomalies(da, start, end)` | Subtrai a referência mensal da série original. |
| `statistics.linear_trend(da)` | Inclinação linear descritiva por ano; não ajusta sazonalidade/autocorrelação e não fornece inferência causal. |
| `statistics.summaries(da, bbox=None, quantiles=(0.05, 0.5, 0.95))` | Devolve dicionário com série espacial, anual, média zonal, tendência, percentis, mínimo, máximo e desvio padrão. Percentis exatos podem exigir muita memória. |
| `analysis.explore(cfg, output, baseline_start, baseline_end)` | Gera relatório EAC4 de PM2.5, NO₂ e O₃, com gráficos, tabelas e mapas. Exige essas variáveis disponíveis na base mensal e referência temporal válida. |

Os notebooks automáticos EAC4 conseguem analisar coberturas parciais por
variável sem exigir Zarr consolidado; a função `statistics.check_monthly()` e
os comandos de análise EAC4 baseados em Zarr são mais restritivos. Para uma
série com lacunas, não trate `allow_gaps=True` como permissão para calcular
climatologia ou tendência sem antes decidir como lidar com as faltas.

## Mapas e interface de comandos

| Módulo e função | Papel e resultado |
|---|---|
| `maps.cell_edges(centres, polar=False)` | Calcula limites das células a partir de centros ordenados de grade regular. |
| `maps.plot_map(da, path, title=None, anomaly=False, coastlines=False, vmin=None, vmax=None)` | Salva mapa de **um** campo latitude × longitude em processo separado. `vmin`/`vmax` definem a escala; `coastlines=True` pode requerer dados cartográficos adicionais. |
| `maps.render_arrays(...)` | **Interna:** desenha os arrays no processo isolado; normalmente chame `plot_map()`. |
| `map_worker.main()` | **Interna:** entrada do processo que renderiza mapas. |
| `cli.parser()` | Monta o interpretador de argumentos usado por `camsaq`. |
| `cli.main(argv=None)` | Executa um comando e devolve código de saída (`0` para sucesso, `1` para erro tratado). `python -m cams_air_quality` chama essa função. |
| `cli.run_one(cfg, batch)` | **Interna EAC4:** baixa e processa um lote. |
| `cli.download_plan(cfg, batches, max_batches=None, retry_failed=False)` | **Interna EAC4:** seleciona lotes, verifica espaço, roda pilotos por representação vertical e depois os demais. |
| `cli.run_ch4_command(args, cfg)` | **Interna CH4:** despacha os subcomandos `camsaq ch4`. |

Para usar a interface sem instalar o script `camsaq`, após instalar o pacote
execute `python -m cams_air_quality --help`. Os arquivos em `scripts/` são
atalhos para `download-monthly`, `download-subdaily`, `update` e `validate`;
não acrescentam funções científicas.

## Funções CAMS73 CH4 (`ghg_inversion.py`)

O adaptador aceita **metano, concentração, `first_guess`, média diária**. Ele
não é um mecanismo genérico para todos os gases ou versões do ADS. As funções
de pedido exigem mês explícito para evitar download involuntário em massa.

| Função | Papel e resultado |
|---|---|
| `source_config(cfg)` | Copia a configuração apontando `metadata_dir` ao manifesto CH4 separado. |
| `manifest(cfg)` | Abre o `Manifest` específico de CH4. |
| `fetch_ch4_catalog(cfg)` | Consulta o catálogo público do produto CAMS73 ao vivo. |
| `build_batch(cfg, period, version="v25r1", observations="first_guess", snap=None)` | Cria um lote CH4 para um mês; com `snap`, valida a combinação no ADS. `latest` é permitido para pedir, mas a versão efetiva é lida do arquivo. |
| `plan_batches(cfg, snap, start, end=None, version="v25r1", observations="first_guess")` | Planeja os meses inclusivos; requer `start` e valida cada um no catálogo. |
| `estimate(batches, storage_copies=4)` | Estima arquivos, dias e GiB com base no arquivo real de setembro de 2024; não mede o tamanho futuro do ADS. |
| `validate_file(path, batch, cfg)` | Confere nome científico, unidade, 34 níveis, grade, todos os dias, campos auxiliares e valores finitos/positivos; devolve QC `PASS`/`WARNING`/`FAIL`. |
| `import_file(cfg, source)` | Valida NetCDF local com nome CAMS73, confere SHA-256, copia para `data/raw/ghg_inversion/` e registra proveniência; devolve `(batch, qc)`. Não executa processamento quando chamada diretamente em Python. |
| `process_batch(cfg, batch)` | Exige original íntegro e QC, preserva os 34 níveis e auxiliares verticais em NetCDF4, registra versão efetiva e checksum; devolve caminho. |
| `consolidate(cfg, version="v25r1", observations="first_guess")` | Publica Zarr anual e `index.json` da versão efetiva. Aceita ano parcial, mas recusa meses duplicados ou derivados corrompidos. |
| `open_processed(cfg, version="v25r1", observations="first_guess")` | Contexto que abre as partições NetCDF verificadas; fornece `(ds, rows)`. A análise CH4 lê essas partições, não depende de abrir o Zarr. |
| `analyze(cfg, level, output, version="v25r1", observations="first_guess", lat=-23.5505, lon=-46.6333, bbox=None, maps=True)` | Exige nível explícito; salva médias espaciais diárias, médias de meses completos, série da célula mais próxima, mapas e `analysis.json`; devolve relatório. `bbox` limita média/mapas, não muda o ponto. |
| `download(cfg, batches, client=None)` | Baixa/valida/processa os lotes preparados e para na primeira falha; devolve lista de resultados. Na CLI, `ch4 download` também chama `consolidate()`. |

Ao chamar `import_file()` diretamente em Python, complete o fluxo assim:

```python
from cams_air_quality.config import load_config
from cams_air_quality import ghg_inversion as ch4

cfg = load_config("config/config.yaml")
batch, qc = ch4.import_file(
    cfg, "../exemplo_ch4/cams73_latest_ch4_conc_first_guess_dm_202409.nc"
)
processed = ch4.process_batch(cfg, batch)
index = ch4.consolidate(cfg, qc["resolved_release"])
report = ch4.analyze(cfg, level=1, output="reports/ch4_inversion", maps=False)
print(processed, index, report["complete_months"])
```

Se o mesmo mês/versão entrar por `import_file()` e por `download()` como pedidos
diferentes, a consolidação recusa a duplicidade. A temperatura `T` e a umidade
`Q` continuam no **original**; o derivado conserva CH4, pressão, área, altitude
e coeficientes híbridos necessários para localizar os níveis.

### Verificadores internos CH4

| Função | O que confere ou produz |
|---|---|
| `_request(period, version, observations)` | Monta seleção fixa `methane` + `concentration` + `first_guess` + `daily_mean`. |
| `_check_catalog(snap, request)` | Confirma campos e uma linha de restrições ADS compatível com a combinação exata. |
| `_grid_check(ds, cfg, failures)` | Confere dimensões, ordem, espaçamento e centros da grade CH4. |
| `_inspect_ch4(ds, batch, cfg)` | Examina identidade, tempo, níveis, auxiliares e valores; monta QC. |
| `_release(row)` | Lê a versão efetiva do registro de QC. |
| `_processed_rows(cfg, version, observations)` | Seleciona partições verificadas por versão/observações e recusa duplicidade. |
| `_store_root(cfg, version, observations)` | Calcula pasta do Zarr CH4. |

## Funções dos notebooks automáticos EAC4

O arquivo `notebooks/available_data.py` é um auxiliar dos notebooks 01–03.
Ele lê o manifesto EAC4 sem modificá-lo e trabalha com partições mensais
verificadas; não baixa dados e não integra CH4 CAMS73.

| Função | Papel e resultado |
|---|---|
| `digest(path)` | SHA-256 de um arquivo. |
| `inventory(cfg, variables=None)` | Devolve `(rows, report)` de partições EAC4 mensais elegíveis; mostra ausências, falhas de checksum e ambiguidades por variável. |
| `open_variable(rows, variable, cfg)` | Contexto que abre somente a variável escolhida, confirmando tempo, nível e unidade. |
| `coverage(a)` | Verifica a fração finita de cada mês; devolve `(meses_utilizáveis, resumo, tabela_QC)`. Exige todas as células finitas para usar um mês. |
| `annual(a, years)` | Média anual ponderada por dias para anos com 12 meses utilizáveis. |
| `reference(a, years)` | Ciclo mensal descritivo dos anos informados; devolve `None` se houver menos de dois. Passe anos completos, como os fornecidos por `coverage()`. |
| `export_series(a, path, metadata)` | Salva tabela, insere linhas `NaN` para meses ausentes entre extremos e devolve série reindexada. |
| `analyze(variable, rows, cfg, output, bbox=None, maps=True)` | Gera séries, ciclo, médias anuais e, quando há referência suficiente, anomalias e mapas para **uma** variável. |
| `point_and_region(variable, rows, cfg, output, lat, lon, bbox=None)` | Exporta célula mais próxima e, se pedido, média regional com QC próprio. |

Os notebooks 01–03 são a forma recomendada de chamar esse auxiliar. O
[guia dos notebooks](../notebooks/NOTEBOOKS_AUTOMATICOS.md) explica como
executá-los e interpretar meses ausentes.
Os notebooks não transformam CH4 em poluente EAC4.
