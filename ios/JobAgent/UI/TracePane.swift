import SwiftUI
import UIKit

/// Trace：Agent 這次執行的每一步，像一份排版好的紀錄。等確認和擋下的那一步是畫面的焦點。
struct TracePane: View {
    @Environment(AppModel.self) private var model
    var compact = false
    @State private var copied = false

    var body: some View {
        let run = model.traceRun
        let steps = run.map { TraceStep.steps(for: $0) } ?? []
        let blocked = steps.filter { $0.status == .blocked }.count

        VStack(spacing: 0) {
            if !compact {
                header(run: run, blocked: blocked)
                Hairline()
            }
            ScrollView {
                VStack(alignment: .leading, spacing: 0) {
                    if compact {
                        VStack(alignment: .leading, spacing: 6) {
                            Text("Trace").font(.displayItalic(34))
                            if let run { meta(run).font(.mono(12)).foregroundStyle(Theme.secondary) }
                            if blocked > 0 { blockedMark(blocked) }
                        }
                        .padding(.bottom, 28)
                    }
                    if let run, !steps.isEmpty {
                        ForEach(steps) { step in
                            TraceStepView(step: step, scenario: scenario(for: run))
                                .padding(.bottom, 36)
                        }
                        if run.status == "done" {
                            FinalAnswer(run: run)
                        }
                    } else if let run, run.status == "done" {
                        Text("這次沒有呼叫任何工具，Agent 直接回覆。").font(.serif(15)).foregroundStyle(Theme.secondary)
                    } else {
                        EmptyTrace()
                    }
                }
                .padding(.horizontal, compact ? 20 : 40)
                .padding(.vertical, compact ? 24 : 32)
                .frame(maxWidth: .infinity, alignment: .leading)
            }
            if model.mode == .demo && run != nil {
                Text("示範模式：模型的決定照劇本，工具、權限、確認和遮蔽都是真的在跑。")
                    .font(.serif(12))
                    .foregroundStyle(Theme.secondary)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.horizontal, compact ? 20 : 40)
                    .padding(.vertical, 10)
            }
        }
        .background(Theme.paper)
    }

    private func header(run: Run?, blocked: Int) -> some View {
        HStack(spacing: 14) {
            Text("Trace").font(.displayItalic(26)).accessibilityAddTraits(.isHeader)
            if let run {
                Text("/").font(.serif(14)).foregroundStyle(Theme.tertiary)
                meta(run, short: true).font(.mono(12)).foregroundStyle(Theme.secondary)
                    .lineLimit(1)
                    .minimumScaleFactor(0.8)
            }
            Spacer(minLength: 8)
            if blocked > 0 { blockedMark(blocked).fixedSize() }
            if let run, run.trace != nil {
                Button {
                    UIPasteboard.general.string = traceJSON(run)
                    copied = true
                } label: {
                    HStack(spacing: 5) {
                        Image(systemName: copied ? "checkmark" : "doc.on.doc").font(.system(size: 12))
                        Text(copied ? "已複製" : "複製").font(.serif(13))
                    }
                    .foregroundStyle(Theme.secondary)
                    .fixedSize()
                    .frame(minWidth: 44, minHeight: 44)
                }
                .buttonStyle(.plain)
                .accessibilityLabel("複製 Trace 的 JSON")
                .onChange(of: run.id) { copied = false }
            }
        }
        .padding(.horizontal, 40)
        .frame(height: 52)
    }

    private func meta(_ run: Run, short: Bool = false) -> Text {
        let t = run.trace
        let calls = short ? "" : " · \(t?.toolCalls.count ?? 0) 次工具呼叫"
        return Text("\(run.id) · \(t?.turns ?? 0) 回合\(calls) · \(String(format: "%.1f", t?.elapsedS ?? 0)) 秒")
    }

    private func blockedMark(_ count: Int) -> some View {
        StatusMark(text: "擋下 \(count) 次", dot: Theme.blocked, textColor: Theme.blockedText)
            .accessibilityIdentifier("trace.blockedCount")
    }

    private func scenario(for run: Run) -> Scenario? {
        model.accounts.flatMap(\.scenarios).first { $0.id == run.scenarioId }
    }

    private func traceJSON(_ run: Run) -> String {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .withoutEscapingSlashes]
        encoder.keyEncodingStrategy = .convertToSnakeCase
        return (try? encoder.encode(run.trace)).flatMap { String(data: $0, encoding: .utf8) } ?? ""
    }
}

