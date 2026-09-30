# 🌍 CAMS Global Air Quality Historical Database

**Uma biblioteca organizada da atmosfera: dos dados oficiais aos mapas e às análises.**

Este projeto utiliza Python para baixar, verificar, organizar e analisar dados históricos globais de poluição atmosférica do CAMS.

Você pode começar com um único ano, aprender como tudo funciona e ampliar sua base aos poucos.

Pense no projeto como uma biblioteca:

- O **ADS** fornece os livros.
- Os **arquivos originais** são os exemplares preservados.
- O **manifesto** é o catálogo que registra o que já chegou.
- A **validação** confere se cada exemplar está completo.
- Os **dados processados** são preparados para consultas.
- Os **notebooks** são cadernos de estudo.
- Os **mapas e tabelas** apresentam os resultados.

> Este guia descreve a versão 0.1.0 do projeto e o complemento opcional `04_testes_um_ano.ipynb`.
>
> Os exemplos iniciais usam **2003**. Antes de escolher outro período, consulte o inventário.
>
> O estado real da sua base depende dos downloads e das validações realizados na sua máquina.

---

## 📚 Sumário

1. O que o projeto faz
2. Fontes dos dados
3. Poluentes, níveis e unidades
4. Instalação
5. Configuração da chave ADS
6. Configurações do projeto
7. Primeiro teste: somente um ano
8. Validação e inventário
9. Execução dos notebooks
10. Mapas globais e regionais
11. Extração de séries temporais
12. Estatísticas e análises
13. Download de toda a série
14. Atualização incremental
15. Dados subdiários
16. Referência dos comandos
17. Organização dos arquivos
18. Retomada, backup e migração
19. Agendamento
20. Solução de problemas
21. Desenvolvimento e novas variáveis
22. Limitações científicas
23. Glossário e referências

---

## 1. O que o projeto faz

O caminho principal é:

**Consultar → planejar → baixar → validar → organizar → analisar.**

### Funcionalidades disponíveis

| Funcionalidade | Situação |
|---|---|
| Consultar períodos disponíveis nos produtos configurados | Implementada |
| Baixar dados mensais EAC4 | Implementada |
| Baixar dados subdiários EAC4 | Implementada |
| Dividir downloads em lotes pequenos | Implementada |
| Reaproveitar arquivos íntegros | Implementada |
| Registrar pedidos e estados em SQLite | Implementada |
| Validar conteúdo dos arquivos | Implementada |
| Preservar originais | Implementada |
| Produzir NetCDF e Zarr | Implementada |
| Extrair séries de pontos e regiões | Implementada |
| Calcular estatísticas descritivas | Implementada |
| Gerar mapas e executar notebooks | Implementada |
| Testar especificamente um ano | Notebook complementar |
| Baixar automaticamente todas as espécies disponíveis no CAMS | Não implementada |
| Mesclar EAC4 e previsão operacional | Não implementada |
| Servidor de API, dashboard e PostGIS | Extensões futuras |

O projeto consulta os produtos configurados. Ele não é um indexador completo de todos os datasets existentes no ADS.

---

## 2. Fontes dos dados

### O que significam CAMS, ECMWF e ADS?

**CAMS** significa *Copernicus Atmosphere Monitoring Service*, um serviço de monitoramento da composição da atmosfera.

**ECMWF** é o centro europeu responsável por sistemas de previsão e reanálise utilizados pelo serviço.

**ADS** significa *Atmosphere Data Store*, o portal de acesso aos dados atmosféricos.

### O que é a EAC4?

A EAC4 é uma **reanálise da composição atmosférica**.

Uma reanálise combina um modelo com observações para reconstruir as condições do passado. O resultado é uma estimativa organizada em uma grade espacial.

> Um valor da EAC4 representa uma célula do modelo. Ele não equivale automaticamente a uma medição de estação ou à exposição de uma pessoa.

### Produtos utilizados

| Produto | Identificador ADS | Uso |
|---|---|---|
| EAC4 mensal | `cams-global-reanalysis-eac4-monthly` | Produto inicial recomendado |
| EAC4 subdiária | `cams-global-reanalysis-eac4` | Estudos com maior detalhe temporal |
| CAMS operacional | `cams-global-atmospheric-composition-forecasts` | Referência para expansão futura |

O produto operacional está documentado, mas não é baixado ou combinado automaticamente com a EAC4.

### Cobertura espacial e temporal

A grade global ADS utilizada possui:

- resolução de **0,75° × 0,75°**;
- **241 latitudes**;
- **480 longitudes**;
- dados mensais ou subdiários de aproximadamente três em três horas.

A série EAC4 começa em 2003. O último período deve ser consultado no catálogo durante a execução.

O projeto não pressupõe um último ano fixo.

```bash
camsaq inventory
```

A primeira fase arquivou evidências de janeiro de 2003 a dezembro de 2025. Isso é um registro daquela consulta, não uma garantia permanente de cobertura atual.

---

## 3. Poluentes, níveis e unidades

O cadastro fica em:

```text
config/pollutants.yaml
```

### Poluentes inicialmente configurados

| Nome interno | Poluente | Nome ADS | Representação | Unidade processada |
|---|---|---|---|---|
| `pm25` | PM2.5 | `particulate_matter_2.5um` | Concentração single-level | µg/m³ |
| `pm10` | PM10 | `particulate_matter_10um` | Concentração single-level | µg/m³ |
| `co` | Monóxido de carbono | `carbon_monoxide` | Nível de modelo 60 | kg/kg |
| `no2` | Dióxido de nitrogênio | `nitrogen_dioxide` | Nível de modelo 60 | kg/kg |
| `so2` | Dióxido de enxofre | `sulphur_dioxide` | Nível de modelo 60 | kg/kg |
| `o3` | Ozônio | `ozone` | Nível de modelo 60 | kg/kg |

