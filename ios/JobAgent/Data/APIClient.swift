import Foundation

enum APIError: LocalizedError, Equatable {
    case unreachable(String)
    case server(Int, String)

    var errorDescription: String? {
        switch self {
        case .unreachable(let url): "連不上伺服器 \(url)"
        case .server(_, let detail): detail
        }
    }
}

/// 呼叫本機的 API 伺服器（server/app.py）。伺服器的錯誤訊息（detail）原樣交給畫面顯示。
struct APIClient {
    var base: URL
    var session: URLSession = .shared

    func health() async throws -> Health { try await get("health") }
    func accounts() async throws -> [Account] { try await get("accounts") }
    func bugs() async throws -> [BugSwitch] { try await get("bugs") }
    func setBugs(_ on: [String]) async throws -> [BugSwitch] { try await send("PUT", "bugs", ["on": on]) }
    func reset() async throws { let _: [String: Bool] = try await send("POST", "reset", [String: String]()) }

    func start(scenario: String) async throws -> Run { try await send("POST", "runs", ["scenario_id": scenario]) }
    func start(userId: String, prompt: String) async throws -> Run {
        try await send("POST", "runs", ["user_id": userId, "prompt": prompt])
    }
    /// wait 秒內執行一結束或需要確認就回來（伺服器端等待），App 不用一直輪詢
    func run(_ id: String, wait: Int = 10) async throws -> Run {
        try await get("runs/\(id)", query: [URLQueryItem(name: "wait", value: String(wait))])
    }
    func confirm(_ id: String, approve: Bool) async throws -> Run {
        try await send("POST", "runs/\(id)/confirm", ["approve": approve])
    }

    private func get<T: Decodable>(_ path: String, query: [URLQueryItem] = []) async throws -> T {
        var components = URLComponents(url: base.appending(path: path), resolvingAgainstBaseURL: false)!
        if !query.isEmpty { components.queryItems = query }
        return try await perform(URLRequest(url: components.url!))
    }

    private func send<T: Decodable, B: Encodable>(_ method: String, _ path: String, _ body: B) async throws -> T {
        var request = URLRequest(url: base.appending(path: path))
        request.httpMethod = method
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSON.encoder.encode(body)
        return try await perform(request)
    }

    private func perform<T: Decodable>(_ request: URLRequest) async throws -> T {
        var request = request
        request.timeoutInterval = 30
        let data: Data, response: URLResponse
        do {
            (data, response) = try await session.data(for: request)
        } catch {
            throw APIError.unreachable(base.absoluteString)
        }
        let code = (response as? HTTPURLResponse)?.statusCode ?? 0
        guard (200..<300).contains(code) else {
            let detail = (try? JSONSerialization.jsonObject(with: data) as? [String: Any])?["detail"]
            throw APIError.server(code, detail as? String ?? "伺服器回應 \(code)")
        }
        return try JSON.decoder.decode(T.self, from: data)
    }
}
