from __future__ import annotations

import hashlib
import math
import random
import statistics
from collections import Counter, defaultdict
from datetime import datetime
from itertools import combinations


# ------------------------------ shared helpers ------------------------------

def _exp_weights(n: int, half_life: float = 12.0):
    if n <= 0:
        return []
    lam = math.log(2) / max(half_life, 1e-6)
    ages = list(reversed(range(n)))  # oldest -> newest
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


def _safe_log(x: float) -> float:
    return math.log(max(x, 1e-12))


def _top_numbers_from_positions(pos_probs: list[dict[str, float]], k: int = 20):
    """Beam-search top exact numbers from six independent position distributions."""
    beam = [('', 0.0)]
    keep = max(k * 6, 120)
    for p in range(6):
        nxt = []
        for prefix, logp in beam:
            for digit, prob in pos_probs[p].items():
                nxt.append((prefix + digit, logp + _safe_log(prob)))
        beam = sorted(nxt, key=lambda x: x[1], reverse=True)[:keep]
    return beam[:k]


def _suffix2_from_positions(pos_probs: list[dict[str, float]]):
    out = {}
    for a in map(str, range(10)):
        for b in map(str, range(10)):
            out[a + b] = pos_probs[4][a] * pos_probs[5][b]
    z = sum(out.values()) or 1.0
    return {k: v / z for k, v in out.items()}


# -------------------------- XSMN adaptive engine ----------------------------

POSITION_VARIANTS = [
    ('freq', 12), ('freq', 24), ('freq', 52), ('freq', 104),
    ('transition', 24), ('transition', 52), ('transition', 104),
    ('delta', 24), ('delta', 52), ('delta', 104),
    ('blend', 24), ('blend', 52), ('blend', 104),
]

MODEL_LABELS = {
    'freq': 'Tần suất vị trí',
    'transition': 'Chuyển trạng thái từ kỳ trước',
    'delta': 'Độ lệch chữ số so với kỳ trước',
    'blend': 'Kết hợp tần suất + chuyển trạng thái + độ lệch',
}


def _fit_position_model(draws: list[dict], kind: str, window: int):
    valid = [d for d in draws if _special(d)]
    if len(valid) < 5:
        return [{str(i): 0.1 for i in range(10)} for _ in range(6)]
    hist = valid[-window:]
    specials = [_special(d) for d in hist]
    prev = specials[-1]
    weights = _exp_weights(len(hist), half_life=max(6.0, min(window / 2, 36.0)))

    base_counts = [defaultdict(float) for _ in range(6)]
    trans_counts = [defaultdict(lambda: defaultdict(float)) for _ in range(6)]
    delta_counts = [defaultdict(float) for _ in range(6)]

    for i, s in enumerate(specials):
        w = weights[i]
        for p, ch in enumerate(s):
            base_counts[p][ch] += w
        if i:
            ps = specials[i - 1]
            for p, ch in enumerate(s):
                trans_counts[p][ps[p]][ch] += w
                delta_counts[p][(int(ch) - int(ps[p])) % 10] += w

    result = []
    for p in range(6):
        base_raw = {str(d): base_counts[p].get(str(d), 0.0) + 0.45 for d in range(10)}
        bz = sum(base_raw.values())
        base = {d: v / bz for d, v in base_raw.items()}

        tr_raw = {str(d): trans_counts[p].get(prev[p], {}).get(str(d), 0.0) + 0.30 for d in range(10)}
        tz = sum(tr_raw.values())
        trans = {d: v / tz for d, v in tr_raw.items()}

        de_raw = {}
        for d in range(10):
            delta = (d - int(prev[p])) % 10
            de_raw[str(d)] = delta_counts[p].get(delta, 0.0) + 0.30
        dz = sum(de_raw.values())
        delta = {d: v / dz for d, v in de_raw.items()}

        if kind == 'freq':
            probs = base
        elif kind == 'transition':
            probs = trans
        elif kind == 'delta':
            probs = delta
        else:
            # Blend is deliberately conservative to reduce one-pattern overfit.
            probs = {d: 0.38 * base[d] + 0.34 * trans[d] + 0.28 * delta[d] for d in base}
        z = sum(probs.values()) or 1.0
        result.append({d: v / z for d, v in probs.items()})
    return result


