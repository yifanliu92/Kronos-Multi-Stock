#!/usr/bin/env python3
import json
from pathlib import Path

BASE = Path('/Users/wxo/Desktop/Kronos')
DAILY_DIR = BASE / 'daily_reports'
THRESHOLD = 0.3
CONSECUTIVE_N = 3


def check_advantage():
    daily_files = sorted(DAILY_DIR.glob('daily_review_603305_*.json'))
    if len(daily_files) < CONSECUTIVE_N:
        print(f"样本不足，需要至少 {CONSECUTIVE_N} 个交易日")
        return

    recent = daily_files[-CONSECUTIVE_N:]
    advantages = []

    for f in recent:
        with open(f, 'r', encoding='utf-8') as fp:
            data = json.load(fp)
        adv = data.get('advantage')
        if adv is not None and adv >= THRESHOLD:
            advantages.append(adv)
        else:
            advantages.append(None)

    if all(a is not None for a in advantages):
        avg_adv = sum(advantages) / len(advantages)
        alert = {
            'alert': True,
            'message': f'影子策略连续 {CONSECUTIVE_N} 日优于主策略，平均优势 {avg_adv:.2f}% > {THRESHOLD}%',
            'suggestion': '建议复核参数是否升级',
            'details': [f.name for f in recent]
        }
        alert_file = BASE / 'guard_outputs' / 'advantage_alert.json'
        with open(alert_file, 'w', encoding='utf-8') as fp:
            json.dump(alert, fp, ensure_ascii=False, indent=2)
        print(f"⚠️ {alert['message']}")
    else:
        print(f"✅ 未触发告警（需要连续 {CONSECUTIVE_N} 日优势 >{THRESHOLD}%）")


if __name__ == '__main__':
    check_advantage()
