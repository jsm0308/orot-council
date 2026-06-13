"""
Qualitative Stock Analysis Module
Deep-dive analysis of individual stocks/ETFs: business model, competitive position,
economic moat, management evaluation, and valuation scenario modeling.

This module provides the prompt templates and analysis framework for qualitative
evaluation — the "story" half of the numbers+story persuasion method.

Usage:
    python deep_dive.py --ticker AAPL                    # Analyze a stock
    python deep_dive.py --ticker 139260 --market KR       # Korean ticker (TIGER S&P500)
    python deep_dive.py --ticker NVDA --output aapl.json  # Save to file
    python deep_dive.py --list-prompts                    # Show available analysis prompts

Output:
    JSON with structured qualitative analysis
"""

import os
import sys
import json
import argparse
from datetime import datetime
from typing import Dict, List, Optional

from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, BASE_DIR)
load_dotenv(os.path.join(BASE_DIR, ".env"))

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DATA_DIR = os.path.join(BASE_DIR, "data")

# ---------------------------------------------------------------------------
# Qualitative Analysis Prompt Templates
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """당신은 월스트리트 셀사이드 리서치 애널리스트입니다.
당신의 임무는 기업을 다음 4가지 질적 차원에서 깊이 분석하는 것입니다:
1. 비즈니스 모델
2. 경쟁 포지션 (Porter's Five Forces)
3. 경제적 해자 (Morningstar 5대 해자)
4. 경영진 평가

모든 응답은 한국어로 작성하세요. 경제 용어와 티커는 원어를 유지하세요.
해자가 없으면 솔직히 "없다"고 말하세요. 억지로 만들어내지 마세요.
근거가 부족한 주장은 "데이터 부재로 판단 보류"라고 명시하세요.
응답은 JSON 형식이어야 합니다."""

BUSINESS_MODEL_PROMPT = """## 비즈니스 모델 분석: {name} ({ticker})

다음 질문에 대해 분석하세요:

1. **핵심 제품/서비스**: 이 회사는 정확히 무엇을 파는가?
2. **매출 구성**: 제품/서비스/지역별 매출 비중을 추정하라.
3. **고객 구조**: 주요 고객은 누구인가? 상위 3개 고객 집중도는?
4. **수익 모델 유형**: 반복 매출(구독, 소비재) vs 일회성(프로젝트, 장비). 구독/반복 비중은?
5. **공급망**: 핵심 원재료/부품 의존도. 공급자 교체 용이성은?
6. **단위 경제(Unit Economics)**: 고객획득비용(CAC) vs 고객생애가치(LTV). 규모의 경제 작동 여부.

분석 후 JSON으로 응답:

```json
{
  "business_model": {
    "core_product": "",
    "revenue_mix": {"products": "", "services": "", "by_region": ""},
    "customer_concentration": {"top_customers": "", "risk_level": "high|medium|low"},
    "revenue_type": "recurring|one-time|hybrid",
    "recurring_pct": 0,
    "supply_chain_risk": "high|medium|low",
    "supply_chain_detail": "",
    "unit_economics": {"cac_estimate": "", "ltv_estimate": "", "scale_efficiency": true|false}
  }
}
```"""

COMPETITIVE_POSITION_PROMPT = """## 경쟁 포지션 분석 (Porter's Five Forces): {name} ({ticker})

각 Force에 대해 1-5점(5가 가장 불리함)으로 평가하고 근거를 제시하세요:

1. **신규 진입 위협 (Threat of New Entrants)**
   - 진입 장벽: 규제, 자본 요구량, 기술 난이도, 브랜드 충성도
2. **공급자 협상력 (Bargaining Power of Suppliers)**
   - 공급자 집중도, 대체 공급처 존재 여부, 전방 통합 가능성
3. **구매자 협상력 (Bargaining Power of Buyers)**
   - 고객 집중도, 전환 비용, 가격 민감도
4. **대체재 위협 (Threat of Substitutes)**
   - 대체 제품/서비스 존재 여부, 전환 비용, 성능 대비 가격
5. **기존 경쟁 강도 (Rivalry Among Existing Competitors)**
   - 시장 집중도(HHI), 차별화 정도, 퇴출 장벽, 성장률

JSON 응답:
```json
{
  "competitive_position": {
    "overall_assessment": "favorable|neutral|unfavorable",
    "threat_of_new_entrants": {"score": 0, "rationale": ""},
    "supplier_power": {"score": 0, "rationale": ""},
    "buyer_power": {"score": 0, "rationale": ""},
    "threat_of_substitutes": {"score": 0, "rationale": ""},
    "rivalry": {"score": 0, "rationale": ""},
    "average_score": 0.0
  }
}
```"""

