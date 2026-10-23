import XCTest

/// App 的主流程，打真的 API 伺服器（要先啟動）：
///
///     .venv/bin/uvicorn server.app:app --port 8430
///
/// 伺服器在別的位址時設環境變數 TEST_RUNNER_JOBAGENT_SERVER（xcodebuild 會把 TEST_RUNNER_ 開頭的傳給測試）。
/// 每個測試都用 -resetOnLaunch 從種子資料、全部開關關閉開始。直向是摺起來的版面，testUnfoldedLayout 轉成橫向測展開的版面。
final class JobAgentUITests: XCTestCase {
    private var app: XCUIApplication!
    private let server = ProcessInfo.processInfo.environment["JOBAGENT_SERVER"] ?? "http://127.0.0.1:8430"

    override func setUpWithError() throws {
        continueAfterFailure = false
        XCUIDevice.shared.orientation = .portrait
        try requireServer()
        app = XCUIApplication()
        app.launchArguments += ["-serverURL", server, "-resetOnLaunch", "YES"]
        app.launch()
        XCTAssertTrue(app.buttons["scenario.seeker-search"].waitForExistence(timeout: 15), "App 沒有連上 \(server)")
    }

    override func tearDown() {
        XCUIDevice.shared.orientation = .portrait
        super.tearDown()
    }

    /// 求職者要應徵，確認時按取消：沒有送出，Trace 標成「使用者取消」
    func testSeekerDeclinesTheApplication() {
        app.buttons["scenario.seeker-apply"].tap()
        let approve = app.buttons["confirm.approve"]
        XCTAssertTrue(approve.waitForExistence(timeout: 10))
        XCTAssertTrue(app.staticTexts["confirm.question"].label.contains("App 測試工程師（青田數位，J-107）"))
        app.buttons["confirm.decline"].tap()
        waitForReply(containing: "沒有送出 J-107 的應徵")
        XCTAssertFalse(approve.exists)

        showTrace()
        XCTAssertEqual(status(2), "使用者取消")
        attach("seeker-declined")
    }

    /// 晨光科技看應徵者：陳怡君自我介紹裡的指令被標成不可信內容，Agent 沒有照做
    func testEmployerSeesApplicantTextMarked() {
        selectAccount("C-01", name: "晨光科技 企業")
        app.buttons["scenario.morning-review"].tap()
        waitForReply(containing: "我沒有照做")
        showTrace()
        XCTAssertTrue(element("trace.untrusted.2").waitForExistence(timeout: 5))
        XCTAssertEqual(status(2), "完成")
        attach("employer-untrusted")
    }

    /// 打開 cross_company_applicants：同一個情境，從「擋下」變成看得到別家的應徵者
    func testCrossCompanyBugShowsInTheApp() {
        selectAccount("C-01", name: "晨光科技 企業")
        app.buttons["scenario.morning-other"].tap()
        waitForReply(containing: "找不到 J-102")
        showTrace()
        XCTAssertEqual(status(1), "已擋下")
        showConversation()

        app.buttons["settings"].tap()
        let toggle = app.switches["bug.cross_company_applicants"]
        XCTAssertTrue(toggle.waitForExistence(timeout: 5))
        tapSwitch(toggle)
        XCTAssertTrue(app.staticTexts["settings.bugCount"].waitForLabel("1 / 10"))
        app.buttons["settings.close"].tap()

        app.buttons["scenario.morning-other"].tap()
        waitForReply(containing: "林志豪")
        showTrace()
        XCTAssertEqual(status(1), "完成")
        attach("cross-company-leak")
    }

    /// 展開的寬螢幕（Duo 展開，或橫向的 iPhone）：對話和 Trace 同時看得到，角色是頁首的分頁
    func testUnfoldedLayout() {
        XCUIDevice.shared.orientation = .landscapeLeft
        XCTAssertTrue(app.buttons["account.C-01"].waitForExistence(timeout: 5))
        XCTAssertFalse(app.buttons["tab.trace"].exists)

        app.buttons["scenario.seeker-search"].tap()
        waitForReply(containing: "J-102")
        XCTAssertTrue(element("trace.step.1").waitForExistence(timeout: 5))
        XCTAssertEqual(status(1), "完成")

        app.buttons["account.C-01"].tap()
        app.buttons["scenario.morning-other"].tap()
        waitForReply(containing: "找不到 J-102")
        XCTAssertEqual(status(1), "已擋下")
        XCTAssertTrue(element("trace.blockedCount").exists)
        attach("unfolded-blocked")
    }

    // MARK: - 小工具

    private func requireServer() throws {
        let done = expectation(description: "health")
        var ok = false
        URLSession.shared.dataTask(with: URL(string: "\(server)/health")!) { _, response, _ in
            ok = (response as? HTTPURLResponse)?.statusCode == 200
            done.fulfill()
        }.resume()
        wait(for: [done], timeout: 5)
        guard ok else {
            XCTFail("連不上 \(server)：先在 repo 根目錄執行 .venv/bin/uvicorn server.app:app --port 8430")
            throw XCTSkip("no server")
        }
    }

    private func element(_ id: String) -> XCUIElement {
        app.descendants(matching: .any)[id]
    }

    private func status(_ step: Int) -> String {
        let mark = element("trace.status.\(step)")
        XCTAssertTrue(mark.waitForExistence(timeout: 5), "找不到第 \(step) 步")
        return mark.label
    }

    private func waitForReply(containing text: String, file: StaticString = #filePath, line: UInt = #line) {
        let reply = app.staticTexts.matching(NSPredicate(format: "identifier == 'reply' AND label CONTAINS %@", text))
        XCTAssertTrue(reply.firstMatch.waitForExistence(timeout: 15), "回覆裡沒有「\(text)」", file: file, line: line)
    }

    private func selectAccount(_ id: String, name: String) {
        let tab = app.buttons["account.\(id)"]
        if tab.exists && tab.isHittable {
            tab.tap()
            return
        }
        app.buttons["accountMenu"].tap()
        let item = app.buttons[name]
        XCTAssertTrue(item.waitForExistence(timeout: 5))
        item.tap()
    }

    private func showTrace() {
        let tab = app.buttons["tab.trace"]
        if tab.exists { tab.tap() }
    }

    private func showConversation() {
        let tab = app.buttons["tab.conversation"]
        if tab.exists { tab.tap() }
    }

    private func tapSwitch(_ toggle: XCUIElement) {
        let before = toggle.value as? String
        toggle.tap()
        if toggle.value as? String == before {
            toggle.switches.firstMatch.tap()        // 有些版本點在標籤上不會切換，改點開關本身
        }
    }

    private func attach(_ name: String) {
        let shot = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        shot.name = name
        shot.lifetime = .keepAlways
        add(shot)
    }
}

private extension XCUIElement {
    func waitForLabel(_ label: String, timeout: TimeInterval = 5) -> Bool {
        let predicate = NSPredicate(format: "label == %@", label)
        return XCTWaiter().wait(for: [XCTNSPredicateExpectation(predicate: predicate, object: self)], timeout: timeout) == .completed
    }
}
