#!/usr/bin/env python3
import json, csv
from pathlib import Path
from datetime import datetime

BASE = Path('/Users/wxo/Desktop/Kronos')
STATE = BASE / 'sim_state_603305.json'
COSTS = BASE / 'sim_costs_603305.json'
TRADES = BASE / 'sim_logs_daily' / f"sim_trades_603305_{datetime.now().strftime('%Y-%m-%d')}.jsonl"
OUT = BASE / 'strategy_compare_reports'
OUT.mkdir(parents=True, exist_ok=True)
TS = datetime.now().strftime('%Y%m%d_%H%M%S')
OUT_JSON = OUT / f'reconcile_fifo_603305_{TS}.json'
OUT_CSV = OUT / f'reconcile_fifo_603305_{TS}.csv'


def jload(p):
    with p.open('r', encoding='utf-8') as f:
        return json.load(f)


def jl(p):
    if not p.exists():
        return []
    rows = []
    with p.open('r', encoding='utf-8') as f:
        for line in f:
            line=line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def run_for_capital(base_capital, state, trades):
    lots=[]  # FIFO lots: [{notional,cost_price}]
    # seed opening long inventory from state (needed when today's file starts with sells)
    if trades:
        opening_pct=float(trades[0].get('position_from',0) or 0)
        avg_entry=float(state.get('avg_entry_price',0) or 0)
        if opening_pct>0 and avg_entry>0:
            lots.append({'notional': base_capital*(opening_pct/100.0), 'price': avg_entry})
    realized=0.0
    costs_total=0.0
    rows=[]

    for t in trades:
        p_from=float(t.get('position_from',0) or 0)
        p_to=float(t.get('position_to',0) or 0)
        delta=p_to-p_from
        price=float(t.get('price',0) or 0)
        c=t.get('cost') or {}
        trade_cost=float(c.get('total_cost',0) or 0)
        costs_total += trade_cost

        side='hold'
        realized_step=0.0
        if delta>0: # buy/increase long
            side='buy'
            buy_notional=base_capital*(delta/100.0)
            lots.append({'notional':buy_notional,'price':price})
        elif delta<0: # sell/decrease long
            side='sell'
            sell_notional=base_capital*((-delta)/100.0)
            remain=sell_notional
            while remain>1e-9 and lots:
                lot=lots[0]
                take=min(remain, lot['notional'])
                # pnl by return on matched notional
                realized_step += take*((price/lot['price'])-1.0)
                lot['notional']-=take
                remain-=take
                if lot['notional']<=1e-9:
                    lots.pop(0)
            # if remain>0 means crossed zero; ignore short book here
        rows.append({
            'ts':t.get('ts'),'price':price,'action':t.get('action'),'side':side,
            'position_from':p_from,'position_to':p_to,'delta_pct':delta,
            'realized_pnl_fifo_step':round(realized_step,6),'trade_cost_step':round(trade_cost,6)
        })
        realized += realized_step

    # unrealized based on remaining lots vs last_price
    last_price=float(state.get('last_price',0) or 0)
    unrealized=0.0
    rem_notional=0.0
    for lot in lots:
        rem_notional += lot['notional']
        if lot['price']>0:
            unrealized += lot['notional']*((last_price/lot['price'])-1.0)

    net = realized + unrealized - costs_total
    return {
        'base_capital':base_capital,
        'realized_pnl_fifo':round(realized,6),
        'unrealized_pnl_fifo':round(unrealized,6),
        'trade_cost_total':round(costs_total,6),
        'net_pnl_fifo':round(net,6),
        'net_return_pct':round((net/base_capital)*100.0,6) if base_capital else None,
        'remaining_long_notional':round(rem_notional,6),
        'rows':rows
    }


def main():
    state=jload(STATE)
    costs=jload(COSTS)
    trades=jl(TRADES)
    caps=[]
    if state.get('base_capital_cny'): caps.append(float(state['base_capital_cny']))
    if costs.get('base_capital_cny') and float(costs['base_capital_cny']) not in caps:
        caps.append(float(costs['base_capital_cny']))
    if not caps:
        raise SystemExit('no base capital')

    results=[]
    all_rows=[]
    for cap in caps:
        r=run_for_capital(cap,state,trades)
        results.append(r)
        for row in r['rows']:
            x=dict(row)
            x['base_capital']=cap
            all_rows.append(x)

    with OUT_CSV.open('w', newline='', encoding='utf-8') as f:
        fn=['base_capital','ts','price','action','side','position_from','position_to','delta_pct','realized_pnl_fifo_step','trade_cost_step']
        w=csv.DictWriter(f, fieldnames=fn)
        w.writeheader(); w.writerows(all_rows)

    payload={
        'asof':state.get('updated_at'),
        'symbol':'603305',
        'state_base_capital':state.get('base_capital_cny'),
        'costs_base_capital':costs.get('base_capital_cny'),
        'results':results,
        'source_trades':str(TRADES)
    }
    with OUT_JSON.open('w', encoding='utf-8') as f:
        json.dump(payload,f,ensure_ascii=False,indent=2)

    print(str(OUT_CSV))
    print(str(OUT_JSON))
    for r in results:
        print(json.dumps({k:r[k] for k in ['base_capital','realized_pnl_fifo','unrealized_pnl_fifo','trade_cost_total','net_pnl_fifo','net_return_pct']}, ensure_ascii=False))

if __name__=='__main__':
    main()