MOAT_PROMPT = """## 경제적 해자 분석 (Morningstar 5대 해자): {name} ({ticker})

5가지 해자 유형 각각에 대해 존재 여부와 근거를 평가하세요:

1. **전환 비용 (Switching Cost)**
   - 고객이 경쟁사로 옮기는 데 드는 금전적/시간적/심리적 비용
   - 예: 기업용 소프트웨어(ERP), 은행, 통신사

2. **무형 자산 (Intangible Assets)**
   - 브랜드 파워, 특허 포트폴리오, 규제 라이선스
   - 예: 코카콜라(브랜드), 퀄컴(특허), 무디스(규제 라이선스)

3. **네트워크 효과 (Network Effect)**
   - 사용자가 늘어날수록 서비스 가치가 증가하는가
   - 예: 비자/마스터카드, 마이크로소프트 윈도우, 이베이

4. **비용 우위 (Cost Advantage)**
   - 규모의 경제, 공정 혁신, 유리한 입지로 경쟁사보다 지속적 저비용
   - 예: 월마트, 코스트코, TSMC

5. **효율적 규모 (Efficient Scale)**
   - 시장이 작아서 추가 경쟁자가 들어오면 모두가 손해 보는 구조
   - 예: 철도, 공항, 파이프라인, 일부 유틸리티

** 해자가 없으면 "없음"이라고 솔직히 답하세요.**

JSON 응답:
```json
{
  "moat": {
    "overall_moat_rating": "wide|narrow|none",
    "switching_cost": {"exists": true|false, "strength": "strong|moderate|weak", "evidence": ""},
    "intangible_assets": {"exists": true|false, "strength": "strong|moderate|weak", "evidence": ""},
    "network_effect": {"exists": true|false, "strength": "strong|moderate|weak", "evidence": ""},
    "cost_advantage": {"exists": true|false, "strength": "strong|moderate|weak", "evidence": ""},
    "efficient_scale": {"exists": true|false, "strength": "strong|moderate|weak", "evidence": ""},
    "moat_trend": "widening|stable|narrowing",
    "moat_risk": ""
  }
}
```"""

MANAGEMENT_PROMPT = """## 경영진 평가: {name} ({ticker})

다음 항목을 평가하세요. 공개 정보가 부족하면 명시하세요.

1. **CEO 평가**
   - 재임 기간, 이전 이력, 업계 평판
   - 주요 전략적 결정의 트랙 레코드
2. **IR 소통 품질**
   - 가이던스 정확도 (제시한 전망을 얼마나 잘 맞췄는가)
   - 컨퍼런스콜 투명성, 질문 회피 여부
3. **자본 배분 실적**
   - M&A 성공률 (인수 후 가치 창출/파괴)
   - 자사주 매입 타이밍 (고점 매입 vs 저점 매입)
   - 배당 정책 일관성
4. **지배구조 (Governance)**
   - 이사회 독립성 (사외이사 비율)
   - 소액주주 보호 장치
   - 내부자 거래 이슈 존재 여부

JSON 응답:
```json
{
  "management": {
    "overall_rating": "excellent|good|average|poor",
    "ceo": {"name": "", "tenure_years": 0, "background": "", "track_record": ""},
    "ir_quality": {"rating": "high|medium|low", "guidance_accuracy": "", "transparency": ""},
    "capital_allocation": {"rating": "high|medium|low", "ma_success_rate": "", "buyback_timing": "", "dividend_consistency": ""},
    "governance": {"rating": "high|medium|low", "board_independence": "", "minority_protection": "", "insider_issues": ""},
    "key_person_risk": "high|medium|low",
    "succession_plan": "clear|unclear"
  }
}
```"""

