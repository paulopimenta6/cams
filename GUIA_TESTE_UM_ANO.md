# CAMS EAC4 — teste de um ano, notebooks pelo terminal e mapas regionais

Este complemento foi preparado para a versão 0.1.0 do projeto. Copie
`notebooks/04_testes_um_ano.ipynb` para a pasta `notebooks/` do projeto existente.
Não substitua seus notebooks anteriores nem mova dados ou o manifesto.

O ano de exemplo é **2003**, confirmado pelas datas que apareceram no notebook.
Os comandos abaixo são para o Linux do usuário. O complemento não contém dados
CAMS nem credenciais. O notebook adicional não baixa dados CAMS.

## 1. Preparar o ambiente

Na raiz do projeto:

```bash
source ~/envs/cams/bin/activate
cd ~/Documentos/meus_codigos/cams/cams-global-air-quality
python -m pip install -e ".[dev,notebooks]" "nbconvert>=7,<8"
python -m pip check
python -m ipykernel install --user --name camsaq --display-name "Python (CAMS Air Quality)"
```

Para registrar explicitamente o executor no projeto, acrescente
`"nbconvert>=7,<8"` à lista `notebooks` de `[project.optional-dependencies]` no
`pyproject.toml`. Não duplique essa seção. Jinja2 e ipykernel devem continuar
nessa lista. `requirements.txt` pode continuar com `-e .[dev,notebooks]`.

O kernel nomeado `camsaq` evita que o notebook use outro Python. Para os comandos
que consultam/baixam dados ADS, a variável já configurada no Bash deve apontar ao
arquivo de credenciais; nunca imprima o conteúdo desse arquivo.

## 2. Testes do código e inventário restrito ao ano

Execute um comando por vez e examine sua saída:

```bash
python -m pytest -q
camsaq inventory --start 2003-01 --end 2003-12
camsaq plan --kind monthly --start 2003-01 --end 2003-12
```

Os testes usam mocks/pequenos dados de teste. Inventário e plano consultam o
catálogo ADS e os arquivos locais; não baixam campos meteorológicos. Para testar
sem consultar o catálogo, use `--offline-evidence evidence`, sabendo que se trata
de um snapshot histórico, não de disponibilidade atual.

O esperado no inventário, para a configuração padrão, é:

| Poluente | Meses esperados | Meses disponíveis | Lacunas | Status |
|---|---:|---:|---:|---|
| pm25 | 12 | 12 | 0 | COMPLETE |
| pm10 | 12 | 12 | 0 | COMPLETE |
| co | 12 | 12 | 0 | COMPLETE |
| no2 | 12 | 12 | 0 | COMPLETE |
| so2 | 12 | 12 | 0 | COMPLETE |
| o3 | 12 | 12 | 0 | COMPLETE |

Isso corresponde a 72 lotes brutos na organização padrão variável/mês, não ao
número total de arquivos incluindo NetCDF processado, chunks Zarr e relatórios.

Se houver lacunas, limite explicitamente o download:

```bash
camsaq download-monthly --start 2003-01 --end 2003-12
```

Arquivos validados e íntegros são reaproveitados pelo manifesto. Não execute
`update` sem limites para este teste; o comando pode planejar a série inteira.
Os pilotos por representação vertical são executados pelo downloader antes dos
lotes restantes quando necessários. Os termos dos datasets devem estar aceitos.

## 3. QC e consolidação local

Se você já consegue abrir `ds`, o índice existe. Para rever o QC e completar o
processamento, os comandos existentes são:

```bash
camsaq validate
camsaq process --kind monthly
camsaq consolidate --kind monthly
```

