# CAMS Global Air Quality Historical Database — relatório da primeira fase

**Entrega: 30 de setembro de 2026.** Projeto Python criado e testado. O catálogo
oficial foi consultado e a tentativa mínima registrada. **A base de poluição ainda
não contém dados CAMS**, pois não há chave ADS neste ambiente. Não se confunde
sucesso em testes sintéticos com validação de um download real.

## 1. Dados e disponibilidade confirmada

Foram obtidos os JSON oficiais de coleção, formulário e constraints dos produtos:

| Dataset ADS | Cobertura observada | Grade ADS / frequência |
|---|---|---|
| `cams-global-reanalysis-eac4-monthly` | janeiro/2003 a dezembro/2025 | 0,75° × 0,75°; médias mensais |
| `cams-global-reanalysis-eac4` | 01/01/2003 a 31/12/2025 | 0,75° × 0,75°; 3 horas na seleção |
| `cams-global-atmospheric-composition-forecasts` | 01/01/2015 a 29/09/2026 no snapshot | grade ADS documentada 0,4°; sem mescla automática |

A cobertura EAC4 foi reconfirmada pelo comando de inventário ao vivo na retomada.
A cobertura operacional acima refere-se ao snapshot de 29/09, não a uma nova
recuperação de campos operacionais. Os arquivos em `evidence/` preservam as fontes;
`metadata/catalog/` guarda snapshots ao vivo com timestamp e hash. Os dados reais
ainda precisam de confirmação por recuperação autenticada e QC.

| Poluente | Nome confirmado na API | Vertical | Original → derivado |
|---|---|---|---|
| PM2.5 | `particulate_matter_2.5um` | superfície | kg/m³ → µg/m³, ×10⁹ |
| PM10 | `particulate_matter_10um` | superfície | kg/m³ → µg/m³, ×10⁹ |
| CO | `carbon_monoxide` | model level 60 | kg/kg mantido |
| NO2 | `nitrogen_dioxide` | model level 60 | kg/kg mantido |
| SO2 | `sulphur_dioxide` | model level 60 | kg/kg mantido |
| O3 | `ozone` | model level 60 | kg/kg mantido |

A grade global planejada tem **241 × 480 = 115.680 células**. Não há interpolação
adicional. Campos mensais usam `monthly_mean`. O formulário atual usa
`data_format` (`grib` ou `netcdf_zip`); os exemplos antigos com `format` não foram
copiados. O nível 60 é específico da EAC4; não se aplicou o nível 137 operacional.

## 2. Infraestrutura entregue

- Pacote instalável, CLI `camsaq` e execução `python -m cams_air_quality`.
- Catálogo dinâmico por variável/nível, sem último ano fixo no downloader.
- Registro YAML de variáveis e configuração de caminhos, datas, chunks, retry,
  limites de disco, formato e concorrência conservadora.
- Downloads por variável/mês, ID remoto persistente, retomada HTTP Range quando
  suportada, backoff, timeout, checksums e publicação atômica após QC.
- SQLite com estado, histórico de eventos, request, tamanho, checksum, erro e
  proveniência. Reutilização de originais bons e recuperação de lacunas antigas.
- QC de conteúdo: variável, nível, unidade, grade, coordenadas, tempos, NaN, Inf,
  duplicatas, mês completo e integridade de arquivo.
- NetCDF4 por lote; Zarr por ano e geração, publicado por índice atômico; originais
  preservados; tabelas CSV/Parquet com metadados JSON.
- Extração por ponto e bbox; médias por área, médias anuais por dias do mês,
  climatologias com referência explícita, anomalias, percentis e tendência OLS descritiva.
- Mapas, roteiro de EDA para PM2.5/NO2/O3 e exemplo de célula próxima de São Paulo.
- Três notebooks, quatro scripts de conveniência, documentação científica,
  dicionário, arquitetura, operação, limitações e recuperação do ambiente.
- Git inicializado localmente; nenhum repositório externo criado ou publicado.

Comandos principais: `inventory`, `plan`, `smoke`, `download-monthly`,
`download-subdaily`, `update`, `validate`, `process`, `consolidate`,
`extract-point`, `extract-region`, `map` e `analyze`.

## 3. Execução e testes

**61 testes pytest aprovados; processo encerrado com código 0.** Evidência em
`reports/pytest-final.txt`. Ruff também aprovado. A suíte cobre requests,
limites temporais, ano bissexto, mudanças de catálogo, identidade de arquivo,
SQLite, arquivos corrompidos, ZIP, GRIB ecCodes, NetCDF4, Zarr, unidades,
retomada HTTP, jobs interrompidos, atualização incremental, antimeridiano,
ponderações espaciais/temporais, exportação e renderização real de mapas sintéticos.
A leitura independente com a biblioteca `netCDF4` confirma os arquivos HDF5
produzidos pelo backend `h5netcdf`. O teste Parquet lê de volta os valores salvos.

