# Operação e manutenção

## Sequência recomendada

1. Configurar venv, credencial e aceite de licença; executar testes.
2. `camsaq inventory` e `camsaq plan --kind monthly` ao vivo.
3. `camsaq smoke ... --pollutants pm25` e `... --pollutants co`.
4. Examinar `metadata/downloads.sqlite` e o QC dos pilotos, inclusive nível/unidade.
5. `camsaq download-monthly`; `camsaq validate`; `camsaq inventory`.
6. `camsaq consolidate` se necessário. A aquisição completa já tenta consolidar.
7. `camsaq analyze --baseline-start ... --baseline-end ...`.
8. Atualizações subsequentes: `python -m cams_air_quality update`.

Para repetir a leitura dos snapshots incluídos sem dependência de rede:

```bash
camsaq inventory --offline-evidence evidence
camsaq plan --kind subdaily --offline-evidence evidence
```

Essa opção só existe em comandos de leitura/planejamento; downloads sempre
revalidam o catálogo. Nunca altere manualmente um final de série só para fazer
um pedido passar. Novos campos/formats não reconhecidos exigem revisar o adaptador.

## Erros e recuperação

- API key ausente: configurar arquivo do SDK, sem compartilhar chave.
- HTTP 401/403: verificar conta, token, URL ADS e termos. Não repetir milhares de pedidos.
- HTTP 429/5xx ou conexão interrompida: backoff exponencial com jitter e tentativas limitadas.
- Deadline de job: ID permanece no SQLite; rode o mesmo comando depois.
- Arquivo truncado: `.part` permanece e o Range tenta continuar.
- QC FAIL: payload isolado com sufixo `.corrupt-*`; consultar `qc_json`.
- Arquivo bom mas derivado ausente: `camsaq process`, sem nova recuperação ADS.
- Checksum do derivado mudou: reconstrução a partir do original verificado.
- Pouco disco: mude `data_dir` **antes** de construir o arquivo ou use lotes
  limitados. Transferir um arquivo já existente exige também reconciliar caminhos
  absolutos do manifesto e revalidar checksums.

Não apague `metadata/` ao retomar: nele ficam IDs de jobs, estados e catálogo.
Faça backup de SQLite e dos originais em consistência com o filesystem. Para
backup do banco em uso, use a API de backup SQLite; não copie apenas o arquivo
principal ignorando WAL. Pare o pipeline ao mover todo o arquivo.

## Agendamento opcional no Ubuntu

A CLI faz atualização incremental quando executada; esta entrega não instala
serviços na máquina do usuário. Depois dos pilotos, um cron local pode chamar:

```cron
# Todo dia 5 do mês às 06h locais da máquina, exemplo editável.
0 6 5 * * cd /caminho/cams-global-air-quality && /usr/bin/flock -n metadata/update.lock .venv/bin/python -m cams_air_quality update >> logs/scheduler.log 2>&1
```

A periodicidade deve ser compatível com a publicação do produto; não há ganho em
consultar incessantemente. O lock evita duas atualizações agendadas simultâneas.

## Recursos e benchmark

`plan` calcula n_variáveis × n_tempos × n_lat × n_lon × 4 bytes, sem assumir uma
razão universal de compressão. O orçamento de quatro cópias representa original,
intermediário, processado e temporário; reservas para gerações antigas, backups,
ZIP e filesystem são adicionais. A estimativa para bbox é global, conservadora.

Depois de uma amostra real, meça `filesize`, elapsed e pico de RAM de 1 mês por
tipo vertical. Extrapole com intervalo, não uma promessa de tempo total. Filas ADS
podem dominar o tempo e dados em fita podem ser mais lentos. Não exceda quatro
workers sem reprojetar explicitamente política de serviço e integração.

A criação de Zarr anual reescreve apenas o ano alterado e mantém gerações antigas.
Planeje limpeza manual após validar backups; o pipeline não apaga dados bons.
NetCDF bruto convertido do ZIP permanece no cache `interim/unpacked` para
reutilização. Alterar chunks ou versão do código pode gerar novos derivados.

Logs incluem timestamps UTC no conteúdo JSON, dataset, variável, ano/mês, request,
status, bytes, elapsed, erro sanitizado e tentativa. Não incluem token nem URL
assinada. `metadata/qc-report.json` é produzido por `camsaq validate`.
