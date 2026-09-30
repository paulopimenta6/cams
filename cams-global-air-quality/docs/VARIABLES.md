# Registro de variáveis e conversões

`config/pollutants.yaml` é a fonte única de nomes ADS, aliases de decodificação,
paramId GRIB, unidades, níveis e política de conversão. Os nomes aceitos pela API
foram conferidos nos formulários JSON reais, não obtidos de snippets antigos.

| Interno | Nome ADS | Short name / paramId | Nível | Unidade de origem | Saída / equação |
|---|---|---|---|---|---|
| pm25 | particulate_matter_2.5um | pm2p5 / 210073 | surface | kg m⁻³ | µg m⁻³ = original × 10⁹ |
| pm10 | particulate_matter_10um | pm10 / 210074 | surface | kg m⁻³ | µg m⁻³ = original × 10⁹ |
| co | carbon_monoxide | co / 210123 | model 60 | kg kg⁻¹ | identidade |
| no2 | nitrogen_dioxide | no2 / 210121 | model 60 | kg kg⁻¹ | identidade |
| so2 | sulphur_dioxide | so2 / 210122 | model 60 | kg kg⁻¹ | identidade |
| o3 | ozone | go3 / 210203 | model 60 | kg kg⁻¹ | identidade |

NetCDF pode expor aliases diferentes; eles são explícitos e testados, sem aceitar
a primeira variável do arquivo por conveniência. Metadados GRIB divergentes do
paramId configurado resultam em falha. O nível também deve ser comprovado no
conteúdo; respostas que omitam toda evidência vertical falham até revisão do
adaptador. Nomes próximos como `total_column_ozone` não são intercambiáveis.

## Conversão termodinâmica opcional

O pipeline não usa esta função por padrão, mas `units.py` disponibiliza:

- `mixing_ratio_to_concentration(q, density)`: C[µg/m³] = q[kg/kg] × ρ[kg/m³] × 10⁹;
- `moist_air_density(p,T,qv)`: ρ = p / {Rd T [1 + (Rv/Rd − 1) qv]}, Rd=287,05 e
  Rv=461,5 J kg⁻¹ K⁻¹; base de ar úmido, gases ideais, desprezando condensados.

Não é preciso massa molar para converter razão **mássica** em concentração de
massa usando densidade. Massa molar seria necessária para converter fração molar,
ppb ou ppm. Não aplicamos essa segunda conversão. Pressão e temperatura devem ser
da mesma célula, tempo e nível; pressão na superfície + temperatura a 2 m não
substituem automaticamente condições do nível 60.

As funções exigem unidades explícitas, alinhamento exato e valores termodinâmicos
válidos. Rejeitam médias declaradas em `cell_methods` na conversão de gás. Para
uso científico, também confira a documentação da base mássica da variável e a
origem da densidade. Converter primeiro os campos instantâneos e só depois agregar.

## Extensão

1. Consultar os dois formulários e suas constraints; podem ter inventários distintos.
2. Confirmar se o campo é superfície, pressão, modelo, coluna ou acumulação.
3. Registrar nomes, paramId, unidade física, nível e função de conversão testada.
4. Validar uma amostra real e confirmar os timestamps/semântica do produto.
5. Só então incluir em `config.yaml: pollutants`.

Black carbon, matéria orgânica, sulfato, poeira e sal marinho podem ser
representados por frações hidrofílicas/hidrofóbicas ou bins de tamanho. Somá-los
requer uma definição física explícita; não existe necessariamente uma variável
única com o nome genérico. AOD é adimensional e integrado verticalmente, não
concentração superficial. `methane_chemistry` da EAC4 não deve ser confundido com
uma reanálise especializada de gases de efeito estufa. Nitrato/amônio e outros
constituintes não são prometidos no produto mensal: a presença no operacional ou
na lista subdiária não garante disponibilidade mensal equivalente.

Fontes: formulários/constraints oficiais em `evidence/`; [tabela ECMWF](https://confluence.ecmwf.int/plugins/viewsource/viewpagesrc.action?pageId=514323240)
e [banco de parâmetros ecCodes](https://codes.ecmwf.int/grib/param-db/).
