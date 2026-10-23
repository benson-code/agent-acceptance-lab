"""證明測試真的抓得到 bug：每打開一個埋 bug 開關，指定的測試就必須失敗。

    .venv/bin/python tools/fault_check.py                   # 十個開關各跑一次
    .venv/bin/python tools/fault_check.py duplicate_apply   # 只跑一個

只看「整套有沒有紅」不夠：可能是別的測試剛好壞掉。所以每個開關都列出「應該被哪些測試抓到」，
少一個就算失敗。另外先在沒有開關的情況下跑一次，確認整套本來是綠的。

這裡只用假模型（ScriptedModel），不用 API key，結果固定，所以放在 CI 每次都跑。
untrusted_unmarked 對真模型的影響（被 prompt injection 騙到的比例）要用 evals/ 量，見 README。
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

EXPECTED = {
    "duplicate_apply": ["test_applying_twice_keeps_one_application",
                        "test_retry_after_lost_response_applies_once"],
    "no_confirmation": ["test_declined_application_is_not_sent",
                        "test_confirmed_application_is_sent_once",
                        "test_declined_status_change_is_not_made",          # 企業改狀態走同一個確認關卡
                        "test_confirmed_status_change_is_made_once"],
    "salary_off_by_one": ["test_salary_filter_includes_the_boundary",
                          "test_negotiable_salary_counts_as_40000",
                          "test_eval_passes_an_agent_that_behaves"],         # 評測的 grounded 也抓到
    "pii_unmasked": ["test_resume_masks_contact_details",
                     "test_no_pii_catches_a_phone_number_in_any_format"],    # no_pii 也檢查工具結果
    "untrusted_unmarked": ["test_employer_text_is_marked_untrusted"],
    "no_turn_limit": ["test_runaway_agent_is_stopped"],
    # 雙角色（tests/test_roles.py）
    "role_tools_leak": ["test_tool_lists_match_the_role_matrix[seeker]",
                        "test_seeker_cannot_list_applicants",
                        "test_seeker_cannot_change_application_status",
                        "test_board_rejects_the_wrong_role_on_its_own[seeker-list_applicants]"],
    "cross_company_applicants": ["test_other_company_job_looks_like_it_does_not_exist",
                                 "test_other_company_applicant_cannot_be_read"],
    "applicant_text_unmarked": ["test_applicant_text_is_marked_untrusted"],
    "pii_before_interview": ["test_contact_details_are_hidden_until_interview"],
}


def run_pytest(bug: str | None) -> tuple[set[str], set[str]]:
    """跑整套測試，回傳（通過的, 失敗的）測試名稱。"""
    with tempfile.TemporaryDirectory() as tmp:
        junit = Path(tmp) / "junit.xml"
        env = {**os.environ, "AGENT_BUGS": bug or ""}
        subprocess.run([sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-q", f"--junitxml={junit}"],
                       cwd=ROOT, env=env, capture_output=True)
        passed, failed = set(), set()
        for case in ET.parse(junit).iter("testcase"):
            bad = case.find("failure") is not None or case.find("error") is not None
            (failed if bad else passed).add(case.get("name"))
        return passed, failed


def main() -> int:
    bugs = sys.argv[1:] or list(EXPECTED)
    unknown = set(bugs) - set(EXPECTED)
    if unknown:
        print(f"沒有這些開關：{sorted(unknown)}")
        return 2

    passed, failed = run_pytest(None)
    if failed:
        print(f"沒有開關時就有測試失敗，先修好：{sorted(failed)}")
        return 1
    print(f"沒有開關：{len(passed)} 個測試全部通過\n")

    ok = True
    for bug in bugs:
        passed, failed = run_pytest(bug)
        missing = [t for t in EXPECTED[bug] if t not in failed]
        unseen = [t for t in EXPECTED[bug] if t not in failed | passed]
        status = "✓" if not missing else "✗"
        ok &= not missing
        print(f"{status} {bug}: {len(failed)} 個測試失敗")
        for t in EXPECTED[bug]:
            print(f"    {'抓到' if t in failed else '沒抓到'}  {t}{'（找不到這個測試）' if t in unseen else ''}")
        others = sorted(failed - set(EXPECTED[bug]))
        if others:
            print(f"    另外失敗：{', '.join(others)}")
    print("\n全部開關都被抓到" if ok else "\n有開關沒被指定的測試抓到")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
