#!/usr/bin/env python3
"""
KRX 신고가 & 거래량 스캐너
FinanceDataReader 사용 (네이버 금융 데이터, 인증 불필요)
"""

import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

try:
    import FinanceDataReader as fdr
    import pandas as pd
except ImportError:
    print("설치 필요: pip install finance-datareader pandas")
    sys.exit(1)

HISTORY_FILE = 'data/history.json'
RESULT_FILE = 'data/market_data.json'
LOOKBACK = 260              # 52주 + 여유분
VOLUME_AVG_DAYS = 20
VOLUME_SPIKE_RATIO = 2.0
MAX_WORKERS = 8             # 동시 다운로드 스레드 (네이버 부하 고려)
INITIAL_DAYS = 400          # 첫 수집 시 캘린더일 (≈260 거래일 확보)


# ─────────────────────────────────────────────
# 1. 유틸
# ─────────────────────────────────────────────
def load_json(path, default):
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    return default


def save_json(path, data, indent=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False,
                  separators=(',', ':') if indent is None else None,
                  indent=indent)


# ─────────────────────────────────────────────
# 2. 종목 목록
# ─────────────────────────────────────────────
def get_listings():
    """KOSPI + KOSDAQ 전 종목: {code: {'name','market','m'}}"""
    listings = {}
    for market in ['KOSPI', 'KOSDAQ']:
        df = fdr.StockListing(market)
        m = 'K' if market == 'KOSPI' else 'Q'
        for _, row in df.iterrows():
            code = str(row['Code']).zfill(6)
            listings[code] = {
                'name': str(row['Name']),
                'market': market,
                'm': m,
            }
    return listings


# ─────────────────────────────────────────────
# 3. 종목별 OHLCV 다운로드
# ─────────────────────────────────────────────
def fetch_ticker(code, market_letter, start_date, end_date):
    """단일 종목 OHLCV → {YYYYMMDD: {h,c,v,m}}.  실패 시 None."""
    try:
        df = fdr.DataReader(code, start_date, end_date)
    except Exception:
        return None
    if df is None or df.empty:
        return {}

    out = {}
    for ts, row in df.iterrows():
        d = ts.strftime('%Y%m%d')
        try:
            h = int(row.get('High') or 0)
            c = int(row.get('Close') or 0)
            v = int(row.get('Volume') or 0)
        except (ValueError, TypeError):
            continue
        if c == 0:
            continue
        out[d] = {'h': h, 'c': c, 'v': v, 'm': market_letter}
    return out


# ─────────────────────────────────────────────
# 4. 거래일 목록 (전체 history에서 도출)
# ─────────────────────────────────────────────
def derive_trading_dates(history, n=LOOKBACK):
    all_dates = set()
    for td in history.values():
        all_dates.update(td.keys())
    return sorted(all_dates)[-n:]


# ─────────────────────────────────────────────
# 5. 연속 신고가 일수 계산 (원본 동일)
# ─────────────────────────────────────────────
def count_consecutive(ticker, history, trading_dates):
    streak = 0
    n = len(trading_dates)
    for i in range(n - 1, max(-1, n - 31), -1):
        d = trading_dates[i]
        d_data = history.get(ticker, {}).get(d)
        if not d_data or d_data['h'] == 0:
            break
        lookback = trading_dates[max(0, i - 252):i]
        prev_highs = [
            history[ticker][ld]['h']
            for ld in lookback
            if ld in history.get(ticker, {}) and history[ticker][ld]['h'] > 0
        ]
        if not prev_highs:
            streak += 1
            continue
        if d_data['h'] > max(prev_highs):
            streak += 1
        else:
            break
    return streak


# ─────────────────────────────────────────────
# 6. 분석 (원본 로직 동일, 종목명/시장은 listings에서 조회)
# ─────────────────────────────────────────────
def analyze(history, trading_dates, listings):
    today = trading_dates[-1]
    prev_251 = set(trading_dates[-252:-1])

    highs = []
    volume_spikes = []

    for ticker, dates_data in history.items():
        today_d = dates_data.get(today)
        if not today_d or today_d['c'] == 0:
            continue

        today_h = today_d['h']
        today_c = today_d['c']
        today_v = today_d['v']

        info = listings.get(ticker, {})
        market = info.get('market') or ('KOSPI' if today_d.get('m') == 'K' else 'KOSDAQ')
        name = info.get('name', ticker)

        # 52주 신고가
        prev_highs = [
            dates_data[d]['h']
            for d in prev_251
            if d in dates_data and dates_data[d]['h'] > 0
        ]
        if not prev_highs:
            continue

        prev_52w_max = max(prev_highs)
        is_52w_high = today_h > prev_52w_max
        breakout_pct = round((today_h / prev_52w_max - 1) * 100, 2) if prev_52w_max > 0 else 0

        if is_52w_high:
            consecutive = count_consecutive(ticker, history, trading_dates)
            first_idx = len(trading_dates) - consecutive
            first_date = trading_dates[first_idx] if first_idx >= 0 else today
            highs.append({
                'code': ticker,
                'name': name,
                'market': market,
                'close': today_c,
                'high': today_h,
                'prev_52w_high': prev_52w_max,
                'breakout_pct': breakout_pct,
                'consecutive': consecutive,
                'first_high_date': first_date,
                'days_since_first': consecutive - 1,
                'volume': today_v,
            })

        # 거래량 급증 (오늘 제외 직전 20거래일 평균 대비)
        recent_dates = [d for d in trading_dates[-21:-1] if d in dates_data]
        recent_vols = [dates_data[d]['v'] for d in recent_dates if dates_data[d]['v'] > 0]
        if recent_vols and today_v > 0:
            avg_vol = sum(recent_vols) / len(recent_vols)
            vol_ratio = today_v / avg_vol if avg_vol > 0 else 0
            if vol_ratio >= VOLUME_SPIKE_RATIO:
                volume_spikes.append({
                    'code': ticker,
                    'name': name,
                    'market': market,
                    'close': today_c,
                    'volume': today_v,
                    'avg_vol_20d': int(avg_vol),
                    'vol_ratio': round(vol_ratio, 2),
                    'is_52w_high': is_52w_high,
                })

    highs.sort(key=lambda x: (-x['consecutive'], -x['breakout_pct']))
    volume_spikes.sort(key=lambda x: -x['vol_ratio'])

    return {
        'highs_today': highs,
        'consecutive_2plus': [x for x in highs if x['consecutive'] >= 2],
        'consecutive_3plus': [x for x in highs if x['consecutive'] >= 3],
        'volume_spikes': volume_spikes,
        'volume_and_high': [x for x in volume_spikes if x['is_52w_high']],
    }


