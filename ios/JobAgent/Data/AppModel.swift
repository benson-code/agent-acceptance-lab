import Foundation
import Observation

/// 一次對話：使用者說的話，和那次執行（Agent 每次執行各自獨立，不記得上一次）
struct Exchange: Identifiable, Hashable {
    let id: String
    let prompt: String
    var run: Run?
    var failure: String?
}

enum Mode: String, CaseIterable, Identifiable {
    case demo, live
    var id: String { rawValue }
    var label: String { self == .demo ? "示範模式" : "真模型" }
}

@Observable
final class AppModel {
    static let defaultServer = "http://127.0.0.1:8430"

    var serverText: String {
        didSet { UserDefaults.standard.set(serverText, forKey: "serverURL") }
    }
    var accounts: [Account] = []
    var bugs: [BugSwitch] = []
    var health: Health?
    var mode: Mode = .demo
    var selectedAccountId = "U-001"
    var connectionError: String?
    var notice: String?                       // 伺服器拒絕的原因（例如 409），顯示一下就好
    private(set) var exchanges: [String: [Exchange]] = [:]
    private var selectedRun: [String: String] = [:]
    private(set) var activeRunId: String?

    init(defaults: UserDefaults = .standard) {
        // UI 測試和開發時用啟動參數 -serverURL 指定（UserDefaults 會讀到）
        serverText = defaults.string(forKey: "serverURL") ?? Self.defaultServer
    }

    var api: APIClient { APIClient(base: URL(string: serverText) ?? URL(string: Self.defaultServer)!) }
    var account: Account? { accounts.first { $0.userId == selectedAccountId } }
    var conversation: [Exchange] { exchanges[selectedAccountId] ?? [] }
    var bugsOn: Int { bugs.filter(\.on).count }
    var isBusy: Bool { activeRunId != nil }

    /// Trace 面板顯示的那次執行：使用者點選的，否則是最新的一次
    var traceRun: Run? {
        let list = conversation
        if let id = selectedRun[selectedAccountId], let picked = list.first(where: { $0.id == id })?.run {
            return picked
        }
        return list.last(where: { $0.run != nil })?.run
    }

    /// 現在要使用者確認的執行（不管是哪個帳號發起的）
    var pendingRun: Run? {
        exchanges.values.joined().compactMap(\.run).first { $0.needsConfirmation && $0.id == activeRunId }
    }

    func isSelected(_ exchange: Exchange) -> Bool { traceRun?.id == exchange.run?.id }
    func select(_ exchange: Exchange) { selectedRun[selectedAccountId] = exchange.id }

    // MARK: - 連線

    func connect(resetFirst: Bool = false) async {
        do {
            if resetFirst {
                try await api.reset()
                bugs = try await api.setBugs([])
                exchanges = [:]
            }
            health = try await api.health()
            accounts = try await api.accounts()
            bugs = try await api.bugs()
            connectionError = nil
            if account == nil { selectedAccountId = accounts.first?.userId ?? selectedAccountId }
        } catch {
            connectionError = error.localizedDescription
        }
    }

    func reset() async {
        do {
            try await api.reset()
            exchanges = [:]
            selectedRun = [:]
            notice = nil
        } catch {
            notice = error.localizedDescription
        }
    }

    // MARK: - 埋 bug 開關

    func setBug(_ key: String, on: Bool) async {
        var keys = Set(bugs.filter(\.on).map(\.key))
        if on { keys.insert(key) } else { keys.remove(key) }
        await applyBugs(Array(keys))
    }

    func clearBugs() async { await applyBugs([]) }

    private func applyBugs(_ keys: [String]) async {
        do {
            bugs = try await api.setBugs(keys.sorted())
        } catch {
            notice = error.localizedDescription
        }
    }

    // MARK: - 執行

    func run(_ scenario: Scenario) async {
        await start(prompt: scenario.prompt) { try await $0.start(scenario: scenario.id) }
    }

    func send(_ prompt: String) async {
        let text = prompt.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { return }
        let userId = selectedAccountId
        await start(prompt: text) { try await $0.start(userId: userId, prompt: text) }
    }

    func answer(_ approve: Bool) async {
        guard let run = pendingRun else { return }
        do {
            let next = try await api.confirm(run.id, approve: approve)
            store(next)
            await follow(next)
        } catch {
            // 常見原因：超過 60 秒沒回答，伺服器已經當作不同意（409）。拿最新的狀態，畫面才不會停在確認上
            await refresh(run.id)
        }
    }

    private func start(prompt: String, _ call: (APIClient) async throws -> Run) async {
        guard !isBusy else { return }
        let accountId = selectedAccountId
        let placeholder = Exchange(id: "pending-\(UUID().uuidString)", prompt: prompt)
        exchanges[accountId, default: []].append(placeholder)
        notice = nil
        do {
            let run = try await call(api)
            replace(placeholder.id, in: accountId, with: Exchange(id: run.id, prompt: prompt, run: run))
            selectedRun[accountId] = nil
            activeRunId = run.id
            await follow(run)
        } catch {
            replace(placeholder.id, in: accountId,
                    with: Exchange(id: placeholder.id, prompt: prompt, failure: error.localizedDescription))
        }
    }

    /// 一直問到執行結束或需要確認為止
    private func follow(_ run: Run) async {
        var current = run
        do {
            while !current.isFinished && !current.needsConfirmation {
                current = try await api.run(current.id)
                store(current)
            }
        } catch {
            // 斷線：不要讓 App 一直停在「執行中」，之後的操作還能用
            notice = error.localizedDescription
            activeRunId = nil
            return
        }
        if current.isFinished {
            activeRunId = nil
            if current.status == "error" { notice = current.error }
            if current.confirmations.contains(where: \.timedOut) {
                notice = "超過 60 秒沒有回答，已經當作不同意，什麼都沒有送出。"
            }
        }
    }

    private func refresh(_ id: String) async {
        do {
            let latest = try await api.run(id, wait: 0)
            store(latest)
            await follow(latest)
        } catch {
            notice = error.localizedDescription
            activeRunId = nil
        }
    }

    private func store(_ run: Run) {
        let accountId = run.account.userId
        guard let i = exchanges[accountId]?.firstIndex(where: { $0.id == run.id }) else { return }
        exchanges[accountId]?[i].run = run
    }

    private func replace(_ id: String, in accountId: String, with exchange: Exchange) {
        guard let i = exchanges[accountId]?.firstIndex(where: { $0.id == id }) else { return }
        exchanges[accountId]?[i] = exchange
    }
}