### Por que nível 60?

A EAC4 possui 60 níveis híbridos. O nível 60 é o mais próximo da superfície.

Ele não corresponde necessariamente a uma altura fixa de dois metros.

Não utilize automaticamente a numeração vertical de outros produtos CAMS.

### Conversão de PM2.5 e PM10

A conversão registrada é:

```text
µg/m³ = kg/m³ × 1.000.000.000
```

### Por que os gases continuam em kg/kg?

Porque kg/kg representa uma razão de mistura em massa.

A conversão para µg/m³ exige densidade do ar compatível com o mesmo local, nível e instante. O projeto não utiliza uma constante arbitrária.

As funções de conversão estão em `units.py`, mas não obtêm automaticamente os campos meteorológicos necessários.

> A média de um produto não é, em geral, o produto das médias. Não multiplique médias mensais de razão de mistura e densidade para apresentar uma concentração mensal como exata.

---

## 4. Instalação

### 4.1. Entre na pasta do projeto

Extraia o projeto e entre na pasta que contém `pyproject.toml`, `config/` e `src/`.

Exemplo:

```bash
cd cams-global-air-quality
```

Adapte o caminho à sua máquina.

### 4.2. Use Python 3.11 ou 3.12

Confira:

```bash
python3 --version
```

Se já possui o ambiente `~/envs/cams`:

```bash
source ~/envs/cams/bin/activate
```

Para criar um ambiente novo, usando um interpretador compatível instalado:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
```

Você pode substituir `python3.11` por `python3.12`.

Não é necessário recriar o ambiente a cada uso. Normalmente, basta ativá-lo.

### 4.3. Instale o projeto

Para instalar o pipeline, as ferramentas de desenvolvimento e os notebooks:

```bash
python -m pip install --upgrade pip

python -m pip install -e ".[dev,notebooks]" "nbconvert>=7,<8"

python -m pip check

camsaq --help
```

O comando:

```bash
python -m pip install -e .
```

instala somente as dependências principais.

O `-e` significa instalação editável: o Python utiliza o código da pasta do projeto.

### 4.4. Dependências dos notebooks

Mantenha estes grupos no `pyproject.toml`:

```toml
[project.optional-dependencies]
dev = [
    "pytest>=8,<10",
    "ruff>=0.9",
    "build>=1.2",
]

notebooks = [
    "jupyterlab>=4",
    "nbclient>=0.10",
    "nbconvert>=7,<8",
    "ipykernel>=6,<7",
    "jinja2>=3.1,<4",
]
```

Se a seção já existir, ajuste seu conteúdo. Não crie outra seção com o mesmo nome.

O `requirements.txt` pode conter:

```text
-e .[dev,notebooks]
```

Nesse caso, a instalação pode ser feita com:

```bash
python -m pip install -r requirements.txt
```

Não é necessário executar todas as alternativas de instalação.

### 4.5. Reprodutibilidade

O `requirements-lock.txt` registra versões exatas do ambiente da primeira fase.

Ele não é atualizado automaticamente quando novas dependências são acrescentadas ao `pyproject.toml`.

Depois de validar uma nova configuração, atualize o lock de forma controlada, preservando o histórico.

Para sair do ambiente virtual:

```bash
deactivate
```

---

## 5. Configuração da chave ADS

A chave ADS identifica sua conta quando o programa solicita dados.

Consulte:

https://ads.atmosphere.copernicus.eu/how-to-api

Crie sua conta, obtenha o token e aceite os termos dos datasets utilizados.

### 5.1. Crie o arquivo de credenciais

No Linux:

```bash
nano ~/.cdsapirc
```

Conteúdo:

```yaml
url: https://ads.atmosphere.copernicus.eu/api
key: SUA_CHAVE_PESSOAL
```

Substitua o texto de exemplo pela chave real, somente na sua máquina.

No Nano:

1. Ctrl+O para salvar;
2. Enter para confirmar;
3. Ctrl+X para sair.

Restrinja o acesso:

```bash
chmod 600 ~/.cdsapirc
```

### 5.2. Informe o caminho ao cliente do projeto

```bash
export ECMWF_DATASTORES_RC_FILE="$HOME/.cdsapirc"
```

Esse comando vale para a sessão atual e seus processos filhos.

Para carregar a configuração em novos terminais Bash, acrescente a mesma linha ao final de:

```bash
nano ~/.bashrc
```

Depois:

```bash
source ~/.bashrc
```

Confira apenas o caminho:

```bash
echo "$ECMWF_DATASTORES_RC_FILE"
```

### 5.3. Preciso colocar a chave no projeto?

Não.

| Local | Conteúdo |
|---|---|
| `~/.cdsapirc` | URL e chave |
| `~/.bashrc` | Caminho do arquivo de credenciais |
| Projeto | Código e configurações sem segredos |

O cliente avançado também aceita `~/.ecmwfdatastoresrc` como arquivo padrão.

Não coloque a chave no Git, em notebooks, prints ou mensagens.

Se estiver trabalhando por SSH, configure as credenciais no Linux remoto, para o usuário que executará o pipeline.

Tarefas `cron`, serviços `systemd` e alguns aplicativos gráficos não leem o `.bashrc`. Nesses casos, configure explicitamente o caminho das credenciais no ambiente do processo.

---

## 6. Configurações do projeto

Os dois arquivos principais são:

```text
config/config.yaml
config/pollutants.yaml
```

O primeiro controla a execução. O segundo descreve os poluentes.

### Limitar a um ano

Altere estas chaves no arquivo existente, preservando as demais:

```yaml
start_date: "2003-01"
end_date: "2003-12"

