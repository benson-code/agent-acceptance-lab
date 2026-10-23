import SwiftUI

/// 設定：模式、伺服器位址、10 個埋 bug 開關。開關一按就改伺服器上的設定，下一次執行就會用。
struct SettingsView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        @Bindable var model = model
        ScrollView {
            VStack(alignment: .leading, spacing: 0) {
                Button {
                    dismiss()
                } label: {
                    HStack(spacing: 6) {
                        Image(systemName: "chevron.left").font(.system(size: 15, weight: .medium))
                        Text("返回").font(.serif(15))
                    }
                    .foregroundStyle(Theme.secondary)
                    .frame(minHeight: 44)
                }
                .buttonStyle(.plain)
                .accessibilityIdentifier("settings.close")

                Text("設定").font(.serif(34, .semibold, relativeTo: .largeTitle)).padding(.top, 4).padding(.bottom, 28)

                section("模型")
                row {
                    Text("運行方式").font(.serif(16))
                    Spacer()
                    ForEach(Mode.allCases) { mode in
                        let selected = model.mode == mode
                        let available = mode == .demo || model.health?.liveAvailable == true
                        Button {
                            model.mode = mode
                        } label: {
                            VStack(spacing: 4) {
                                Text(mode.label).font(.serif(16, selected ? .semibold : .regular))
                                Rectangle().fill(selected ? Theme.ink : .clear).frame(height: 1.5)
                            }
                            .foregroundStyle(available ? (selected ? Theme.ink : Theme.secondary) : Theme.tertiary)
                            .fixedSize()
                            .frame(minWidth: 44, minHeight: 44)
                        }
                        .buttonStyle(.plain)
                        .disabled(!available)
                        .accessibilityIdentifier("mode.\(mode.rawValue)")
                    }
                }
                footnote(model.health?.liveAvailable == true
                         ? "示範模式由劇本決定要呼叫哪些工具；真模型由 Claude 決定。兩種模式的工具、權限和確認流程都是同一份程式。"
                         : "示範模式由劇本決定要呼叫哪些工具，工具、權限和確認流程都是真的在跑。真模型需要先在伺服器設定 ANTHROPIC_API_KEY。")

                section("伺服器").padding(.top, 28)
                row {
                    TextField(AppModel.defaultServer, text: $model.serverText)
                        .font(.mono(14))
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                        .keyboardType(.URL)
                        .onSubmit { Task { await model.connect() } }
                        .accessibilityIdentifier("settings.server")
                }
                HStack(spacing: 20) {
                    textButton("重新連線") { Task { await model.connect() } }
                    textButton("重設平台資料") { Task { await model.reset() } }
                        .disabled(model.isBusy)
                }
                .padding(.vertical, 6)
                footnote("重設會把應徵紀錄和狀態還原成種子資料，對話也會清空。")

                HStack(alignment: .firstTextBaseline) {
                    section("埋 bug 開關")
                    Text("\(model.bugsOn) / \(model.bugs.count)")
                        .font(.mono(13))
                        .foregroundStyle(model.bugsOn > 0 ? Theme.blockedText : Theme.secondary)
                        .accessibilityIdentifier("settings.bugCount")
                    Spacer()
                    textButton("全部關閉") { Task { await model.clearBugs() } }
                        .disabled(model.bugsOn == 0)
                        .accessibilityIdentifier("settings.clearBugs")
                }
                .padding(.top, 28)
                Hairline()
                ForEach(model.bugs) { bug in
                    BugRow(bug: bug)
                    Hairline()
                }
                footnote("每個開關模擬一種 Agent 服務真的會出的錯。CI 會逐一打開它們，要求指定的測試一定失敗（tools/fault_check.py）。")
                    .padding(.bottom, 40)
            }
            .padding(.horizontal, 28)
            .padding(.top, 12)
            .frame(maxWidth: 640, alignment: .leading)
            .frame(maxWidth: .infinity)
        }
        .background(Theme.paper)
        .foregroundStyle(Theme.ink)
    }

    private func section(_ title: String) -> some View {
        Text(title).font(.serif(13)).foregroundStyle(Theme.secondary).padding(.bottom, 10)
    }

    private func row<Content: View>(@ViewBuilder _ content: () -> Content) -> some View {
        VStack(spacing: 0) {
            Hairline()
            HStack(spacing: 18) { content() }.frame(minHeight: 60)
            Hairline()
        }
    }

    private func footnote(_ text: String) -> some View {
        Text(text).font(.serif(13)).foregroundStyle(Theme.secondary).lineSpacing(4).padding(.top, 12)
            .fixedSize(horizontal: false, vertical: true)
    }

    private func textButton(_ title: String, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Text(title).font(.serif(14)).underline(color: Theme.tertiary).frame(minHeight: 44)
        }
        .buttonStyle(.plain)
    }
}

private struct BugRow: View {
    @Environment(AppModel.self) private var model
    let bug: BugSwitch

    var body: some View {
        Toggle(isOn: Binding(get: { bug.on }, set: { on in Task { await model.setBug(bug.key, on: on) } })) {
            VStack(alignment: .leading, spacing: 3) {
                HStack(spacing: 8) {
                    Text(bug.label).font(.serif(16))
                    if bug.isEmployerSide {
                        Text("企業端")
                            .font(.serif(11))
                            .foregroundStyle(Theme.secondary)
                            .padding(.horizontal, 5)
                            .padding(.vertical, 1)
                            .overlay(Rectangle().stroke(Theme.hairline, lineWidth: 1))
                    }
                }
                Text(bug.key).font(.mono(12)).foregroundStyle(Theme.secondary)
            }
        }
        .tint(Theme.blocked)
        .frame(minHeight: 64)
        .accessibilityIdentifier("bug.\(bug.key)")
    }
}