def _eval_position_variant(draws: list[dict], kind: str, window: int, max_tests: int = 48):
    valid = [d for d in draws if _special(d)]
    min_train = max(10, min(window // 2, 20))
    start = max(min_train, len(valid) - max_tests)
    m = {
        'tests': 0, 'nll_sum': 0.0, 'digit_hits': 0, 'digits': 0,
        'suffix2_top1': 0, 'suffix2_top5': 0, 'suffix2_top10': 0,
        'exact_top20': 0,
    }
    for i in range(start, len(valid)):
        hist = valid[:i]
        if len(hist) < min_train:
            continue
        probs = _fit_position_model(hist, kind, window)
        actual = _special(valid[i])
        m['tests'] += 1
        for p, ch in enumerate(actual):
            m['nll_sum'] += -_safe_log(probs[p].get(ch, 1e-12))
            m['digit_hits'] += int(max(probs[p], key=probs[p].get) == ch)
            m['digits'] += 1
        s2 = _suffix2_from_positions(probs)
        ranked2 = [k for k, _ in sorted(s2.items(), key=lambda kv: kv[1], reverse=True)]
        rank = ranked2.index(actual[-2:]) + 1
        m['suffix2_top1'] += int(rank <= 1)
        m['suffix2_top5'] += int(rank <= 5)
        m['suffix2_top10'] += int(rank <= 10)
        top20 = {s for s, _ in _top_numbers_from_positions(probs, 20)}
        m['exact_top20'] += int(actual in top20)

    tests = max(m['tests'], 1)
    digits = max(m['digits'], 1)
    nll = m['nll_sum'] / digits
    log_skill = 1.0 - nll / math.log(10)  # uniform digit baseline = ln(10)
    digit_acc = m['digit_hits'] / digits
    top1 = m['suffix2_top1'] / tests
    top5 = m['suffix2_top5'] / tests
    top10 = m['suffix2_top10'] / tests
    exact20 = m['exact_top20'] / tests

    # Skill is measured against honest random baselines. Sample shrinkage prevents
    # a tiny run of lucky hits from taking over the next prediction.
    shrink = m['tests'] / (m['tests'] + 18.0)
    score = shrink * (
        0.56 * log_skill
        + 0.14 * (digit_acc - 0.10)
        + 0.10 * (top1 - 0.01)
        + 0.10 * (top5 - 0.05)
        + 0.10 * (top10 - 0.10)
    )
    return {
        'kind': kind,
        'window': window,
        'name': f'{MODEL_LABELS[kind]} · {window} kỳ',
        'tests': m['tests'],
        'digit_logloss': nll,
        'log_skill_vs_uniform': log_skill,
        'digit_top1_rate': digit_acc,
        'suffix2_top1_rate': top1,
        'suffix2_top5_rate': top5,
        'suffix2_top10_rate': top10,
        'exact_top20_hits': m['exact_top20'],
        'exact_top20_rate': exact20,
        'score': score,
    }


def _evaluate_position_catalog(draws: list[dict], max_tests: int = 48):
    stats = [_eval_position_variant(draws, k, w, max_tests=max_tests) for k, w in POSITION_VARIANTS]
    return sorted(stats, key=lambda x: (x['score'], x['tests']), reverse=True)


def _select_position_weights(stats: list[dict], max_models: int = 5):
    usable = [s for s in stats if s['tests'] >= 8][:max_models]
    if not usable:
        usable = stats[:1]
    # Softmax on out-of-sample skill. A weak model can participate, but cannot
    # dominate just because of a single exact coincidence.
    raw = [math.exp(8.0 * max(-0.08, min(0.20, s['score']))) for s in usable]
    z = sum(raw) or 1.0
    return [({**s}, r / z) for s, r in zip(usable, raw)]


def _blend_position_models(draws: list[dict], weighted_models):
    out = [{str(d): 0.0 for d in range(10)} for _ in range(6)]
    for stat, weight in weighted_models:
        probs = _fit_position_model(draws, stat['kind'], stat['window'])
        for p in range(6):
            for d, v in probs[p].items():
                out[p][d] += weight * v
    for p in range(6):
        z = sum(out[p].values()) or 1.0
        out[p] = {d: v / z for d, v in out[p].items()}
    return out


# Direct suffix engine: learn how the previous draw's prize endings map to the
# next special-prize ending. This is explicitly "kỳ trước -> kỳ sau".
SUFFIX_SOURCES = ['2TỶ', '30TR', '15TR', '10TR', '3TR', '1TR', '400N', '200N', '100N']
SUFFIX_VARIANTS = [('freq', '2TỶ', 24), ('freq', '2TỶ', 52), ('freq', '2TỶ', 104)] + [
    ('delta', src, window) for src in SUFFIX_SOURCES for window in (24, 52, 104)
]


def _source_suffix2(draw: dict, source: str):
    v = _first_value(draw, source)
    return v[-2:] if v and len(v) >= 2 else None


def _fit_suffix2_model(draws: list[dict], kind: str, source: str, window: int):
    valid = [d for d in draws if _special(d)]
    hist = valid[-window:]
    if len(hist) < 5:
        return {f'{i:02d}': 0.01 for i in range(100)}
    weights = _exp_weights(len(hist), half_life=max(6.0, min(window / 2, 36.0)))
    raw = {f'{i:02d}': 0.20 for i in range(100)}
    if kind == 'freq':
        for i, d in enumerate(hist):
            raw[_special(d)[-2:]] += weights[i]
    else:
        current_source = _source_suffix2(hist[-1], source)
        if current_source is None:
            return {f'{i:02d}': 0.01 for i in range(100)}
        delta_counts = defaultdict(float)
        for i in range(1, len(hist)):
            src = _source_suffix2(hist[i - 1], source)
            if src is None:
                continue
            delta = (int(_special(hist[i])[-2:]) - int(src)) % 100
            delta_counts[delta] += weights[i]
        base = int(current_source)
        for delta, count in delta_counts.items():
            raw[f'{(base + delta) % 100:02d}'] += count
    z = sum(raw.values()) or 1.0
    return {k: v / z for k, v in raw.items()}


def _eval_suffix_variant(draws: list[dict], kind: str, source: str, window: int, max_tests: int = 48):
    valid = [d for d in draws if _special(d)]
    start = max(12, len(valid) - max_tests)
    tests = 0; nll = 0.0; h1 = h5 = h10 = 0
    for i in range(start, len(valid)):
        hist = valid[:i]
        if len(hist) < 10:
            continue
        probs = _fit_suffix2_model(hist, kind, source, window)
        actual = _special(valid[i])[-2:]
        tests += 1
        nll += -_safe_log(probs.get(actual, 1e-12))
        ranked = [k for k, _ in sorted(probs.items(), key=lambda kv: kv[1], reverse=True)]
        rank = ranked.index(actual) + 1
        h1 += int(rank <= 1); h5 += int(rank <= 5); h10 += int(rank <= 10)
    t = max(tests, 1)
    ll = nll / t
    log_skill = 1.0 - ll / math.log(100)
    r1, r5, r10 = h1/t, h5/t, h10/t
    shrink = tests / (tests + 18.0)
    score = shrink * (0.62*log_skill + 0.12*(r1-.01) + 0.12*(r5-.05) + 0.14*(r10-.10))
    label = 'Tần suất ĐB 2 số' if kind == 'freq' else f'Độ lệch từ {source} kỳ trước'
    return {
        'kind': kind, 'source': source, 'window': window,
        'name': f'{label} · {window} kỳ', 'tests': tests,
        'logloss': ll, 'log_skill_vs_uniform': log_skill,
        'top1_rate': r1, 'top5_rate': r5, 'top10_rate': r10,
        'score': score,
    }


def _evaluate_suffix_catalog(draws: list[dict], max_tests: int = 48):
    stats = [_eval_suffix_variant(draws, *v, max_tests=max_tests) for v in SUFFIX_VARIANTS]
    return sorted(stats, key=lambda x: (x['score'], x['tests']), reverse=True)


def _select_suffix_weights(stats: list[dict], max_models: int = 5):
    usable = [s for s in stats if s['tests'] >= 8][:max_models] or stats[:1]
    raw = [math.exp(7.0 * max(-0.08, min(0.25, s['score']))) for s in usable]
    z = sum(raw) or 1.0
    return [({**s}, r/z) for s, r in zip(usable, raw)]


def _blend_suffix_models(draws: list[dict], weighted):
    out = {f'{i:02d}': 0.0 for i in range(100)}
    for stat, weight in weighted:
        probs = _fit_suffix2_model(draws, stat['kind'], stat['source'], stat['window'])
        for k, v in probs.items():
            out[k] += weight * v
    z = sum(out.values()) or 1.0
    return {k: v/z for k, v in out.items()}


def _adaptive_holdout(draws: list[dict], holdout: int = 12):
    """Leakage-free holdout audit of automatic model selection.

    Model variants/weights are selected ONCE using only the history before the
    holdout block. Those frozen choices are then walked forward across the last
    N historical draws. Each prediction can refit its chosen model on data
    available at that point, but it cannot re-select weights using holdout answers.
    """
    valid = [d for d in draws if _special(d)]
    start = max(24, len(valid) - holdout)
    selection_hist = valid[:start]
    if len(selection_hist) < 20:
        return {
            'tests': 0, 'digit_top1_rate': 0, 'digit_logloss': 0,
            'digit_log_skill_vs_uniform': 0, 'suffix2_top5_rate': 0,
            'suffix2_top10_rate': 0, 'suffix2_logloss': 0,
            'suffix2_log_skill_vs_uniform': 0, 'exact_top20_hits': 0,
            'exact_top20_rate': 0,
            'random_baselines': {'digit_top1': .10, 'suffix2_top5': .05, 'suffix2_top10': .10, 'exact_top20': 20/1_000_000},
        }

    # Freeze model selection before seeing any holdout result.
    pstats = _evaluate_position_catalog(selection_hist, max_tests=min(36, max(16, len(selection_hist)-12)))
    pweights = _select_position_weights(pstats)
    sstats = _evaluate_suffix_catalog(selection_hist, max_tests=min(36, max(16, len(selection_hist)-12)))
    sweights = _select_suffix_weights(sstats)

    tests = 0; digit_hits = 0; digits = 0; s2_top5 = s2_top10 = 0; exact20 = 0
    nll_digits = 0.0; nll_s2 = 0.0
    for i in range(start, len(valid)):
        hist = valid[:i]
        pprobs = _blend_position_models(hist, pweights)
        s2probs = _blend_suffix_models(hist, sweights)
        actual = _special(valid[i])
        tests += 1
        for p, ch in enumerate(actual):
            nll_digits += -_safe_log(pprobs[p].get(ch, 1e-12))
            digit_hits += int(max(pprobs[p], key=pprobs[p].get) == ch)
            digits += 1
        nll_s2 += -_safe_log(s2probs.get(actual[-2:], 1e-12))
        ranked2 = [k for k,_ in sorted(s2probs.items(), key=lambda kv: kv[1], reverse=True)]
        rank = ranked2.index(actual[-2:]) + 1
        s2_top5 += int(rank <= 5); s2_top10 += int(rank <= 10)
        raw = []
        for number, lp in _top_numbers_from_positions(pprobs, 120):
            raw.append((number, lp + 0.85 * _safe_log(s2probs.get(number[-2:], .01)/.01)))
        top20 = {number for number,_ in sorted(raw, key=lambda x:x[1], reverse=True)[:20]}
        exact20 += int(actual in top20)
    return {
        'tests': tests,
        'digit_top1_rate': digit_hits/max(digits,1),
        'digit_logloss': nll_digits/max(digits,1),
        'digit_log_skill_vs_uniform': 1-(nll_digits/max(digits,1))/math.log(10),
        'suffix2_top5_rate': s2_top5/max(tests,1),
        'suffix2_top10_rate': s2_top10/max(tests,1),
        'suffix2_logloss': nll_s2/max(tests,1),
        'suffix2_log_skill_vs_uniform': 1-(nll_s2/max(tests,1))/math.log(100),
        'exact_top20_hits': exact20,
        'exact_top20_rate': exact20/max(tests,1),
        'selection_cutoff_date': selection_hist[-1]['draw_date'] if selection_hist else None,
        'random_baselines': {'digit_top1': .10, 'suffix2_top5': .05, 'suffix2_top10': .10, 'exact_top20': 20/1_000_000},
    }


# ----------------------------- formula miner -------------------------------

def _formula_candidates(prev_draw: dict, target_date: str):
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
        'Vị trí 2-3 ĐB': s[1:3],
        'Vị trí 3-4 ĐB': s[2:4],
        'Vị trí 4-5 ĐB': s[3:5],
    }
    for prize in ['100N','200N','400N','1TR','3TR','10TR','15TR','30TR']:
        v = _first_value(prev_draw, prize)
        if v and len(v) >= 2:
            prefixes[f'2 số cuối {prize}'] = v[-2:]

    suffixes = {'4 số cuối ĐB': s[-4:], '4 số đầu ĐB': s[:4], 'Đảo 4 số cuối ĐB': s[-4:][::-1]}
    for prize in ['400N','1TR','3TR','10TR','15TR','30TR']:
        v = _first_value(prev_draw, prize)
        if v and len(v) >= 4:
            suffixes[f'4 số cuối {prize}'] = v[-4:]

    out = {f'{pn} + {sn}': pv + sv for pn,pv in prefixes.items() for sn,sv in suffixes.items()}
    out.update({
        'Đảo ngược 6 số ĐB': s[::-1],
        'Xoay trái 2 chữ số ĐB': s[2:] + s[:2],
        'Xoay phải 2 chữ số ĐB': s[-2:] + s[:-2],
    })
    return out


def backtest_formulas(draws: list[dict]):
    valid = [d for d in draws if _special(d)]
    metrics = defaultdict(lambda: {'tests':0,'exact':0,'suffix4':0,'suffix3':0,'suffix2':0,'digit_matches':0,'recent_weight':0.0,'recent_suffix2':0.0})
    weights = _exp_weights(max(0,len(valid)-1), half_life=20)
    for i in range(1, len(valid)):
        prev, cur = valid[i-1], valid[i]
        actual = _special(cur); w = weights[i-1] if weights else 1.0
        for name,pred in _formula_candidates(prev, cur['draw_date']).items():
            m=metrics[name]; m['tests']+=1
            m['exact']+=int(pred==actual); m['suffix4']+=int(pred[-4:]==actual[-4:]); m['suffix3']+=int(pred[-3:]==actual[-3:]); m['suffix2']+=int(pred[-2:]==actual[-2:]); m['digit_matches']+=sum(a==b for a,b in zip(pred,actual))
            m['recent_weight'] += w; m['recent_suffix2'] += w*int(pred[-2:]==actual[-2:])
    out=[]
    for name,m in metrics.items():
        t=max(m['tests'],1)
        # Formula ranking emphasizes repeatability, not a single spectacular exact hit.
        s2=m['suffix2']/t; s3=m['suffix3']/t; s4=m['suffix4']/t; exact=m['exact']/t
        recent_s2=m['recent_suffix2']/max(m['recent_weight'],1e-9)
        shrink=t/(t+30.0)
        score=shrink*(0.45*(s2-.01)+0.20*(recent_s2-.01)+0.18*(s3-.001)+0.10*(s4-.0001)+0.07*min(exact,0.01))
        out.append({'name':name,**m,'exact_rate':exact,'suffix4_rate':s4,'suffix3_rate':s3,'suffix2_rate':s2,'recent_suffix2_rate':recent_s2,'avg_digit_matches':m['digit_matches']/t,'score':score})
    return sorted(out,key=lambda x:(x['score'],x['tests']),reverse=True)


def xsmn_analysis(draws: list[dict], target_date: str, top_n: int = 20):
    valid = [d for d in draws if _special(d)]
    if len(valid) < 24:
        return {'error': 'Cần tối thiểu 24 kỳ cùng đài để engine tự chọn mô hình ổn định.', 'draw_count': len(valid)}

    # 1) score every candidate model with walk-forward history
    pstats = _evaluate_position_catalog(valid, max_tests=48)
    pweights = _select_position_weights(pstats)
    pos_probs = _blend_position_models(valid, pweights)

    sstats = _evaluate_suffix_catalog(valid, max_tests=48)
    sweights = _select_suffix_weights(sstats)
    suffix2_probs = _blend_suffix_models(valid, sweights)

    # 2) nested holdout audits the auto-selection algorithm itself
    adaptive_bt = _adaptive_holdout(valid, holdout=min(12, max(6, len(valid)//8)))

    # 3) formula miner is only a secondary signal, heavily backtest-gated
    formula_stats = backtest_formulas(valid)
    formula_scores = {x['name']: max(0.0, x['score']) for x in formula_stats}
    formula_today = _formula_candidates(valid[-1], target_date)
    formula_by_value = defaultdict(float); formula_reasons=defaultdict(list)
    for name,value in formula_today.items():
        formula_by_value[value] += formula_scores.get(name,0.0)
        formula_reasons[value].append(name)
    formula_norm = _normalize(dict(formula_by_value))

    # 4) candidate exact 6 ranking: position ensemble + direct previous-draw suffix engine
    candidate_map = {}
    for s, lp in _top_numbers_from_positions(pos_probs, 1400):
        suffix_lift = suffix2_probs.get(s[-2:], .01)/.01
        formula_bonus = formula_norm.get(s,0.0)
        rank_log = lp + 0.90*_safe_log(max(suffix_lift,1e-6)) + 0.18*formula_bonus
        model_prob = math.exp(lp)
        candidate_map[s] = {
            'value':s, 'rank_log':rank_log, 'position_probability':model_prob,
            'suffix2_model_probability':suffix2_probs.get(s[-2:],.01),
            'relative_likelihood_vs_uniform': model_prob/1e-6,
            'formula_score': formula_bonus, 'reasons':formula_reasons.get(s,[]),
        }
    # Ensure interpretable formula predictions can be inspected even if outside beam.
    for s in formula_today.values():
        if len(s)!=6 or not s.isdigit() or s in candidate_map: continue
        lp=sum(_safe_log(pos_probs[p].get(ch,.1)) for p,ch in enumerate(s))
        model_prob=math.exp(lp); suffix_lift=suffix2_probs.get(s[-2:],.01)/.01
        candidate_map[s]={'value':s,'rank_log':lp+0.90*_safe_log(max(suffix_lift,1e-6))+0.18*formula_norm.get(s,0.0),'position_probability':model_prob,'suffix2_model_probability':suffix2_probs.get(s[-2:],.01),'relative_likelihood_vs_uniform':model_prob/1e-6,'formula_score':formula_norm.get(s,0.0),'reasons':formula_reasons.get(s,[])}

    ranked = sorted(candidate_map.values(), key=lambda x:x['rank_log'], reverse=True)
    rnorm = _normalize({x['value']:x['rank_log'] for x in ranked[:300]})
    top=[]
    for x in ranked[:top_n]:
        y=dict(x); y['score']=round(100*rnorm.get(x['value'],0.0),2); y['model_probability']=y.pop('position_probability')
        top.append(y)

    # 5) direct suffix lists are true normalized model distributions (but not a guarantee)
    top2 = sorted(suffix2_probs.items(), key=lambda kv:kv[1], reverse=True)[:15]
    # 3-digit recency remains a descriptive secondary signal.
    loto3=Counter(); recent=valid[-36:]; rw=_exp_weights(len(recent),12)
    for i,d in enumerate(recent):
        for x in _all_loto3(d): loto3[x]+=rw[i]
    n3=_normalize(dict(loto3)); top3=sorted(n3.items(),key=lambda kv:kv[1],reverse=True)[:12]

    ranked_formula_today = sorted([
        {'name':n,'value':v,'backtest_score':formula_scores.get(n,0.0)} for n,v in formula_today.items()
    ],key=lambda x:x['backtest_score'],reverse=True)
    key_name='Ngày kỳ trước + 4 số cuối ĐB'
    shown=ranked_formula_today[:15]
    if not any(x['name']==key_name for x in shown):
        z=next((x for x in ranked_formula_today if x['name']==key_name),None)
        if z: shown.append(z)

    # model metadata for transparent UI
    model_weights=[{
        'name':s['name'],'weight':round(w,4),'score':round(s['score'],5),'tests':s['tests'],
        'digit_top1_rate':round(s['digit_top1_rate'],4),'suffix2_top10_rate':round(s['suffix2_top10_rate'],4),
        'log_skill_vs_uniform':round(s['log_skill_vs_uniform'],4)
    } for s,w in pweights]
    suffix_weights=[{
        'name':s['name'],'weight':round(w,4),'score':round(s['score'],5),'tests':s['tests'],
        'top10_rate':round(s['top10_rate'],4),'log_skill_vs_uniform':round(s['log_skill_vs_uniform'],4)
    } for s,w in sweights]

    skill_positive = (adaptive_bt['digit_log_skill_vs_uniform'] > 0 and adaptive_bt['suffix2_log_skill_vs_uniform'] > 0)
    return {
        'engine_version':'adaptive-walk-forward-v1',
        'draw_count':len(valid),'history_from':valid[0]['draw_date'],'history_to':valid[-1]['draw_date'],
        'last_special':_special(valid[-1]),'last_date':valid[-1]['draw_date'],'target_date':target_date,
        'previous_draw_basis':{'draw_date':valid[-1]['draw_date'],'special':_special(valid[-1]),'rule':'Dự đoán kỳ sau chỉ dùng dữ liệu đến kỳ này.'},
        'candidates':top,
        'top_suffix2':[{'value':k,'score':round(v*100,3),'model_probability':v} for k,v in top2],
        'top_suffix3':[{'value':k,'score':round(v*100,2)} for k,v in top3],
        'adaptive_engine':{
            'position_models':model_weights,
            'suffix_models':suffix_weights,
            'holdout':adaptive_bt,
            'status':'Có tín hiệu vượt baseline trong holdout' if skill_positive else 'Chưa chứng minh được lợi thế ổn định so với baseline',
            'principle':'Mô hình được chọn bằng lịch sử trước khối holdout; các kỳ holdout chỉ dùng để chấm điểm, không dùng để chọn trọng số.'
        },
        'formulas':formula_stats[:50],'formula_count':len(formula_stats),
        'formula_today':[{**x,'backtest_score':round(x['backtest_score'],6)} for x in shown],
        'note':'Xác suất mô hình/điểm xếp hạng là ước lượng từ lịch sử. Xác suất lý thuyết Exact 6 vẫn là 1/1.000.000 nếu kỳ quay độc lập và công bằng.'
    }


# ------------------------------ Vietlott ------------------------------------

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
    hot = ranked[:12]; cold = sorted(score.items(), key=lambda kv: kv[1])[:12]
    overdue = sorted(gaps.items(), key=lambda kv: kv[1], reverse=True)[:12]

    seed_src = f'{product_name}|{draws[-1]["draw_id"]}|{draws[-1]["draw_date"]}'
    seed = int(hashlib.sha256(seed_src.encode()).hexdigest()[:16], 16)
    rng = random.Random(seed)
    weights = [0.15 + score[i] for i in range(1, max_n + 1)]
    population = list(range(1, max_n + 1))
    sets = {}
    for _ in range(6000):
        avail = population[:]; ws = weights[:]; pick=[]
        for __ in range(6):
            total=sum(ws); r=rng.random()*total; acc=0; idx=0
            for idx,w in enumerate(ws):
                acc += w
                if acc >= r: break
            pick.append(avail.pop(idx)); ws.pop(idx)
        pick=tuple(sorted(pick)); q=_set_quality(pick,score,pairs,sum_mu,sum_sd,max_n)
        if q>sets.get(pick,-999): sets[pick]=q
    best=sorted(sets.items(),key=lambda kv:kv[1],reverse=True)[:top_sets]
    qnorm=_normalize({k:v for k,v in best})

    tests=0; model_matches=0; start=max(20,len(draws)-80)
    for i in range(start,len(draws)):
        hist=draws[:i]; s2,_,_,_=_viet_scores(hist,max_n)
        pool={n for n,_ in sorted(s2.items(),key=lambda kv:kv[1],reverse=True)[:12]}
        model_matches += len(pool.intersection(draws[i]['numbers'])); tests += 1
    avg_pool_matches=model_matches/tests if tests else 0; random_pool_expected=12*6/max_n
    jackpot_combinations=math.comb(max_n,6)
    return {
        'draw_count':len(draws),'history_from':draws[0]['draw_date'],'history_to':draws[-1]['draw_date'],'last_draw':draws[-1],
        'hot':[{'number':n,'score':round(v*100,2)} for n,v in hot],
        'cold':[{'number':n,'score':round(v*100,2)} for n,v in cold],
        'overdue':[{'number':n,'gap_draws':g} for n,g in overdue],
        'sets':[{'numbers':list(nums),'score':round(qnorm.get(nums,0)*100,2),'sum':sum(nums)} for nums,_ in best],
        'theoretical_jackpot_probability':1/jackpot_combinations,'jackpot_combinations':jackpot_combinations,
        'backtest':{'tests':tests,'top12_pool_avg_matches':round(avg_pool_matches,4),'random_top12_expected_matches':round(random_pool_expected,4),'edge_vs_random':round(avg_pool_matches-random_pool_expected,4)},
        'note':'Mỗi tổ hợp 6 số hợp lệ vẫn có xác suất lý thuyết bằng nhau nếu kỳ quay độc lập và công bằng.'
    }
