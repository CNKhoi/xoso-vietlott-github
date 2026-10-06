import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))

from scraper_base import parse_xsmn_html, parse_vietlott_html
from analytics import xsmn_analysis, _formula_candidates

xhtml = '''<html><body>
<span>02/102026</span><b>Thứ sáu</b>
<a>Vĩnh Long</a><a>Bình Dương</a><a>Trà Vinh</a><span>47VL40</span>
<table>
<tr><td>100N</td><td>40</td><td>07</td><td>57</td></tr>
<tr><td>200N</td><td>496</td><td>143</td><td>477</td></tr>
<tr><td>400N</td><td>3753 0609 3108</td><td>4242 2886 9451</td><td>4822 8960 0026</td></tr>
<tr><td>1TR</td><td>1802</td><td>0705</td><td>4386</td></tr>
<tr><td>3TR</td><td>18666 15990 44238 49325 25037 90913 60453</td><td>17467 02851 90548 29519 91876 50071 04917</td><td>94340 96971 37408 54812 57205 99055 98036</td></tr>
<tr><td>10TR</td><td>50576 14938</td><td>18090 57493</td><td>75794 90469</td></tr>
<tr><td>15TR</td><td>31549</td><td>39283</td><td>84718</td></tr>
<tr><td>30TR</td><td>77305</td><td>00879</td><td>59378</td></tr>
<tr><td>2TỶ</td><td>132697</td><td>313004</td><td>886827</td></tr>
</table></body></html>'''
rows = parse_xsmn_html(xhtml, 'test')
assert len(rows) == 54, len(rows)
assert any(r['province']=='Vĩnh Long' and r['prize']=='2TỶ' and r['value']=='132697' for r in rows)

vhtml = '<div>Kết quả QSMT kỳ #1570 ngày 02/10/2026</div><div>01 06 20 27 31 41</div>'
v = parse_vietlott_html(vhtml, 'mega645', 'test')
assert len(v) == 1 and v[0]['numbers'] == [1,6,20,27,31,41]

phtml = '<div>Kết quả QSMT kỳ #1406 ngày 03/10/2026</div><div>07 11 13 16 18 54 41</div>'
p = parse_vietlott_html(phtml, 'power655', 'test')
assert len(p) == 1 and p[0]['special'] == 41

def mkdraw(dt, db, salt=0):
    # Deterministic but varied supporting prizes for analytics smoke tests.
    n=int(db[-4:]) + salt
    return {'draw_date':dt,'province':'Bình Thuận','prizes':{
      '100N':[f'{n%100:02d}'],'200N':[f'{n%1000:03d}'],'400N':[f'{(n+11)%10000:04d}',f'{(n+22)%10000:04d}',f'{(n+33)%10000:04d}'],'1TR':[f'{(n+44)%10000:04d}'],
      '3TR':[f'{(n+i*101)%100000:05d}' for i in range(1,8)],
      '10TR':[f'{(n+808)%100000:05d}',f'{(n+909)%100000:05d}'],'15TR':[f'{(n+1010)%100000:05d}'],'30TR':[f'{(n+1111)%100000:05d}'],'2TỶ':[db]}}

# Direct audit of the user's 24 + 7346 pattern uses only the previous draw.
prev=mkdraw('2026-09-24','377346')
assert _formula_candidates(prev,'2026-10-01')['Ngày kỳ trước + 4 số cuối ĐB']=='247346'

# Build enough history to exercise adaptive walk-forward engine.
from datetime import date,timedelta
base=date(2026,3,12)
case=[]
for i in range(30):
    dt=(base+timedelta(days=7*i)).isoformat()
    # pseudo-history with a mild deterministic digit-delta pattern
    db=''.join(str((i*3+p*2+(i//4))%10) for p in range(6))
    case.append(mkdraw(dt,db,i))
# Replace latest draw with the known 24/09 value; target stays unseen.
case[-1]=mkdraw('2026-09-24','377346',29)
a=xsmn_analysis(case,'2026-10-01')
assert a['history_to']=='2026-09-24'
assert a['engine_version']=='adaptive-walk-forward-v1'
assert a['adaptive_engine']['position_models']
assert a['adaptive_engine']['suffix_models']
key=next(x for x in a['formula_today'] if x['name']=='Ngày kỳ trước + 4 số cuối ĐB')
assert key['value']=='247346', key

stub=json.loads((ROOT/'data/dashboard.json').read_text(encoding='utf-8'))
assert stub['audit_247346']['predicted']=='247346'
print('smoke tests OK')
