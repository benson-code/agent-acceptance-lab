import SwiftUI

/// 對話：像真的聊天一樣從下往上長。要確認的事固定在情境列上方，不會被捲走。
struct ConversationPane: View {
    @Environment(AppModel.self) private var model
    var compact = false

    var body: some View {
        VStack(spacing: 0) {
            HStack {
                StatusMark(text: "對話", dot: model.isBusy ? Theme.waiting : Theme.done, textColor: Theme.ink)
                Spacer()
                Button {
                    Task { await model.reset() }
                } label: {
                    Image(systemName: "arrow.counterclockwise")
                        .font(.system(size: 15))
                        .foregroundStyle(model.isBusy ? Theme.tertiary : Theme.secondary)
                        .frame(width: 44, height: 44)
                }
                .disabled(model.isBusy)
                .accessibilityLabel("重設平台資料")
                .accessibilityIdentifier("reset")
            }
            .padding(.leading, 24)
            .padding(.trailing, 12)
            .frame(height: 52)
            Hairline()

            ScrollView {
                LazyVStack(alignment: .leading, spacing: 28) {
                    if model.conversation.isEmpty {
                        EmptyConversation()
                    }
                    ForEach(model.conversation) { exchange in
                        ExchangeView(exchange: exchange)
                    }
                }
                .padding(.horizontal, 24)
                .padding(.vertical, 28)
            }
            .defaultScrollAnchor(.bottom)

            if let notice = model.notice {
                Text(notice)
                    .font(.serif(13))
                    .foregroundStyle(Theme.blockedText)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.horizontal, 24)
                    .padding(.bottom, 8)
                    .accessibilityIdentifier("notice")
            }
            if let run = model.pendingRun, let pending = run.pending {
                if run.account.userId == model.selectedAccountId {
                    ConfirmationBlock(pending: pending)
                } else {
                    OtherAccountWaiting(name: run.account.name, userId: run.account.userId)
                }
            }
            Hairline()
            if model.mode == .live {
                PromptField()
            } else {
                ScenarioBar()
            }
        }
        // 展開時兩欄用底色區分；摺起來整頁是紙色。底色延伸到橫向時的安全區域（瀏海那一側）
        .background((compact ? Theme.paper : Theme.surface).ignoresSafeArea(edges: [.horizontal, .bottom]))
    }
}

private struct EmptyConversation: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text(model.account.map { "\($0.name)的\($0.isEmployer ? "招募" : "求職")助理" } ?? "")
                .font(.serif(22, .semibold))
            Text(model.mode == .demo
                 ? "從下面選一個示範情境。模型的決定照劇本，工具、權限和確認都是真的在跑；到設定打開 bug 開關，同一個情境的結果就會變。"
                 : "直接輸入要 Agent 做的事。每一則訊息各自獨立，Agent 不記得上一則。")
                .font(.serif(15))
                .foregroundStyle(Theme.secondary)
                .lineSpacing(5)
        }
        .padding(.top, 8)
    }
}

private struct ExchangeView: View {
    @Environment(AppModel.self) private var model
    let exchange: Exchange

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text(exchange.prompt)
                .font(.serif(16))
                .lineSpacing(4)
                .frame(maxWidth: .infinity, alignment: .trailing)
                .multilineTextAlignment(.trailing)
                .accessibilityIdentifier("prompt")

            reply
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(.leading, model.isSelected(exchange) && model.conversation.count > 1 ? 12 : 0)
                .overlay(alignment: .leading) {
                    if model.isSelected(exchange) && model.conversation.count > 1 {
                        Hairline(vertical: true, color: Theme.ink)
                    }
                }
                .contentShape(Rectangle())
                .onTapGesture { model.select(exchange) }
        }
    }

    @ViewBuilder private var reply: some View {
        if let failure = exchange.failure {
            Text(failure).font(.serif(15)).foregroundStyle(Theme.blockedText)
        } else if let run = exchange.run, run.status == "done", let text = run.trace?.finalText {
            Text(text)
                .font(.serif(16))
                .lineSpacing(6)
                .textSelection(.enabled)
                .accessibilityIdentifier("reply")
        } else if let run = exchange.run, run.status == "error" {
            Text("執行失敗：\(run.error ?? "")").font(.serif(15)).foregroundStyle(Theme.blockedText)
        } else if exchange.run?.needsConfirmation == true {
            Text("等你確認之後繼續。").font(.serif(15)).italic().foregroundStyle(Theme.secondary)
        } else {
            HStack(spacing: 8) {
                ProgressView().controlSize(.small)
                Text("Agent 執行中").font(.serif(15)).foregroundStyle(Theme.secondary)
            }
        }
    }
}

