#!/usr/bin/env python3
"""
Teste de Qualidade de Sinais - Trading AI Hub
Avalia a qualidade das ordens geradas pelo sistema melhorado.
"""

import random
import statistics
from datetime import datetime, timedelta, timezone
from pathlib import Path

from packages.strategy_core.data import Candle
from packages.strategy_core.signals import detect_forex_signal, Signal
from packages.strategy_core.advanced_filters import (
    detect_divergence,
    candlestick_boost,
    dynamic_spread_filter,
    detect_candlestick_patterns,
    smart_exit_check,
    check_correlation_risk,
    calculate_dynamic_lot,
)
from packages.strategy_core.signals import calculate_confluence


def generate_trending_data(n_candles: int = 100, direction: str = "up") -> list[Candle]:
    candles = []
    base_price = 1.0850
    trend_factor = 0.0002 if direction == "up" else -0.0002

    for i in range(n_candles):
        noise = random.uniform(-0.0005, 0.0005)
        o = base_price + noise
        h = o + random.uniform(0.0001, 0.0015)
        l = o - random.uniform(0.0001, 0.0015)
        c = o + trend_factor + random.uniform(-0.0003, 0.0003)

        candles.append(Candle(
            time=f"2024-01-{(i % 28) + 1:02d}T{i % 24:02d}:00:00Z",
            open=round(o, 5),
            high=round(h, 5),
            low=round(l, 5),
            close=round(c, 5),
            volume=random.randint(500, 2000),
        ))
        base_price = c
    return candles


def generate_ranging_data(n_candles: int = 100) -> list[Candle]:
    candles = []
    base_price = 1.0850

    for i in range(n_candles):
        noise = random.uniform(-0.0008, 0.0008)
        o = base_price + noise
        h = o + random.uniform(0.0001, 0.0010)
        l = o - random.uniform(0.0001, 0.0010)
        c = o + random.uniform(-0.0005, 0.0005)

        candles.append(Candle(
            time=f"2024-01-{(i % 28) + 1:02d}T{i % 24:02d}:00:00Z",
            open=round(o, 5),
            high=round(h, 5),
            low=round(l, 5),
            close=round(c, 5),
            volume=random.randint(500, 2000),
        ))
        base_price = (base_price + c) / 2
    return candles


def generate_volatile_data(n_candles: int = 100) -> list[Candle]:
    candles = []
    base_price = 1.0850

    for i in range(n_candles):
        volatility = random.uniform(0.001, 0.003)
        o = base_price + random.uniform(-volatility, volatility)
        h = o + random.uniform(0, volatility * 1.5)
        l = o - random.uniform(0, volatility * 1.5)
        c = o + random.uniform(-volatility, volatility)

        candles.append(Candle(
            time=f"2024-01-{(i % 28) + 1:02d}T{i % 24:02d}:00:00Z",
            open=round(o, 5),
            high=round(h, 5),
            low=round(l, 5),
            close=round(c, 5),
            volume=random.randint(500, 2000),
        ))
        base_price = c
    return candles


def test_confluence(candles: list[Candle], side: str) -> dict:
    count, reasons = calculate_confluence(candles, side)
    return {
        "confluence_count": count,
        "reasons": reasons,
        "passed": count >= 2,
    }


def test_divergence(candles: list[Candle], side: str) -> dict:
    has_divergence, reason = detect_divergence(candles, side)
    return {
        "has_divergence": has_divergence,
        "reason": reason,
    }


def test_candlestick_patterns(candles: list[Candle], side: str) -> dict:
    patterns = detect_candlestick_patterns(candles)
    boost, descriptions = candlestick_boost(candles, side)
    return {
        "patterns_found": len(patterns),
        "boost": boost,
        "descriptions": descriptions,
    }


def test_smart_exit(entry: float, current: float, stop: float, tp: float, side: str, candles: list[Candle]) -> dict:
    decision = smart_exit_check(entry, current, stop, tp, side, candles)
    return {
        "should_exit": decision.should_exit,
        "exit_type": decision.exit_type,
        "exit_pct": decision.exit_pct,
        "reason": decision.reason,
    }


def test_position_sizing(balance: float, entry: float, stop: float) -> dict:
    lot = calculate_dynamic_lot(balance, 1.0, entry, stop)
    risk_amount = balance * 0.01
    stop_pips = abs(entry - stop) * 10000
    return {
        "calculated_lot": lot,
        "risk_amount": round(risk_amount, 2),
        "stop_pips": round(stop_pips, 1),
    }


