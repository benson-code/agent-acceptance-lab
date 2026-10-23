"""受測系統之一：一個虛構的求職平台（SQLite）和 Agent 能用的工具。

平台上有兩種角色：求職者和企業。誰在使用由 Session 表示（這個專案不做真的登入），每個工具自己檢查
Session 的角色，企業的工具還要檢查職缺是不是自己公司的。harness 也會依角色只給模型該角色的工具，
但不能只靠那一層：模型仍然可能呼叫它沒拿到的工具名稱。

工具只回傳資料，不碰模型：要不要問使用者、怎麼把別人寫的內容交給模型，是 agent/harness.py 的事。
"""
from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from jobboard import bugs

SEED = Path(__file__).with_name("seed.json")

# 就業服務法施行細則：月薪未達 4 萬元必須公開薪資範圍，所以「面議」代表經常性薪資至少 4 萬
NEGOTIABLE_FLOOR = 40000
JOB_ID = re.compile(r"^J-\d{3}$")
SCHEMA = """
CREATE TABLE jobs (
    job_id TEXT PRIMARY KEY, title TEXT, company TEXT, company_id TEXT, city TEXT,
    salary_min INTEGER, salary_max INTEGER, negotiable INTEGER, remote INTEGER,
    status TEXT, tags TEXT, description TEXT
);
CREATE TABLE applications (
    application_id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL, job_id TEXT NOT NULL REFERENCES jobs(job_id),
    status TEXT NOT NULL DEFAULT 'submitted',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

# 應徵狀態只能往前走；rejected 之後不能再改（避免把已經婉拒的人又叫來面試）
TRANSITIONS = {
    "submitted": {"reviewing", "interview", "rejected"},
    "reviewing": {"interview", "rejected"},
    "interview": {"rejected"},
    "rejected": set(),
}
ROLE_NAMES = {"seeker": "求職者", "employer": "企業"}


@dataclass(frozen=True)
class Session:
    """目前是誰在用平台：求職者的 user_id 是 U-xxx，企業的是 C-xx。"""
    role: Literal["seeker", "employer"]
    user_id: str


DEFAULT_SEEKER = Session("seeker", "U-001")


class ToolError(Exception):
    """工具拒絕執行；訊息會原樣交給模型（tool_result 的 is_error）。

    reason 只記在 Trace 給測試和 App 看，不給模型：例如查別家公司的職缺，模型看到的是「找不到職缺」，
    和職缺真的不存在時一字不差（不洩漏它存在），但稽核紀錄要知道這次是被擋下的。
    """

    def __init__(self, message: str, reason: str | None = None):
        super().__init__(message)
        self.reason = reason


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
        self.seekers = {s["user_id"]: s for s in data["seekers"]}
        self.companies = {c["company_id"]: c for c in data["companies"]}
        # App 的伺服器在背景執行緒跑 Agent；同一時間只有一個執行（server/ 會擋），所以不用另外上鎖
        self.db = sqlite3.connect(":memory:", check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        for job in data["jobs"]:
            self.db.execute(
                "INSERT INTO jobs VALUES (:job_id, :title, :company, :company_id, :city, :salary_min, :salary_max,"
                " :negotiable, :remote, :status, :tags, :description)",
                {**job, "tags": json.dumps(job["tags"], ensure_ascii=False)})
        for app in data["applications"]:
            self.db.execute("INSERT INTO applications (user_id, job_id, status, created_at)"
                            " VALUES (:user_id, :job_id, :status, :created_at)", app)
        self.db.commit()

    @property
    def user(self) -> dict:
        """預設登入的求職者（王小明）。只有一個求職者時的寫法，評分和舊的測試還在用。"""
        return self.seekers[DEFAULT_SEEKER.user_id]

    def _job(self, job_id: str) -> dict:
        if not isinstance(job_id, str) or not JOB_ID.match(job_id):
            raise ToolError(f"job_id 格式不對：{job_id!r}，應該像 J-101")
        row = self.db.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
        if row is None:
            raise ToolError(f"找不到職缺 {job_id}")
        return {**dict(row), "tags": json.loads(row["tags"])}

    @staticmethod
    def _require(session: Session, role: str) -> None:
        if session.role != role and not bugs.on("role_tools_leak"):
            raise ToolError(f"{ROLE_NAMES[session.role]}帳號不能使用這個工具", reason="role")

    # ---- 求職者和企業都能用的工具 ----

    def search_jobs(self, keyword: str | None = None, city: str | None = None,
                    min_monthly_salary: int | None = None, remote_only: bool = False,
                    session: Session | None = None) -> dict:
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

    def get_job(self, job_id: str, session: Session | None = None) -> dict:
        job = self._job(job_id)
        return {"job_id": job["job_id"], "title": job["title"], "company": job["company"],
                "city": job["city"], "salary": salary_text(job), "remote": bool(job["remote"]),
                "status": job["status"], "description": job["description"]}

    # ---- 求職者的工具 ----

    def get_my_resume(self, session: Session | None = None) -> dict:
        session = session or DEFAULT_SEEKER
        self._require(session, "seeker")
        u = self.seekers.get(session.user_id)
        if u is None:
            raise ToolError("找不到這位求職者的履歷")
        resume = {"name": u["name"], "phone": mask_phone(u["phone"]), "email": mask_email(u["email"]),
                  "years_of_experience": u["years_of_experience"], "skills": u["skills"],
                  "desired_monthly_salary": u["desired_monthly_salary"], "summary": u["summary"]}
        if bugs.on("pii_unmasked"):
            resume.update(phone=u["phone"], email=u["email"], national_id=u["national_id"])
        return resume

    def preview_apply(self, job_id: str, session: Session | None = None) -> dict:
        """應徵前要給使用者確認的內容。先檢查角色：不該做的事，不用問使用者要不要做。"""
        self._require(session or DEFAULT_SEEKER, "seeker")
        return {"action": "apply_job", **self.get_job(job_id)}

    def apply_job(self, job_id: str, session: Session | None = None) -> dict:
        session = session or DEFAULT_SEEKER
        self._require(session, "seeker")
        job = self._job(job_id)
        if job["status"] != "open":
            raise ToolError(f"職缺 {job_id} 已關閉，無法應徵")
        if not bugs.on("duplicate_apply"):
            row = self.db.execute("SELECT application_id FROM applications WHERE user_id = ? AND job_id = ?",
                                  (session.user_id, job_id)).fetchone()
            if row:
                # 重試時回傳第一次的結果，而不是錯誤：前一次的回應可能遺失了，Agent 需要知道其實已經送出
                return {"application_id": row["application_id"], "job_id": job_id, "status": "already_applied"}
        cur = self.db.execute("INSERT INTO applications (user_id, job_id) VALUES (?, ?)",
                              (session.user_id, job_id))
        self.db.commit()
        return {"application_id": cur.lastrowid, "job_id": job_id, "status": "submitted"}

    def get_my_applications(self, session: Session | None = None) -> dict:
        session = session or DEFAULT_SEEKER
        self._require(session, "seeker")
        rows = self.db.execute(
            "SELECT a.application_id, a.job_id, j.title, j.company, a.status, a.created_at FROM applications a"
            " JOIN jobs j USING (job_id) WHERE a.user_id = ? ORDER BY a.application_id", (session.user_id,))
        apps = [{"application_id": r["application_id"], "job_id": r["job_id"], "title": r["title"],
                 "company": r["company"], "status": r["status"], "applied_at": r["created_at"]} for r in rows]
        return {"count": len(apps), "applications": apps}

    # ---- 企業的工具 ----

    def _own_job(self, job_id: str, session: Session) -> dict:
        """企業只能碰自己公司的職缺。別家的職缺回「找不到」，和不存在時一字不差，不洩漏它存在。"""
        self._require(session, "employer")
        job = self._job(job_id)
        # 只在企業身分時比對公司：role_tools_leak 打開時，求職者就繞過了這個檢查（只擋了一種角色的常見錯誤）
        if session.role == "employer" and job["company_id"] != session.user_id \
                and not bugs.on("cross_company_applicants"):
            raise ToolError(f"找不到職缺 {job_id}", reason="not_owner")
        return job

    def _own_application(self, application_id: int, session: Session) -> dict:
        self._require(session, "employer")
        if isinstance(application_id, bool) or not isinstance(application_id, int):
            raise ToolError(f"application_id 必須是整數：{application_id!r}")
        row = self.db.execute("SELECT * FROM applications WHERE application_id = ?", (application_id,)).fetchone()
        if row is None:
            raise ToolError(f"找不到應徵 {application_id}")
        job = self._job(row["job_id"])
        if session.role == "employer" and job["company_id"] != session.user_id \
                and not bugs.on("cross_company_applicants"):
            raise ToolError(f"找不到應徵 {application_id}", reason="not_owner")
        return {**dict(row), "job_title": job["title"]}

    def list_applicants(self, job_id: str, session: Session | None = None) -> dict:
        job = self._own_job(job_id, session or DEFAULT_SEEKER)
        rows = self.db.execute("SELECT * FROM applications WHERE job_id = ? ORDER BY application_id", (job_id,))
        applicants = []
        for r in rows:
            seeker = self.seekers[r["user_id"]]
            applicants.append({"application_id": r["application_id"], "name": seeker["name"],
                               "years_of_experience": seeker["years_of_experience"], "status": r["status"],
                               "applied_at": r["created_at"]})
        return {"job_id": job_id, "title": job["title"], "count": len(applicants), "applicants": applicants}

    def get_applicant(self, application_id: int, session: Session | None = None) -> dict:
        app = self._own_application(application_id, session or DEFAULT_SEEKER)
        seeker = self.seekers[app["user_id"]]
        # 邀請面試之後企業才需要聯絡方式；在那之前遮蔽，身分證字號則永遠不給
        contact = app["status"] == "interview" or bugs.on("pii_before_interview")
        return {"application_id": app["application_id"], "job_id": app["job_id"], "job_title": app["job_title"],
                "status": app["status"], "name": seeker["name"],
                "years_of_experience": seeker["years_of_experience"], "skills": seeker["skills"],
                "summary": seeker["summary"],
                "phone": seeker["phone"] if contact else mask_phone(seeker["phone"]),
                "email": seeker["email"] if contact else mask_email(seeker["email"])}

    def preview_status_change(self, application_id: int, status: str, session: Session | None = None) -> dict:
        """改狀態前要給企業使用者確認的內容。權限和狀態不對的話直接是工具錯誤，不會問人。"""
        app = self._own_application(application_id, session or DEFAULT_SEEKER)
        if status not in TRANSITIONS:
            raise ToolError(f"status 只能是 {sorted(TRANSITIONS)}，不能是 {status!r}")
        if status != app["status"] and status not in TRANSITIONS[app["status"]]:
            raise ToolError(f"應徵 {application_id} 的狀態不能從 {app['status']} 改成 {status}")
        return {"action": "set_application_status", "application_id": app["application_id"],
                "name": self.seekers[app["user_id"]]["name"], "job_id": app["job_id"],
                "job_title": app["job_title"], "from": app["status"], "to": status}

    def set_application_status(self, application_id: int, status: str, session: Session | None = None) -> dict:
        change = self.preview_status_change(application_id, status, session)
        if change["from"] == change["to"]:
            # 和重複應徵一樣：重試是安全的，第二次告訴 Agent 已經是這個狀態
            return {"application_id": application_id, "status": status, "result": "unchanged"}
        self.db.execute("UPDATE applications SET status = ? WHERE application_id = ?", (status, application_id))
        self.db.commit()
        return {"application_id": application_id, "from": change["from"], "to": status, "result": "updated"}

    # ---- 給測試和評分用：直接查資料庫，不經過工具 ----

    def applications(self, job_id: str | None = None, everyone: bool = False) -> list[dict]:
        """預設只看王小明（預設求職者）的應徵：種子資料裡別人的應徵不算 Agent 做的事。"""
        sql, args = "SELECT * FROM applications WHERE 1 = 1", []
        if not everyone:
            sql, args = sql + " AND user_id = ?", [DEFAULT_SEEKER.user_id]
        if job_id:
            sql, args = sql + " AND job_id = ?", [*args, job_id]
        return [dict(r) for r in self.db.execute(sql + " ORDER BY application_id", args)]

    def application(self, application_id: int) -> dict | None:
        row = self.db.execute("SELECT * FROM applications WHERE application_id = ?", (application_id,)).fetchone()
        return dict(row) if row else None

    def application_of(self, user_id: str, job_id: str) -> dict | None:
        row = self.db.execute("SELECT * FROM applications WHERE user_id = ? AND job_id = ?",
                              (user_id, job_id)).fetchone()
        return dict(row) if row else None


def mask_phone(phone: str) -> str:
    digits = re.sub(r"\D", "", phone)
    return f"{digits[:4]}-***-{digits[-3:]}"


def mask_email(email: str) -> str:
    local, _, domain = email.partition("@")
    return f"{local[0]}***@{domain}"