pollutants:
  - pm25
  - pm10
  - co
  - no2
  - so2
  - o3

workers: 1
area: null
```

### Utilizar toda a cobertura disponível

```yaml
start_date: null
end_date: null
```

`null` significa que a configuração não impõe aquele limite temporal.

Os argumentos `--start` e `--end` do comando têm prioridade sobre o arquivo.

### Principais opções

| Opção | Função |
|---|---|
| `data_dir` | Diretório dos dados |
| `metadata_dir` | Manifesto, inventários e QC |
| `log_dir` | Diretório dos logs |
| `data_format` | `grib` ou `netcdf_zip` |
| `workers` | Concorrência entre 1 e 4 |
| `retry_attempts` | Número de tentativas |
| `backoff_seconds` | Espera inicial entre novas tentativas |
| `http_timeout` | Timeout HTTP |
| `job_timeout_seconds` | Tempo de espera por um pedido remoto nesta tentativa |
| `poll_seconds` | Intervalo de consulta do pedido |
| `min_free_disk_gib` | Reserva mínima de disco |
| `max_download_gib` | Limite de tamanho de um lote remoto |
| `storage_copies` | Multiplicador usado na estimativa de armazenamento |
| `chunks` | Tamanho dos blocos de dados |
| `area` | `null` para cobertura global |
| `netcdf_engine` | Backend de leitura/escrita NetCDF |
| `qc` | Critérios de validação |

Comece com `workers: 1`.

Não altere a configuração da grade para contornar uma incompatibilidade encontrada no arquivo.

### Outra configuração

O argumento `--config` vem antes do subcomando:

```bash
camsaq --config config/config_teste.yaml inventory \
  --start 2003-01 --end 2003-12
```

Os caminhos relativos dependem de `root` e da localização do YAML. Confira-os ao copiar uma configuração para outra pasta.

---

## 7. Primeiro teste: somente um ano

🎯 **Missão inicial: completar e verificar 2003.**

São 12 meses para seis poluentes: 72 lotes mensais na organização padrão.

Execute uma etapa por vez.

### Etapa A — testes do código

```bash
python -m pytest -q
```

Os testes utilizam mocks e pequenos dados de exemplo.

### Etapa B — inventário e planejamento

```bash
camsaq inventory --start 2003-01 --end 2003-12

camsaq plan --kind monthly --start 2003-01 --end 2003-12
```

Esses comandos não baixam os campos CAMS.

O plano é registrado em:

```text
metadata/plan-monthly.json
```

### Etapa C — pilotos reais

```bash
camsaq smoke --start 2003-01 --end 2003-01 --pollutants pm25

camsaq smoke --start 2003-01 --end 2003-01 --pollutants co
```

Esses pilotos verificam as duas representações usadas pelo projeto: PM single-level e gás no nível de modelo 60.

`smoke` utiliza somente o primeiro mês e a primeira variável da seleção.

### Etapa D — completar o ano

```bash
camsaq download-monthly --start 2003-01 --end 2003-12
```

Arquivos íntegros já reconhecidos pelo manifesto são reaproveitados.

### Etapa E — verificar os resultados

```bash
camsaq inventory --start 2003-01 --end 2003-12

camsaq validate
```

Para completar processamento e consolidação, se necessário:

```bash
camsaq process --kind monthly

camsaq consolidate --kind monthly
```

Esses dois comandos trabalham com os dados locais.

> `validate`, `process` e `consolidate` não possuem filtros de data nesta versão.
>
> Um ano seguinte parcialmente baixado pode aparecer no QC ou impedir a consolidação por cobertura desigual entre poluentes.
>
> Limitar o download não filtra automaticamente essas outras etapas. Preserve os arquivos e examine a mensagem de erro.

Se você já consegue abrir `ds`, existe uma base consolidada. Não é necessário reconstruí-la apenas para executar novamente os notebooks.

---

## 8. Validação e inventário

Para cada poluente do ano escolhido, o esperado é:

| Campo | Resultado |
|---|---|
| `months_expected` | 12 |
| `months_available` | 12 |
| `missing` | 0 |
| `status` | `COMPLETE` |

Isso não significa que existam apenas 72 arquivos no disco: produtos NetCDF, chunks Zarr e relatórios aumentam essa quantidade.

### O que o QC verifica?

Entre outros critérios:

- abertura do arquivo;
- variável solicitada;
- nível vertical;
- unidades;
- dimensões e coordenadas;
- intervalo e continuidade temporal;
- valores ausentes;
- valores infinitos;
- integridade por checksum.

### Como interpretar o resultado

| Resultado | Significado |
|---|---|
| `PASS` | Passou nas verificações implementadas |
| `WARNING` | Precisa de investigação |
| `FAIL` | Não atende aos critérios |

Consulte:

```text
metadata/qc-report.json
logs/camsaq.log
```

O inventário confirma cobertura. O QC confirma critérios de integridade e conteúdo. Nenhum dos dois substitui a avaliação científica de adequação à sua pesquisa.

---

## 9. Execução dos notebooks

Um notebook é um caderno com texto, código e resultados.

Execute as células de cima para baixo.

### 9.1. Registrar o kernel correto

Com o ambiente ativado:

```bash
python -m ipykernel install --user \
  --name camsaq \
  --display-name "Python (CAMS Air Quality)"
