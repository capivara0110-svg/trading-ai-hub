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
- `http://127.0.0.1:8765/backtest`
- `http://127.0.0.1:8765/ml/status`

Tambem e possivel simular o ambiente do Railway usando uma porta dinamica:

```powershell
$env:PORT="8777"
python main.py
```

## Deploy

O projeto esta preparado para Railway com `railway.json`, `Procfile`, `.python-version` e `requirements.txt`.

Guia:

[docs/deploy-railway.md](docs/deploy-railway.md)

## Estado Atual

O primeiro protótipo está focado em Forex, usando EUR/USD M5 como amostra. Ele já tem uma primeira camada de machine learning leve para pontuar a qualidade do sinal, mas ainda precisa de histórico real amplo para ficar útil.

Antes de vender acesso, o sistema ainda precisa de dados reais, backtest com custos/spread, auditoria de sinais e validação em conta demo.

## Importando Dados Reais

No painel web, use a area `Importar CSV` para enviar um historico exportado do MT5 ou outra plataforma.

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
