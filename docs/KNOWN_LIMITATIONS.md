# Limitações conhecidas e critérios de liberação

1. **Integração autenticada pendente.** Catálogo, formulário e constraints reais
   foram recuperados. Sem token, a tentativa de download foi bloqueada no SDK
   antes da submissão. O código ainda precisa ser exercitado contra payloads
   mensais PM/gás e subdiários reais. Um teste sintético de GRIB não certifica
   a convenção mensal real ou o conteúdo NetCDF experimental do ADS.
2. **Ciência ainda sem dados locais.** Nenhuma EDA real foi executada. Notebooks e
   `analyze` são reproduzíveis quando a base existir; falham com mensagem clara
   quando ela não existe. Não se incluem mapas simulados com aparência de resultados.
3. **NetCDF do ADS é experimental.** Variáveis ou coordenadas sem metadados
   suficientes para comprovar nível falham intencionalmente. Prefira GRIB nativo.
   ZIP por lote limita descompressão a 4 GiB; novos agrupamentos grandes exigem revisão.
4. **Cliente incubating.** API avançada 0.5.3 fixada; mudanças de esquema são
   detectadas no formulário e nos testes, mas evolução do provedor pode exigir manutenção.
5. **Cobertura global regular.** Máscaras bbox usam centros de células; média
   regional não é interseção exata de polígonos. Suporte a áreas que cruzam o
   antimeridiano existe na extração; pedidos ADS dessas áreas precisam validar
   ordenação/grade do payload e podem exigir dois recortes no futuro.
6. **Concorrência/retomada.** Não há transação distribuída entre ADS e SQLite;
   um crash logo após submit pode deixar job órfão. Um asset com URL renovada
   recomeça seu parcial, preservando os demais arquivos. Tokens nunca ficam no banco.
7. **Armazenamento e portabilidade.** SQLite usa caminhos absolutos; após migração
   de máquina o usuário deve reconciliar caminhos e fazer QC. O ZIP não é uma
   imagem executável universal: requer Python/dependências e acesso à Internet.
8. **Estatística descritiva.** OLS não ajusta autocorrelação, sazonalidade ou quebras;
   não oferece inferência epidemiológica válida por si só. Percentis exatos podem
   exigir muito RAM em subdiários: a função foi projetada/testada para mensal.
9. **Zarr local POSIX.** Publicação atômica usa rename no mesmo filesystem.
   Object stores remotos precisam de outro mecanismo de commit. Não há API,
   autenticação web, dashboard ou PostGIS implementados nesta fase.
10. **Inventário de produtos.** Investigados os três datasets relevantes listados;
    não prometida indexação de todo o ADS. Operacional não é adquirido/mesclado.
11. **Atualizações retroativas.** `update` busca novos/ausentes e valida arquivos
    locais. Não substitui automaticamente um mês já validado se o provedor
    reprocessar dados sem mudar seu identificador. Revisões exigem uma política
    explícita de versionamento após consultar anúncios/metadata.
12. **Integração de bibliotecas nativas.** O ambiente inicial apresentou encerramento
    anormal após testes aprovados. A versão final usa versões compatíveis fixadas,
    backends explícitos e renderização Cartopy em processo separado. A suíte final
    passou e encerrou com código zero. Não se demonstrou a causa interna exata da
    interação C; preservar o isolamento e repetir a suíte ao atualizar dependências.
    Veja `ENVIRONMENT_RECOVERY.md`. O processo de mapas tem timeout de 180 s.


Critérios para liberação de uma base científica: pilotos reais PASS/WARNING
investigados; zero lacunas esperadas; checksums de originais; unidades/níveis
comprovados; cobertura mensal consistente entre variáveis; metadados rastreáveis;
validação externa apropriada à pergunta científica; ambiente reproduzido.