def test_spread_filter(spread: float) -> dict:
    ok, reason = dynamic_spread_filter(spread)
    return {"passed": ok, "reason": reason}


def run_comprehensive_test():
    print("=" * 70)
    print("TESTE DE QUALIDADE DE SINAIS - TRADING AI HUB")
    print("=" * 70)
    print()

    results = {
        "total_signals": 0,
        "buy_signals": 0,
        "sell_signals": 0,
        "no_trade": 0,
        "avg_confidence": 0,
        "avg_confluence": 0,
        "divergence_detected": 0,
        "candlestick_patterns": 0,
        "quality_scores": [],
    }

    scenarios = [
        ("Tendencia de Alta", generate_trending_data(100, "up")),
        ("Tendencia de Baixa", generate_trending_data(100, "down")),
        ("Mercado Lateral", generate_ranging_data(100)),
        ("Alta Volatilidade", generate_volatile_data(100)),
    ]

    for scenario_name, candles in scenarios:
        print(f"\n{'='*70}")
        print(f"CENARIO: {scenario_name}")
        print(f"{'='*70}")

        signal = detect_forex_signal(candles, "EURUSD", "M5")
        results["total_signals"] += 1

        if signal.side == "BUY":
            results["buy_signals"] += 1
        elif signal.side == "SELL":
            results["sell_signals"] += 1
        else:
            results["no_trade"] += 1

        print(f"\n  SINAL DETECTADO:")
        print(f"    Direcao: {signal.side}")
        print(f"    Confianca: {signal.confidence:.2f}")
        print(f"    Estrategia: {signal.strategy_style or 'N/A'}")
        print(f"    Entry: {signal.entry}")
        print(f"    Stop Loss: {signal.stop_loss}")
        print(f"    Take Profit: {signal.take_profit}")
        print(f"    ML Score: {signal.ml_score or 'N/A'}")

        if signal.side in ("BUY", "SELL"):
            confluence = test_confluence(candles, signal.side)
            print(f"\n  CONFLUENCIA:")
            print(f"    Contagem: {confluence['confluence_count']}/2 minimo")
            print(f"    Razoes: {confluence['reasons']}")
            print(f"    Aprovado: {'SIM' if confluence['passed'] else 'NAO'}")

            divergence = test_divergence(candles, signal.side)
            print(f"\n  DIVERGENCIA:")
            print(f"    Detectada: {'SIM' if divergence['has_divergence'] else 'NAO'}")
            print(f"    Razao: {divergence['reason']}")

            candlestick = test_candlestick_patterns(candles, signal.side)
            print(f"\n  PADROES CANDLESTICK:")
            print(f"    Padroes encontrados: {candlestick['patterns_found']}")
            print(f"    Boost de confianca: +{candlestick['boost']:.2f}")
            print(f"    Descricoes: {candlestick['descriptions']}")

            if signal.entry and signal.stop_loss and signal.take_profit:
                exit_decision = test_smart_exit(
                    signal.entry,
                    signal.entry + 0.0010 if signal.side == "BUY" else signal.entry - 0.0010,
                    signal.stop_loss,
                    signal.take_profit[0],
                    signal.side,
                    candles,
                )
                print(f"\n  SAIDA INTELIGENTE:")
                print(f"    Deve sair: {'SIM' if exit_decision['should_exit'] else 'NAO'}")
                print(f"    Tipo: {exit_decision['exit_type']}")
                print(f"    Motivo: {exit_decision['reason']}")

                sizing = test_position_sizing(1000, signal.entry, signal.stop_loss)
                print(f"\n  POSITION SIZING (saldo $1000):")
                print(f"    Lote calculado: {sizing['calculated_lot']}")
                print(f"    Risco: ${sizing['risk_amount']}")
                print(f"    Stop: {sizing['stop_pips']} pips")

            spread = test_spread_filter(0.8)
            print(f"\n  FILTRO SPREAD (0.8 pips):")
            print(f"    Aprovado: {'SIM' if spread['passed'] else 'NAO'}")
            print(f"    Motivo: {spread['reason']}")

            quality_score = (
                signal.confidence * 0.3 +
                (confluence['confluence_count'] / 4) * 0.25 +
                (1 if divergence['has_divergence'] else 0.5) * 0.15 +
                (candlestick['boost'] / 0.10) * 0.15 +
                (1 if spread['passed'] else 0) * 0.15
            )
            results["quality_scores"].append(quality_score)
            results["avg_confidence"] += signal.confidence
            results["avg_confluence"] += confluence['confluence_count']
            if divergence['has_divergence']:
                results["divergence_detected"] += 1
            results["candlestick_patterns"] += candlestick['patterns_found']

            print(f"\n  SCORE DE QUALIDADE: {quality_score:.2f}/1.00")

    print("\n" + "=" * 70)
    print("RESUMO GERAL")
    print("=" * 70)

    valid_signals = results["buy_signals"] + results["sell_signals"]
    print(f"\n  Total de Cenarios Testados: {results['total_signals']}")
    print(f"  Sinais BUY: {results['buy_signals']}")
    print(f"  Sinais SELL: {results['sell_signals']}")
    print(f"  Sem Sinal (NO_TRADE): {results['no_trade']}")

    if valid_signals > 0:
        print(f"\n  Confianca Media: {results['avg_confidence'] / valid_signals:.2f}")
        print(f"  Confluencia Media: {results['avg_confluence'] / valid_signals:.1f}/4")
        print(f"  Divergencias Detectadas: {results['divergence_detected']}/{valid_signals}")
        print(f"  Padroes Candlestick: {results['candlestick_patterns']}/{valid_signals}")

    if results["quality_scores"]:
        avg_quality = statistics.mean(results["quality_scores"])
        print(f"\n  SCORE MEDIO DE QUALIDADE: {avg_quality:.2f}/1.00")

        if avg_quality >= 0.7:
            print("  CLASSIFICACAO: EXCELENTE")
        elif avg_quality >= 0.5:
            print("  CLASSIFICACAO: BOM")
        elif avg_quality >= 0.3:
            print("  CLASSIFICACAO: REGULAR")
        else:
            print("  CLASSIFICACAO: PRECISA MELHORIA")

    print("\n" + "=" * 70)
    print("TESTE DE STRESS - 50 SINAIS SIMULTANEOS")
    print("=" * 70)

    stress_results = []
    for i in range(50):
        candles = generate_trending_data(random.randint(50, 150), random.choice(["up", "down"]))
        signal = detect_forex_signal(candles, "EURUSD", "M5")
        stress_results.append(signal)

    buy_count = sum(1 for s in stress_results if s.side == "BUY")
    sell_count = sum(1 for s in stress_results if s.side == "SELL")
    no_trade_count = sum(1 for s in stress_results if s.side == "NO_TRADE")
    confidences = [s.confidence for s in stress_results if s.side != "NO_TRADE"]

    print(f"\n  Sinais Gerados: {len(stress_results)}")
    print(f"  BUY: {buy_count} ({buy_count/len(stress_results)*100:.0f}%)")
    print(f"  SELL: {sell_count} ({sell_count/len(stress_results)*100:.0f}%)")
    print(f"  NO_TRADE: {no_trade_count} ({no_trade_count/len(stress_results)*100:.0f}%)")

    if confidences:
        print(f"  Confianca Media: {statistics.mean(confidences):.2f}")
        print(f"  Confianca Min: {min(confidences):.2f}")
        print(f"  Confianca Max: {max(confidences):.2f}")
        print(f"  Desvio Padrao: {statistics.stdev(confidences):.2f}")

    print("\n" + "=" * 70)
    print("RECOMENDACOES")
    print("=" * 70)

    if results["quality_scores"]:
        avg_quality = statistics.mean(results["quality_scores"])
        if avg_quality < 0.5:
            print("\n  [!] QUALIDADE BAIXA - Recomendacoes:")
            print("      - Aumentar SIGNAL_MIN_CONFLUENCE para 3")
            print("      - Aumentar AUTO_TRADE_MIN_CONFIDENCE para 0.85")
            print("      - Considerar desativar strategies com baixo win rate")
        elif avg_quality < 0.7:
            print("\n  [*] QUALIDADE MEDIA - Recomendacoes:")
            print("      - Manter configuracoes atuais")
            print("      - Monitorar performance por estrategia")
        else:
            print("\n  [+] QUALIDADE ALTA - Sistema operando bem")
            print("      - Configuracoes atuais sao otimas")
            print("      - Considerar aumentar tamanho dos lotes")

    print("\n" + "=" * 70)
    print("TESTE CONCLUIDO")
    print("=" * 70)


if __name__ == "__main__":
    random.seed(42)
    run_comprehensive_test()
