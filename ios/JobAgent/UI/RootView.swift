import SwiftUI

/// iPhone Duo 展開（寬度 ≥ 700pt）：左邊對話、右邊 Trace，兩欄同時看得到。
/// 摺起來或一般 iPhone：對話和 Trace 用分頁切換。
struct RootView: View {
    @Environment(AppModel.self) private var model
    @State private var showSettings = false

    var body: some View {
        GeometryReader { geo in
            Group {
                if geo.size.width >= 700 {
                    WideLayout(showSettings: $showSettings)
                } else {
                    CompactLayout(showSettings: $showSettings)
                }
            }
            .frame(width: geo.size.width, height: geo.size.height)
        }
        .background(Theme.paper)
        .foregroundStyle(Theme.ink)
        .sheet(isPresented: $showSettings) {
            SettingsView()
        }
        .overlay {
            if let error = model.connectionError {
                ConnectionErrorView(message: error)
            }
        }
    }
}

// MARK: - 展開

private struct WideLayout: View {
    @Environment(AppModel.self) private var model
    @Binding var showSettings: Bool

    var body: some View {
        VStack(spacing: 0) {
            HStack(spacing: 24) {
                Text("求職 Agent 驗收")
                    .font(.serif(20, relativeTo: .title3))
                    .lineLimit(1)
                    .fixedSize()
                    .accessibilityAddTraits(.isHeader)
                Spacer(minLength: 16)
                AccountTabs()
                Spacer(minLength: 16)
                ModeMark()
                SettingsButton(showSettings: $showSettings)
            }
            .padding(.horizontal, 24)
            .frame(height: 60)
            Hairline()
            GeometryReader { geo in
                HStack(spacing: 0) {
                    ConversationPane()
                        .frame(width: geo.size.width * 0.4)
                    Hairline(vertical: true)
                    TracePane()
                }
            }
        }
    }
}

/// 角色切換：底線文字分頁
private struct AccountTabs: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        HStack(spacing: 24) {
            ForEach(model.accounts) { account in
                let selected = account.userId == model.selectedAccountId
                Button {
                    model.selectedAccountId = account.userId
                } label: {
                    VStack(spacing: 6) {
                        Text("\(account.name) \(account.roleText)")
                            .font(.serif(15, selected ? .semibold : .regular))
                            .foregroundStyle(selected ? Theme.ink : Theme.secondary)
                        Rectangle().fill(selected ? Theme.ink : .clear).frame(height: 1.5)
                    }
                    .fixedSize()
                    .frame(minHeight: 44)
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .accessibilityIdentifier("account.\(account.userId)")
                .accessibilityAddTraits(selected ? .isSelected : [])
            }
        }
    }
}

// MARK: - 摺起來

private struct CompactLayout: View {
    @Environment(AppModel.self) private var model
    @Binding var showSettings: Bool
    @State private var tab = Tab.conversation

    enum Tab { case conversation, trace }

    var body: some View {
        VStack(spacing: 0) {
            HStack(spacing: 12) {
                AccountMenu()
                Spacer()
                ModeMark()
                SettingsButton(showSettings: $showSettings)
            }
            .padding(.horizontal, 20)
            .padding(.top, 4)
            HStack(spacing: 28) {
                tabButton("對話", .conversation, id: "tab.conversation")
                tabButton("Trace", .trace, id: "tab.trace", count: model.traceRun?.trace?.toolCalls.count)
                Spacer()
            }
            .padding(.horizontal, 20)
            Hairline()
            switch tab {
            case .conversation:
                ConversationPane(compact: true)
            case .trace:
                TracePane(compact: true)
                if model.pendingRun?.account.userId == model.selectedAccountId, let pending = model.pendingRun?.pending {
                    VStack(spacing: 0) {
                        Hairline()
                        Button {
                            tab = .conversation
                        } label: {
                            Text("回到對話\(pending.shortLabel)")
                                .font(.serif(16, .semibold))
                                .frame(maxWidth: .infinity, minHeight: 50)
                                .background(Theme.ink)
                                .foregroundStyle(Theme.surface)
                        }
                        .buttonStyle(.plain)
                        .padding(.horizontal, 20)
                        .padding(.vertical, 12)
                        .accessibilityIdentifier("trace.backToConfirm")
                    }
                }
            }
        }
        .onChange(of: model.selectedAccountId) { tab = .conversation }
    }

