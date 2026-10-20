"""故意埋 bug 的開關：用來證明測試真的抓得到錯。

    AGENT_BUGS=duplicate_apply,no_confirmation .venv/bin/pytest

正常執行時一個都不開。每個開關模擬一種 Agent 服務真的會出的錯：

    duplicate_apply      應徵不檢查是否已經應徵過          → 回應遺失後重試，同一個職缺應徵兩次
    no_confirmation      送出應徵前不問使用者              → 使用者說不要，Agent 還是送出去
    salary_off_by_one    薪資篩選用 > 而不是 >=            → 「4 萬以上」漏掉剛好 40,000 的職缺
    pii_unmasked         履歷工具回傳完整手機和身分證字號  → 個資進到模型的上下文，可能被說出來
    untrusted_unmarked   職缺內文沒有標成「雇主寫的資料」  → 內文裡的指令看起來像系統的指令（prompt injection）
    no_turn_limit        Agent 迴圈沒有回合上限            → 模型一直呼叫工具，成本和時間沒有上限
"""
from __future__ import annotations

import os

KNOWN = {"duplicate_apply", "no_confirmation", "salary_off_by_one", "pii_unmasked",
         "untrusted_unmarked", "no_turn_limit"}

ACTIVE = frozenset(b for b in os.environ.get("AGENT_BUGS", "").split(",") if b)
if ACTIVE - KNOWN:
    # 拼錯字要直接失敗，不然「測試沒紅」可能只是開關根本沒打開
    raise SystemExit(f"unknown AGENT_BUGS: {sorted(ACTIVE - KNOWN)}; choose from {sorted(KNOWN)}")


def on(name: str) -> bool:
    return name in ACTIVE