Uma falha importante foi investigada na última etapa: o ambiente inicial podia
aprovar as asserções e abortar no encerramento. Instalação isolada, fixação de
versões e troca de backends, sozinhas, não resolveram. A renderização Cartopy
foi separada em worker; o PNG só é publicado se esse processo retornar zero.
A suíte integrada final passou e encerrou normalmente. Não se afirma ter
identificado o defeito interno exato na interação das bibliotecas C.
Veja `docs/ENVIRONMENT_RECOVERY.md`; as versões estão em `requirements-lock.txt`.

Os notebooks passaram pela validação estrutural e de sintaxe. As células do
inventário foram executadas diretamente em Python; os dois notebooks dependentes
de dados reais não foram executados. O kernel Jupyter encontrou restrições de
sockets do ambiente, registradas no relatório de validação.

**Piloto real:** a request de PM2.5 global para janeiro de 2003 foi construída a
partir do catálogo atual. O SDK oficial respondeu **“The API key is needed to
access this resource”**, antes de submeter o job. Registro em
`reports/live-smoke.txt` e no manifesto. Não se obtiveram payload, dimensões ou
unidades de um arquivo real. Por isso, não se iniciou a aquisição em massa.

## 4. Inventário local e planejamento

| Poluente | Meses esperados | Meses locais válidos | Faltantes | Arquivos válidos |
|---|---:|---:|---:|---:|
| PM2.5 | 276 | 0 | 276 | 0 |
| PM10 | 276 | 0 | 276 | 0 |
| CO | 276 | 0 | 276 | 0 |
| NO2 | 276 | 0 | 276 | 0 |
| SO2 | 276 | 0 | 276 | 0 |
| O3 | 276 | 0 | 276 | 0 |
| Total variável × mês | **1.656** | **0** | **1.656** | **0** |

**Bytes de dados CAMS baixados: 0.** Metadados oficiais, código e fixtures de teste
não entram nessa contagem. Primeira/última data local permanecem vazias.

| Produto completo, seis variáveis | Lotes originais | Campos | Float32 sem compressão | Reserva de quatro cópias |
|---|---:|---:|---:|---:|
| Mensal 2003–2025 | 1.656 | 1.656 | 0,714 GiB | 2,855 GiB + margem |
| Subdiário 2003–2025 | 1.656 | 403.248 | 173,776 GiB | 695,105 GiB + margem |

Subdiário: 8.401 dias, 67.208 instantes. Valores são **estimativas**, não tamanhos
medidos de GRIB/ZIP. Não incluem uma estimativa universal de compressão, backups
ou todas as gerações antigas de Zarr. O ambiente oferecia cerca de 29,7 GiB livres
no início, insuficientes para a série subdiária completa. Duração de download e
custo computacional real só podem ser calibrados após amostra autenticada; não
foi inventado tempo de fila, taxa de transferência ou custo financeiro.

## 5. Continuação na máquina do usuário

```bash
cd cams-global-air-quality
python3 -m venv .venv   # Python 3.11 ou 3.12
source .venv/bin/activate
pip install -r requirements-lock.txt
pip install --no-deps -e .
pytest -q
```

Configure o token em `~/.ecmwfdatastoresrc` conforme o README, ou indique
`ECMWF_DATASTORES_RC_FILE="$HOME/.cdsapirc"`, e aceite os termos no ADS.
Não envie a chave por mensagem nem a inclua no projeto.

```bash
camsaq inventory
camsaq smoke --start 2003-01 --end 2003-01 --pollutants pm25
camsaq smoke --start 2003-01 --end 2003-01 --pollutants co
camsaq validate
camsaq download-monthly
camsaq inventory
camsaq analyze --baseline-start 2003-01 --baseline-end 2022-12
python -m cams_air_quality update
```

Depois dos pilotos, qualquer diferença real de estrutura/nível/unidade será um
erro de QC a investigar, não uma conversão silenciosa. Para subdiários, planejar
armazenamento, testar um mês e usar `--max-batches` ou máquina com maior capacidade.

## 6. Próximas fases

1. Completar pilotos reais, toda a série mensal, QC e EDA científica.
2. Calibrar recursos e chunks; executar subdiários incrementais em armazenamento adequado.
3. API de séries/recortes, índices espaciais e fronteiras administrativas em PostGIS.
4. Dashboard consumindo derivados, sem consultas ADS pesadas na interface.
5. Integração meteorológica com alinhamento de níveis, grade e tempos.
6. Protocolo epidemiológico com definição de exposição, validação externa,
   população, confundimento e dependência espaço-temporal.
7. Avaliar a extensão operacional separadamente, com ciclos IFS, lead times,
   mudanças de grade/assimilação e transição explícita nos metadados.

**Conclusão de escopo:** infraestrutura criada, verificações locais concluídas e
entrega reprodutível preparada. A validação autenticada em dados CAMS reais e a
construção da base histórica permanecem pendentes de credenciais/acesso e, para
subdiários completos, capacidade de armazenamento.
