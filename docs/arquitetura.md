# Arquitetura

## Componentes

### API

Responsável por:

- Receber candles.
- Expor sinais atuais.
- Rodar backtests.
- Registrar operações simuladas.
- Servir métricas para o painel.

Stack sugerida para o MVP:

- Python com FastAPI para API e ML.
- SQLite ou Postgres para histórico.
- Pandas, NumPy e scikit-learn para pesquisa inicial.

### Strategy Core

Módulo puro, testável e sem dependência de plataforma.

Funções principais:

- Cálculo de indicadores.
- Identificação de setups.
- Cálculo de stop, alvo e tamanho da posição.
- Normalização de candles.

### ML Lab

Área de treino e validação.

Responsável por:

- Criar features.
- Rotular exemplos.
- Separar treino/teste por data.
- Treinar modelos.
- Salvar modelo versionado.

### Web

Painel para o operador.

Telas iniciais:

- Sinais atuais.
- Backtest.
- Histórico.
- Configurações de risco.

### Bridges

Integrações externas.

Possíveis caminhos:

- MetaTrader 5 via Expert Advisor enviando candles para a API.
- MetaTrader 5 Python package em ambiente local.
- CSV exportado pela corretora/plataforma.
- Webhook para alertas em WhatsApp, Telegram ou e-mail.

## Fluxo de Dados

```text
Fonte de mercado
  -> candles
  -> normalização
  -> indicadores/features
  -> regra-base + modelo ML
  -> sinal
  -> painel/backtest/alerta
```

## Princípios

- O modelo nunca recebe dados do futuro.
- Nenhum sinal é aceito sem stop loss.
- Toda estratégia precisa de backtest antes de ir para tempo real.
- Métricas importam mais que taxa de acerto isolada.
- Execução automática é a última etapa, não a primeira.