**Limitação da CLI atual:** esses três comandos não possuem `--start`/`--end` e
percorrem o manifesto/arquivo local correspondente. O download limitado a um ano
não torna a consolidação automaticamente filtrada por ano. Arquivos solicitados
mas incompletos em outro ano podem causar FAIL no validate, e coberturas desiguais
entre variáveis em outro ano podem impedir a consolidação. Preserve esses arquivos,
registre a mensagem e não edite o manifesto para mascarar a lacuna. Se o índice
anterior contém 2003 completo, o notebook adicional pode usar esse índice existente.
Uma extensão de filtros de período exigiria alteração da CLI e testes próprios.

O relatório `metadata/qc-report.json` registra a validação dos originais. O
notebook adicional complementa essa verificação nos campos processados.

## 4. Executar o notebook anual pelo terminal

Depois de copiar o novo notebook para `notebooks/`, rode da raiz do projeto:

```bash
mkdir -p reports/executed
export CAMSAQ_CONFIG="$PWD/config/config.yaml"
export CAMSAQ_YEAR=2003
export CAMSAQ_MONTH=7
export CAMSAQ_COASTLINES=0

python -m nbconvert --to notebook --execute notebooks/04_testes_um_ano.ipynb \
  --ExecutePreprocessor.kernel_name=camsaq \
  --ExecutePreprocessor.timeout=900 \
  --output 04_testes_2003_executado.ipynb \
  --output-dir reports/executed
```

O timeout é de 900 segundos **por célula**, não para o notebook inteiro. Erros
interrompem a execução; não use `--allow-errors` para considerar testes aprovados.
O fonte é preservado; a cópia com saídas fica em `reports/executed/`. A repetição
substitui essa cópia de saída; use outro nome se quiser guardar todas as execuções.
Os produtos científicos usam pastas com timestamps UTC e não se sobrescrevem.

Para gerar uma versão HTML a partir da cópia executada, sem executar novamente:

```bash
python -m nbconvert --to html \
  reports/executed/04_testes_2003_executado.ipynb \
  --output-dir reports/executed
```

Para outro ano já disponível, altere `CAMSAQ_YEAR`, `CAMSAQ_MONTH` e o nome da
cópia executada. Essas variáveis são do **novo notebook**; os três originais não
passam a lê-las automaticamente.

## 5. Executar os notebooks originais

A mesma sintaxe serve para qualquer `.ipynb`, por exemplo:

```bash
python -m nbconvert --to notebook --execute notebooks/01_inventory.ipynb \
  --ExecutePreprocessor.kernel_name=camsaq \
  --ExecutePreprocessor.timeout=900 \
  --output 01_inventory_executado.ipynb --output-dir reports/executed
```

Cada notebook inicia um kernel novo. Execute todas as células do próprio arquivo;
variáveis criadas no notebook 01 não são compartilhadas com o 02 ou 03.

| Notebook original | Produtos e restrições |
|---|---|
| 01_inventory | Inventário e estimativas. Usa os snapshots oficiais arquivados e o período do config.yaml; sem mapas. Para limitar seu plano interno, passe start="2003-01", end="2003-12" às chamadas plan_batches. |
| 02_global_climatology | Séries, mapas globais, média anual, climatologia, anomalias e análise exploratória. Antes de executá-lo inteiro com um ano, remova as referências fixas a 2020 e ajuste o período 2003–2022. Não use as seções climatologia/anomalias/explore como climatologia de longo prazo com um único ano. Para esta etapa, prefira o novo 04, que já faz essa distinção. |
| 03_timeseries_example | Série da célula próxima de São Paulo, média de um bbox e CSV/Parquet; não gera mapas. Usa todo o intervalo disponível no índice; para um ano selecione o ano no DataFrame antes de plotar/salvar ou use o novo 04. |

Não execute os três em um loop cego: o 02 original contém períodos ausentes na
base de um ano e deve falhar nesses casos. Os mapas salvos por `plot_map` são PNG;
para exibi-los também no notebook, use `display(Image(filename=str(caminho)))`.

## 6. O que o notebook anual testa e produz