```

Selecione esse kernel no Positron, VS Code ou Jupyter.

Para iniciar o JupyterLab:

```bash
jupyter lab
```

Dentro de uma célula, confira:

```python
import sys
import cams_air_quality

print(sys.executable)
print(cams_air_quality.__file__)
```

### 9.2. O que cada notebook faz?

| Notebook | Função |
|---|---|
| `01_inventory.ipynb` | Inventário e estimativas |
| `02_global_climatology.ipynb` | Séries, mapas, climatologias e anomalias |
| `03_timeseries_example.ipynb` | São Paulo e uma região |
| `04_testes_um_ano.ipynb` | Verificações e produtos de um único ano |

O notebook 04 é um complemento entregue em `CAMS_Teste_Um_Ano.zip`. Copie-o para `notebooks/`.

O notebook 01 utiliza snapshots arquivados por padrão.

O notebook 02 original possui referências a 2003–2022 e mapas de 2020. Ajuste todas as datas antes de executá-lo com outra cobertura.

Para a primeira análise de um ano, prefira o notebook 04.

### 9.3. Executar pela linha de comando

Na raiz do projeto:

```bash
mkdir -p reports/executed

CAMSAQ_YEAR=2003 CAMSAQ_MONTH=7 \
python -m nbconvert \
  --to notebook \
  --execute notebooks/04_testes_um_ano.ipynb \
  --ExecutePreprocessor.kernel_name=camsaq \
  --ExecutePreprocessor.timeout=900 \
  --output 04_testes_2003_executado.ipynb \
  --output-dir reports/executed
```

O comando:

- executa as células;
- usa o kernel `camsaq`;
- permite até 900 segundos por célula;
- salva uma cópia com os resultados;
- preserva o notebook fonte.

Erros interrompem a execução. Não use `--allow-errors` para considerar testes aprovados.

### Parâmetros do notebook 04

| Variável | Padrão | Função |
|---|---|---|
| `CAMSAQ_YEAR` | `2003` | Ano analisado |
| `CAMSAQ_MONTH` | `7` | Mês dos mapas |
| `CAMSAQ_CONFIG` | Configuração encontrada na pasta do projeto | YAML alternativo |
| `CAMSAQ_COASTLINES` | `0` | `1` ativa linhas de costa |

Esses parâmetros são do notebook 04. Os notebooks anteriores não passam a utilizá-los automaticamente.

### 9.4. Executar outro notebook

```bash
python -m nbconvert \
  --to notebook \
  --execute notebooks/01_inventory.ipynb \
  --ExecutePreprocessor.kernel_name=camsaq \
  --ExecutePreprocessor.timeout=900 \
  --output 01_inventory_executado.ipynb \
  --output-dir reports/executed
```

Troque o nome do arquivo para executar outro caderno.

Cada notebook inicia uma sessão independente. Variáveis criadas no notebook 01 não ficam disponíveis no 02.

### 9.5. Exportar para HTML

```bash
python -m nbconvert --to html \
  reports/executed/04_testes_2003_executado.ipynb \
  --output-dir reports/executed
```

O HTML pode ser aberto no navegador.

Esse comando exporta as saídas existentes; não executa novamente os cálculos.

### Produtos do notebook 04

- 72 registros de verificação dos campos processados;
- seis séries globais mensais;
- médias globais anuais;
- mapa global do mês escolhido;
- mapa da média anual de PM2.5;
- três mapas regionais de PM2.5;
- séries regionais;
- extração da célula próxima de São Paulo;
- CSV, Parquet e relatório JSON.

Os resultados ficam em:

```text
reports/one_year/<ano>/<identificador_da_execução>/
```

---

## 10. Mapas globais e regionais

### Mapa global pelo terminal

```bash
camsaq map \
  --pollutant pm25 \
  --date 2003-07 \
  --output reports/maps/pm25_global_2003_07.png
```

Para incluir linhas de costa, acrescente:

```text
--coastlines
```

O Cartopy poderá baixar os contornos Natural Earth na primeira utilização.

### Como escolher uma região?

A ordem do bbox é:

```text
[norte, oeste, sul, leste]
```

| Janela aproximada | Norte | Oeste | Sul | Leste |
|---|---:|---:|---:|---:|
| Brasil e entorno | 6 | -75 | -35 | -30 |
| Sudeste e entorno | -14 | -54 | -26 | -38 |
| Europa e entorno | 72 | -25 | 34 | 45 |
| América do Sul e entorno | 13 | -82 | -57 | -34 |

O bbox é um retângulo. Ele não recorta exatamente as fronteiras de um país ou estado.

### Mapa regional em Python

```python
from pathlib import Path

from cams_air_quality.config import load_config
from cams_air_quality.processing import open_database
from cams_air_quality.extraction import subset_bbox
from cams_air_quality.maps import plot_map

cfg = load_config("config/config.yaml")

output = (
    Path(cfg["root"])
    / "reports/maps/pm25_brasil_2003_07.png"
)

with open_database(cfg) as ds:
    field = ds["pm25"].sel(time="2003-07-01", drop=True)

    regional = subset_bbox(
        field,
        north=6,
        west=-75,
        south=-35,
        east=-30,
    )

    plot_map(
        regional,
        output,
        title="PM2.5 — Brasil e entorno — julho de 2003",
    )

