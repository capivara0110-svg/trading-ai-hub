#!/usr/bin/env python3
"""
Teste de Qualidade de Sinais v2 - Trading AI Hub
Gera dados mais realistas para avaliar o sistema.
"""

import random
import statistics
from packages.strategy_core.data import Candle
from packages.strategy_core.signals import detect_forex_signal, calculate_confluence
from packages.strategy_core.advanced_filters import (
    detect_divergence,
    candlestick_boost,
    dynamic_spread_filter,
    detect_candlestick_patterns,
    smart_exit_check,
    calculate_dynamic_lot,
)


def generate_realistic_trending(n_candles: int = 100, direction: str = "up") -> list[Candle]:
    candles = []
    base_price = 1.0850
    trend_strength = 0.00015 if direction == "up" else -0.00015

    for i in range(n_candles):
        trend_component = trend_strength * (1 + 0.3 * (i / n_candles))
        noise = random.gauss(0, 0.0003)
        momentum = trend_strength * 0.5 * (1 if i % 5 < 3 else -0.3)

        o = base_price + noise
        body_size = abs(trend_component) + abs(momentum) + random.uniform(0.0001, 0.0004)
        h = o + body_size * random.uniform(0.3, 0.7)
        l = o - body_size * random.uniform(0.3, 0.7)
        c = o + trend_component + momentum

        if direction == "up":
            c = max(c, o + body_size * 0.2)
        else:
            c = min(c, o - body_size * 0.2)

        candles.append(Candle(
            time=f"2024-01-{(i % 28) + 1:02d}T{i % 24:02d}:00:00Z",
            open=round(o, 5),
            high=round(max(o, h, c), 5),
            low=round(min(o, l, c), 5),
            close=round(c, 5),
            volume=random.randint(800, 2500),
        ))
        base_price = c
    return candles


def generate_realistic_reversal(n_candles: int = 100) -> list[Candle]:
    candles = []
    base_price = 1.0850

    for i in range(n_candles):
        if i < 40:
            trend = 0.0002
        elif i < 60:
            trend = 0.0001 * (1 - (i - 40) / 20)
        elif i < 80:
            trend = -0.0001 * ((i - 60) / 20)
        else:
            trend = -0.0002

        noise = random.gauss(0, 0.0002)
        o = base_price + noise
        h = o + random.uniform(0.0001, 0.0008)
        l = o - random.uniform(0.0001, 0.0008)
        c = o + trend + random.uniform(-0.0002, 0.0002)

        candles.append(Candle(
            time=f"2024-01-{(i % 28) + 1:02d}T{i % 24:02d}:00:00Z",
            open=round(o, 5),
            high=round(max(o, h, c), 5),
            low=round(min(o, l, c), 5),
            close=round(c, 5),
            volume=random.randint(800, 2500),
        ))
        base_price = c
    return candles


def generate_confluence_friendly(direction: str = "up") -> list[Candle]:
    candles = []
    base_price = 1.0850
    trend = 0.0002 if direction == "up" else -0.0002

    for i in range(100):
        momentum = trend * (0.8 + 0.4 * (i / 100))
        noise = random.gauss(0, 0.00015)

        o = base_price + noise
        body = abs(trend) * (1 + 0.2 * (i % 10) / 10)
        h = o + body * random.uniform(0.4, 0.6)
        l = o - body * random.uniform(0.4, 0.6)
        c = o + momentum

        candles.append(Candle(
            time=f"2024-01-{(i % 28) + 1:02d}T{i % 24:02d}:00:00Z",
            open=round(o, 5),
            high=round(max(o, h, c), 5),
            low=round(min(o, l, c), 5),
            close=round(c, 5),
            volume=random.randint(1000, 3000),
        ))
        base_price = c
    return candles


def analyze_signal(signal: Signal, candles: list[Candle]) -> dict:
    result = {
        "side": signal.side,
        "confidence": signal.confidence,
        "strategy": signal.strategy_style,
        "entry": signal.entry,
        "stop_loss": signal.stop_loss,
        "take_profit": signal.take_profit,
        "ml_score": signal.ml_score,
        "reasons": signal.reason,
    }

    if signal.side in ("BUY", "SELL"):
        conf_count, conf_reasons = calculate_confluence(candles, signal.side)
        result["confluence_count"] = conf_count
        result["confluence_reasons"] = conf_reasons
        result["confluence_passed"] = conf_count >= 2

        has_div, div_reason = detect_divergence(candles, signal.side)
        result["has_divergence"] = has_div
        result["divergence_reason"] = div_reason

        patterns = detect_candlestick_patterns(candles)
        boost, boost_desc = candlestick_boost(candles, signal.side)
        result["candlestick_patterns"] = len(patterns)
        result["candlestick_boost"] = boost
        result["candlestick_descriptions"] = boost_desc

        spread_ok, spread_reason = dynamic_spread_filter(0.8)
        result["spread_ok"] = spread_ok
        result["spread_reason"] = spread_reason

        if signal.entry and signal.stop_loss:
            sizing = calculate_dynamic_lot(1000, 1.0, signal.entry, signal.stop_loss)
            result["position_lot"] = sizing

    return result


