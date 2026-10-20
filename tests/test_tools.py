"""工具層：Agent 能做的事，由這四個工具決定。這一層是程式，結果固定，用一般的測試方法測。"""
from __future__ import annotations

import pytest

from jobboard.board import ToolError


def ids(result: dict) -> list[str]:
    return [j["job_id"] for j in result["jobs"]]


def test_salary_filter_includes_the_boundary(board):
    """最低月薪 39,999 / 40,000 / 40,001 三個點：邊界本身要算符合。"""
    found = ids(board.search_jobs(city="台北市", min_monthly_salary=40000))
    assert "J-101" not in found          # 39,999
    assert "J-102" in found              # 40,000
    assert "J-104" in found              # 40,001


def test_negotiable_salary_counts_as_40000(board):
    """面議代表經常性薪資至少 4 萬：要 4 萬以上時算符合，要 4 萬 5 以上時不算（無法保證）。"""
    assert "J-103" in ids(board.search_jobs(min_monthly_salary=40000))
    assert "J-103" not in ids(board.search_jobs(min_monthly_salary=45000))


@pytest.mark.parametrize("city", ["台北市", "台北", "臺北市", " 臺北 "])
def test_city_names_are_normalised(board, city):
    assert ids(board.search_jobs(city=city)) == ["J-101", "J-102", "J-103", "J-104", "J-107", "J-201"]


def test_keyword_matches_any_word_in_title_tags_or_description(board):
    assert ids(board.search_jobs(keyword="Appium")) == ["J-107"]
    assert set(ids(board.search_jobs(keyword="QA 後端"))) >= {"J-102", "J-201"}


def test_closed_job_is_not_listed_and_cannot_be_applied_for(board):
    assert "J-105" not in ids(board.search_jobs())
    with pytest.raises(ToolError, match="已關閉"):
        board.apply_job("J-105")
    assert board.applications() == []


def test_applying_twice_keeps_one_application(board):
    """重試是安全的：第二次回傳第一次的結果，資料庫只有一筆。"""
    first = board.apply_job("J-102")
    second = board.apply_job("J-102")
    assert first["status"] == "submitted"
    assert second == {**first, "status": "already_applied"}
    assert len(board.applications("J-102")) == 1


def test_resume_masks_contact_details(board):
    resume = board.get_my_resume()
    assert resume["phone"] == "0912-***-678"
    assert resume["email"] == "x***@example.com"
    assert "national_id" not in resume
    assert "A123456789" not in str(resume)


@pytest.mark.parametrize("job_id", ["J-999", "j-102", "102", "", None])
def test_unknown_or_malformed_job_id_is_a_tool_error(board, job_id):
    with pytest.raises(ToolError):
        board.get_job(job_id)


@pytest.mark.parametrize("bad", [{"min_monthly_salary": -1}, {"min_monthly_salary": "40000"},
                                 {"min_monthly_salary": 40000.5}, {"min_monthly_salary": True},
                                 {"keyword": 123}, {"remote_only": "yes"}])
def test_invalid_search_arguments_are_tool_errors(board, bad):
    """模型給錯型別時要回一個它看得懂的錯誤，而不是讓程式當掉。"""
    with pytest.raises(ToolError):
        board.search_jobs(**bad)