print(output)
```

Para exibir no notebook:

```python
from IPython.display import Image, display

display(Image(filename=str(output)))
```

O comando `camsaq map` ainda não possui `--bbox`. Use Python ou o notebook 04 para os recortes.

### Regiões no notebook 04

Edite a primeira célula:

```python
REGIOES = {
    "brasil_bbox": [6, -75, -35, -30],
    "europa_bbox": [72, -25, 34, 45],
}
```

Será produzido um mapa para cada entrada.

### Média anual

```python
from cams_air_quality.statistics import annual_mean

with open_database(cfg) as ds:
    year = ds["pm25"].sel(
        time=slice("2003-01-01", "2003-12-31")
    )

    yearly = annual_mean(year)

    if yearly.sizes["time"] != 1:
        raise ValueError("O ano precisa ter os 12 meses.")

    field = yearly.isel(time=0, drop=True)
    regional = subset_bbox(field, 72, -25, 34, 45)

    plot_map(
        regional,
        Path(cfg["root"]) / "reports/maps/pm25_europa_2003.png",
        title="PM2.5 — Europa e entorno — média anual de 2003",
    )
```

### Cuidados ao interpretar mapas

- O recorte preserva a resolução original.
- Não há criação de detalhes de bairros ou ruas.
- O bbox pode incluir oceano e territórios vizinhos.
- O renderizador precisa de pelo menos duas latitudes e duas longitudes.
- A extração suporta antimeridiano, mas o renderizador atual exige adaptação para desenhar diretamente esse tipo de recorte.
- A escala de cores é automática por imagem. Compare as barras numéricas, não apenas as cores.
- Mapas de gases continuam em kg/kg.

---

## 11. Extração de séries temporais

### Uma coordenada

```bash
camsaq extract-point \
  --pollutant pm25 \
  --lat -23.5505 \
  --lon -46.6333 \
  --output reports/sao_paulo_pm25.parquet
```

O programa escolhe o centro de célula mais próximo e registra sua localização e distância aproximada.

Essa coordenada é um exemplo de extração, não uma estação.

### Uma região

```bash
camsaq extract-region \
  --pollutant no2 \
  --bbox -14 -54 -26 -38 \
  --output reports/sudeste_no2.csv
```

A média regional é ponderada pela área das células.

### Em Python

```python
from cams_air_quality.config import load_config
from cams_air_quality.extraction import (
    get_timeseries,
    get_region_timeseries,
    save_table,
)

cfg = load_config()

point = get_timeseries(
    cfg,
    pollutant="pm25",
    lat=-23.5505,
    lon=-46.6333,
)

region = get_region_timeseries(
    cfg,
    pollutant="no2",
    bbox=[-14, -54, -26, -38],
)

print(point.head())

save_table(point, "reports/sao_paulo.csv")
save_table(region, "reports/sudeste.parquet")
```

As funções retornam DataFrames pandas.

CSV e Parquet recebem um arquivo `.metadata.json` acompanhante. Preserve os dois ao compartilhar os resultados.

Essas interfaces usam a base mensal aberta. Para limitar um ano, filtre o DataFrame ou utilize o notebook 04.

---

## 12. Estatísticas e análises

| Função | Resultado |
|---|---|
| `area_mean` | Média espacial ponderada por área |
| `annual_mean` | Média anual ponderada pelos dias dos meses |
| `climatology` | Média de cada mês no período de referência |
| `anomalies` | Diferença em relação à referência mensal |
| `linear_trend` | Inclinação linear descritiva por ano |
| `summaries` | Conjunto de médias, tendência, percentis e dispersão |

`summaries` inclui:

- média espacial mensal;
- média espacial anual;
- média zonal;
- tendência linear;
- percentis 5%, 50% e 95%;
- mínimo;
- máximo;
- desvio padrão com `ddof=0`.

### Quando há somente um ano

Você pode analisar:

- ciclo mensal;
- média anual;
- distribuição espacial;
- diferenças entre regiões.

Não apresente esse resultado como climatologia de longo prazo.

Calcular anomalias de um ano usando cada mês desse mesmo ano como referência produzirá diferenças nulas.

### Quando há vários anos

Escolha explicitamente o período de referência.

O exemplo abaixo exige 2003–2022 completo:

```bash
camsaq analyze \
  --baseline-start 2003-01 \
  --baseline-end 2022-12 \
  --output reports/exploratory
```

O programa não encurta silenciosamente uma referência indisponível.

O comando produz análises de PM2.5, NO2 e O3, mapas médios, séries e extração de São Paulo.

Escolha pastas distintas para preservar resultados de análises diferentes.

### Exemplo regional

```python
from pathlib import Path

from cams_air_quality.config import load_config
from cams_air_quality.processing import open_database
from cams_air_quality.extraction import subset_bbox
from cams_air_quality.statistics import summaries

cfg = load_config()

output = Path(cfg["root"]) / "reports/statistics"
output.mkdir(parents=True, exist_ok=True)

with open_database(cfg) as ds:
    field = subset_bbox(ds.pm25, -14, -54, -26, -38)
    results = summaries(field)

    results["global_monthly"].to_netcdf(
        output / "regional_monthly.nc",
        engine=cfg["netcdf_engine"],
    )