- Exige exatamente janeiro–dezembro do ano pedido, sem duplicatas ou lacunas.
- Exige os seis poluentes e a grade global ADS de 241 × 480, 0,75°.
- Verifica unidades contra o cadastro de poluentes da configuração.
- Examina NaN, infinito, mínimo e máximo por variável/mês (72 registros QC).
- Registra negativos como WARNING, sem correção silenciosa.
- Gera seis séries globais mensais ponderadas por área e médias anuais por dias.
- Salva dois mapas globais de PM2.5: mês selecionado e média anual.
- Salva três mapas mensais regionais: bbox Brasil, Sudeste e Europa.
- Exporta séries regionais e a célula próxima de São Paulo em CSV/Parquet.
- Registra versões, ano, unidades, índice fonte e seu hash em um relatório JSON.

Os produtos ficam em `reports/one_year/2003/<timestamp-UTC>/`. O status final
refere-se aos checks básicos do dataset processado, não a uma avaliação completa
de acurácia do CAMS ou de adequação a estudos de exposição individual.

## 7. Como escolher outras regiões

A ordem do bbox é **[norte, oeste, sul, leste]**, com longitudes no intervalo
-180 a 180. Exemplos de janelas aproximadas:

| Região de interesse | Norte | Oeste | Sul | Leste |
|---|---:|---:|---:|---:|
| Brasil e entorno | 6 | -75 | -35 | -30 |
| Sudeste e entorno | -14 | -54 | -26 | -38 |
| Europa e entorno | 72 | -25 | 34 | 45 |
| América do Sul e entorno | 13 | -82 | -57 | -34 |

Edite o dicionário REGIOES na primeira célula do notebook. Ou use diretamente:

```python
from pathlib import Path
from IPython.display import Image, display
from cams_air_quality.extraction import subset_bbox
from cams_air_quality.maps import plot_map

# ds deve estar aberto, e o mês escolhido precisa existir.
campo = ds["pm25"].sel(time="2003-07-01", drop=True)
regional = subset_bbox(campo, north=6, west=-75, south=-35, east=-30)
caminho = plot_map(
    regional,
    Path(cfg["root"]) / "reports/maps/pm25_brasil_bbox_2003_07.png",
    title="PM2.5 — Brasil e entorno — julho de 2003",
    coastlines=False,
)
display(Image(filename=str(caminho)))
```

Para gases, substitua `pm25` por `no2`, `co`, `so2` ou `o3`. A barra de cores usará
a unidade dos metadados; não rotule kg/kg como µg/m³. Para média anual, use
`annual_mean(ds["pm25"].sel(time=slice("2003-01-01", "2003-12-31"))).isel(time=0, drop=True)`
antes do recorte.

O bbox seleciona células cujos centros estão no retângulo, sem interpolar. Não
recorta o contorno exato de um estado/país, não exclui oceano e não aumenta a
resolução física. O renderizador precisa de pelo menos duas latitudes e duas
longitudes, e atualmente não desenha diretamente recortes que cruzem o
antimeridiano. `subset_bbox` suporta essa extração, mas a visualização requer
separar as partes ou adaptar o renderizador. Mapas com escala automática distinta
não devem ser comparados apenas pela cor; para comparação quantitativa visual,
será necessário acrescentar limites comuns de cor ao renderizador.

Com `coastlines=True` ou `CAMSAQ_COASTLINES=1`, o Cartopy pode baixar Natural Earth
na primeira execução. Comece sem esse recurso para um teste local independente
de downloads cartográficos. Os contornos não equivalem a observações CAMS.

## Referências oficiais de execução

- nbconvert: https://nbconvert.readthedocs.io/en/latest/execute_api.html
- Cartopy: https://scitools.org.uk/cartopy/docs/v0.24/reference/io.html

## Validação deste complemento

Consulte VALIDACAO.md no pacote. Não foram acessados os dados do computador do
usuário. O resultado científico real deve ser produzido executando o notebook no
ambiente Linux com a base local.