    private func tabButton(_ title: String, _ value: Tab, id: String, count: Int? = nil) -> some View {
        let selected = tab == value
        return Button {
            tab = value
        } label: {
            VStack(spacing: 8) {
                HStack(spacing: 6) {
                    Text(title).font(.serif(16, selected ? .semibold : .regular))
                    if let count, count > 0 {
                        Text("\(count)").font(.mono(11, .medium)).foregroundStyle(Theme.secondary)
                    }
                }
                .foregroundStyle(selected ? Theme.ink : Theme.secondary)
                Rectangle().fill(selected ? Theme.ink : .clear).frame(height: 1.5)
            }
            .fixedSize()
            .frame(minHeight: 44)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityIdentifier(id)
        .accessibilityAddTraits(selected ? .isSelected : [])
    }
}

private struct AccountMenu: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        Menu {
            ForEach(model.accounts) { account in
                Button("\(account.name) \(account.roleText)") { model.selectedAccountId = account.userId }
                    .accessibilityIdentifier("account.\(account.userId)")
            }
        } label: {
            HStack(spacing: 8) {
                Text(model.account?.name ?? "—").font(.serif(18, .semibold))
                Text(model.account?.roleText ?? "").font(.serif(14)).foregroundStyle(Theme.secondary)
                Image(systemName: "chevron.down").font(.system(size: 11, weight: .semibold)).foregroundStyle(Theme.secondary)
            }
            .foregroundStyle(Theme.ink)
            .frame(minHeight: 44)
        }
        .accessibilityIdentifier("accountMenu")
    }
}

// MARK: - 共用

/// 右上角的「• 示範模式」；有開 bug 時旁邊標出幾個
private struct ModeMark: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        HStack(spacing: 14) {
            if model.bugsOn > 0 {
                StatusMark(text: "Bug \(model.bugsOn)", dot: Theme.blocked, textColor: Theme.blockedText)
                    .accessibilityIdentifier("bugCount")
            }
            StatusMark(text: model.mode.label, dot: Theme.waiting, textColor: Theme.secondary)
        }
    }
}

private struct SettingsButton: View {
    @Binding var showSettings: Bool

    var body: some View {
        Button {
            showSettings = true
        } label: {
            Image(systemName: "slider.horizontal.3")
                .font(.system(size: 17))
                .foregroundStyle(Theme.ink)
                .frame(width: 44, height: 44)
        }
        .accessibilityLabel("設定")
        .accessibilityIdentifier("settings")
    }
}

private struct ConnectionErrorView: View {
    @Environment(AppModel.self) private var model
    let message: String

    var body: some View {
        @Bindable var model = model
        VStack(alignment: .leading, spacing: 16) {
            Text("連不上伺服器").font(.serif(24, .semibold))
            Text(message).font(.serif(15)).foregroundStyle(Theme.secondary)
            VStack(alignment: .leading, spacing: 6) {
                Text("在 Mac 上啟動：").font(.serif(13)).foregroundStyle(Theme.secondary)
                Text(".venv/bin/uvicorn server.app:app --host 0.0.0.0 --port 8430")
                    .font(.mono(12))
                    .textSelection(.enabled)
            }
            VStack(alignment: .leading, spacing: 6) {
                Text("伺服器位址（實機要用 Mac 的區網或 Tailscale IP）").font(.serif(13)).foregroundStyle(Theme.secondary)
                TextField(AppModel.defaultServer, text: $model.serverText)
                    .font(.mono(14))
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                    .keyboardType(.URL)
                    .padding(.vertical, 10)
                    .overlay(alignment: .bottom) { Hairline() }
                    .onSubmit { Task { await model.connect() } }
            }
            Button {
                Task { await model.connect() }
            } label: {
                Text("重新連線")
                    .font(.serif(15, .semibold))
                    .padding(.horizontal, 20)
                    .frame(minHeight: 44)
                    .background(Theme.ink)
                    .foregroundStyle(Theme.surface)
            }
            .buttonStyle(.plain)
            .accessibilityIdentifier("reconnect")
        }
        .padding(32)
        .frame(maxWidth: 480, alignment: .leading)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(Theme.paper)
    }
}
