# Envio de Candles Reais

Use `POST /market/candles` para enviar candles de uma corretora, MT5, script local ou API externa.

## Segurança

No Railway, configure uma chave:

```text
MARKET_INGEST_SECRET=uma_senha_grande
```

Envie essa chave no header:

```text
X-Market-Secret: uma_senha_grande
```

Se `MARKET_INGEST_SECRET` nao estiver configurado, o endpoint aceita dados sem chave. Isso e util para teste, mas nao e recomendado em producao.

## Payload

```json
{
  "symbol": "EURUSD",
  "timeframe": "M5",
  "alert": true,
  "candles": [
    {
      "time": "2026-05-22 10:00:00",
      "open": 1.0842,
      "high": 1.085,
      "low": 1.0838,
      "close": 1.0847,
      "volume": 1200
    }
  ]
}
```

Regras:

- Envie pelo menos 25 candles.
- O dataset recebido vira o dataset ativo.
- Se `alert` for `true`, o sistema analisa o ultimo candle e chama o alerta inteligente do Telegram.
- O alerta so e enviado se passar por confianca minima e anti-repeticao.

## Exemplo cURL

```bash
curl -X POST "https://seu-app.up.railway.app/market/candles" \
  -H "Content-Type: application/json" \
  -H "X-Market-Secret: sua_chave" \
  -d @candles.json
```
