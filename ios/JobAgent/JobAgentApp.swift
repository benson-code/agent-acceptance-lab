import SwiftUI

@main
struct JobAgentApp: App {
    @State private var model = AppModel()

    var body: some Scene {
        WindowGroup {
            RootView()
                .environment(model)
                // UI 測試用 -resetOnLaunch YES：每次從種子資料、全部開關關閉開始
                .task { await model.connect(resetFirst: UserDefaults.standard.bool(forKey: "resetOnLaunch")) }
        }
    }
}
