# Trading AI Hub

Sistema experimental para estudar sinais de compra e venda em Forex, mini índice e outros ativos negociados em plataformas como MetaTrader.

> Aviso: este projeto não promete lucro e não deve ser usado como recomendação financeira. A primeira meta é pesquisa, backtest e operação simulada. Execução real só deve vir depois de validação, gestão de risco e testes em conta demo.

## Objetivo

Criar uma plataforma que combine:

- Coleta de candles e indicadores técnicos.
- Motor de sinais com regras clássicas e modelos de machine learning.
- Backtest para medir acerto, drawdown, payoff e expectativa.
- Painel web para acompanhar sinais, entradas, saídas e performance.
- Ponte futura com MetaTrader 5, bots ou webhooks.

## Escopo Inicial

O MVP deve responder quatro perguntas:

1. Existe um possível sinal de compra ou venda agora?
2. Qual é a confiança estimada do modelo?
3. Onde ficariam entrada, stop loss e alvos?
4. O setup funcionou historicamente no ativo e timeframe escolhidos?

## Arquitetura Proposta

```text
trading-ai-hub/
  apps/
    api/             API para sinais, backtests e modelos
    web/             Painel do operador
  packages/
    strategy-core/   Indicadores, regras e cálculo de risco
    ml-lab/          Treino, validação e notebooks/scripts
  bridges/
    mt5/             Ponte futura com MetaTrader 5
  docs/
    arquitetura.md
    modelo-de-sinais.md
    roadmap.md
```

## Como a IA deve entrar

O modelo não deve "adivinhar o mercado". Ele deve estimar probabilidade com base em contexto:

- Tendência: médias, inclinação, estrutura de topo/fundo.
- Momentum: RSI, MACD, variação recente, força do candle.
- Volatilidade: ATR, range, expansão/contração.
- Volume quando disponível.
- Horário da sessão.
- Distância até suporte/resistência.
- Resultado histórico de setups parecidos.

Saída esperada:

```json
{
  "symbol": "WINM26",
  "timeframe": "M5",
  "side": "BUY",
  "confidence": 0.68,
  "entry": 129850,
  "stopLoss": 129650,
  "takeProfit": [130050, 130250],
  "reason": [
    "tendência curta acima da média",
    "rompimento com volatilidade crescente",
    "risco/retorno mínimo de 1.5"
  ]
}
```

## Fases

### Fase 1: Pesquisa e Backtest

- Importar candles em CSV.
- Calcular indicadores.
- Criar regra-base sem IA.
- Medir resultado histórico.

### Fase 2: Machine Learning

- Gerar dataset rotulado com resultado futuro.
- Treinar modelo de classificação.
- Validar por período fora da amostra.
- Evitar vazamento de dados do futuro.

### Fase 3: Painel

- Tela de sinais ao vivo.
- Histórico de sinais.
- Métricas de performance.
- Controle de risco por operação.

### Fase 4: Integração

- Webhook para alertas.
- Ponte com MetaTrader 5.
- Conta demo.
- Execução assistida antes de execução automática.

## Relação com o Igrejahub

Este projeto deve ficar separado do `church-SaaS`. No futuro, dá para reaproveitar ideias de login, notificações, assinatura e painel administrativo, mas o domínio de trading precisa ter base, banco e regras próprias.

## Rodando o Protótipo

Na pasta `trading-ai-hub`:

```powershell
python run_demo.py
```

Para subir a API local:

```powershell
python main.py
```

Endpoints iniciais:

- `http://127.0.0.1:8765/health`
- `http://127.0.0.1:8765/datasets`
- `http://127.0.0.1:8765/signals/latest`
- `http://127.0.0.1:8765/signals/history`
- `http://127.0.0.1:8765/backtest`
- `http://127.0.0.1:8765/ml/status`
- `http://127.0.0.1:8765/ml/validation`
- `http://127.0.0.1:8765/alerts/telegram/status`
- `http://127.0.0.1:8765/ai/status`
- `http://127.0.0.1:8765/jobs/status`
- `http://127.0.0.1:8765/market/forex/status`
- `http://127.0.0.1:8765/market/candles`

Tambem e possivel simular o ambiente do Railway usando uma porta dinamica:

```powershell
$env:PORT="8777"
python main.py
```

## Deploy

O projeto esta preparado para Railway com `railway.json`, `Procfile`, `.python-version` e `requirements.txt`.

Guia:

[docs/deploy-railway.md](docs/deploy-railway.md)

## Frontend no Netlify

O repositorio inclui `netlify.toml`, entao o Netlify deve publicar automaticamente a pasta:

```text
apps/web
```

Se configurar manualmente no Netlify:

```text
Base directory: vazio
Build command: vazio
Publish directory: apps/web
```

Depois de abrir o site no Netlify, informe no campo `API Railway` a URL publica da API, por exemplo:

```text
https://seu-app.up.railway.app
```

Tambem da para abrir uma vez com `?api=https://seu-app.up.railway.app`; o painel salva essa URL no navegador.

## Estado Atual

O primeiro protótipo está focado em Forex, usando EUR/USD M5 como amostra. Ele já tem uma primeira camada de machine learning leve para pontuar a qualidade do sinal, mas ainda precisa de histórico real amplo para ficar útil.

Antes de vender acesso, o sistema ainda precisa de dados reais, backtest com custos/spread, auditoria de sinais e validação em conta demo.

## Importando Dados Reais

