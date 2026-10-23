import Foundation

/// Trace 的一步要怎麼呈現：狀態、摘要、別人寫的內容、擋下的原因。
/// 全部由伺服器回傳的 ToolCall 算出來，不碰畫面，所以能用單元測試測。
struct TraceStep: Identifiable, Hashable {
    enum Status: Hashable {
        case done, waiting, declined, blocked, error, lost

        var word: String {
            switch self {
            case .done: "完成"
            case .waiting: "等待使用者確認"
            case .declined: "使用者取消"
            case .blocked: "已擋下"
            case .error: "工具錯誤"
            case .lost: "回應遺失"
            }
        }
    }

    /// 別人寫的內容（職缺內文、自我介紹）。marked 是 false 時代表沒有被標記：埋了 bug 才會這樣
    struct Untrusted: Hashable {
        let author: String
        let text: String
        let marked: Bool
    }

    let index: Int
    let call: ToolCall
    let status: Status
    let summary: String?
    let untrusted: Untrusted?
    let blockedReason: String?
    let fullContact: Bool

    var id: Int { index }
    var numeral: String { String(format: "%02d", index) }
    /// 等待和擋下是畫面的焦點：序號、細線都用狀態色
    var isFocus: Bool { status == .waiting || status == .blocked }

    init(index: Int, call: ToolCall, waitingForUser: Bool) {
        self.index = index
        self.call = call
        let data = (try? JSONSerialization.jsonObject(with: Data(call.output.utf8))) as? [String: Any]

        if call.blocked != nil {
            status = .blocked
        } else if call.responseLost {
            status = .lost
        } else if call.isError {
            status = .error
        } else if waitingForUser {
            status = .waiting
        } else if call.confirmed == false || data?["status"] as? String == "declined_by_user" {
            status = .declined
        } else {
            status = .done
        }

        blockedReason = switch call.blocked {
        case "role": "角色權限：這個帳號不能使用 \(call.name)"
        case "not_owner": "資料隔離：不是自己公司的資料（對模型只說「找不到」）"
        default: nil
        }
        summary = waitingForUser ? "按下確定之前不會寫入資料" : Self.summary(call, data)
        untrusted = Self.untrusted(call, data)
        fullContact = !call.isError && call.output.range(of: #"09\d{2}-\d{3}-\d{3}"#, options: .regularExpression) != nil
    }

    private static func summary(_ call: ToolCall, _ data: [String: Any]?) -> String? {
        if call.isError { return call.output }
        guard let data else { return nil }
        let count = data["count"] as? Int ?? 0
        switch call.name {
        case "search_jobs": return "\(count) 筆結果"
        case "get_job": return [data["job_id"], data["title"], data["company"]].compactMap { $0 as? String }.joined(separator: " ")
        case "get_my_resume": return data["name"] as? String
        case "get_my_applications": return "\(count) 筆應徵"
        case "list_applicants": return "\(count) 位應徵者"
        case "get_applicant":
            let name = data["name"] as? String ?? ""
            return "\(name) · \(statusText[data["status"] as? String ?? ""] ?? "")"
        case "apply_job":
            switch data["status"] as? String {
            case "submitted": return "已送出（應徵 #\(data["application_id"] as? Int ?? 0)）"
            case "already_applied": return "先前已經應徵過，這次沒有重複送出"
            case "declined_by_user": return "使用者沒有同意，沒有送出"
            default: return nil
            }
        case "set_application_status":
            if data["status"] as? String == "declined_by_user" { return "使用者沒有同意，狀態沒有改" }
            if data["result"] as? String == "unchanged" { return "已經是這個狀態，沒有再改" }
            let from = statusText[data["from"] as? String ?? ""] ?? ""
            let to = statusText[data["to"] as? String ?? ""] ?? ""
            return "\(from) → \(to)"
        default: return nil
        }
    }

    private static func untrusted(_ call: ToolCall, _ data: [String: Any]?) -> Untrusted? {
        let (field, tag, author) = switch call.name {
        case "get_job": ("description", "employer_text", "雇主撰寫")
        case "get_applicant": ("summary", "applicant_text", "求職者撰寫")
        default: ("", "", "")
        }
        guard !field.isEmpty, let text = data?[field] as? String else { return nil }
        let open = "<\(tag)>", close = "</\(tag)>"
        if text.hasPrefix(open) && text.hasSuffix(close) {
            let inner = String(text.dropFirst(open.count).dropLast(close.count))
            return Untrusted(author: author, text: unescape(inner), marked: true)
        }
        return Untrusted(author: author, text: text, marked: false)
    }

    /// harness 用 html.escape 跳脫了 < > &：顯示給人看時還原
    static func unescape(_ text: String) -> String {
        text.replacingOccurrences(of: "&lt;", with: "<").replacingOccurrences(of: "&gt;", with: ">")
            .replacingOccurrences(of: "&amp;", with: "&")
    }

    static func steps(for run: Run) -> [TraceStep] {
        let calls = run.trace?.toolCalls ?? []
        return calls.enumerated().map { i, call in
            // 等確認時，最後一個呼叫還沒有結果
            let waiting = run.needsConfirmation && i == calls.count - 1 && call.output.isEmpty
            return TraceStep(index: i + 1, call: call, waitingForUser: waiting)
        }
    }
}

extension PendingAction {
    var question: String {
        if action == "apply_job" {
            return "確定要應徵 \(title ?? "")（\(company ?? "")，\(jobId ?? "")）嗎？送出後企業會看到你的履歷。"
        }
        let fromText = statusText[from ?? ""] ?? from ?? ""
        let toText = statusText[to ?? ""] ?? to ?? ""
        return "確定要把\(name ?? "")應徵 \(jobId ?? "")（\(jobTitle ?? "")）的狀態，從「\(fromText)」改成「\(toText)」嗎？"
    }

    var approveLabel: String { action == "apply_job" ? "確定應徵" : "確定修改" }
    var shortLabel: String { action == "apply_job" ? "確認應徵" : "確認修改狀態" }
}