```

A chave se chama `global_monthly`, mas, nesse exemplo, a entrada já foi recortada. Portanto, o resultado representa a região selecionada.

Calcule ou salve os resultados enquanto o dataset estiver aberto.

Evite carregar toda a série histórica com `ds.load()`.

---

## 13. Download de toda a série

Depois dos pilotos e do teste anual, configure:

```yaml
start_date: null
end_date: null
```

Então:

```bash
camsaq plan --kind monthly

camsaq download-monthly

camsaq inventory
```

O projeto usa lotes por variável e mês, não uma requisição gigantesca para décadas inteiras.

A disponibilidade é consultada antes dos pedidos.

Confira o espaço previsto pelo plano antes de avançar.

---

## 14. Atualização incremental

Para verificar períodos novos e preencher lacunas:

```bash
camsaq update
```

Alternativa equivalente:

```bash
python -m cams_air_quality update
```

Para restringir a atualização a um ano:

```bash
camsaq update --start 2003-01 --end 2003-12
```

A atualização:

1. consulta o catálogo;
2. considera o período selecionado;
3. compara os lotes com o manifesto;
4. reaproveita arquivos íntegros;
5. baixa e processa o que estiver faltando.

Ela também procura lacunas antigas.

Se o provedor revisar um mês sem mudar seu identificador, o projeto não substitui automaticamente um arquivo local já validado. Revisões retroativas exigem uma política explícita de versionamento.

---

## 15. Dados subdiários

Os dados subdiários oferecem oito horários por dia, mas exigem muito mais armazenamento.

Comece planejando:

```bash
camsaq plan \
  --kind subdaily \
  --start 2003-01 \
  --end 2003-12
```

Teste dois pilotos:

```bash
camsaq smoke \
  --kind subdaily \
  --start 2003-01 \
  --end 2003-01 \
  --pollutants pm25

camsaq smoke \
  --kind subdaily \
  --start 2003-01 \
  --end 2003-01 \
  --pollutants co
```

Avance em lotes:

```bash
camsaq download-subdaily \
  --start 2003-01 \
  --end 2003-12 \
  --max-batches 12
```

`--max-batches 12` significa até 12 lotes selecionados para download, não necessariamente 12 meses de todos os poluentes.

Para processar e consolidar:

```bash
camsaq process --kind subdaily

camsaq consolidate --kind subdaily
```

Para abrir em Python:

```python
with open_database(cfg, kind="subdaily") as ds_subdaily:
    print(ds_subdaily.sizes)
```

Os notebooks e comandos prontos de análise são orientados à base mensal. As estatísticas mensais não devem ser aplicadas diretamente a uma sequência de três em três horas.

### Como interpretar a estimativa de espaço

O planejamento utiliza valores float32 sem compressão e um multiplicador para cópias e temporários.

Isso não é:

- o tamanho exato do download;
- uma promessa de tempo de execução;
- uma medição do espaço final comprimido.

Para seis variáveis globais de 2003–2025, a estimativa histórica foi de aproximadamente:

| Produto | Apenas valores float32 |
|---|---:|
| Mensal | 0,714 GiB |
| Subdiário | 173,78 GiB |

Quatro cópias do volume subdiário já se aproximam de 695 GiB, antes de margens adicionais.

Use sempre o plano da seleção atual.

---

## 16. Referência dos comandos

```bash
camsaq --help
camsaq download-monthly --help
```

| Comando | Finalidade |
|---|---|
| `inventory` | Comparar cobertura esperada e local |
| `plan` | Montar pedidos e estimar disco |
| `smoke` | Executar um piloto |
| `download-monthly` | Baixar e processar dados mensais |
| `download-subdaily` | Baixar e processar dados subdiários |
| `update` | Atualizar a base mensal |
| `validate` | Verificar originais registrados |
| `process` | Produzir ou verificar derivados NetCDF |
| `consolidate` | Construir os Zarr anuais e o índice |
| `extract-point` | Exportar série de uma célula |
| `extract-region` | Exportar média regional |
| `map` | Salvar um mapa mensal |
| `analyze` | Executar análise exploratória mensal |

### Opções de período e seleção

`inventory`, `plan`, `smoke`, downloads e `update` aceitam `--start`, `--end` e `--pollutants`.

Exemplo:

```bash
camsaq download-monthly \
  --start 2003-01 \
  --end 2003-12 \
  --pollutants pm25 pm10
```

Essa seleção não modifica permanentemente o YAML.

Quando há seleção explícita de poluentes pela CLI, o caminho atual não faz consolidação automática.

Para consolidar somente duas variáveis, utilize uma configuração cujo campo `pollutants` corresponda a esse conjunto e execute `consolidate` explicitamente.

### Consulta offline

```bash
camsaq inventory \
  --start 2003-01 \
  --end 2003-12 \
  --offline-evidence evidence