def run_quality_test():
    print("=" * 70)
    print("TESTE DE QUALIDADE v2 - TRADING AI HUB")
    print("=" * 70)

    all_results = []

    scenarios = [
        ("Tendencia de Alta (Confluencia)", generate_confluence_friendly("up")),
        ("Tendencia de Baixa (Confluencia)", generate_confluence_friendly("down")),
        ("Tendencia Forte Alta", generate_realistic_trending(100, "up")),
        ("Tendencia Forte Baixa", generate_realistic_trending(100, "down")),
        ("Reversao de Mercado", generate_realistic_reversal(100)),
    ]

    for name, candles in scenarios:
        print(f"\n{'='*70}")
        print(f"CENARIO: {name}")
        print(f"{'='*70}")

        signal = detect_forex_signal(candles, "EURUSD", "M5")
        analysis = analyze_signal(signal, candles)
        all_results.append(analysis)

        print(f"\n  SINAL: {analysis['side']}")
        print(f"  CONFIANCA: {analysis['confidence']:.2f}")
        print(f"  ESTRATEGIA: {analysis.get('strategy') or 'N/A'}")

        if analysis['side'] in ("BUY", "SELL"):
            print(f"\n  --- DETALHES DA QUALIDADE ---")
            print(f"  Confluencia: {analysis.get('confluence_count', 0)}/2 {'OK' if analysis.get('confluence_passed') else 'FALHOU'}")
            if analysis.get('confluence_reasons'):
                for r in analysis['confluence_reasons']:
                    print(f"    - {r}")

            print(f"  Divergencia: {'SIM' if analysis.get('has_divergence') else 'NAO'}")
            print(f"  Padroes Candle: {analysis.get('candlestick_patterns', 0)} (+{analysis.get('candlestick_boost', 0):.2f})")
            if analysis.get('candlestick_descriptions'):
                for d in analysis['candlestick_descriptions']:
                    print(f"    - {d}")

            print(f"  Spread: {'OK' if analysis.get('spread_ok') else 'FALHOU'}")
            print(f"  Lote Sugerido: {analysis.get('position_lot', 'N/A')}")

            print(f"\n  RAZOES DO SINAL:")
            for r in analysis.get('reasons', []):
                print(f"    - {r}")

    print("\n" + "=" * 70)
    print("ANALISE ESTATISTICA")
    print("=" * 70)

    buy_signals = [r for r in all_results if r['side'] == 'BUY']
    sell_signals = [r for r in all_results if r['side'] == 'SELL']
    no_trade = [r for r in all_results if r['side'] == 'NO_TRADE']

    print(f"\n  Total de Cenarios: {len(all_results)}")
    print(f"  Sinais BUY: {len(buy_signals)}")
    print(f"  Sinais SELL: {len(sell_signals)}")
    print(f"  Sem Sinal: {len(no_trade)}")
    print(f"  Taxa de Sinalizacao: {(len(buy_signals) + len(sell_signals)) / len(all_results) * 100:.0f}%")

    valid_signals = buy_signals + sell_signals
    if valid_signals:
        confidences = [s['confidence'] for s in valid_signals]
        print(f"\n  Confianca Media: {statistics.mean(confidences):.2f}")
        print(f"  Confianca Min: {min(confidences):.2f}")
        print(f"  Confianca Max: {max(confidences):.2f}")

        confluences = [s.get('confluence_count', 0) for s in valid_signals]
        print(f"  Confluencia Media: {statistics.mean(confluences):.1f}")

        confluence_passed = sum(1 for s in valid_signals if s.get('confluence_passed'))
        print(f"  Confluencia Aprovada: {confluence_passed}/{len(valid_signals)}")

        divergences = sum(1 for s in valid_signals if s.get('has_divergence'))
        print(f"  Divergencias Detectadas: {divergences}/{len(valid_signals)}")

        patterns = sum(s.get('candlestick_patterns', 0) for s in valid_signals)
        print(f"  Total Padroes Candlestick: {patterns}")

    print("\n" + "=" * 70)
    print("RECOMENDACOES DE OTIMIZACAO")
    print("=" * 70)

    if len(no_trade) > len(all_results) * 0.7:
        print("\n  [!] SISTEMA MUITO SELETIVO")
        print("      - Considere reduzir SIGNAL_MIN_CONFLUENCE para 1")
        print("      - Reduza AUTO_TRADE_MIN_CONFIDENCE para 0.75")
        print("      - Teste com MTF_REQUIRE_MTF_CONFIRMATION=false")

    if valid_signals:
        low_conf = sum(1 for s in valid_signals if s['confidence'] < 0.7)
        if low_conf > len(valid_signals) * 0.5:
            print("\n  [*] MUITOS SINAIS COM CONFIANCIA BAIXA")
            print("      - Aumente os filtros de qualidade")
            print("      - Verifique os pesos do ML")

    print("\n  [+] CONFIGURACAO ATUAL:")
    print("      SIGNAL_MIN_CONFLUENCE=2 (recomendado: 2)")
    print("      AUTO_TRADE_MIN_CONFIDENCE=0.80 (recomendado: 0.75-0.85)")
    print("      DRAWDOWN_MAX_CONSECUTIVE_LOSSES=3 (recomendado: 3)")

    print("\n" + "=" * 70)
    print("TESTE CONCLUIDO")
    print("=" * 70)


if __name__ == "__main__":
    random.seed(42)
    run_quality_test()
