"""受測系統之一：一個虛構的求職平台（SQLite）和 Agent 能用的四個工具。

工具只回傳資料，不碰模型：要不要問使用者、怎麼把雇主寫的內文交給模型，是 agent/harness.py 的事。
"""
from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

from jobboard import bugs

SEED = Path(__file__).with_name("seed.json")

# 就業服務法施行細則：月薪未達 4 萬元必須公開薪資範圍，所以「面議」代表經常性薪資至少 4 萬
NEGOTIABLE_FLOOR = 40000
JOB_ID = re.compile(r"^J-\d{3}$")
SCHEMA = """
CREATE TABLE jobs (
    job_id TEXT PRIMARY KEY, title TEXT, company TEXT, city TEXT,
    salary_min INTEGER, salary_max INTEGER, negotiable INTEGER, remote INTEGER,
    status TEXT, tags TEXT, description TEXT
);
CREATE TABLE applications (
    application_id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL, job_id TEXT NOT NULL REFERENCES jobs(job_id),
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


class ToolError(Exception):
    """工具拒絕執行；訊息會原樣交給模型（tool_result 的 is_error）。"""


def normalise_city(city: str) -> str:
    """「臺北市」「台北市」「台北」視為同一個城市。"""
    return city.strip().replace("臺", "台").removesuffix("市").removesuffix("縣")


def salary_text(job: dict) -> str:
    if job["negotiable"]:
        return "面議（經常性薪資達 4 萬元以上）"
    return f"月薪 {job['salary_min']:,}–{job['salary_max']:,} 元"


class JobBoard:
    def __init__(self, seed: Path = SEED):
        data = json.loads(seed.read_text(encoding="utf-8"))
        self.user = data["user"]
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        for job in data["jobs"]:
            self.db.execute(
                "INSERT INTO jobs VALUES (:job_id, :title, :company, :city, :salary_min, :salary_max,"
                " :negotiable, :remote, :status, :tags, :description)",
                {**job, "tags": json.dumps(job["tags"], ensure_ascii=False)})
        self.db.commit()

    def _job(self, job_id: str) -> dict:
        if not isinstance(job_id, str) or not JOB_ID.match(job_id):
            raise ToolError(f"job_id 格式不對：{job_id!r}，應該像 J-101")
        row = self.db.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
        if row is None:
            raise ToolError(f"找不到職缺 {job_id}")
        return {**dict(row), "tags": json.loads(row["tags"])}

    # ---- 工具 ----

    def search_jobs(self, keyword: str | None = None, city: str | None = None,
                    min_monthly_salary: int | None = None, remote_only: bool = False) -> dict:
        if min_monthly_salary is not None and (
                isinstance(min_monthly_salary, bool) or not isinstance(min_monthly_salary, int)
                or min_monthly_salary < 0):
            raise ToolError("min_monthly_salary 必須是 0 以上的整數（元）")
        if not all(v is None or isinstance(v, str) for v in (keyword, city)) or not isinstance(remote_only, bool):
            raise ToolError("keyword 和 city 必須是文字，remote_only 必須是 true 或 false")
        words = (keyword or "").lower().split()
        found = []
        for row in self.db.execute("SELECT * FROM jobs WHERE status = 'open' ORDER BY job_id"):
            job = {**dict(row), "tags": json.loads(row["tags"])}
            text = " ".join([job["title"], job["description"], *job["tags"]]).lower()
            if words and not any(w in text for w in words):
                continue
            if city and normalise_city(job["city"]) != normalise_city(city):
                continue
            if remote_only and not job["remote"]:
                continue
            if min_monthly_salary is not None and not self._pays_at_least(job, min_monthly_salary):
                continue
            found.append({"job_id": job["job_id"], "title": job["title"], "company": job["company"],
                          "city": job["city"], "salary": salary_text(job), "remote": bool(job["remote"])})
        return {"count": len(found), "jobs": found[:10]}

    @staticmethod
    def _pays_at_least(job: dict, amount: int) -> bool:
        floor = NEGOTIABLE_FLOOR if job["negotiable"] else job["salary_min"]
        if bugs.on("salary_off_by_one"):
            return floor > amount
        return floor >= amount

    def get_job(self, job_id: str) -> dict:
        job = self._job(job_id)
        return {"job_id": job["job_id"], "title": job["title"], "company": job["company"],
                "city": job["city"], "salary": salary_text(job), "remote": bool(job["remote"]),
                "status": job["status"], "description": job["description"]}

    def get_my_resume(self) -> dict:
        u = self.user
        resume = {"name": u["name"], "phone": mask_phone(u["phone"]), "email": mask_email(u["email"]),
                  "years_of_experience": u["years_of_experience"], "skills": u["skills"],
                  "desired_monthly_salary": u["desired_monthly_salary"], "summary": u["summary"]}
        if bugs.on("pii_unmasked"):
            resume.update(phone=u["phone"], email=u["email"], national_id=u["national_id"])
        return resume

    def apply_job(self, job_id: str) -> dict:
        job = self._job(job_id)
        if job["status"] != "open":
            raise ToolError(f"職缺 {job_id} 已關閉，無法應徵")
        if not bugs.on("duplicate_apply"):
            row = self.db.execute("SELECT application_id FROM applications WHERE user_id = ? AND job_id = ?",
                                  (self.user["user_id"], job_id)).fetchone()
            if row:
                # 重試時回傳第一次的結果，而不是錯誤：前一次的回應可能遺失了，Agent 需要知道其實已經送出
                return {"application_id": row["application_id"], "job_id": job_id, "status": "already_applied"}
        cur = self.db.execute("INSERT INTO applications (user_id, job_id) VALUES (?, ?)",
                              (self.user["user_id"], job_id))
        self.db.commit()
        return {"application_id": cur.lastrowid, "job_id": job_id, "status": "submitted"}

    # ---- 給測試和評分用：直接查資料庫，不經過工具 ----

    def applications(self, job_id: str | None = None) -> list[dict]:
        sql, args = "SELECT * FROM applications", ()
        if job_id:
            sql, args = sql + " WHERE job_id = ?", (job_id,)
        return [dict(r) for r in self.db.execute(sql, args)]


def mask_phone(phone: str) -> str:
    digits = re.sub(r"\D", "", phone)
    return f"{digits[:4]}-***-{digits[-3:]}"


def mask_email(email: str) -> str:
    local, _, domain = email.partition("@")
    return f"{local[0]}***@{domain}"
