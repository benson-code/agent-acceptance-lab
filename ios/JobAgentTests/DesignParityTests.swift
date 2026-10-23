import XCTest
@testable import JobAgent

/// 實作要照設計稿：Theme 裡的顏色都要出現在 Stitch 匯出的 HTML（design/stitch/）裡。
/// 有人在 App 裡「順手」改了一個顏色，這裡會紅，提醒他先改設計稿。
final class DesignParityTests: XCTestCase {
    private func designHTML() throws -> String {
        let names = ["1-duo-jobseeker", "2-duo-employer", "3-folded-trace", "4-settings"]
        return try names.map { name in
            let url = try XCTUnwrap(Bundle(for: Self.self).url(forResource: name, withExtension: "html"), name)
            return try String(contentsOf: url, encoding: .utf8)
        }.joined().uppercased()
    }

    func testThemeColorsComeFromTheDesign() throws {
        let html = try designHTML()
        for hex in Theme.designHex {
            let code = String(format: "#%06X", hex)
            XCTAssertTrue(html.contains(code), "\(code) 不在設計稿裡")
        }
    }

    func testDesignFontsAreBundled() throws {
        let html = try designHTML()
        for (family, file) in [("NEWSREADER", "Newsreader-Light"), ("NOTO+SERIF+TC", "NotoSerifTC-Regular"),
                               ("JETBRAINS+MONO", "JetBrainsMono-Regular")] {
            XCTAssertTrue(html.contains(family), "設計稿沒有用 \(family)")
            XCTAssertNotNil(Bundle.main.url(forResource: file, withExtension: "ttf"), "App 沒有內建 \(file)")
        }
    }
}