VALUATION_SCENARIO_PROMPT = """## 밸류에이션 시나리오 분석: {name} ({ticker})

다음 3가지 시나리오에 대한 예상 가치 범위를 제시하세요:

**Input data (if available):**
{fundamentals}

**Scenario 1: Bull Case (확률 20-30%)**
- 낙관적 가정: (매출 성장률, 마진, 멀티플 등)
- 예상 주가 범위
- 촉매(Catalyst): 어떤 이벤트가 발생해야 이 시나리오가 실현되는가?

**Scenario 2: Base Case (확률 50-60%)**
- 중립적 가정: 컨센서스 부합
- 예상 주가 범위
- 근거

**Scenario 3: Bear Case (확률 20-30%)**
- 비관적 가정: (경기 침체, 경쟁 심화, 규제 등)
- 예상 주가 범위
- 트리거: 어떤 조건에서 이 시나리오가 현실화되는가?

JSON 응답:
```json
{
  "valuation_scenarios": {
    "current_price": 0.0,
    "bull_case": {"probability_pct": 0, "key_assumptions": "", "target_price": 0, "upside_pct": 0, "catalyst": ""},
    "base_case": {"probability_pct": 0, "key_assumptions": "", "target_price": 0, "upside_pct": 0},
    "bear_case": {"probability_pct": 0, "key_assumptions": "", "target_price": 0, "downside_pct": 0, "trigger": ""},
    "expected_value": 0.0,
    "risk_reward_ratio": 0.0
  }
}
```"""

# ---------------------------------------------------------------------------
# Analysis Runner
# ---------------------------------------------------------------------------

def extract_json(content: str) -> Optional[Dict]:
    """Extract JSON from LLM response."""
    import re
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass
    match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', content, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1).strip())
        except json.JSONDecodeError:
            pass
    match = re.search(r'\{.*\}', content, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass
    return None


def fetch_fundamentals(ticker: str, market: str = "US") -> Dict:
    """Fetch fundamental data for a ticker."""
    try:
        import yfinance as yf
        symbol = ticker
        if market.upper() == "KR":
            symbol = ticker + ".KS"  # Korean ticker suffix for yfinance

        t = yf.Ticker(symbol)
        info = t.info
        return {
            "name": info.get("longName", info.get("shortName", ticker)),
            "sector": info.get("sector", ""),
            "industry": info.get("industry", ""),
            "market_cap": info.get("marketCap", 0),
            "pe_ratio": info.get("trailingPE"),
            "forward_pe": info.get("forwardPE"),
            "price_to_book": info.get("priceToBook"),
            "roe": info.get("returnOnEquity"),
            "revenue_growth": info.get("revenueGrowth"),
            "profit_margins": info.get("profitMargins"),
            "debt_to_equity": info.get("debtToEquity"),
            "current_price": info.get("currentPrice") or info.get("regularMarketPreviousClose"),
        }
    except Exception as e:
        return {"error": str(e), "ticker": ticker}


def run_qualitative_analysis(
    ticker: str,
    market: str = "US",
    dimensions: Optional[List[str]] = None,
    dry_run: bool = False
) -> Dict:
    """Run qualitative analysis on a stock across specified dimensions."""
    if not DEEPSEEK_API_KEY and not dry_run:
        return {"error": "DEEPSEEK_API_KEY not set in .env"}

    fundamentals = fetch_fundamentals(ticker, market)
    name = fundamentals.get("name", ticker)

    if dimensions is None:
        dimensions = ["business_model", "competitive_position", "moat", "management", "valuation"]

    prompt_map = {
        "business_model": BUSINESS_MODEL_PROMPT,
        "competitive_position": COMPETITIVE_POSITION_PROMPT,
        "moat": MOAT_PROMPT,
        "management": MANAGEMENT_PROMPT,
        "valuation": VALUATION_SCENARIO_PROMPT,
    }

    results = {
        "ticker": ticker,
        "name": name,
        "market": market,
        "analyzed_at": datetime.now().isoformat(),
        "fundamentals": fundamentals,
        "analysis": {},
        "errors": [],
    }

    if dry_run:
        print(f"\n[DRY RUN] Would analyze {ticker} ({name}) across {len(dimensions)} dimensions:")
        for d in dimensions:
            prompt = prompt_map[d].format(name=name, ticker=ticker, fundamentals=json.dumps(fundamentals, indent=2))
            print(f"  - {d}: prompt length = {len(prompt)} chars")
        return results

    try:
        from openai import OpenAI
        client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url="https://api.deepseek.com")

        for dimension in dimensions:
            if dimension not in prompt_map:
                results["errors"].append(f"Unknown dimension: {dimension}")
                continue

            prompt_text = prompt_map[dimension].format(
                name=name,
                ticker=ticker,
                fundamentals=json.dumps(fundamentals, ensure_ascii=False, indent=2)
            )

            print(f"\n[DD] Analyzing {dimension} for {ticker}...")
            try:
                response = client.chat.completions.create(
                    model="deepseek-v4-pro",
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": prompt_text},
                    ],
                    temperature=0.2,
                    max_tokens=2000,
                )
                content = response.choices[0].message.content
                parsed = extract_json(content)
                if parsed:
                    results["analysis"][dimension] = parsed
                    print(f"  [OK] {dimension} completed")
                else:
                    results["errors"].append(f"Failed to parse JSON for {dimension}")
                    results["analysis"][dimension] = {"raw_response": content, "parse_error": True}
            except Exception as e:
                results["errors"].append(f"{dimension} API call failed: {e}")
                results["analysis"][dimension] = {"error": str(e)}

    except ImportError:
        results["errors"].append("openai package not installed. pip install openai")
    except Exception as e:
        results["errors"].append(f"Analysis failed: {e}")

    return results


