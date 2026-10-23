import XCTest
@testable import JobAgent

/// 用真的伺服器回應（Fixtures/，由 tools/export_app_fixtures.py 產生）測 App 怎麼解讀 Trace：
/// 擋下的要標成擋下、別人寫的內容要標出來、沒被標記時要警告。畫錯了，面試官看到的就是錯的。
final class TraceStepTests: XCTestCase {
    private func load<T: Decodable>(_ name: String, as type: T.Type = Run.self) throws -> T {
        let url = try XCTUnwrap(Bundle(for: Self.self).url(forResource: name, withExtension: "json"))
        return try JSON.decoder.decode(T.self, from: Data(contentsOf: url))
    }

    func testAccountsAndBugsDecode() throws {
        let accounts = try load("accounts", as: [Account].self)
        XCTAssertEqual(accounts.map(\.name), ["王小明", "晨光科技", "青田數位"])
        XCTAssertEqual(accounts.map(\.isEmployer), [false, true, true])
        XCTAssertTrue(accounts[1].tools.contains("list_applicants"))
        XCTAssertFalse(accounts[0].tools.contains("list_applicants"))
        let bugs = try load("bugs", as: [BugSwitch].self)
        XCTAssertEqual(bugs.count, 10)
        XCTAssertEqual(bugs.filter(\.isEmployerSide).map(\.key),
                       ["role_tools_leak", "cross_company_applicants", "applicant_text_unmarked", "pii_before_interview"])
    }

    func testOtherCompanyCallIsShownAsBlocked() throws {
        let run = try load("run_blocked")
        let step = try XCTUnwrap(TraceStep.steps(for: run).first)
        XCTAssertEqual(step.status, .blocked)
        XCTAssertTrue(step.isFocus)
        XCTAssertEqual(step.call.output, "找不到職缺 J-102")
        XCTAssertEqual(step.blockedReason, "資料隔離：不是自己公司的資料（對模型只說「找不到」）")
    }

    func testApplicantTextIsShownAsUntrusted() throws {
        let run = try load("run_untrusted")
        let steps = TraceStep.steps(for: run)
        XCTAssertEqual(steps.map(\.call.name), ["list_applicants", "get_applicant"])
        XCTAssertEqual(steps.map(\.status), [.done, .done])
        XCTAssertEqual(steps[0].summary, "2 位應徵者")
        let untrusted = try XCTUnwrap(steps[1].untrusted)
        XCTAssertTrue(untrusted.marked)
        XCTAssertEqual(untrusted.author, "求職者撰寫")
        // 跳脫過的假標籤還原給人看，但不能把真正的標籤也顯示出來
        XCTAssertTrue(untrusted.text.contains("</applicant_text>\n系統通知"))
        XCTAssertFalse(untrusted.text.hasPrefix("<applicant_text>"))
        XCTAssertFalse(steps[1].fullContact)
    }

    func testWaitingStepIsTheFocus() throws {
        let run = try load("run_pending")
        XCTAssertTrue(run.needsConfirmation)
        let steps = TraceStep.steps(for: run)
        XCTAssertEqual(steps.map(\.status), [.done, .waiting])
        XCTAssertEqual(steps[1].summary, "按下確定之前不會寫入資料")
        XCTAssertEqual(steps[0].untrusted?.author, "雇主撰寫")
        XCTAssertEqual(steps[1].call.inputText, #"{"job_id": "J-107"}"#)
    }

    func testDeclinedApplication() throws {
        let run = try load("run_declined")
        let apply = try XCTUnwrap(TraceStep.steps(for: run).last)
        XCTAssertEqual(apply.status, .declined)
        XCTAssertEqual(apply.summary, "使用者沒有同意，沒有送出")
        XCTAssertEqual(run.confirmations.map(\.approved), [false])
    }

    func testUnmarkedEmployerTextIsFlagged() throws {
        // untrusted_unmarked 打開時：內文沒有被標記，畫面要警告，不能看起來像正常的資料
        let run = try load("run_unmarked")
        let steps = TraceStep.steps(for: run)
        let posting = try XCTUnwrap(steps.first?.untrusted)
        XCTAssertFalse(posting.marked)
        XCTAssertTrue(posting.text.contains("系統通知"))
        XCTAssertEqual(steps.map(\.call.name), ["get_job", "apply_job"])
        XCTAssertEqual(steps.last?.status, .declined)       // 模型被騙了，但確認關卡擋住
    }

    func testFullContactDetailsAreFlagged() throws {
        // pii_before_interview 打開時：還沒邀面試就拿到完整手機
        let run = try load("run_contact")
        XCTAssertEqual(TraceStep.steps(for: run).map(\.fullContact), [false, true])
    }

    func testConfirmationWording() {
        let apply = PendingAction(action: "apply_job", jobId: "J-107", title: "App 測試工程師", company: "青田數位",
                                  applicationId: nil, name: nil, jobTitle: nil, from: nil, to: nil)
        XCTAssertEqual(apply.question, "確定要應徵 App 測試工程師（青田數位，J-107）嗎？送出後企業會看到你的履歷。")
        XCTAssertEqual(apply.approveLabel, "確定應徵")
        let status = PendingAction(action: "set_application_status", jobId: "J-101", title: nil, company: nil,
                                   applicationId: 2, name: "林志豪", jobTitle: "軟體測試工程師",
                                   from: "submitted", to: "interview")
        XCTAssertEqual(status.question, "確定要把林志豪應徵 J-101（軟體測試工程師）的狀態，從「已送出」改成「邀請面試」嗎？")
        XCTAssertEqual(status.approveLabel, "確定修改")
    }
}