/// Agent 要應徵或改狀態：使用者按「確定」才會送出（harness 的確認關卡）
private struct ConfirmationBlock: View {
    @Environment(AppModel.self) private var model
    let pending: PendingAction
    @State private var sending = false

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            Hairline()
            HStack(alignment: .firstTextBaseline, spacing: 12) {
                Image(systemName: "exclamationmark.circle")
                    .font(.system(size: 15))
                    .foregroundStyle(Theme.waiting)
                Text(pending.question)
                    .font(.serif(16))
                    .lineSpacing(5)
                    .fixedSize(horizontal: false, vertical: true)
                    .accessibilityIdentifier("confirm.question")
            }
            HStack(spacing: 8) {
                Spacer()
                Button {
                    answer(false)
                } label: {
                    Text("取消").font(.serif(16)).foregroundStyle(Theme.secondary)
                        .padding(.horizontal, 18).frame(minHeight: 44)
                }
                .buttonStyle(.plain)
                .accessibilityIdentifier("confirm.decline")
                Button {
                    answer(true)
                } label: {
                    Text(pending.approveLabel).font(.serif(16, .semibold)).foregroundStyle(Theme.surface)
                        .padding(.horizontal, 22).frame(minHeight: 44)
                        .background(Theme.ink)
                }
                .buttonStyle(.plain)
                .accessibilityIdentifier("confirm.approve")
            }
            .disabled(sending)
        }
        .padding(.horizontal, 24)
        .padding(.bottom, 18)
        .background(Theme.paper)
    }

    private func answer(_ approve: Bool) {
        sending = true
        Task {
            await model.answer(approve)
            sending = false
        }
    }
}

private struct OtherAccountWaiting: View {
    @Environment(AppModel.self) private var model
    let name: String
    let userId: String

    var body: some View {
        Button {
            model.selectedAccountId = userId
        } label: {
            HStack {
                StatusMark(text: "\(name)有一件事在等確認", dot: Theme.waiting, textColor: Theme.waitingText)
                Spacer()
                Text("前往").font(.serif(14, .semibold))
            }
            .padding(.horizontal, 24)
            .frame(minHeight: 48)
            .background(Theme.waitingWash)
        }
        .buttonStyle(.plain)
    }
}

/// 示範情境：底線文字，選了就照劇本跑一次
private struct ScenarioBar: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("示範情境").font(.serif(13)).foregroundStyle(Theme.secondary)
            FlowLayout(spacing: 20, lineSpacing: 6) {
                ForEach(model.account?.scenarios ?? []) { scenario in
                    Button {
                        Task { await model.run(scenario) }
                    } label: {
                        Text(scenario.label)
                            .font(.serif(15))
                            .foregroundStyle(model.isBusy ? Theme.tertiary : Theme.ink)
                            .underline(color: Theme.tertiary)
                            .frame(minHeight: 36)
                    }
                    .buttonStyle(.plain)
                    .disabled(model.isBusy)
                    .accessibilityIdentifier("scenario.\(scenario.id)")
                }
            }
        }
        .padding(.horizontal, 24)
        .padding(.top, 14)
        .padding(.bottom, 16)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Theme.paper)
    }
}

/// 真模型模式：自由輸入
private struct PromptField: View {
    @Environment(AppModel.self) private var model
    @State private var text = ""

    var body: some View {
        HStack(spacing: 12) {
            TextField("輸入要 Agent 做的事", text: $text, axis: .vertical)
                .font(.serif(16))
                .lineLimit(1...4)
                .submitLabel(.send)
                .onSubmit(send)
                .accessibilityIdentifier("prompt.field")
            Button(action: send) {
                Image(systemName: "arrow.up")
                    .font(.system(size: 15, weight: .semibold))
                    .foregroundStyle(Theme.surface)
                    .frame(width: 36, height: 36)
                    .background(text.isEmpty || model.isBusy ? Theme.tertiary : Theme.ink)
            }
            .disabled(text.isEmpty || model.isBusy)
            .accessibilityLabel("送出")
            .frame(minWidth: 44, minHeight: 44)
        }
        .padding(.horizontal, 24)
        .padding(.vertical, 12)
        .background(Theme.paper)
    }

    private func send() {
        let prompt = text
        text = ""
        Task { await model.send(prompt) }
    }
}

/// 一行放不下就換行的排版（情境列用）
struct FlowLayout: Layout {
    var spacing: CGFloat = 16
    var lineSpacing: CGFloat = 8

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        let rows = arrange(width: proposal.width ?? .infinity, subviews: subviews)
        let height = rows.map(\.height).reduce(0, +) + lineSpacing * CGFloat(max(rows.count - 1, 0))
        let width = rows.map(\.width).max() ?? 0
        return CGSize(width: proposal.width ?? width, height: height)
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        var y = bounds.minY
        for row in arrange(width: bounds.width, subviews: subviews) {
            var x = bounds.minX
            for (index, size) in row.items {
                subviews[index].place(at: CGPoint(x: x, y: y), proposal: ProposedViewSize(size))
                x += size.width + spacing
            }
            y += row.height + lineSpacing
        }
    }

    private struct Row {
        var items: [(Int, CGSize)] = []
        var width: CGFloat = 0
        var height: CGFloat = 0
    }

    private func arrange(width: CGFloat, subviews: Subviews) -> [Row] {
        var rows = [Row()]
        for (index, subview) in subviews.enumerated() {
            let size = subview.sizeThatFits(.unspecified)
            if !rows[rows.count - 1].items.isEmpty && rows[rows.count - 1].width + spacing + size.width > width {
                rows.append(Row())
            }
            var row = rows.removeLast()
            row.width += (row.items.isEmpty ? 0 : spacing) + size.width
            row.height = max(row.height, size.height)
            row.items.append((index, size))
            rows.append(row)
        }
        return rows
    }
}