# ---------------------------------------------------------------------------
# Report Formatting
# ---------------------------------------------------------------------------

def format_analysis_report(results: Dict) -> str:
    """Format analysis results as a readable markdown report."""
    lines = [
        f"# {results.get('name', results.get('ticker'))} ({results.get('ticker')}) — 심층 분석",
        f"분석일: {results.get('analyzed_at', '')[:10]}",
        "",
    ]

    # Fundamentals summary
    fund = results.get("fundamentals", {})
    if fund and "error" not in fund:
        lines.extend([
            "## 기본 정보",
            f"- 섹터: {fund.get('sector', 'N/A')} / 산업: {fund.get('industry', 'N/A')}",
            f"- 시가총액: {fund.get('market_cap', 0):,.0f} USD" if fund.get('market_cap') else "",
            f"- P/E: {fund.get('pe_ratio', 'N/A')} (Forward: {fund.get('forward_pe', 'N/A')})",
            f"- P/B: {fund.get('price_to_book', 'N/A')}",
            f"- ROE: {fund.get('roe', 'N/A')}%" if fund.get('roe') else "",
            f"- 매출 성장률: {fund.get('revenue_growth', 'N/A')}%" if fund.get('revenue_growth') else "",
            f"- 부채비율: {fund.get('debt_to_equity', 'N/A')}",
            f"- 현재가: {fund.get('current_price', 'N/A')}",
            "",
        ])

    # Analysis sections
    analysis = results.get("analysis", {})

    if "business_model" in analysis:
        bm = analysis["business_model"].get("business_model", {})
        lines.extend([
            "## 비즈니스 모델",
            f"- 핵심 제품: {bm.get('core_product', 'N/A')}",
            f"- 수익 유형: {bm.get('revenue_type', 'N/A')} (반복: {bm.get('recurring_pct', 0)}%)",
            f"- 공급망 리스크: {bm.get('supply_chain_risk', 'N/A')}",
            "",
        ])

    if "competitive_position" in analysis:
        cp = analysis["competitive_position"].get("competitive_position", {})
        lines.extend([
            f"## 경쟁 포지션 (종합: {cp.get('overall_assessment', 'N/A')})",
            f"- 평균 점수: {cp.get('average_score', 'N/A')}/5",
            "",
        ])

    if "moat" in analysis:
        moat = analysis["moat"].get("moat", {})
        lines.extend([
            f"## 경제적 해자 (평가: {moat.get('overall_moat_rating', 'N/A')})",
            f"- 트렌드: {moat.get('moat_trend', 'N/A')}",
            f"- 주요 리스크: {moat.get('moat_risk', 'N/A')}",
            "",
        ])

    if "management" in analysis:
        mgmt = analysis["management"].get("management", {})
        lines.extend([
            f"## 경영진 (평가: {mgmt.get('overall_rating', 'N/A')})",
            f"- 핵심인물 리스크: {mgmt.get('key_person_risk', 'N/A')}",
            f"- 승계 계획: {mgmt.get('succession_plan', 'N/A')}",
            "",
        ])

    if "valuation" in analysis:
        val = analysis["valuation"].get("valuation_scenarios", {})
        lines.extend([
            "## 밸류에이션 시나리오",
            f"현재가: {val.get('current_price', 'N/A')}",
            f"기대값: {val.get('expected_value', 'N/A')}",
            f"리스크/보상 비율: {val.get('risk_reward_ratio', 'N/A')}",
            "",
        ])

    if results.get("errors"):
        lines.extend([
            "## 오류",
            *[f"- {e}" for e in results["errors"]],
            "",
        ])

    return "\n".join(lines)


