#!/usr/bin/env python3
import json
from pathlib import Path
from datetime import datetime, timedelta

BASE=Path('/Users/wxo/Desktop/Kronos')
MAIN=BASE/'sim_trades_603305.jsonl'
SHADOW=BASE/'shadow_trades_603305.jsonl'
OUT=BASE/'strategy_compare_reports'
OUT.mkdir(parents=True, exist_ok=True)


def load(p):
    rows=[]
    if not p.exists(): return rows
    for ln in p.read_text(encoding='utf-8').splitlines():
        if not ln.strip(): continue
        try: rows.append(json.loads(ln))
        except: pass
    rows.sort(key=lambda x:x.get('ts',''))
    return rows

def parse_ts(s):
    try:return datetime.strptime(s,'%Y-%m-%d %H:%M:%S')
    except:return None

def direction_at_horizon(rows, mins=30):
    w=l=0
    for i,r in enumerate(rows):
        sig=str(r.get('signal',''))
        if '中性' in sig: continue
        p0=float(r.get('price',0) or 0)
        t0=parse_ts(str(r.get('ts','')))
        if p0<=0 or not t0: continue
        target=t0+timedelta(minutes=mins)
        j=None
        for k in range(i+1,len(rows)):
            tk=parse_ts(str(rows[k].get('ts','')))
            if tk and tk>=target:
                j=k; break
        if j is None: continue
        p1=float(rows[j].get('price',0) or 0)
        if p1<=0 or p1==p0: continue
        bull=('多' in sig)
        if (bull and p1>p0) or ((not bull) and p1<p0): w+=1
        else: l+=1
    n=w+l
    return {'wins':w,'losses':l,'samples':n,'winrate': round(w/n*100,2) if n else None}

def direction_next(rows):
    w=l=0
    for i in range(len(rows)-1):
        sig=str(rows[i].get('signal',''))
        if '中性' in sig: continue
        p0=float(rows[i].get('price',0) or 0);p1=float(rows[i+1].get('price',0) or 0)
        if p0<=0 or p1<=0 or p1==p0: continue
        bull=('多' in sig)
        if (bull and p1>p0) or ((not bull) and p1<p0): w+=1
        else: l+=1
    n=w+l
    return {'wins':w,'losses':l,'samples':n,'winrate': round(w/n*100,2) if n else None}

def close_winrate(rows):
    by_day={}
    for r in rows:
        ts=str(r.get('ts',''))
        d=ts[:10]
        by_day.setdefault(d,[]).append(r)
    w=l=0
    for d,arr in by_day.items():
        close=float(arr[-1].get('price',0) or 0)
        for r in arr:
            sig=str(r.get('signal',''))
            if '中性' in sig: continue
            p0=float(r.get('price',0) or 0)
            if close<=0 or p0<=0 or close==p0: continue
            bull=('多' in sig)
            if (bull and close>p0) or ((not bull) and close<p0): w+=1
            else: l+=1
    n=w+l
    return {'wins':w,'losses':l,'samples':n,'winrate': round(w/n*100,2) if n else None}

def action_to_next_action_winrate(rows):
    actions=[r for r in rows if str(r.get('action',''))!='持仓不变']
    wins=losses=0
    for i in range(len(actions)-1):
        a,b=actions[i],actions[i+1]
        p0=float(a.get('price',0) or 0); p1=float(b.get('price',0) or 0)
        if p0<=0 or p1<=0: continue
        delta=int((a.get('position_to',0) or 0)-(a.get('position_from',0) or 0))
        pnl=(p1-p0) if delta>0 else (p0-p1)
        if pnl>0: wins+=1
        elif pnl<0: losses+=1
    n=wins+losses
    return {'wins':wins,'losses':losses,'samples':n,'winrate': round(wins/n*100,2) if n else None}

def pack(name,rows):
    return {'strategy':name,'records':len(rows),'next_tick':direction_next(rows),'h30':direction_at_horizon(rows,30),'close':close_winrate(rows),'action_to_next_action':action_to_next_action_winrate(rows)}

main=load(MAIN); shadow=load(SHADOW)
rep={'generated_at':datetime.now().strftime('%Y-%m-%d %H:%M:%S'),'symbol':'603305','version':'winrate_multi_v1','main':pack('main',main),'shadow':pack('shadow',shadow)}
out=OUT/f'winrate_multi_603305_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'
out.write_text(json.dumps(rep,ensure_ascii=False,indent=2),encoding='utf-8')
print(out)
print(json.dumps(rep,ensure_ascii=False,indent=2))