No painel web, use a area `Importar CSV` para enviar um historico exportado do MT5 ou outra plataforma.

O repositorio tambem inclui um historico diario EUR/USD baixado do Yahoo Finance para treino inicial:

```text
data/forex/eurusd_d1_yahoo.csv
```

Para atualizar esse historico:

```powershell
python scripts/download_yahoo_history.py --symbol EURUSD=X --from-date 2020-01-01 --output data/forex/eurusd_d1_yahoo.csv
```

Tambem existe um downloader para Stooq, mas a fonte pode exigir API key:

```powershell
python scripts/download_stooq_history.py --symbol eurusd --from-date 20200101 --apikey SUA_CHAVE
```

Formato esperado:

```csv
time,open,high,low,close,volume
2026-05-18 09:00:00,1.08420,1.08462,1.08402,1.08450,1200
```

Tambem aceita o formato comum exportado pelo MT5:

```csv
<DATE>	<TIME>	<OPEN>	<HIGH>	<LOW>	<CLOSE>	<TICKVOL>
2026.05.18	09:00:00	1.08420	1.08462	1.08402	1.08450	1200
```

O CSV precisa ter pelo menos 25 candles. Apos importar, o dataset vira o ativo e o painel passa a calcular sinal/backtest usando esse historico.

## Alertas Telegram

Configure no Railway:

```text
TELEGRAM_BOT_TOKEN=token_do_bot
TELEGRAM_CHAT_ID=id_do_grupo_ou_canal
TELEGRAM_MIN_CONFIDENCE=0.60
TELEGRAM_SEND_NO_SIGNAL_STATUS=false
TELEGRAM_STATUS_EVERY_MINUTES=240
ALERT_JOB_SECRET=uma_senha_grande_para_cron
MARKET_INGEST_SECRET=uma_senha_grande_para_receber_candles
ALPHA_VANTAGE_API_KEY=sua_chave_alpha_vantage
TWELVE_DATA_API_KEY=sua_chave_twelve_data
OPENAI_API_KEY=sua_chave_openai
AI_MODEL=gpt-4.1-nano
AI_TELEGRAM_EXPLANATION=true
WATCH_SYMBOL=EURUSD
WATCH_TIMEFRAME=M5
WATCH_OUTPUTSIZE=120
SIGNAL_LOOKBACK_CANDLES=4
FOREX_MARKET_GUARD=true
FOREX_FRIDAY_CLOSE_HOUR=18
FOREX_SUNDAY_OPEN_HOUR=18
MARKET_TIMEZONE=America/Sao_Paulo
```

Depois use o painel para testar a conexao e enviar o sinal atual ao grupo.

O botao `Verificar e alertar` so envia se houver sinal operacional, se a confianca for maior que o minimo e se o mesmo sinal ainda nao tiver sido enviado.

Se o Telegram ficar quieto, veja o card `Robo` no painel ou chame `/jobs/status`. Ele mostra o ultimo motivo: sem sinal, confianca abaixo do minimo, sinal repetido, mercado fechado ou alerta enviado.

Cada sinal operacional enviado ao Telegram tambem entra em `/signals/history`. Quando novos candles chegam, o sistema marca o sinal como `OPEN`, `WIN` ou `LOSS` conforme bater primeiro no primeiro alvo ou no stop. Isso serve muito bem para conta demo e medicao real; para conta real ainda faltam spread, slippage e gestao de risco.

Para receber uma mensagem de status mesmo quando nao houver entrada, ative:

```text
TELEGRAM_SEND_NO_SIGNAL_STATUS=true
TELEGRAM_STATUS_EVERY_MINUTES=240
```

`SIGNAL_LOOKBACK_CANDLES=4` faz o robo aceitar setups detectados nos ultimos 4 candles, com pequena reducao de confianca para candles mais antigos.

Se `OPENAI_API_KEY` estiver configurada, o painel tambem pode gerar uma leitura curta do sinal. Quando `AI_TELEGRAM_EXPLANATION=true`, essa leitura entra como complemento na mensagem do Telegram. A IA nao decide a ordem; ela apenas explica o sinal tecnico/ML.

Para chamada automatica por cron, use:

```text
POST /jobs/check-alerts
Header: X-Job-Secret: valor_do_ALERT_JOB_SECRET
```

Para o robô monitorar sozinho com dados novos da Twelve Data, use:

```text
POST /jobs/twelve-data-scan
Header: X-Job-Secret: valor_do_ALERT_JOB_SECRET
```

Esse job baixa candles, salva o dataset ativo, analisa o sinal e envia Telegram se houver oportunidade valida. Sem corpo JSON, ele usa `WATCH_SYMBOL`, `WATCH_TIMEFRAME` e `WATCH_OUTPUTSIZE`. Tambem aceita sobrescrever por chamada:

```json
{
  "symbol": "EURUSD",
  "timeframe": "M5",
  "outputsize": 120
}
```

Por padrao, o job respeita o fim de semana do Forex: pausa na sexta as 18h e volta no domingo as 18h, usando `MARKET_TIMEZONE`. Para teste manual fora do horario, envie `"force": true` no JSON.

## Dados ao Vivo

Para receber candles de MT5, API de corretora ou script externo:

[docs/market-ingest.md](docs/market-ingest.md)

Tambem e possivel atualizar candles de Forex pela Alpha Vantage no painel ou pelo endpoint:

```text
POST /market/alpha-vantage/refresh
```

Ou pela Twelve Data:

```text
POST /market/twelve-data/refresh
```
