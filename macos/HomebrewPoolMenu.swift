import AppKit
import Darwin
import Foundation

private let agentLabel = "com.stefanalmare.homebrew-intel-bottle-pool"

private struct PoolStatus: Decodable {
    let connected: Bool
    let spool_entries: Int
    let state: String
}

final class AppDelegate: NSObject, NSApplicationDelegate, NSMenuDelegate {
    private var statusItem: NSStatusItem!
    private let menu = NSMenu()
    private let statusLine = NSMenuItem(title: "Status: Starting…", action: nil, keyEquivalent: "")
    private let syncItem = NSMenuItem(title: "Sync now", action: #selector(syncNow), keyEquivalent: "s")
    private let upgradeItem = NSMenuItem(title: "Update & Upgrade", action: #selector(upgradeViaPool), keyEquivalent: "u")
    private let installItem = NSMenuItem(title: "Install…", action: #selector(openInstall), keyEquivalent: "i")
    private let settingsItem = NSMenuItem(title: "Settings…", action: #selector(openSettings), keyEquivalent: ",")
    private let loginItem = NSMenuItem(title: "Start at Login", action: #selector(toggleLogin), keyEquivalent: "")
    private var timer: Timer?
    private var activeProcess: Process?
    private var activity: String?
    private var statusProcess: Process?
    private var settingsProcess: Process?
    private var setupWindow: NSWindow?
    private var installWindow: NSWindow?
    private let serverField = NSTextField()
    private let tokenField = NSSecureTextField()
    private let tokenFileField = NSTextField()
    private let caField = NSTextField()
    private let httpCheckbox = NSButton(checkboxWithTitle: "Allow HTTP on a trusted private network", target: nil, action: nil)
    private let connectionLabel = NSTextField(wrappingLabelWithString: "")
    private let testButton = NSButton(title: "Test Connection", target: nil, action: nil)
    private let saveButton = NSButton(title: "Save & Finish", target: nil, action: nil)
    private let packageField = NSTextField()
    private let typePicker = NSPopUpButton()
    private let mutableCheckbox = NSButton(checkboxWithTitle: "Allow upstream-only casks without a fixed checksum", target: nil, action: nil)
    private let logLock = NSLock()
    private var uiSmokeDirectory: String? {
        let args = CommandLine.arguments
        guard let index = args.firstIndex(of: "--ui-smoke"), index + 1 < args.count else { return nil }
        return args[index + 1]
    }

    private var configURL: URL {
        if let xdg = ProcessInfo.processInfo.environment["XDG_CONFIG_HOME"], !xdg.isEmpty {
            return URL(fileURLWithPath: xdg).appendingPathComponent("intel-bottle-pool/config.json")
        }
        return FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent(".config/intel-bottle-pool/config.json")
    }

    private var logURL: URL {
        FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Logs/HomebrewIntelBottlePool/agent.log")
    }

    private var launchAgentURL: URL {
        FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/LaunchAgents/\(agentLabel).plist")
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.accessory)
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        statusItem.button?.imagePosition = .imageOnly
        statusItem.button?.toolTip = "Homebrew Intel Bottle Pool"
        buildMenu()
        if let directory = uiSmokeDirectory {
            NSApp.appearance = NSAppearance(named: .aqua)
            DispatchQueue.main.async { self.captureUITest(directory) }
            return
        }
        setVisual(symbol: "hourglass", title: "Checking…")
        refreshStatus()
        timer = Timer.scheduledTimer(withTimeInterval: 60, repeats: true) { [weak self] _ in
            self?.refreshStatus()
        }
        if !FileManager.default.fileExists(atPath: configURL.path) {
            DispatchQueue.main.async { self.openSettings() }
        }
    }

    private func buildMenu() {
        menu.delegate = self
        statusLine.isEnabled = false
        menu.addItem(statusLine)
        menu.addItem(.separator())
        syncItem.target = self
        upgradeItem.target = self
        menu.addItem(upgradeItem)
        installItem.target = self
        menu.addItem(installItem)
        menu.addItem(syncItem)
        menu.addItem(.separator())

        settingsItem.target = self
        menu.addItem(settingsItem)
        let openLogs = NSMenuItem(title: "Open logs", action: #selector(openLogs), keyEquivalent: "l")
        openLogs.target = self
        menu.addItem(openLogs)
        loginItem.target = self
        menu.addItem(loginItem)
        menu.addItem(.separator())
        let quit = NSMenuItem(title: "Quit", action: #selector(quitApp), keyEquivalent: "q")
        quit.target = self
        menu.addItem(quit)
        statusItem.menu = menu
    }

    func menuWillOpen(_ menu: NSMenu) {
        loginItem.state = FileManager.default.fileExists(atPath: launchAgentURL.path) ? .on : .off
        refreshStatus()
    }

    private func setVisual(symbol: String, title: String) {
        let image = NSImage(systemSymbolName: symbol, accessibilityDescription: title)
        image?.isTemplate = true
        statusItem.button?.image = image
        statusItem.button?.toolTip = "Homebrew Pool — \(title)"
        statusLine.title = "Status: \(title)"
    }

    private func bundledEntry() -> URL? {
        Bundle.main.resourceURL?.appendingPathComponent("client/entry.py")
    }

    private func configuredPython() -> String? {
        if let value = ProcessInfo.processInfo.environment["POOL_PYTHON"], isExecutable(value) { return value }
        if let data = try? Data(contentsOf: configURL),
           let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
           let value = object["python"] as? String, isExecutable(value) { return value }
        for candidate in ["/usr/local/bin/python3", "/opt/homebrew/bin/python3", "/Library/Frameworks/Python.framework/Versions/Current/bin/python3", "/usr/bin/python3"] {
            if isExecutable(candidate) { return candidate }
        }
        return nil
    }

    private func isExecutable(_ path: String) -> Bool {
        FileManager.default.isExecutableFile(atPath: (path as NSString).expandingTildeInPath)
    }

    private func clientArguments(_ command: [String]) -> (String, [String])? {
        guard let python = configuredPython(), let entry = bundledEntry() else { return nil }
        return (python, ["-B", entry.path, "--config", configURL.path] + command)
    }

    private func appendLog(_ text: String) {
        logLock.lock()
        defer { logLock.unlock() }
        let directory = logURL.deletingLastPathComponent()
        try? FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        if !FileManager.default.fileExists(atPath: logURL.path) {
            _ = FileManager.default.createFile(atPath: logURL.path, contents: nil)
        }
        guard let data = text.data(using: .utf8), let handle = try? FileHandle(forWritingTo: logURL) else { return }
        defer { try? handle.close() }
        do {
            try handle.seekToEnd()
            try handle.write(contentsOf: data)
        } catch { }
    }

    private func runStatus() {
        guard activeProcess == nil, statusProcess == nil, settingsProcess == nil else { return }
        guard FileManager.default.fileExists(atPath: configURL.path) else {
            setVisual(symbol: "exclamationmark.triangle.fill", title: "Error — not configured")
            return
        }
        guard let (executable, arguments) = clientArguments(["status", "--json"]) else {
            setVisual(symbol: "exclamationmark.triangle.fill", title: "Error — Python 3.9+ not found")
            return
        }
        let process = Process()
        let pipe = Pipe()
        process.executableURL = URL(fileURLWithPath: executable)
        process.arguments = arguments
        process.standardOutput = pipe
        process.standardError = pipe
        statusProcess = process
        process.terminationHandler = { [weak self] process in
            let data = pipe.fileHandleForReading.readDataToEndOfFile()
            DispatchQueue.main.async {
                guard let self = self else { return }
                self.statusProcess = nil
                guard self.activeProcess == nil, self.settingsProcess == nil else { return }
                if process.terminationStatus == 0,
                   let decoded = try? JSONDecoder().decode(PoolStatus.self, from: data) {
                    if decoded.connected && decoded.spool_entries == 0 {
                        self.setVisual(symbol: "checkmark.circle.fill", title: "Healthy/Connected")
                    } else {
                        let detail = decoded.spool_entries == 1 ? "1 item queued" : "\(decoded.spool_entries) items queued"
                        self.setVisual(symbol: "arrow.triangle.2.circlepath.circle.fill", title: "Offline/Spooling — \(detail)")
                    }
                } else {
                    let message = String(data: data, encoding: .utf8)?.trimmingCharacters(in: .whitespacesAndNewlines) ?? "Unknown error"
                    self.appendLog("\n[status] \(message)\n")
                    self.setVisual(symbol: "exclamationmark.triangle.fill", title: "Error")
                }
            }
        }
        do { try process.run() }
        catch {
            statusProcess = nil
            appendLog("\n[status] \(error)\n")
            setVisual(symbol: "exclamationmark.triangle.fill", title: "Error")
        }
    }

    private func runInteractive(command: [String], activity title: String) {
        guard activeProcess == nil, settingsProcess == nil else { return }
        guard FileManager.default.fileExists(atPath: configURL.path) else { openSettings(); return }
        guard let (executable, arguments) = clientArguments(command) else {
            showAlert(title: "Cannot run Homebrew Pool", message: "Python 3.9 or newer was not found. Set the python path in the existing config if it is installed elsewhere.")
            return
        }
        let process = Process()
        let pipe = Pipe()
        process.executableURL = URL(fileURLWithPath: executable)
        process.arguments = arguments
        process.standardOutput = pipe
        process.standardError = pipe
        activeProcess = process
        activity = title
        syncItem.isEnabled = false
        upgradeItem.isEnabled = false
        installItem.isEnabled = false
        settingsItem.isEnabled = false
        setVisual(symbol: "gearshape.2.fill", title: title)
        appendLog("\n[\(ISO8601DateFormatter().string(from: Date()))] \(command.joined(separator: " "))\n")
        pipe.fileHandleForReading.readabilityHandler = { [weak self] handle in
            let data = handle.availableData
            if !data.isEmpty, let text = String(data: data, encoding: .utf8) { self?.appendLog(text) }
        }
        process.terminationHandler = { [weak self] process in
            pipe.fileHandleForReading.readabilityHandler = nil
            let remaining = pipe.fileHandleForReading.readDataToEndOfFile()
            if let tail = String(data: remaining, encoding: .utf8), !tail.isEmpty { self?.appendLog(tail) }
            DispatchQueue.main.async {
                guard let self = self else { return }
                self.activeProcess = nil
                self.activity = nil
                self.syncItem.isEnabled = true
                self.upgradeItem.isEnabled = true
                self.installItem.isEnabled = true
                self.settingsItem.isEnabled = true
                if process.terminationStatus == 2 && command.first == "sync" {
                    self.refreshStatus()
                } else if process.terminationStatus != 0 {
                    self.setVisual(symbol: "exclamationmark.triangle.fill", title: "Error — see logs")
                    self.showAlert(title: "Homebrew Pool command failed", message: "The command ended with status \(process.terminationStatus). Open logs for details.")
                } else {
                    self.refreshStatus()
                    self.showAlert(title: "Homebrew Pool finished", message: "The operation completed. Open logs to see downloads, builds, and publication results.")
                }
            }
        }
        do { try process.run() }
        catch {
            activeProcess = nil
            activity = nil
            syncItem.isEnabled = true
            upgradeItem.isEnabled = true
            installItem.isEnabled = true
            settingsItem.isEnabled = true
            appendLog("\(error)\n")
            setVisual(symbol: "exclamationmark.triangle.fill", title: "Error")
        }
    }

    @objc private func refreshStatus() {
        if let activity = activity {
            setVisual(symbol: "gearshape.2.fill", title: activity)
        } else {
            runStatus()
        }
    }

    @objc private func syncNow() {
        runInteractive(command: ["sync"], activity: "Busy/Syncing")
    }

    @objc private func upgradeViaPool() {
        let alert = NSAlert()
        alert.messageText = "Update & Upgrade via Homebrew Pool?"
        alert.informativeText = "This explicitly runs brew update and the pool-aware upgrade. It may download, build, install, and publish compatible artifacts. It is never run automatically."
        alert.alertStyle = .informational
        alert.addButton(withTitle: "Update & Upgrade")
        alert.addButton(withTitle: "Cancel")
        NSApp.activate(ignoringOtherApps: true)
        if alert.runModal() == .alertFirstButtonReturn {
            runInteractive(command: ["upgrade"], activity: "Busy/Building or Syncing")
        }
    }

    private func makeWindow(title: String, stack: NSStackView, height: CGFloat) -> NSWindow {
        let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 600, height: height),
                              styleMask: [.titled, .closable], backing: .buffered, defer: false)
        window.title = title
        window.isReleasedWhenClosed = false
        window.contentView?.wantsLayer = true
        window.effectiveAppearance.performAsCurrentDrawingAppearance {
            window.contentView?.layer?.backgroundColor = NSColor.windowBackgroundColor.cgColor
        }
        stack.orientation = .vertical
        stack.alignment = .leading
        stack.spacing = 14
        stack.translatesAutoresizingMaskIntoConstraints = false
        window.contentView?.addSubview(stack)
        NSLayoutConstraint.activate([
            stack.leadingAnchor.constraint(equalTo: window.contentView!.leadingAnchor, constant: 28),
            stack.trailingAnchor.constraint(equalTo: window.contentView!.trailingAnchor, constant: -28),
            stack.topAnchor.constraint(equalTo: window.contentView!.topAnchor, constant: 28)
        ])
        window.center()
        return window
    }

    private func row(_ label: String, field: NSTextField, browse: Selector? = nil) -> NSStackView {
        let title = NSTextField(labelWithString: label)
        title.widthAnchor.constraint(equalToConstant: 105).isActive = true
        let stack = NSStackView(views: [title, field])
        stack.orientation = .horizontal
        stack.spacing = 10
        field.widthAnchor.constraint(equalToConstant: browse == nil ? 425 : 335).isActive = true
        if let action = browse {
            let button = NSButton(title: "Choose…", target: self, action: action)
            stack.addArrangedSubview(button)
        }
        return stack
    }

    @objc private func openInstall() {
        guard activeProcess == nil, settingsProcess == nil else { return }
        guard uiSmokeDirectory != nil || FileManager.default.fileExists(atPath: configURL.path) else { openSettings(); return }
        if installWindow == nil {
            let heading = NSTextField(labelWithString: "Install on this Mac and share reusable artifacts")
            heading.font = .boldSystemFont(ofSize: 16)
            packageField.placeholderString = "Package name, e.g. wget or firefox"
            typePicker.addItems(withTitles: ["Auto", "Formula", "Cask"])
            let explanation = NSTextField(wrappingLabelWithString: "Pool first, then verified upstream download or a local build. Auto asks you to choose a type if the name is ambiguous. Mutable casks are never published.")
            explanation.widthAnchor.constraint(equalToConstant: 540).isActive = true
            let button = NSButton(title: "Install", target: self, action: #selector(installPackage))
            button.bezelStyle = .rounded
            button.keyEquivalent = "\r"
            let typeLabel = NSTextField(labelWithString: "Type")
            typeLabel.widthAnchor.constraint(equalToConstant: 105).isActive = true
            let typeRow = NSStackView(views: [typeLabel, typePicker])
            typeRow.spacing = 10
            let stack = NSStackView(views: [heading, row("Package", field: packageField), typeRow,
                                           explanation, mutableCheckbox, button])
            installWindow = makeWindow(title: "Install via Homebrew Pool", stack: stack, height: 290)
        }
        NSApp.activate(ignoringOtherApps: true)
        installWindow?.makeKeyAndOrderFront(nil)
    }

    @objc private func installPackage() {
        let name = packageField.stringValue.trimmingCharacters(in: .whitespacesAndNewlines)
        let pattern = "^[A-Za-z0-9][A-Za-z0-9_+@.-]*(/[A-Za-z0-9][A-Za-z0-9_+@.-]*){0,2}$"
        guard name.range(of: pattern, options: .regularExpression) != nil else {
            showAlert(title: "Enter one package name", message: "Use a Homebrew name such as wget, firefox, or user/tap/package.")
            return
        }
        var command = ["install", "--type", typePicker.titleOfSelectedItem!.lowercased(), name]
        if mutableCheckbox.state == .on { command.append("--allow-upstream-only-cask") }
        installWindow?.orderOut(nil)
        runInteractive(command: command, activity: "Busy/Installing \(name)")
    }

    @objc private func openSettings() {
        guard activeProcess == nil, settingsProcess == nil else { return }
        if setupWindow == nil {
            let heading = NSTextField(labelWithString: "Connect this Mac to your Homebrew Pool")
            heading.font = .boldSystemFont(ofSize: 18)
            let description = NSTextField(wrappingLabelWithString: "Enter your server address and token. Test Connection verifies authentication and the Pool API. These settings can be changed here at any time.")
            description.widthAnchor.constraint(equalToConstant: 540).isActive = true
            serverField.placeholderString = "https://your-pool-server:8765"
            tokenField.placeholderString = "Paste a token, or leave blank to use the selected file"
            tokenFileField.placeholderString = "Optional token file"
            caField.placeholderString = "Optional private CA certificate (.pem)"
            testButton.target = self
            testButton.action = #selector(testConnection)
            saveButton.target = self
            saveButton.action = #selector(saveSettings)
            testButton.bezelStyle = .rounded
            saveButton.bezelStyle = .rounded
            connectionLabel.widthAnchor.constraint(equalToConstant: 540).isActive = true
            let prerequisites = NSTextField(wrappingLabelWithString: "Requires an Intel Mac, Homebrew and Python 3.9+. Command Line Tools are needed for local builds. Start at Login is available in the menu.")
            prerequisites.widthAnchor.constraint(equalToConstant: 540).isActive = true
            let stack = NSStackView(views: [heading, description, row("Server URL", field: serverField),
                row("Token", field: tokenField), row("Token file", field: tokenFileField, browse: #selector(chooseToken)),
                row("CA certificate", field: caField, browse: #selector(chooseCA)), httpCheckbox,
                NSStackView(views: [testButton, saveButton]), connectionLabel, prerequisites])
            setupWindow = makeWindow(title: "Homebrew Pool — Setup & Settings", stack: stack, height: 445)
        }
        if let data = try? Data(contentsOf: configURL),
           let config = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
            serverField.stringValue = config["url"] as? String ?? ""
            tokenFileField.stringValue = config["token_file"] as? String ?? ""
            caField.stringValue = config["ca_file"] as? String ?? ""
            httpCheckbox.state = config["allow_insecure_http"] as? Bool == true ? .on : .off
        }
        tokenField.stringValue = ""
        connectionLabel.stringValue = "Settings are saved only after a successful connection test."
        NSApp.activate(ignoringOtherApps: true)
        setupWindow?.makeKeyAndOrderFront(nil)
    }

    private func chooseFile(_ field: NSTextField) {
        let panel = NSOpenPanel()
        panel.canChooseDirectories = false
        panel.allowsMultipleSelection = false
        if panel.runModal() == .OK, let url = panel.url { field.stringValue = url.path }
    }

    private func captureUITest(_ directory: String) {
        do {
            let root = URL(fileURLWithPath: directory)
            try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
            openSettings()
            setupWindow?.contentView?.layoutSubtreeIfNeeded()
            try captureView(setupWindow!.contentView!, to: root.appendingPathComponent("settings.png"))
            setupWindow?.orderOut(nil)
            openInstall()
            installWindow?.contentView?.layoutSubtreeIfNeeded()
            try captureView(installWindow!.contentView!, to: root.appendingPathComponent("install.png"))
            let titles = menu.items.map { $0.title }
            let data = try JSONSerialization.data(withJSONObject: ["menu": titles, "config_written": false], options: .prettyPrinted)
            try data.write(to: root.appendingPathComponent("ui-smoke.json"))
            NSApp.terminate(nil)
        } catch {
            fputs("UI smoke failed: \(error)\n", stderr)
            exit(1)
        }
    }

    private func captureView(_ view: NSView, to url: URL) throws {
        guard let representation = view.bitmapImageRepForCachingDisplay(in: view.bounds) else {
            throw NSError(domain: "HomebrewPool", code: 1)
        }
        view.cacheDisplay(in: view.bounds, to: representation)
        guard let data = representation.representation(using: .png, properties: [:]) else {
            throw NSError(domain: "HomebrewPool", code: 2)
        }
        try data.write(to: url)
    }

    @objc private func chooseToken() { chooseFile(tokenFileField); tokenField.stringValue = "" }
    @objc private func chooseCA() { chooseFile(caField) }
    @objc private func testConnection() { submitSettings(save: false) }
    @objc private func saveSettings() { submitSettings(save: true) }

    private func submitSettings(save: Bool) {
        guard activeProcess == nil, settingsProcess == nil else { return }
        guard let (python, args) = clientArguments(["settings"] + (save ? ["--save"] : [])) else {
            connectionLabel.stringValue = "Python 3.9+ was not found. Install Python and reopen Homebrew Pool."
            return
        }
        let values: [String: Any] = ["url": serverField.stringValue, "token": tokenField.stringValue,
            "token_file": tokenFileField.stringValue, "ca_file": caField.stringValue,
            "allow_insecure_http": httpCheckbox.state == .on]
        guard let inputData = try? JSONSerialization.data(withJSONObject: values) else { return }
        let process = Process()
        let input = Pipe()
        let output = Pipe()
        process.executableURL = URL(fileURLWithPath: python)
        process.arguments = args
        process.standardInput = input
        process.standardOutput = output
        process.standardError = output
        settingsProcess = process
        testButton.isEnabled = false
        saveButton.isEnabled = false
        syncItem.isEnabled = false
        upgradeItem.isEnabled = false
        installItem.isEnabled = false
        connectionLabel.stringValue = "Testing connection…"
        process.terminationHandler = { [weak self] process in
            let data = output.fileHandleForReading.readDataToEndOfFile()
            DispatchQueue.main.async {
                guard let self = self else { return }
                self.settingsProcess = nil
                self.testButton.isEnabled = true
                self.saveButton.isEnabled = true
                self.syncItem.isEnabled = true
                self.upgradeItem.isEnabled = true
                self.installItem.isEnabled = true
                if process.terminationStatus == 0 {
                    self.connectionLabel.stringValue = "Healthy/Connected — token and API verified"
                    if save {
                        self.tokenField.stringValue = ""
                        self.setupWindow?.orderOut(nil)
                        self.appendLog("\n[settings] Configuration saved after successful connection test.\n")
                        self.refreshStatus()
                    }
                } else {
                    self.connectionLabel.stringValue = String(data: data, encoding: .utf8)?.trimmingCharacters(in: .whitespacesAndNewlines) ?? "Connection test failed."
                }
            }
        }
        do {
            try process.run()
            input.fileHandleForWriting.write(inputData)
            try input.fileHandleForWriting.close()
        } catch {
            settingsProcess = nil
            testButton.isEnabled = true
            saveButton.isEnabled = true
            syncItem.isEnabled = true
            upgradeItem.isEnabled = true
            installItem.isEnabled = true
            connectionLabel.stringValue = error.localizedDescription
        }
    }

    @objc private func openLogs() {
        appendLog("")
        NSWorkspace.shared.open(logURL)
    }

    @objc private func toggleLogin() {
        setLoginEnabled(!FileManager.default.fileExists(atPath: launchAgentURL.path))
    }

    private func setLoginEnabled(_ enabled: Bool) {
        let uid = getuid()
        let domain = "gui/\(uid)"
        if enabled {
            guard let executable = Bundle.main.executableURL?.path else { return }
            let plist: [String: Any] = [
                "Label": agentLabel,
                "ProgramArguments": [executable],
                "RunAtLoad": true,
                "ProcessType": "Interactive"
            ]
            do {
                let data = try PropertyListSerialization.data(fromPropertyList: plist, format: .xml, options: 0)
                try FileManager.default.createDirectory(at: launchAgentURL.deletingLastPathComponent(), withIntermediateDirectories: true)
                try data.write(to: launchAgentURL, options: .atomic)
                _ = runLaunchctl(["bootstrap", domain, launchAgentURL.path])
                loginItem.state = .on
            } catch {
                showAlert(title: "Could not enable Start at Login", message: error.localizedDescription)
            }
        } else {
            _ = runLaunchctl(["bootout", domain, launchAgentURL.path])
            do { try FileManager.default.removeItem(at: launchAgentURL) }
            catch where (error as NSError).code != NSFileNoSuchFileError {
                showAlert(title: "Could not disable Start at Login", message: error.localizedDescription)
            }
            catch { }
            loginItem.state = .off
        }
    }

    private func runLaunchctl(_ arguments: [String]) -> Int32 {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/bin/launchctl")
        process.arguments = arguments
        process.standardOutput = FileHandle.nullDevice
        process.standardError = FileHandle.nullDevice
        do { try process.run(); process.waitUntilExit(); return process.terminationStatus }
        catch { return -1 }
    }

    private func showAlert(title: String, message: String) {
        let alert = NSAlert()
        alert.messageText = title
        alert.informativeText = message
        alert.alertStyle = .warning
        alert.addButton(withTitle: "OK")
        NSApp.activate(ignoringOtherApps: true)
        alert.runModal()
    }

    @objc private func quitApp() {
        if activeProcess != nil || settingsProcess != nil {
            showAlert(title: "A Pool operation is still running", message: "Wait for it to finish before quitting so a build or sync is not interrupted.")
            return
        }
        NSApp.terminate(nil)
    }
}

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.run()
