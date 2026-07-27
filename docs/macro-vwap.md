# Estrategia MACRO_VWAP

`MACRO_VWAP` e a estrategia Forex principal do Hub em modo experimental/demo.
A estrategia anterior permanece acessivel com `FOREX_STRATEGY=LEGACY` para comparacao.

## Regras

- Timeframe M5.
- Compra: EMA 9 cruza acima da SMA 21, fechamento acima da VWAP da sessao e os
  dois ultimos volumes superam a media dos 20 candles anteriores.
- Venda: condicoes inversas.
- O vies `COMPRADOR` bloqueia vendas; `VENDEDOR` bloqueia compras; `NEUTRO`
  permite ambos os lados.
- Stop padrao de 12 pips e alvo de 24 pips.
- O backtest modela breakeven depois de 50% do alvo de forma conservadora: um
  stop ativado por um candle passa a valer a partir do candle seguinte.

## Configuracao

```text
FOREX_STRATEGY=MACRO_VWAP
MACRO_VWAP_DAILY_BIAS=NEUTRO
MACRO_VWAP_SESSION=LONDON
MACRO_VWAP_SESSION_TIMEZONE=Europe/London
MACRO_VWAP_SESSION_HOUR=8
MACRO_VWAP_SESSION_MINUTE=0
MACRO_VWAP_STOP_PIPS=12
MACRO_VWAP_TARGET_PIPS=24
```

A timezone IANA aplica horario de verao corretamente. Para Nova York, use
`MACRO_VWAP_SESSION=NEW_YORK` e `MACRO_VWAP_SESSION_TIMEZONE=America/New_York`.

O endpoint `GET /strategy/status` mostra a configuracao operacional ativa.
O endpoint `/backtest?strategy=LEGACY` permite consultar a estrategia anterior.

## Estado da validacao

No historico local EURUSD M5 da FBS, com spread de 1,0 pip, slippage de 0,2 e
comissao de 0,1, a primeira especificacao neutra produziu 418 trades, -748,4
pips e profit factor 0,74. Portanto, a integracao deve permanecer em paper/demo;
ela ainda nao esta aprovada para conta real. O resultado foi registrado sem
recalibrar parametros usando o periodo de teste.