# ─────────────────────────────────────────────
# 7. 메인
# ─────────────────────────────────────────────
def main():
    print(f"\n{'='*50}")
    print(f"  KRX 신고가 스캐너 (FDR)  |  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*50}\n")

    # 종목 목록
    print("종목 목록 조회 중...")
    listings = get_listings()
    print(f"  KOSPI+KOSDAQ {len(listings):,}종목\n")

    # 히스토리 로드
    history = load_json(HISTORY_FILE, {})
    print(f"기존 히스토리: {len(history):,}종목")

    end_date = datetime.today()
    end_str = end_date.strftime('%Y-%m-%d')
    default_start = (end_date - timedelta(days=INITIAL_DAYS)).strftime('%Y-%m-%d')

    def ticker_start(code):
        td = history.get(code, {})
        if not td:
            return default_start
        latest = max(td.keys())
        return (datetime.strptime(latest, '%Y%m%d') + timedelta(days=1)).strftime('%Y-%m-%d')

    codes = list(listings.keys())
    total = len(codes)
    print(f"\n전 종목 OHLCV 다운로드 (워커 {MAX_WORKERS})...")

    success = 0
    fail = 0
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futures = {
            ex.submit(fetch_ticker, c, listings[c]['m'], ticker_start(c), end_str): c
            for c in codes
        }
        for i, fut in enumerate(as_completed(futures), 1):
            code = futures[fut]
            data = fut.result()
            if data is None:
                fail += 1
            else:
                if code not in history:
                    history[code] = {}
                history[code].update(data)
                success += 1
            if i % 200 == 0 or i == total:
                elapsed = time.time() - t0
                rate = i / elapsed if elapsed else 0
                print(f"  [{i:5d}/{total}] 성공 {success:5d} 실패 {fail:4d}  "
                      f"({elapsed:5.1f}s, {rate:.1f} req/s)")

    # 거래일 목록
    trading_dates = derive_trading_dates(history, LOOKBACK)
    if not trading_dates:
        print("거래일이 없습니다. 종료.")
        return
    today = trading_dates[-1]
    print(f"\n거래일: {len(trading_dates)}일  |  최신: {today}")

    # 오래된 데이터 정리
    valid = set(trading_dates)
    for code in list(history.keys()):
        history[code] = {d: v for d, v in history[code].items() if d in valid}
        if not history[code]:
            del history[code]

    # 분석
    print("\n분석 중...")
    results = analyze(history, trading_dates, listings)

    stats = {
        'total_stocks': len([c for c, d in history.items() if today in d]),
        'highs_today': len(results['highs_today']),
        'consecutive_2plus': len(results['consecutive_2plus']),
        'consecutive_3plus': len(results['consecutive_3plus']),
        'volume_spikes': len(results['volume_spikes']),
        'volume_and_high': len(results['volume_and_high']),
    }

    print("\n저장 중...")
    save_json(HISTORY_FILE, history)
    save_json(RESULT_FILE, {
        'updated_at': today,
        'stats': stats,
        'results': results,
    }, indent=2)

    print(f"\n{'='*50}")
    print(f"  완료! 오늘 기준 분석 결과")
    print(f"  전체 종목수    : {stats['total_stocks']:,}")
    print(f"  52주 신고가    : {stats['highs_today']:,}종목")
    print(f"  연속 2회 이상  : {stats['consecutive_2plus']:,}종목")
    print(f"  연속 3회 이상  : {stats['consecutive_3plus']:,}종목")
    print(f"  거래량 급증    : {stats['volume_spikes']:,}종목")
    print(f"  신고가+거래량  : {stats['volume_and_high']:,}종목")
    print(f"{'='*50}\n")


if __name__ == '__main__':
    main()