def save_results(results: Dict, output_path: str, format: str = "json") -> str:
    """Save analysis results to file."""
    os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else DATA_DIR, exist_ok=True)

    if not os.path.dirname(output_path):
        output_path = os.path.join(DATA_DIR, output_path)

    if format == "json":
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
    else:
        report = format_analysis_report(results)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(report)

    return output_path


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Qualitative stock analysis with DeepSeek")
    parser.add_argument("--ticker", "-t", type=str, required=True,
                        help="Stock ticker (e.g., AAPL, 139260 for KR market)")
    parser.add_argument("--market", "-m", type=str, default="US",
                        choices=["US", "KR"], help="Market: US or KR (default: US)")
    parser.add_argument("--dimensions", "-d", type=str, nargs="+",
                        default=None,
                        choices=["business_model", "competitive_position", "moat", "management", "valuation"],
                        help="Analysis dimensions to run (default: all)")
    parser.add_argument("--output", "-o", type=str, default=None,
                        help="Output file path")
    parser.add_argument("--format", "-f", type=str, default="json",
                        choices=["json", "md"], help="Output format")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be analyzed without calling LLM")
    parser.add_argument("--list-prompts", action="store_true",
                        help="Show all available analysis prompts")
    args = parser.parse_args()

    if args.list_prompts:
        print("Available Qualitative Analysis Dimensions:")
        print("  1. business_model     — 핵심 제품, 매출 구성, 고객 구조, 수익 모델, 공급망, 단위 경제")
        print("  2. competitive_position — Porter's Five Forces (5개 차원 점수화)")
        print("  3. moat               — Morningstar 5대 해자 유형별 평가")
        print("  4. management         — CEO, IR 품질, 자본 배분, 지배구조")
        print("  5. valuation          — Bull/Base/Bear 3가지 시나리오")
        return

    print(f"\n{'=' * 60}")
    print(f"  Qualitative Deep-Dive: {args.ticker} ({args.market})")
    print(f"  {'(DRY RUN)' if args.dry_run else ''}")
    print(f"{'=' * 60}")

    results = run_qualitative_analysis(
        ticker=args.ticker,
        market=args.market,
        dimensions=args.dimensions,
        dry_run=args.dry_run
    )

    if args.dry_run:
        return

    # Save
    if args.output:
        output_path = save_results(results, args.output, args.format)
    else:
        slug = args.ticker.lower().replace(".", "-")
        if args.format == "json":
            filename = f"deep_dive_{slug}.json"
        else:
            filename = f"deep_dive_{slug}.md"
        output_path = save_results(results, filename, args.format)

    print(f"\n[SAVED] {output_path}")

    # Console output
    if args.format == "md":
        report = format_analysis_report(results)
        print("\n" + report)
    else:
        print(f"\nDimensions analyzed: {list(results.get('analysis', {}).keys())}")
        if results.get("errors"):
            print(f"Errors: {len(results['errors'])}")


if __name__ == "__main__":
    main()
