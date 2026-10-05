from __future__ import annotations

import hashlib
import math
import random
from collections import Counter, defaultdict
from datetime import date, datetime
from itertools import combinations, product

import statistics


def _exp_weights(n: int, half_life: float = 12.0):
    if n <= 0:
        return []
    lam = math.log(2) / max(half_life, 1e-6)
    # oldest -> newest
    ages = list(reversed(range(n)))
    return [math.exp(-lam * a) for a in ages]


def _normalize(d: dict):
    if not d:
        return d
    vals = list(d.values())
    lo, hi = min(vals), max(vals)
    if hi - lo < 1e-12:
        return {k: 0.5 for k in d}
    return {k: (v - lo) / (hi - lo) for k, v in d.items()}


def _special(draw):
    vals = draw.get('prizes', {}).get('2TỶ', [])
    return vals[0] if vals else None


def _all_loto2(draw):
    out = []
    for vals in draw.get('prizes', {}).values():
        for v in vals:
            if v and v.isdigit() and len(v) >= 2:
                out.append(v[-2:])
    return out


def _all_loto3(draw):
    out = []
    for vals in draw.get('prizes', {}).values():
        for v in vals:
            if v and v.isdigit() and len(v) >= 3:
                out.append(v[-3:])
    return out


def _first_value(draw, prize: str):
    vals = draw.get('prizes', {}).get(prize, [])
    return vals[0] if vals else None


def _formula_candidates(prev_draw: dict, target_date: str):
    """Generate formula library using only the previous same-province draw.

    The library intentionally includes the user's observed pattern
    `previous draw day + last 4 digits of previous special prize`, but also
    tests analogous constructions from other prize tiers so walk-forward
    backtest can reject one-off coincidences.
    """
    s = _special(prev_draw)
    if not s or len(s) != 6:
        return {}
    pd = datetime.fromisoformat(prev_draw['draw_date']).date()
    td = datetime.fromisoformat(target_date).date()
    digit_sum = sum(map(int, s))

    prefixes = {
        'Ngày kỳ trước': f'{pd.day:02d}',
        'Ngày kỳ dự đoán': f'{td.day:02d}',
        '2 số đầu ĐB': s[:2],
        '2 số cuối ĐB': s[-2:],
        'Tổng chữ số ĐB mod100': f'{digit_sum % 100:02d}',
    }
    # Add 2-digit features from other prize tiers.
    for prize in ['100N','200N','400N','1TR','3TR','10TR','15TR','30TR']:
        v = _first_value(prev_draw, prize)
        if v and len(v) >= 2:
            prefixes[f'2 số cuối {prize}'] = v[-2:]

    suffixes = {
        '4 số cuối ĐB': s[-4:],
        '4 số đầu ĐB': s[:4],
    }
    for prize in ['400N','1TR','3TR','10TR','15TR','30TR']:
        v = _first_value(prev_draw, prize)
        if v and len(v) >= 4:
            suffixes[f'4 số cuối {prize}'] = v[-4:]

    out = {}
    for pn, pv in prefixes.items():
        for sn, sv in suffixes.items():
            out[f'{pn} + {sn}'] = pv + sv

    # Pure transforms of the previous special prize.
    out.update({
        'Đảo ngược 6 số ĐB': s[::-1],
        'Xoay trái 2 chữ số ĐB': s[2:] + s[:2],
        'Xoay phải 2 chữ số ĐB': s[-2:] + s[:-2],
    })
    return out


