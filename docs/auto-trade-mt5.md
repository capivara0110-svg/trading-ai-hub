# Auto Trade MT5

Fluxo inicial para conta demo:

1. A API analisa o mercado e envia o sinal aprovado ao Telegram.
2. Se `AUTO_TRADE_ENABLED=true`, a API cria uma ordem pendente curta.
3. O EA do MT5 consulta `/execution/pending`.
4. O EA valida idade do sinal, desvio do preco, lote, stop e alvo.
5. O EA chama `/execution/claim`, abre a ordem e chama `/execution/result`.

## Variaveis no Railway

- `AUTO_TRADE_ENABLED=false` por padrao.
- `EXECUTION_SECRET`: senha do EA para consultar ordens.
- `AUTO_TRADE_MODE=DEMO_ONLY`
- `AUTO_TRADE_LOT=0.01`
- `AUTO_TRADE_MIN_CONFIDENCE=0.75`
- `AUTO_TRADE_ORDER_TTL_SECONDS=60`
- `AUTO_TRADE_MAX_ENTRY_DEVIATION_PIPS=1.5`
- `AUTO_TRADE_MAX_ORDERS_PER_DAY=3`

## Endpoints

Status publico:

```text
GET /execution/status
```

Consulta do EA:

```text
GET /execution/pending?secret=SUA_SENHA
```

Reserva da ordem antes de executar:

```text
POST /execution/claim
{
  "secret": "SUA_SENHA",
  "id": "ORDER_ID"
}
```

Resultado depois da tentativa no MT5:

```text
POST /execution/result
{
  "secret": "SUA_SENHA",
  "id": "ORDER_ID",
  "status": "EXECUTED",
  "brokerTicket": "123456",
  "fillPrice": 1.16433,
  "message": "opened in demo"
}
```

Use primeiro somente em conta demo. O EA deve recusar ordem expirada, ordem sem stop ou ordem com preco atual distante da entrada.
