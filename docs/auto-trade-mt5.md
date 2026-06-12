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
- `AUTO_TRADE_MIN_CONFIDENCE=0.72`
- `AUTO_TRADE_MIN_ML_SCORE=0.50`
- `AUTO_TRADE_MIN_RISK_REWARD=1.35`
- `AUTO_TRADE_REQUIRE_MTF_CONFIRMATION=false` (MTF ajusta confianca; bloqueio duro so se ativar)
- `AUTO_TRADE_BLOCK_MTF_CONFLICT=true`
- `AUTO_TRADE_ORDER_TTL_SECONDS=180`
- `AUTO_TRADE_CLAIMED_TTL_SECONDS=300`
- `AUTO_TRADE_MAX_ENTRY_DEVIATION_PIPS=1.5`
- `AUTO_TRADE_MAX_ORDERS_PER_DAY=4`
- `AUTO_TRADE_REPLACE_MIN_CONFIDENCE_DELTA=0.04`
- `AUTO_TRADE_REPLACE_GRACE_SECONDS=45`
- `AUTO_TRADE_NEWS_BLOCK_ENABLED=false`
- `AUTO_TRADE_NEWS_BLOCK_UNTIL=` vazio quando nao houver noticia
- `AUTO_TRADE_NEWS_BLOCK_REASON=` opcional
- `AI_ONLY_FOR_AUTO_TRADE=true`

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

## Filtro de qualidade para auto trade

O Telegram pode receber sinais mais amplos, mas o MT5 deve ser mais exigente.
Por padrao, a API so cria ordem pendente automatica quando:

- o score final passa de `AUTO_TRADE_MIN_CONFIDENCE`;
- o score da IA passa de `AUTO_TRADE_MIN_ML_SCORE`;
- existe confirmacao M15 ou H1 a favor;
- nao existe M15 ou H1 contra o sinal.

Isso reduz entradas em lateralidade e evita que um alerta experimental vire ordem real/demo sem confirmacao suficiente.

## Bloqueio manual de noticia

Para pausar o auto trade em horario de noticia forte, use uma destas opcoes no Railway:

```text
AUTO_TRADE_NEWS_BLOCK_ENABLED=true
AUTO_TRADE_NEWS_BLOCK_REASON=noticia forte
```

ou bloqueie ate um horario UTC especifico:

```text
AUTO_TRADE_NEWS_BLOCK_UNTIL=2026-06-01T19:30:00+00:00
AUTO_TRADE_NEWS_BLOCK_REASON=noticia forte EUR/USD
```

Quando o bloqueio esta ativo, o Telegram pode continuar recebendo sinal, mas a API nao cria ordem pendente para o MT5.

## Economia de IA

Com `AI_ONLY_FOR_AUTO_TRADE=true`, a OpenAI so gera leitura explicativa quando o sinal tambem esta elegivel para virar ordem automatica. Sinais fracos continuam podendo aparecer no Telegram, mas sem gastar tokens da IA.

## Instalar o EA no MT5

Arquivo do robo:

```text
mt5/TradingAiHubBridgeEA.mq5
```

Passos:

1. Abra o MetaTrader 5.
2. Va em `Arquivo > Abrir Pasta de Dados`.
3. Entre em `MQL5/Experts`.
4. Copie `TradingAiHubBridgeEA.mq5` para essa pasta.
5. Abra o MetaEditor e compile o arquivo.
6. No MT5, va em `Ferramentas > Opcoes > Expert Advisors`.
7. Marque `Permitir WebRequest para URLs listadas`.
8. Adicione:

```text
https://trading-ai-hub-production.up.railway.app
```

9. Arraste o EA para o grafico do `EURUSD`.
10. Preencha:

```text
InpExecutionSecret = mesmo valor do EXECUTION_SECRET no Railway
InpExpectedApiSymbol = EURUSD
InpTradeSymbol = deixe vazio para usar o simbolo do grafico
InpDemoOnly = true
InpMaxSpreadPips = 1.2
InpBreakEvenEnabled = true
InpBreakEvenTriggerPips = 3.0
InpBreakEvenOffsetPips = 0.1
```

Se sua corretora usa sufixo no ativo, como `EURUSDm`, coloque:

```text
InpTradeSymbol = EURUSDm
InpExpectedApiSymbol = EURUSD
```

O EA consulta a API a cada 2 segundos. Quando houver ordem pendente valida, ele reserva a ordem, confere preco e abre em conta demo.

Antes de abrir, o EA tambem bloqueia spread alto. Depois de abrir, se a posicao andar `InpBreakEvenTriggerPips` a favor, ele move o stop para a entrada com pequeno offset definido em `InpBreakEvenOffsetPips`.