def backtest_formulas(draws: list[dict]):
    metrics = defaultdict(lambda: {'tests': 0, 'exact': 0, 'suffix4': 0, 'suffix3': 0, 'suffix2': 0, 'digit_matches': 0})
    valid = [d for d in draws if _special(d)]
    for i in range(1, len(valid)):
        prev, cur = valid[i - 1], valid[i]
        actual = _special(cur)
        for name, pred in _formula_candidates(prev, cur['draw_date']).items():
            m = metrics[name]
            m['tests'] += 1
            m['exact'] += int(pred == actual)
            m['suffix4'] += int(pred[-4:] == actual[-4:])
            m['suffix3'] += int(pred[-3:] == actual[-3:])
            m['suffix2'] += int(pred[-2:] == actual[-2:])
            m['digit_matches'] += sum(a == b for a, b in zip(pred, actual))
    out = []
    for name, m in metrics.items():
        t = max(m['tests'], 1)
        # Conservative score: exact hits matter, but one isolated hit cannot
        # dominate without repeated suffix/position evidence.
        score = (
            8 * m['exact'] + 3 * m['suffix4'] + 1.5 * m['suffix3'] + 0.7 * m['suffix2'] +
            0.15 * m['digit_matches']
        ) / t
        out.append({
            'name': name, **m,
            'exact_rate': m['exact'] / t,
            'suffix4_rate': m['suffix4'] / t,
            'suffix3_rate': m['suffix3'] / t,
            'suffix2_rate': m['suffix2'] / t,
            'avg_digit_matches': m['digit_matches'] / t,
            'score': score,
        })
    return sorted(out, key=lambda x: (x['score'], x['tests']), reverse=True)


def xsmn_analysis(draws: list[dict], target_date: str, top_n: int = 20):
    valid = [d for d in draws if _special(d)]
    if len(valid) < 6:
        return {'error': 'Chưa đủ dữ liệu cùng đài để phân tích ổn định.', 'draw_count': len(valid)}

    specials = [_special(d) for d in valid]
    weights = _exp_weights(len(valid), half_life=12)

    # Position model + one-step transition model for the six special-prize digits.
    pos_counts = [defaultdict(float) for _ in range(6)]
    trans_counts = [defaultdict(lambda: defaultdict(float)) for _ in range(6)]
    for i, s in enumerate(specials):
        w = weights[i]
        for p, ch in enumerate(s):
            pos_counts[p][ch] += w
        if i > 0:
            prev = specials[i - 1]
            for p, ch in enumerate(s):
                trans_counts[p][prev[p]][ch] += w

    prev = specials[-1]
    pos_probs = []
    for p in range(6):
        base = {str(d): pos_counts[p].get(str(d), 0.0) + 0.25 for d in range(10)}
        trans = trans_counts[p].get(prev[p], {})
        scores = {d: 0.60 * base[d] + 0.40 * (trans.get(d, 0.0) + 0.15) for d in base}
        z = sum(scores.values())
        pos_probs.append({d: v / z for d, v in scores.items()})

    # All-prize suffix signal. This is where G1..G8 contribute to ranking.
    recent = valid[-30:]
    loto2 = Counter(); loto3 = Counter()
    rw = _exp_weights(len(recent), 10)
    for i, d in enumerate(recent):
        w = rw[i]
        for x in _all_loto2(d): loto2[x] += w
        for x in _all_loto3(d): loto3[x] += w
    n2 = _normalize(dict(loto2)); n3 = _normalize(dict(loto3))

    # Beam search over digit-position probabilities.
    beam = [('', 1.0)]
    for p in range(6):
        top_digits = sorted(pos_probs[p].items(), key=lambda kv: kv[1], reverse=True)[:5]
        nxt = []
        for prefix, sc in beam:
            for digit, prob in top_digits:
                nxt.append((prefix + digit, sc * prob))
        beam = sorted(nxt, key=lambda kv: kv[1], reverse=True)[:500]

    formula_stats = backtest_formulas(valid)
    formula_scores = {x['name']: x['score'] for x in formula_stats}
    all_formula_candidates = _formula_candidates(valid[-1], target_date)
    formula_by_value = defaultdict(float); formula_reasons = defaultdict(list)
    for name, value in all_formula_candidates.items():
        fs = formula_scores.get(name, 0.0)
        formula_by_value[value] += fs
        formula_reasons[value].append(name)
    fnorm = _normalize(dict(formula_by_value))

    candidates = {}
    for s, pscore in beam:
        suffix_score = 0.65 * n2.get(s[-2:], 0.0) + 0.35 * n3.get(s[-3:], 0.0)
        candidates[s] = {'value': s, 'position_score': pscore, 'suffix_score': suffix_score, 'formula_score': fnorm.get(s, 0.0), 'reasons': formula_reasons.get(s, [])}
    for s in all_formula_candidates.values():
        if s not in candidates:
            pscore = math.prod(pos_probs[p].get(ch, 1e-6) for p, ch in enumerate(s))
            suffix_score = 0.65 * n2.get(s[-2:], 0.0) + 0.35 * n3.get(s[-3:], 0.0)
            candidates[s] = {'value': s, 'position_score': pscore, 'suffix_score': suffix_score, 'formula_score': fnorm.get(s, 0.0), 'reasons': formula_reasons.get(s, [])}

    pnorm = _normalize({k: v['position_score'] for k, v in candidates.items()})
    for k, item in candidates.items():
        item['score'] = 100 * (0.58 * pnorm.get(k, 0) + 0.27 * item['suffix_score'] + 0.15 * item['formula_score'])
    top = sorted(candidates.values(), key=lambda x: x['score'], reverse=True)[:top_n]

    top2 = sorted(n2.items(), key=lambda kv: kv[1], reverse=True)[:12]
    top3 = sorted(n3.items(), key=lambda kv: kv[1], reverse=True)[:12]

    # Show only the most historically supported formula predictions, but always
    # retain the user's observed "previous day + DB last4" formula for audit.
    ranked_formula_today = sorted(
        [{'name': n, 'value': v, 'backtest_score': formula_scores.get(n, 0.0)} for n, v in all_formula_candidates.items()],
        key=lambda x: x['backtest_score'], reverse=True
    )
    key_name = 'Ngày kỳ trước + 4 số cuối ĐB'
    shown = ranked_formula_today[:15]
    if not any(x['name'] == key_name for x in shown):
        key_item = next((x for x in ranked_formula_today if x['name'] == key_name), None)
        if key_item: shown.append(key_item)

    return {
        'draw_count': len(valid),
        'history_from': valid[0]['draw_date'],
        'history_to': valid[-1]['draw_date'],
        'last_special': prev,
        'last_date': valid[-1]['draw_date'],
        'target_date': target_date,
        'candidates': top,
        'top_suffix2': [{'value': k, 'score': round(v * 100, 2)} for k, v in top2],
        'top_suffix3': [{'value': k, 'score': round(v * 100, 2)} for k, v in top3],
        'formulas': formula_stats[:40],
        'formula_count': len(formula_stats),
        'formula_today': [{**x, 'backtest_score': round(x['backtest_score'], 4)} for x in shown],
        'note': 'Điểm là xếp hạng thống kê lịch sử, không phải xác suất trúng thực tế.'
    }

