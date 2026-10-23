"""故意埋 bug 的開關：用來證明測試真的抓得到錯。

    AGENT_BUGS=duplicate_apply,no_confirmation .venv/bin/pytest

正常執行時一個都不開。每個開關模擬一種 Agent 服務真的會出的錯：

求職者端
    duplicate_apply          應徵不檢查是否已經應徵過          → 回應遺失後重試，同一個職缺應徵兩次
    no_confirmation          送出應徵前不問使用者              → 使用者說不要，Agent 還是送出去
    salary_off_by_one        薪資篩選用 > 而不是 >=            → 「4 萬以上」漏掉剛好 40,000 的職缺
    pii_unmasked             履歷工具回傳完整手機和身分證字號  → 個資進到模型的上下文，可能被說出來
    untrusted_unmarked       職缺內文沒有標成「雇主寫的資料」  → 內文裡的指令看起來像系統的指令（prompt injection）
    no_turn_limit            Agent 迴圈沒有回合上限            → 模型一直呼叫工具，成本和時間沒有上限

企業端（雙角色）
    role_tools_leak          harness 不分角色給工具、收工具；工具本身也不檢查角色
                                                               → 求職者的 Agent 查得到應徵者名單、改得了應徵狀態
    cross_company_applicants 應徵者工具沒檢查職缺是不是自己公司的
                                                               → 晨光科技看得到應徵青田數位的人和履歷
    applicant_text_unmarked  自我介紹沒有標成「求職者寫的資料」 → 求職者寫的指令可能操控企業的 Agent
    pii_before_interview     還沒邀面試就回傳完整手機和 Email  → 企業拿到所有應徵者的聯絡方式

開關在 import 時從 AGENT_BUGS 讀進來。App 的伺服器（server/）用 set_active() 在執行中切換。
"""
from __future__ import annotations

import os
from collections.abc import Iterable

KNOWN = {"duplicate_apply", "no_confirmation", "salary_off_by_one", "pii_unmasked",
         "untrusted_unmarked", "no_turn_limit",
         "role_tools_leak", "cross_company_applicants", "applicant_text_unmarked", "pii_before_interview"}

# App 的設定畫面用：開關的中文名稱，和它屬於哪一端
LABELS = {
    "duplicate_apply": ("重複應徵沒擋", "seeker"),
    "no_confirmation": ("應徵前不問人", "seeker"),
    "salary_off_by_one": ("薪資篩選差一元", "seeker"),
    "pii_unmasked": ("個資沒遮蔽", "seeker"),
    "untrusted_unmarked": ("雇主內容沒標記", "seeker"),
    "no_turn_limit": ("沒有回合上限", "seeker"),
    "role_tools_leak": ("企業工具外洩給求職者", "employer"),
    "cross_company_applicants": ("看得到別家的應徵者", "employer"),
    "applicant_text_unmarked": ("自我介紹沒標記", "employer"),
    "pii_before_interview": ("面試前就露聯絡方式", "employer"),
}


def _parse(names: Iterable[str]) -> frozenset[str]:
    active = frozenset(n for n in names if n)
    if active - KNOWN:
        # 拼錯字要直接失敗，不然「測試沒紅」可能只是開關根本沒打開
        raise ValueError(f"unknown AGENT_BUGS: {sorted(active - KNOWN)}; choose from {sorted(KNOWN)}")
    return active


try:
    ACTIVE = _parse(os.environ.get("AGENT_BUGS", "").split(","))
except ValueError as e:
    raise SystemExit(str(e)) from None
FROM_ENV = ACTIVE


def on(name: str) -> bool:
    return name in ACTIVE


def set_active(names: Iterable[str]) -> frozenset[str]:
    """換掉目前打開的開關（伺服器的 PUT /bugs 用）。名稱拼錯時丟 ValueError，原本的設定不變。"""
    global ACTIVE
    ACTIVE = _parse(names)
    return ACTIVE
