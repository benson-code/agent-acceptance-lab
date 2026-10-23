import SwiftUI

/// 設計稿（design/stitch/，Google Stitch 的「編輯典雅」）的顏色和字體。
/// 每種狀態色只代表一件事：綠是完成、琥珀是等待、朱紅只給「擋下」。
/// 小字用的是加深過的版本，對比才到 4.5:1；圓點和細線用設計稿的原色。
enum Theme {
    static let paper = Color(hex: 0xFAF8F5)
    static let surface = Color(hex: 0xFFFFFF)
    static let ink = Color(hex: 0x1C1A18)
    static let secondary = Color(hex: 0x6E6B65)
    static let tertiary = Color(hex: 0x9B978F)          // 只用在大字（大號序號）和裝飾
    static let hairline = Color(hex: 0xE8E4DC)
    static let tint = Color(hex: 0xF3EFEA)               // 使用者訊息、選取中的列

    static let done = Color(hex: 0x3A7D44)
    static let waiting = Color(hex: 0xB7791F)
    static let waitingText = Color(hex: 0x8A5A12)
    static let waitingWash = Color(hex: 0xFBF5EA)
    static let blocked = Color(hex: 0xC86D51)
    static let blockedText = Color(hex: 0x9E4D38)
    static let blockedWash = Color(hex: 0xFAF1EE)

    /// 設計稿裡實際出現的顏色（JobAgentTests 會到 Stitch 匯出的 HTML 裡找，確認沒有偏離設計）
    static let designHex: [UInt32] = [0xFAF8F5, 0x1C1A18, 0x6E6B65, 0x9B978F, 0xE8E4DC,
                                      0x3A7D44, 0xB7791F, 0xC86D51, 0x9E4D38]
}

extension Color {
    init(hex: UInt32) {
        self.init(red: Double((hex >> 16) & 0xFF) / 255, green: Double((hex >> 8) & 0xFF) / 255,
                  blue: Double(hex & 0xFF) / 255)
    }
}

/// 字體：內文和中文用 Noto Serif TC，大號序號和「Trace」用 Newsreader，工具名稱和參數用 JetBrains Mono。
/// 都跟著動態字級縮放（relativeTo）。中文字型是子集（常用字），罕見字會退回系統字型。
extension Font {
    static func serif(_ size: CGFloat, _ weight: Font.Weight = .regular, relativeTo style: TextStyle = .body) -> Font {
        .custom(weight == .regular ? "NotoSerifTC-Regular" : "NotoSerifTC-SemiBold", size: size, relativeTo: style)
    }

    static func numeral(_ size: CGFloat) -> Font {
        .custom("Newsreader-Light", size: size, relativeTo: .largeTitle)
    }

    static func displayItalic(_ size: CGFloat) -> Font {
        .custom("Newsreader-Italic", size: size, relativeTo: .title)
    }

    static func mono(_ size: CGFloat, _ weight: Font.Weight = .regular) -> Font {
        .custom(weight == .regular ? "JetBrainsMono-Regular" : "JetBrainsMono-Medium", size: size, relativeTo: .callout)
    }
}

/// 一條細線（水平或垂直）
struct Hairline: View {
    var vertical = false
    var color = Theme.hairline

    var body: some View {
        Rectangle().fill(color).frame(width: vertical ? 1 : nil, height: vertical ? nil : 1)
    }
}

/// 小圓點 + 文字的狀態標示（設計稿不用膠囊標籤）
struct StatusMark: View {
    let text: String
    let dot: Color
    let textColor: Color

    var body: some View {
        HStack(spacing: 6) {
            Circle().fill(dot).frame(width: 6, height: 6)
            Text(text).font(.serif(13)).foregroundStyle(textColor).lineLimit(1)
        }
        .fixedSize()
        .accessibilityElement(children: .combine)       // 讀成一個元素：「已擋下」，UI 測試也用它
    }
}