def _viet_scores(draws, max_n: int):
    n = len(draws)
    weights = _exp_weights(n, half_life=24)
    freq = defaultdict(float)
    last_seen = {i: None for i in range(1, max_n + 1)}
    pairs = defaultdict(float)
    sums = []
    for i, d in enumerate(draws):
        w = weights[i]
        nums = d['numbers']
        sums.append(sum(nums))
        for x in nums:
            freq[x] += w
            last_seen[x] = i
        for a, b in combinations(nums, 2):
            pairs[(a, b)] += w
    freq_n = _normalize({i: freq.get(i, 0.0) for i in range(1, max_n + 1)})
    gaps = {i: (n - 1 - last_seen[i]) if last_seen[i] is not None else n for i in range(1, max_n + 1)}
    gap_n = _normalize(gaps)
    score = {i: 0.72 * freq_n[i] + 0.28 * gap_n[i] for i in range(1, max_n + 1)}
    return score, pairs, sums, gaps


def _set_quality(nums, score, pairs, sum_mu, sum_sd, max_n):
    nums = tuple(sorted(nums))
    base = sum(score[x] for x in nums) / 6
    pair_vals = [pairs.get(tuple(sorted((a, b))), 0.0) for a, b in combinations(nums, 2)]
    pair_raw = sum(pair_vals) / max(len(pair_vals), 1)
    odd = sum(x % 2 for x in nums)
    low = sum(x <= max_n / 2 for x in nums)
    bal = 1 - (abs(odd - 3) + abs(low - 3)) / 6
    s = sum(nums)
    sumfit = math.exp(-0.5 * ((s - sum_mu) / max(sum_sd, 1.0)) ** 2)
    consecutive_pen = sum(1 for a, b in zip(nums, nums[1:]) if b == a + 1)
    return base + 0.08 * pair_raw + 0.18 * bal + 0.12 * sumfit - 0.03 * consecutive_pen


