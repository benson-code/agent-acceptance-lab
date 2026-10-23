import Foundation

// 伺服器（server/app.py）回傳的 JSON。欄位是 snake_case，解碼時轉成 camelCase。

struct Account: Codable, Identifiable, Hashable {
    let role: String
    let userId: String
    let name: String
    let tools: [String]
    let scenarios: [Scenario]

    var id: String { userId }
    var isEmployer: Bool { role == "employer" }
    var roleText: String { isEmployer ? "企業" : "求職者" }
}

struct Scenario: Codable, Identifiable, Hashable {
    let id: String
    let userId: String
    let label: String
    let prompt: String
    let bugs: [String]
    let covers: [String]
}

struct BugSwitch: Codable, Identifiable, Hashable {
    let key: String
    let label: String
    let side: String
    var on: Bool

    var id: String { key }
    var isEmployerSide: Bool { side == "employer" }
}

struct Health: Codable, Hashable {
    let ok: Bool
    let liveAvailable: Bool
}

struct RunAccount: Codable, Hashable {
    let role: String
    let userId: String
    let name: String
}

/// Agent 要做、正在等使用者同意的事
struct PendingAction: Codable, Hashable {
    let action: String
    let jobId: String?
    let title: String?
    let company: String?
    let applicationId: Int?
    let name: String?
    let jobTitle: String?
    let from: String?
    let to: String?
}

struct Confirmation: Codable, Hashable {
    let action: String
    let approved: Bool
    let timedOut: Bool
}

struct ToolCall: Codable, Hashable {
    let name: String
    let inputText: String
    let output: String
    let isError: Bool
    let confirmed: Bool?
    let responseLost: Bool
    let blocked: String?
}

struct Trace: Codable, Hashable {
    let prompt: String
    let model: String
    let role: String
    let userId: String
    let toolCalls: [ToolCall]
    let finalText: String
    let stopped: String?
    let turns: Int
    let inputTokens: Int
    let outputTokens: Int
    let elapsedS: Double
}

struct Run: Codable, Identifiable, Hashable {
    let id: String
    let mode: String
    let scenarioId: String?
    let prompt: String
    let account: RunAccount
    let status: String
    let pending: PendingAction?
    let confirmations: [Confirmation]
    let error: String?
    let trace: Trace?

    var isFinished: Bool { status == "done" || status == "error" }
    var needsConfirmation: Bool { status == "needs_confirmation" }
}

enum JSON {
    static let decoder: JSONDecoder = {
        let d = JSONDecoder()
        d.keyDecodingStrategy = .convertFromSnakeCase
        return d
    }()

    static let encoder: JSONEncoder = {
        let e = JSONEncoder()
        e.keyEncodingStrategy = .convertToSnakeCase
        return e
    }()
}

/// 應徵狀態的中文（和 server/scenarios.py 的 STATUS_TEXT 一致）
let statusText = ["submitted": "已送出", "reviewing": "審核中", "interview": "邀請面試", "rejected": "不錄取"]