private struct EmptyTrace: View {
    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("還沒有執行").font(.serif(18, .semibold))
            Text("Trace 會列出 Agent 每一次工具呼叫：參數、結果、有沒有問使用者、哪裡被擋下。評分看的是 Agent 做了什麼，不只是它說了什麼。")
                .font(.serif(15))
                .foregroundStyle(Theme.secondary)
                .lineSpacing(5)
                .frame(maxWidth: 520, alignment: .leading)
        }
    }
}

private struct FinalAnswer: View {
    let run: Run

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("回覆").font(.serif(12)).foregroundStyle(Theme.secondary)
            Text(run.trace?.finalText ?? "").font(.serif(14)).foregroundStyle(Theme.ink).lineSpacing(4)
            if let t = run.trace, t.inputTokens + t.outputTokens > 0 {
                Text("tokens 輸入 \(t.inputTokens) / 輸出 \(t.outputTokens)").font(.mono(11)).foregroundStyle(Theme.secondary)
            }
        }
        .padding(.leading, 70)
    }
}

struct TraceStepView: View {
    let step: TraceStep
    let scenario: Scenario?

    private var tone: (dot: Color, text: Color, rule: Color) {
        switch step.status {
        case .done: (Theme.done, Theme.done, Theme.hairline)
        case .waiting, .declined, .lost: (Theme.waiting, Theme.waitingText, step.isFocus ? Theme.waiting : Theme.hairline)
        case .blocked, .error: (Theme.blocked, Theme.blockedText, step.isFocus ? Theme.blocked : Theme.hairline)
        }
    }

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 22) {
            Text(step.numeral)
                .font(.numeral(38))
                .foregroundStyle(step.isFocus ? tone.dot : Theme.tertiary)
                .frame(width: 48, alignment: .leading)
                .accessibilityHidden(true)

            VStack(alignment: .leading, spacing: 14) {
                VStack(spacing: 10) {
                    HStack(alignment: .firstTextBaseline) {
                        Text(step.call.name).font(.mono(16, .medium))
                        Spacer(minLength: 12)
                        StatusMark(text: step.status.word, dot: tone.dot, textColor: tone.text)
                            .accessibilityIdentifier("trace.status.\(step.index)")
                    }
                    Hairline(color: tone.rule)
                }

                ruled(label: "參數", color: Theme.hairline) {
                    Text(step.call.inputText).font(.mono(13)).textSelection(.enabled)
                }

                if let untrusted = step.untrusted {
                    ruled(label: untrusted.marked ? "不可信內容（\(untrusted.author)）" : "沒有標記的外部內容（\(untrusted.author)）",
                          color: untrusted.marked ? Theme.waiting : Theme.blocked,
                          labelColor: untrusted.marked ? Theme.waitingText : Theme.blockedText) {
                        Text(untrusted.text).font(.serif(14)).lineSpacing(4).foregroundStyle(Theme.ink)
                    }
                    .accessibilityIdentifier("trace.untrusted.\(step.index)")
                }

                if step.status == .blocked || step.status == .error {
                    ruled(label: nil, color: Theme.blocked) {
                        Text(step.call.output).font(.mono(13)).foregroundStyle(Theme.blockedText)
                    }
                    if let reason = step.blockedReason {
                        Text(reason).font(.serif(13)).foregroundStyle(Theme.secondary)
                    }
                    if let scenario, !scenario.covers.isEmpty {
                        Text("對應 \(scenario.covers.joined(separator: "、"))")
                            .font(.mono(11))
                            .foregroundStyle(Theme.secondary)
                    }
                } else if let summary = step.summary {
                    HStack(spacing: 6) {
                        if step.status == .waiting {
                            Image(systemName: "lock").font(.system(size: 12)).foregroundStyle(Theme.secondary)
                        }
                        Text(summary).font(.serif(14)).foregroundStyle(Theme.secondary)
                    }
                    .padding(.leading, 16)
                    .accessibilityIdentifier("trace.summary.\(step.index)")
                }

                if step.fullContact {
                    Text("結果含完整聯絡方式").font(.serif(13)).foregroundStyle(Theme.blockedText).padding(.leading, 16)
                }
            }
        }
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("trace.step.\(step.index)")
    }

    /// 左邊一條細線、上面一個小標籤的區塊（參數、別人寫的內容、錯誤訊息）
    private func ruled<Content: View>(label: String?, color: Color, labelColor: Color = Theme.secondary,
                                      @ViewBuilder content: () -> Content) -> some View {
        HStack(alignment: .top, spacing: 15) {
            Rectangle().fill(color).frame(width: color == Theme.hairline ? 1 : 2)
            VStack(alignment: .leading, spacing: 6) {
                if let label { Text(label).font(.serif(12)).foregroundStyle(labelColor) }
                content()
            }
            .padding(.vertical, 2)
        }
        .fixedSize(horizontal: false, vertical: true)
    }
}
