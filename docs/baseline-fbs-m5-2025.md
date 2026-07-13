# Linha de base EUR/USD M5 - FBS

Data da analise: 2026-07-13

## Fonte e qualidade

- Fonte: historico local MT4 FBS Real, arquivo HST v401.
- Timeframe: EUR/USD M5.
- Horario do servidor: EET, convertido para UTC com GMT+2 no inverno e GMT+3 no verao.
- Referencia do horario FBS: https://fbs.com/trading/trading-hours
- CSV extraido: `data/forex/eurusd_m5_fbs_real_12m.csv`.
- Total extraido: 50.641 candles, de 2025-01-30 a 2026-01-30.
- Sem duplicatas, ordem temporal invalida ou OHLC inconsistente.
- Gap encontrado: 2025-07-25 20:50 UTC ate 2025-11-19 00:45 UTC.

O gap nao foi atravessado pela validacao. Foram analisados dois blocos independentes.

## Configuracao

- Custos por operacao: spread 1,0 pip, slippage 0,2 pip, comissao 0,1 pip.
- Bloco inicial: 36.289 candles; treino 10.000, teste 4.000, passo 4.000.
- Bloco recente: 14.352 candles; treino 5.000, teste 2.000, passo 2.000.
- KNN usa 150 referencias temporalmente distribuidas; centroides usam todo o treino.

## Resultados walk-forward

### Bloco inicial

| Metrica | Regra-base | Filtro ML |
|---|---:|---:|
| Trades | 7.497 | 1.550 |
| Pips liquidos | -10.800,5 | -2.027,5 |
| Win rate | 38% | 40% |
| Profit factor | 0,63 | 0,66 |
| Payoff | 1,03 | 0,99 |
| Drawdown | 10.958,0 | 2.183,4 |
| Custos | 9.746,1 | 2.015,0 |

O filtro ML melhorou o resultado em 8.773,0 pips, mas apenas 1 de 6 folds foi lucrativo.

### Bloco recente

| Metrica | Regra-base | Filtro ML |
|---|---:|---:|
| Trades | 2.392 | 505 |
| Pips liquidos | -3.286,3 | -677,7 |
| Win rate | 34% | 36% |
| Profit factor | 0,45 | 0,45 |
| Payoff | 0,86 | 0,79 |
| Drawdown | 3.295,3 | 677,7 |
| Custos | 3.109,6 | 656,5 |

O filtro ML melhorou o resultado em 2.608,6 pips, mas nenhum dos 4 folds foi lucrativo.

## Conclusao

A estrategia atual nao demonstrou vantagem depois dos custos. O ML funciona como redutor de
operacoes e perdas, mas ainda nao seleciona um conjunto lucrativo.

Antes de recalibrar o modelo, o simulador deve impedir operacoes simultaneas, aplicar sessoes e
confirmacoes equivalentes as usadas no robo ao vivo e modelar entrada/saida pelo preco executavel.

## Segunda rodada: simulacao operacional

Foram adicionados posicao unica, cooldown, limite diario, Londres/NY, confirmacao M15/H1 com
candles fechados, bloqueio de scalper/lateralidade, filtro de volatilidade, custo minimo e horizonte
de 24 candles. A calibracao usou apenas dados anteriores a 2025-06-01.

Configuracao escolhida no desenvolvimento: confianca 0,72, ML 0,55, cooldown 12 candles e no
maximo 2 trades por dia. No desenvolvimento: 56 trades, +24,0 pips e profit factor 1,07.

### Testes finais intocados

| Periodo | Trades ML | Pips | Win rate | Profit factor | Drawdown |
|---|---:|---:|---:|---:|---:|
| Jun-Jul/2025 | 43 | -69,5 | 37% | 0,73 | 92,7 |
| Nov/2025-Jan/2026 | 44 | -52,2 | 36% | 0,72 | 96,1 |

A configuracao falhou nos dois testes intocados. Ela nao deve ser promovida para auto trade real.
As melhorias operacionais e de auditoria podem ser publicadas em modo paper para coletar dados
futuros com o modelo congelado.
