# Telemetria eletromecanica no COUS

## Escopo

O COUS consome as linhas `TMA_DATA` documentadas pelo firmware. Linhas
`TMA_DIAG` sao diagnostico operacional do dispositivo e nao sao medicoes.

Contratos agregados aceitos:

- `electromechanical_observation_frame`, versao 3;
- `electromechanical_correlation_frame`, versao 4.

Ambos pertencem a vertical `signature`. Os snapshots brutos de Hall, potencia,
vibracao, curso e campo magnetico continuam compativeis.

O contrato v4 fixa os graficos em tres conjuntos:

- assinatura fisica: tensao, corrente, potencia eletrica, frequencia de
  furacao, vibracao RMS e RPM do motor inferido pelo MPU;
- motor principal: torque, FCEM eletrica, RPM MPU, eficiencia inferida,
  potencia eletrica medida e resistencia do enrolamento;
- motor secundario: erro de FCEM, erro da resistencia do enrolamento, erro de
  RPM e erro de potencia eletrica.

Os erros do motor sao publicados com valor em permille e validade propria. O
COUS nao deve transformar um campo invalido em zero medido. O erro de
resistencia compara medicao e datasheet; os erros de RPM e potencia comparam o
ponto medido com o ponto esperado pelo perfil na tensao aplicada.

A observacao v3 separa a vibracao em RMS total medido, RMS sincrono inferido
nas ordens `1x`, `2x` e `3x` da rotacao e RMS residual inferido. Tambem publica
a frequencia usada, fracao de energia sincrona, quantidade de harmonicos,
confianca e validade. O residual representa energia nao sincrona; nao deve ser
tratado isoladamente como falha.

## Responsabilidades

O firmware:

- adquire e qualifica os canais;
- calcula o fechamento fisico;
- publica relacoes explicaveis;
- classifica modos como `consistent`, `suspect`, `critical` ou
  `indeterminate`.

O COUS:

- valida o par `type/version`;
- preserva perfil, fechamento, assinatura fisica, fontes e limitacoes;
- consolida temporalmente as hipoteses;
- gera evidencia estruturada para o OpenTracy;
- apresenta as hipoteses no diagnostico e no laudo.

O OpenTracy e o tecnico:

- correlacionam as hipoteses com documentos, historico e contexto operacional;
- confirmam ou rejeitam a causa da falha.

No diagnostico remoto, o OpenTracy nao recalcula os limiares dos sensores. Ele
usa o modo publicado pelo firmware como hipotese fisica, impede que unidades de
conhecimento sem relacao substituam essa hipotese e recalcula a confianca formal
com quatro dimensoes: evidencia, documento, historico e consistencia. O callback
devolve o modo, estado atual, persistencia, fontes, limitacoes, unidades de
conhecimento corroborantes e cadeia causal aplicavel.

Uma relacao presente no frame nao representa falha ativa. Somente relacoes
validas dos modos conhecidos, com avaliacao `suspect` ou `critical`, sao
tratadas como hipoteses ativas.

## Confirmacao temporal

Uma hipotese e classificada como persistente quando aparece ativa em pelo menos
dois frames consecutivos, separados por no maximo cinco segundos. Uma unica
ocorrencia, uma lacuna maior ou um frame intermediario consistente reinicia a
sequencia.

O COUS conserva separadamente:

- ocorrencia historica;
- estado ativo no frame mais recente;
- maior sequencia consecutiva;
- confianca maxima e media;
- canais de origem;
- limitacao declarada pelo firmware.

Persistencia nao transforma a hipotese em causa confirmada. O laudo identifica
explicitamente essa limitacao.

## Modos reconhecidos

- `locked_rotor_hypothesis`;
- `mechanical_decoupling_hypothesis`;
- `motor_nominal_overload_hypothesis`;
- `source_overvoltage_hypothesis`;
- `source_interruption_hypothesis`;
- `source_sag_under_load_hypothesis`.

Novos modos exigem inclusao explicita no registro do COUS. Isso impede que uma
relacao desconhecida seja promovida silenciosamente a diagnostico.

## Evidencia remota

Para frames agregados, o COUS nao reduz o payload a medias de campos no primeiro
nivel. A evidencia enviada ao OpenTracy inclui:

- perfil ativo;
- fechamento mais recente;
- assinatura fisica mais recente;
- aderencia global agregada;
- completude do fechamento;
- resumo temporal de cada modo;
- indicacao de truncamento das relacoes.

O payload permanece limitado a um resumo da sessao; ele nao replica todos os
frames aninhados.

# Identidade operacional da medicao

Toda medicao deve possuir no cabecalho:

- `ordem_servico`: numero da OS previamente indexada no OpenTracy;
- `numero_serie`: identificador observado no equipamento;
- `observacoes`: relato livre associado explicitamente a essa OS.

Antes de abrir a captura remota, o OpenTracy localiza o documento
`service_order`, recupera a serie cadastrada e compara com `numero_serie`.
OS inexistente, OS sem serie ou divergencia de serie impedem a resolucao da
identidade. A captura persiste `service_order_document_id`, mantendo
rastreabilidade entre medicao, equipamento e documento.

As observacoes sao enviadas como `service_order_context`, com forca `weak` e
papel epistemico `reported_context`. Elas podem corroborar a formulacao de uma
hipotese, mas nao substituem medicao fisica nem confirmam isoladamente um modo
de falha.