def vietlott_analysis(draws: list[dict], product_name: str, top_sets: int = 12):
    max_n = 45 if product_name == 'mega645' else 55
    if len(draws) < 20:
        return {'error': 'Chưa đủ dữ liệu Vietlott để phân tích.', 'draw_count': len(draws)}
    score, pairs, sums, gaps = _viet_scores(draws, max_n)
    sum_mu = statistics.fmean(sums); sum_sd = statistics.pstdev(sums) if len(sums) > 1 else 1.0

    ranked = sorted(score.items(), key=lambda kv: kv[1], reverse=True)
    hot = ranked[:12]
    cold = sorted(score.items(), key=lambda kv: kv[1])[:12]
    overdue = sorted(gaps.items(), key=lambda kv: kv[1], reverse=True)[:12]

    # Reproducible Monte Carlo generation: same history => same candidates.
    seed_src = f'{product_name}|{draws[-1]["draw_id"]}|{draws[-1]["draw_date"]}'
    seed = int(hashlib.sha256(seed_src.encode()).hexdigest()[:16], 16)
    rng = random.Random(seed)
    weights = [0.15 + score[i] for i in range(1, max_n + 1)]
    population = list(range(1, max_n + 1))

    sets = {}
    for _ in range(6000):
        # weighted sampling without replacement
        avail = population[:]
        ws = weights[:]
        pick = []
        for __ in range(6):
            total = sum(ws)
            r = rng.random() * total
            acc = 0
            idx = 0
            for idx, w in enumerate(ws):
                acc += w
                if acc >= r:
                    break
            pick.append(avail.pop(idx)); ws.pop(idx)
        pick = tuple(sorted(pick))
        q = _set_quality(pick, score, pairs, sum_mu, sum_sd, max_n)
        if q > sets.get(pick, -999):
            sets[pick] = q
    best = sorted(sets.items(), key=lambda kv: kv[1], reverse=True)[:top_sets]
    qnorm = _normalize({k: v for k, v in best})

    # Simple walk-forward comparison: model top-12 pool vs random expected matches.
    tests = 0; model_matches = 0
    start = max(20, len(draws) - 80)
    for i in range(start, len(draws)):
        hist = draws[:i]
        s2, _, _, _ = _viet_scores(hist, max_n)
        pool = {n for n, _ in sorted(s2.items(), key=lambda kv: kv[1], reverse=True)[:12]}
        model_matches += len(pool.intersection(draws[i]['numbers']))
        tests += 1
    avg_pool_matches = model_matches / tests if tests else 0
    random_pool_expected = 12 * 6 / max_n

    jackpot_combinations = math.comb(max_n, 6)
    return {
        'draw_count': len(draws),
        'history_from': draws[0]['draw_date'],
        'history_to': draws[-1]['draw_date'],
        'last_draw': draws[-1],
        'hot': [{'number': n, 'score': round(v * 100, 2)} for n, v in hot],
        'cold': [{'number': n, 'score': round(v * 100, 2)} for n, v in cold],
        'overdue': [{'number': n, 'gap_draws': g} for n, g in overdue],
        'sets': [{'numbers': list(nums), 'score': round(qnorm.get(nums, 0) * 100, 2), 'sum': sum(nums)} for nums, _ in best],
        'theoretical_jackpot_probability': 1 / jackpot_combinations,
        'jackpot_combinations': jackpot_combinations,
        'backtest': {
            'tests': tests,
            'top12_pool_avg_matches': round(avg_pool_matches, 4),
            'random_top12_expected_matches': round(random_pool_expected, 4),
            'edge_vs_random': round(avg_pool_matches - random_pool_expected, 4),
        },
        'note': 'Mỗi tổ hợp 6 số hợp lệ vẫn có xác suất lý thuyết bằng nhau nếu kỳ quay độc lập và công bằng.'
    }