```

A opção existe em `inventory` e `plan`.

O resultado descreve um snapshot histórico, não a disponibilidade atual.

### Atalhos em scripts

Há também:

```text
scripts/download_monthly.py
scripts/download_subdaily.py
scripts/update_database.py
scripts/validate_archive.py
```

Instale o projeto antes de utilizá-los.

Para configurações alternativas, prefira a CLI principal com `--config`.

---

## 17. Organização dos arquivos

| Local | Conteúdo |
|---|---|
| `src/cams_air_quality/` | Código Python |
| `config/` | Configurações |
| `data/raw/eac4/` | Originais |
| `data/interim/` | Intermediários e cache |
| `data/processed/eac4/` | NetCDF e Zarr |
| `metadata/downloads.sqlite` | Manifesto |
| `metadata/` | Planos, inventários e QC |
| `logs/` | Logs |
| `reports/` | Figuras, tabelas e relatórios |
| `notebooks/` | Cadernos |
| `tests/` | Testes automatizados |
| `evidence/` | Evidências do catálogo |
| `docs/` | Documentação técnica e científica |

### Estados do manifesto

```text
requested → downloading → downloaded → validated → processed
```

Falhas de aquisição ou QC podem receber `failed`.

Uma falha apenas no processamento pode preservar o original como `validated`, com um erro de processamento registrado.

### Formatos

- **GRIB/ZIP:** arquivos originais.
- **NetCDF4/HDF5:** interoperabilidade científica.
- **Zarr:** leitura de blocos e análise com xarray/Dask.
- **CSV/Parquet:** produtos tabulares.
- **SQLite:** controle do pipeline.

O Zarr é organizado por ano. Atualizações podem criar novas gerações, mantendo as anteriores.

O arquivo `index.json` aponta para as gerações publicadas.

### Proveniência

Os registros permitem identificar:

- dataset;
- pedido;
- arquivo original;
- checksum;
- data de download;
- conversões;
- processamento;
- versão do código.

Um checksum identifica mudanças nos bytes. Ele não demonstra, sozinho, correção científica.

---

## 18. Retomada, backup e migração

### Se o processo for interrompido

Execute novamente o mesmo comando, com os mesmos limites.

O manifesto ajuda a reconhecer arquivos íntegros e pedidos remotos.

Arquivos parciais podem ser retomados quando o servidor e a identidade do arquivo permitem. Em alguns casos, aquele arquivo precisa recomeçar.

Não há garantia de exatamente uma submissão remota em toda situação possível de interrupção.

### Repetir somente falhas

```bash
camsaq download-monthly \
  --start 2003-01 \
  --end 2003-12 \
  --retry-failed
```

Essa opção não inclui automaticamente lotes nunca solicitados.

Para erros apenas nos derivados, utilize:

```bash
camsaq process
```

### Levar a base a outra máquina

1. Pare os processos que escrevem nos dados e no banco.
2. Preserve código, configurações, `data/` e `metadata/`.
3. Recrie o ambiente Python.
4. Configure as credenciais separadamente.
5. Reconcilie os caminhos do manifesto.
6. Execute inventário e QC.

O manifesto contém caminhos absolutos.

Alterar somente `data_dir` não migra automaticamente todos os registros.

Não existe um comando completo de migração nesta versão. A reconciliação deve ser revisada antes de retomar a operação.

Com o SQLite em uso, utilize a API de backup do SQLite. Copiar somente o arquivo principal pode ignorar transações presentes no WAL.

---

## 19. Agendamento

O comando `update` executa uma atualização quando chamado.

Ele não instala um serviço e não fica ativo permanentemente.

Depois de validar a execução manual, você pode utilizar `cron` ou `systemd`.

Exemplo de entrada de cron, com caminhos a substituir:

```cron
0 6 5 * * cd /CAMINHO/DO/PROJETO && ECMWF_DATASTORES_RC_FILE=/home/USUARIO/.cdsapirc /usr/bin/flock -n metadata/update.lock /CAMINHO/DO/AMBIENTE/bin/python -m cams_air_quality update >> logs/scheduler.log 2>&1
```

Esse exemplo executa às 06h do dia 5 de cada mês, conforme o fuso da máquina.

As pastas `metadata/` e `logs/` precisam existir.

O `flock` evita duas execuções agendadas simultâneas.

A chave não aparece no comando: apenas o caminho do arquivo.

Este README não cria a tarefa automaticamente.

---

## 20. Solução de problemas

| Problema | O que verificar |
|---|---|
| `camsaq: command not found` | Ambiente ativado e pacote instalado |
| `No module named cams_air_quality` | Kernel correto e instalação editável |
| Chave ausente / HTTP 401 | Credenciais e caminho do arquivo |
| HTTP 403 | Conta, permissões e termos do dataset |
| `index.json` ausente | Configuração, processamento e consolidação |
| Referência climatológica indisponível | Datas realmente existentes |
| `Unequal variable coverage` | Lacunas diferentes entre poluentes |
| `NoneType ... render` | Jinja2 no ambiente do notebook |
| `'list' object has no attribute 'set_title'` | Uso correto do objeto `ax` |
| Falha ao baixar linhas de costa | Rede/cache do Natural Earth |
| Pouco espaço | Plano, período e tamanho dos lotes |
| Testes aprovados seguidos de abortamento | Bibliotecas nativas e código de saída |

### Verificar a cobertura aberta

```python
print(ds)
print(ds.time.min().values)
print(ds.time.max().values)
print(ds.time.to_index().strftime("%Y-%m").tolist())
```

### Corrigir exibição HTML

No kernel correto:

```python
%pip install "jinja2>=3.1,<4"
```

Reinicie o kernel.

Enquanto isso, a representação textual pode ser usada:

```python
print(ds)
```

### Criar corretamente um gráfico de linha

```python
import matplotlib.pyplot as plt

fig, ax = plt.subplots(figsize=(9, 4))

pm25_global.plot(ax=ax, marker="o")

ax.set_title("PM2.5 — média global mensal")
ax.set_xlabel("Data")
ax.set_ylabel("PM2.5 [µg/m³]")

