import Foundation

struct UpgradePaths {
    let config: URL
    let testRoot: URL?
    let support: URL
    let log: URL
    let legacyRoot: URL
    var agentLabel: String {
        "com.stefanalmare.homebrew-intel-bottle-pool" + (testRoot == nil ? "" : ".test")
    }

    init(home: URL = FileManager.default.homeDirectoryForCurrentUser,
         environment: [String: String] = ProcessInfo.processInfo.environment,
         preferred: String = Bundle.main.object(forInfoDictionaryKey: "PoolUpgradePreferredProfile") as? String ?? "standard") {
        let standard = home.appendingPathComponent(".config/intel-bottle-pool/config.json")
        let oldTest = home.appendingPathComponent("Library/Application Support/Homebrew Pool 0.3.6 Test")
        let testConfig = oldTest.appendingPathComponent("config/intel-bottle-pool/config.json")
        func nonempty(_ key: String) -> String? {
            guard let value = environment[key], !value.isEmpty else { return nil }
            return value
        }
        let appOverride = nonempty("HOMEBREW_POOL_APP_ROOT").map { URL(fileURLWithPath: $0) }
        let explicitTest = nonempty("HOMEBREW_POOL_TEST_ROOT") ?? nonempty("POOL_FIXTURE_ROOT")
        if let root = appOverride?.appendingPathComponent("global") {
            testRoot = root
            config = root.appendingPathComponent("config/intel-bottle-pool/config.json")
        } else if let value = explicitTest {
            let root = URL(fileURLWithPath: value)
            testRoot = root
            config = root.appendingPathComponent("config/intel-bottle-pool/config.json")
        } else if let xdg = nonempty("XDG_CONFIG_HOME") {
            testRoot = nil
            config = URL(fileURLWithPath: xdg).appendingPathComponent("intel-bottle-pool/config.json")
        } else if FileManager.default.fileExists(atPath: testConfig.path) &&
                    (preferred == "test" || !FileManager.default.fileExists(atPath: standard.path)) {
            testRoot = oldTest
            config = testConfig
        } else {
            testRoot = nil
            config = standard
        }
        support = testRoot ?? home.appendingPathComponent("Library/Application Support/Homebrew Pool")
        log = testRoot?.appendingPathComponent("logs/agent.log") ?? home.appendingPathComponent("Library/Logs/HomebrewIntelBottlePool/agent.log")
        legacyRoot = appOverride ?? home.appendingPathComponent("Library/Application Support/Homebrew Pool Core2 Legacy")
    }
}