fig.tight_layout()
plt.show()
```

### Sobre a mensagem de referência indisponível

Se a base contém apenas 2003, uma referência 2003–2022 deve falhar.

Essa proteção evita produzir resultados incompletos com aparência de climatologia válida.

### Sobre problemas de bibliotecas nativas

Se o processo abortar depois de mostrar testes aprovados, a execução não terminou corretamente.

Consulte:

```text
docs/ENVIRONMENT_RECOVERY.md
```

Preserve as versões compatíveis e o isolamento do renderizador de mapas.

---

## 21. Desenvolvimento e novas variáveis

Para verificar o código:

```bash
python -m pytest -q
python -m ruff check src tests
```

Adicionar um constituinte exige:

1. confirmar seu nome no formulário atual do ADS;
2. confirmar o produto em que está disponível;
3. identificar a grandeza física;
4. verificar nível, unidades e aliases;
5. cadastrar a variável;
6. implementar conversões adicionais, se necessárias;
7. adicionar testes;
8. executar um piloto real;
9. estimar recursos.

Não basta acrescentar um nome imaginado ao YAML.

Black carbon, sulfato, poeira, metano e profundidade óptica podem representar grandezas distintas e exigir tratamentos diferentes.

### Git

Versione:

- código;
- documentação;
- configurações sem segredos;
- testes;
- pequenos exemplos.

Não versione:

- dados brutos;
- Zarr;
- credenciais;
- logs;
- grandes resultados.

Antes de adicionar alterações:

```bash
git status --short
git diff
```

O Git local não implica publicação automática no GitHub.

---

## 22. Limitações científicas

- Uma célula de 0,75° não representa uma residência ou rua.
- Reanálises dependem do modelo e das observações assimiladas.
- Mudanças no sistema de observação podem afetar a série.
- Média espacial por área não equivale a exposição populacional.
- Gases no nível 60 não são medições a dois metros.
- Tendências OLS são descritivas e não ajustam automaticamente sazonalidade ou autocorrelação.
- Aplicações epidemiológicas exigem desenho e validação próprios.
- A EAC4 e o operacional não devem ser concatenados silenciosamente.
- Recortes retangulares não são máscaras de fronteiras.
- Percentis exatos podem exigir muita memória em séries subdiárias.
- O mecanismo atual de publicação Zarr foi pensado para filesystem local.

### Melhorias futuras

- filtros de período para consolidação;
- migração automatizada;
- máscaras de polígonos;
- escalas de cores comuns entre mapas;
- mais constituintes;
- integração meteorológica;
- API;
- dashboard;
- PostGIS;
- estudos de exposição e epidemiologia com validação adequada.

---

## 23. Glossário e referências

### Pequeno dicionário

| Termo | Significado |
|---|---|
| API | Interface usada pelo programa para solicitar dados |
| Token | Credencial pessoal |
| CLI | Interface por comandos |
| Kernel | Python que executa o notebook |
| Reanálise | Reconstrução do passado com modelo e observações |
| Manifesto | Catálogo persistente dos lotes |
| QC | Controle de qualidade |
| Checksum | Impressão digital dos bytes |
| Chunk | Bloco de dados |
| Lazy | Cálculo executado quando necessário |
| Zarr | Armazenamento de arrays em blocos |
| Bbox | Retângulo geográfico |
| Climatologia | Referência construída sobre um período |
| Anomalia | Diferença em relação à referência |
| Proveniência | Histórico de origem e processamento |

### Documentação do projeto

- [Fonte dos dados](cams-global-air-quality/docs/DATA_SOURCE.md)
- [Variáveis](cams-global-air-quality/docs/VARIABLES.md)
- [Arquitetura](cams-global-air-quality/docs/ARCHITECTURE.md)
- [Dicionário de dados](cams-global-air-quality/docs/DATA_DICTIONARY.md)
- [Operação](cams-global-air-quality/docs/OPERATIONS.md)
- [Extensão operacional](cams-global-air-quality/docs/OPERATIONAL_EXTENSION.md)
- [Limitações da primeira fase](cams-global-air-quality/docs/KNOWN_LIMITATIONS.md)
- [Recuperação do ambiente](cams-global-air-quality/docs/ENVIRONMENT_RECOVERY.md)
- [Relatório histórico da primeira fase](cams-global-air-quality/reports/PHASE1_REPORT.md)

### Fontes oficiais

- [Configuração da API ADS](https://ads.atmosphere.copernicus.eu/how-to-api)
- [EAC4 mensal](https://ads.atmosphere.copernicus.eu/datasets/cams-global-reanalysis-eac4-monthly)
- [EAC4 subdiária](https://ads.atmosphere.copernicus.eu/datasets/cams-global-reanalysis-eac4)
- [CAMS operacional](https://ads.atmosphere.copernicus.eu/datasets/cams-global-atmospheric-composition-forecasts)
- [Documentação da reanálise CAMS](https://confluence.ecmwf.int/display/CKB/CAMS%3A+Reanalysis+data+documentation)
- [Cliente ECMWF Data Stores](https://ecmwf.github.io/ecmwf-datastores-client/)
- [Execução com nbconvert](https://nbconvert.readthedocs.io/en/latest/execute_api.html)
- [Dados cartográficos no Cartopy](https://scitools.org.uk/cartopy/docs/v0.24/reference/io.html)
- [Artigo da EAC4 — Inness et al. (2019)](https://doi.org/10.5194/acp-19-3515-2019)

Ao publicar análises, registre dataset, período, unidades, versão do código, métodos, recortes e referência climatológica.

Observe os termos do provedor e cite os dados utilizados.

---

**Guia revisado em 30/09/2026.**

Comece com um ano, confira cada etapa e amplie a base mantendo o mesmo cuidado com integridade, unidades e rastreabilidade.
