import AppKit
import Darwin
import Foundation
import UserNotifications

private let agentLabel = "com.stefanalmare.homebrew-intel-bottle-pool"

private struct PoolStatus: Decodable {
    let connected: Bool
    let spool_entries: Int
    let state: String
    let job: RunState?
}

private struct FailedItem: Codable {
    let name: String
    let kind: String
    let error: String
}

private struct RunState: Codable {
    var status: String
    var failed_count: Int
    var remaining_count: Int
    var failures: [FailedItem]
    var current: String
    var command: String
    var resume_command: [String]? = nil
}

private struct PendingRun: Codable {
    var state: RunState
    var command: [String]
    var activity: String
}

private enum IconState: String, CaseIterable {
    case healthy, busy, action, error, stopped
    var symbol: String {
        switch self {
        case .healthy: return "checkmark.circle"
        case .busy: return "arrow.triangle.2.circlepath.circle"
        case .action: return "exclamationmark.circle.fill"
        case .error: return "exclamationmark.triangle.fill"
        case .stopped: return "pause.circle"
        }
    }
    func image() -> NSImage? {
        let image = NSImage(systemSymbolName: symbol, accessibilityDescription: rawValue)
        image?.isTemplate = true
        return image
    }
}

private struct ActionChoice: Codable {
    let id: String
    let label: String
}

private struct PendingAction: Codable {
    let schema: Int
    let id: String
    let category: String
    let subject: String
    let reason: String
    let detail: String
    let choices: [ActionChoice]
    var command: [String]?
    var activity: String?
}

private let actionMarker = "HOMEBREW_POOL_ACTION_REQUIRED="

final class AppDelegate: NSObject, NSApplicationDelegate, NSMenuDelegate {
    private var statusItem: NSStatusItem!
    private let menu = NSMenu()
    private let statusLine = NSMenuItem(title: "Status: Starting…", action: nil, keyEquivalent: "")
    private let reviewItem = NSMenuItem(title: "Review Action…", action: #selector(reviewAction), keyEquivalent: "r")
    private let errorsItem = NSMenuItem(title: "Review Errors…", action: #selector(reviewErrors), keyEquivalent: "e")
    private let retryItem = NSMenuItem(title: "Retry Failed…", action: #selector(retryFailed), keyEquivalent: "")
    private let resumeItem = NSMenuItem(title: "Resume…", action: #selector(resumeRun), keyEquivalent: "")
    private let stopItem = NSMenuItem(title: "Stop", action: #selector(stopRun), keyEquivalent: ".")
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
    private var pendingAction: PendingAction?
    private var pendingRun: PendingRun?
    private var stopping = false
    private var quitAfterStop = false
    private var activeGroups = Set<Int32>()
    private var busyTimer: Timer?
    private var busyFrame = false
    private var workflowTimer: Timer?
    private var workflowPhase = 0
    private var workflowDeadline = Date()
    private var workflowSmokeDirectory: String? {
        let args = CommandLine.arguments
        guard let index = args.firstIndex(of: "--workflow-smoke"), index + 1 < args.count else { return nil }
        return args[index + 1]
    }
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
        if let directory = uiSmokeDirectory ?? workflowSmokeDirectory { return URL(fileURLWithPath: directory).appendingPathComponent("agent.log") }
        return FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Logs/HomebrewIntelBottlePool/agent.log")
    }

    private var launchAgentURL: URL {
        FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/LaunchAgents/\(agentLabel).plist")
    }

    private var actionURL: URL {
        supportURL.appendingPathComponent("action-required.json")
    }

    private var supportURL: URL {
        if let directory = uiSmokeDirectory ?? workflowSmokeDirectory { return URL(fileURLWithPath: directory).appendingPathComponent("support") }
        return FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library/Application Support/Homebrew Pool")
    }
    private var runURL: URL { supportURL.appendingPathComponent("pending-run.json") }

    private func normalizedEnvironment(extra: [String: String] = [:]) -> [String: String] {
        var environment = ProcessInfo.processInfo.environment
        var path = environment["PATH", default: ""].split(separator: ":").map(String.init)
        for required in ["/usr/local/bin", "/usr/local/sbin"] where !path.contains(required) {
            path.append(required)
        }
        environment["PATH"] = path.joined(separator: ":")
        environment["HOMEBREW_NO_ASK"] = "1"
        environment["HOMEBREW_POOL_GUI"] = "1"
        environment["PYTHONUNBUFFERED"] = "1"
        for (key, value) in extra { environment[key] = value }
        return environment
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.accessory)
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        statusItem.button?.imagePosition = .imageOnly
        statusItem.button?.toolTip = "Homebrew Intel Bottle Pool"
        buildMenu()
        menu.autoenablesItems = false
        if uiSmokeDirectory == nil && workflowSmokeDirectory == nil {
            UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound]) { _, _ in }
        }
        restorePendingRun()
        restorePendingAction()
        if let directory = workflowSmokeDirectory {
            DispatchQueue.main.async { self.startWorkflowSmoke(directory) }
            return
        }
        if let directory = uiSmokeDirectory {
            NSApp.appearance = NSAppearance(named: .aqua)
            DispatchQueue.main.async { self.captureUITest(directory) }
            return
        }
        if pendingAction == nil { setVisual(symbol: "hourglass", title: "Checking…") }
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
        reviewItem.target = self
        reviewItem.isHidden = true
        menu.addItem(reviewItem)
        for item in [errorsItem, retryItem, resumeItem, stopItem] {
            item.target = self
            item.isHidden = true
            menu.addItem(item)
        }
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
        // Native template contrast follows the actual menu-bar appearance,
        // including white on a dark/blue bar. State is encoded by shape and text.
        statusItem.button?.contentTintColor = nil
        statusItem.button?.toolTip = "Homebrew Pool — \(title)"
        statusLine.title = "Status: \(title)"
        updateRunMenu()
    }

    private func showActionVisual() {
        setVisual(symbol: "exclamationmark.circle.fill", title: "🔴 Action Required")
        reviewItem.isHidden = false
        reviewItem.isEnabled = true
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
        guard pendingAction == nil else { showActionVisual(); return }
        guard pendingRun == nil else { showRunVisual(); return }
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
        process.environment = normalizedEnvironment()
        process.standardOutput = pipe
        process.standardError = pipe
        statusProcess = process
        process.terminationHandler = { [weak self] process in
            let data = pipe.fileHandleForReading.readDataToEndOfFile()
            DispatchQueue.main.async {
                guard let self = self else { return }
                self.statusProcess = nil
                guard self.activeProcess == nil, self.settingsProcess == nil else { return }
                guard self.pendingAction == nil, self.pendingRun == nil else { self.refreshStatus(); return }
                if process.terminationStatus == 0,
                   let decoded = try? JSONDecoder().decode(PoolStatus.self, from: data) {
                    if let job = decoded.job, job.failed_count > 0 || job.remaining_count > 0 {
                        // The CLI may have created the queue outside this GUI.
                        self.pendingRun = PendingRun(state: job, command: job.resume_command ?? (job.command == "upgrade" ? ["upgrade"] : []), activity: "Busy/Resuming")
                        self.savePendingRun()
                        self.showRunVisual()
                    } else if decoded.connected && decoded.spool_entries == 0 {
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
        process.environment = normalizedEnvironment()
        process.standardOutput = pipe
        process.standardError = pipe
        process.standardInput = FileHandle.nullDevice
        activeProcess = process
        stopping = false
        activeGroups.removeAll()
        activity = title
        if command.first != "job" {
            let base = command.filter { $0 != "--resume" && $0 != "--retry-failed" }
            let state = pendingRun?.state ?? RunState(status: "running", failed_count: 0, remaining_count: 1,
                                                     failures: [], current: "", command: base.first ?? "")
            pendingRun = PendingRun(state: state, command: base, activity: title)
            savePendingRun()
        }
        setVisual(symbol: IconState.busy.symbol, title: title)
        busyTimer?.invalidate()
        busyTimer = Timer.scheduledTimer(withTimeInterval: 0.45, repeats: true) { [weak self] _ in
            guard let self = self, self.activeProcess != nil, !self.stopping else { return }
            self.busyFrame.toggle()
            self.setVisual(symbol: self.busyFrame ? "arrow.triangle.2.circlepath.circle.fill" : IconState.busy.symbol,
                           title: self.activity ?? "Busy")
        }
        appendLog("\n[\(ISO8601DateFormatter().string(from: Date()))] \(command.joined(separator: " "))\n")
        let outputLock = NSLock()
        var captured = Data()
        var lineBuffer = ""
        pipe.fileHandleForReading.readabilityHandler = { [weak self] handle in
            let data = handle.availableData
            guard !data.isEmpty else { return }
            outputLock.lock()
            captured.append(data)
            if captured.count > 262144 { captured.removeFirst(captured.count - 262144) }
            lineBuffer += String(data: data, encoding: .utf8) ?? ""
            let lines = lineBuffer.components(separatedBy: "\n")
            lineBuffer = lines.last ?? ""
            outputLock.unlock()
            if let text = String(data: data, encoding: .utf8) { self?.appendLog(text) }
            for line in lines.dropLast() {
                DispatchQueue.main.async { self?.trackProcessMarker(line) }
            }
        }
        process.terminationHandler = { [weak self] process in
            pipe.fileHandleForReading.readabilityHandler = nil
            let remaining = pipe.fileHandleForReading.readDataToEndOfFile()
            outputLock.lock()
            captured.append(remaining)
            let commandOutput = captured
            outputLock.unlock()
            if let tail = String(data: remaining, encoding: .utf8), !tail.isEmpty { self?.appendLog(tail) }
            DispatchQueue.main.async {
                guard let self = self else { return }
                let wasStopped = self.stopping || process.terminationStatus == 4
                self.activeProcess = nil
                self.activity = nil
                self.busyTimer?.invalidate()
                self.busyTimer = nil
                self.activeGroups.removeAll()
                self.stopping = false
                if let state: RunState = self.decodeMarker("HOMEBREW_POOL_RUN_STATE=", from: commandOutput),
                   process.terminationStatus == 0 || process.terminationStatus == 4 || state.failed_count > 0 || state.remaining_count > 0 {
                    if state.failed_count == 0 && state.remaining_count == 0 && state.status != "action_required" {
                        self.pendingRun = nil
                        try? FileManager.default.removeItem(at: self.runURL)
                    } else {
                        let previous = self.pendingRun
                        self.pendingRun = PendingRun(state: state, command: previous?.command ?? command,
                                                     activity: previous?.activity ?? title)
                        self.savePendingRun()
                    }
                } else if wasStopped, var pending = self.pendingRun {
                    pending.state.status = "stopped"
                    self.pendingRun = pending
                    self.savePendingRun()
                } else if process.terminationStatus == 2 && command.first == "sync" {
                    self.pendingRun = nil
                    try? FileManager.default.removeItem(at: self.runURL)
                } else if process.terminationStatus != 0 {
                    let detail = String(data: commandOutput, encoding: .utf8) ?? "No output captured"
                    let state = RunState(status: "paused_error", failed_count: 1, remaining_count: 0,
                                         failures: [FailedItem(name: command.first ?? "command", kind: "command", error: String(detail.suffix(8000)))],
                                         current: "", command: command.first ?? "")
                    self.pendingRun = PendingRun(state: state, command: command, activity: title)
                    self.savePendingRun()
                } else if command.first != "job" {
                    self.pendingRun = nil
                    try? FileManager.default.removeItem(at: self.runURL)
                }
                if process.terminationStatus == 3, var action = self.decodeAction(from: commandOutput) {
                    action.command = self.pendingRun?.command ?? command
                    action.activity = title
                    self.setPendingAction(action)
                } else {
                    self.refreshStatus()
                    if self.workflowSmokeDirectory == nil && !wasStopped && process.terminationStatus != 0 && !(process.terminationStatus == 2 && command.first == "sync") {
                        self.showAlert(title: "Paused — Error", message: "The operation stopped. Review Errors shows what failed. The remaining queue is saved.")
                    }
                }
                self.updateRunMenu()
                if self.quitAfterStop {
                    self.quitAfterStop = false
                    NSApp.terminate(nil)
                }
            }
        }
        do { try process.run() }
        catch {
            activeProcess = nil
            activity = nil
            busyTimer?.invalidate()
            appendLog("\(error)\n")
            pendingRun?.state.status = "paused_error"
            pendingRun?.state.failed_count = 1
            pendingRun?.state.failures = [FailedItem(name: command.first ?? "command", kind: "command", error: String(describing: error))]
            savePendingRun()
            refreshStatus()
        }
    }

    private func trackProcessMarker(_ line: String) {
        if line.hasPrefix("HOMEBREW_POOL_PROCESS_GROUP_DONE="),
           let pid = Int32(line.dropFirst("HOMEBREW_POOL_PROCESS_GROUP_DONE=".count)) {
            activeGroups.remove(pid)
        } else if line.hasPrefix("HOMEBREW_POOL_PROCESS_GROUP="),
                  let pid = Int32(line.dropFirst("HOMEBREW_POOL_PROCESS_GROUP=".count)), pid > 1 {
            activeGroups.insert(pid)
        }
    }

    private func decodeMarker<T: Decodable>(_ marker: String, from data: Data) -> T? {
        guard let text = String(data: data, encoding: .utf8),
              let range = text.range(of: marker, options: .backwards),
              let line = text[range.upperBound...].split(whereSeparator: { $0 == "\n" || $0 == "\r" }).first,
              let payload = String(line).data(using: .utf8) else { return nil }
        return try? JSONDecoder().decode(T.self, from: payload)
    }

    private func savePendingRun() {
        guard let pending = pendingRun, let data = try? JSONEncoder().encode(pending) else { return }
        try? FileManager.default.createDirectory(at: supportURL, withIntermediateDirectories: true)
        try? data.write(to: runURL, options: .atomic)
    }

    private func restorePendingRun() {
        guard let data = try? Data(contentsOf: runURL),
              var pending = try? JSONDecoder().decode(PendingRun.self, from: data) else { return }
        if pending.state.status == "running" { pending.state.status = "stopped" }
        pendingRun = pending
        showRunVisual()
    }

    private func updateRunMenu() {
        let busy = activeProcess != nil
        let failures = pendingRun?.state.failed_count ?? 0
        let remaining = pendingRun?.state.remaining_count ?? 0
        errorsItem.isHidden = failures == 0
        errorsItem.isEnabled = !busy
        retryItem.isHidden = failures == 0
        retryItem.isEnabled = !busy && pendingAction == nil
        resumeItem.isHidden = remaining == 0
        resumeItem.isEnabled = !busy && pendingAction == nil && !(pendingRun?.command.isEmpty ?? true)
        stopItem.isHidden = !busy && pendingRun == nil
        stopItem.isEnabled = !stopping
        syncItem.isEnabled = !busy && pendingRun == nil && pendingAction == nil
        upgradeItem.isEnabled = syncItem.isEnabled
        installItem.isEnabled = syncItem.isEnabled
        settingsItem.isEnabled = !busy && settingsProcess == nil
    }

    private func showRunVisual() {
        guard let state = pendingRun?.state else { return }
        if state.failed_count > 0 {
            setVisual(symbol: IconState.error.symbol, title: "Paused — Error · \(state.failed_count) failed · \(state.remaining_count) remaining")
        } else {
            setVisual(symbol: IconState.stopped.symbol, title: "Paused/Stopped · \(state.remaining_count) remaining")
        }
    }

    @objc private func reviewErrors() {
        guard let pending = pendingRun else { return }
        let alert = NSAlert()
        alert.messageText = "\(pending.state.failed_count) failed item(s)"
        alert.informativeText = pending.state.failures.map { "\($0.name): \($0.error)" }.joined(separator: "\n\n").suffix(6000).description
        alert.addButton(withTitle: "Close")
        alert.addButton(withTitle: "Resolve / Skip Failed")
        alert.addButton(withTitle: "Cancel Saved Queue")
        NSApp.activate(ignoringOtherApps: true)
        let response = alert.runModal()
        if response == .alertSecondButtonReturn {
            if pending.state.command == "upgrade" || pending.state.command == "install" {
                runInteractive(command: ["job", "resolve"], activity: "Busy/Resolving")
            } else {
                pendingRun = nil
                try? FileManager.default.removeItem(at: runURL)
                refreshStatus()
            }
        } else if response == .alertThirdButtonReturn {
            clearPendingActionWithoutRefresh()
            runInteractive(command: ["job", "cancel"], activity: "Busy/Cancelling")
        }
    }

    private func continuationCommand(retry: Bool) -> [String]? {
        guard let pending = pendingRun, !pending.command.isEmpty else { return nil }
        var command = pending.command.filter { $0 != "--resume" && $0 != "--retry-failed" }
        if (command.first == "upgrade" || command.first == "install") && !pending.state.failures.contains(where: { $0.kind == "command" }) {
            command.append(retry ? "--retry-failed" : "--resume")
        }
        return command
    }

    @objc private func retryFailed() {
        guard let command = continuationCommand(retry: true) else { return }
        runInteractive(command: command, activity: "Busy/Retrying failed items")
    }

    @objc private func resumeRun() {
        guard let command = continuationCommand(retry: false) else { return }
        runInteractive(command: command, activity: "Busy/Resuming saved queue")
    }

    @objc private func stopRun() {
        guard let process = activeProcess else {
            pendingRun?.state.status = "stopped"
            savePendingRun()
            refreshStatus()
            return
        }
        guard !stopping else { return }
        stopping = true
        busyTimer?.invalidate()
        setVisual(symbol: IconState.stopped.symbol, title: "Stopping… · queue retained")
        appendLog("\n[stop] Graceful stop requested\n")
        kill(process.processIdentifier, SIGTERM)
        DispatchQueue.main.asyncAfter(deadline: .now() + 22) { [weak self, weak process] in
            guard let self = self, let process = process,
                  self.activeProcess === process, process.isRunning else { return }
            self.appendLog("[stop] Worker timeout; terminating registered process groups\n")
            for group in self.activeGroups { kill(-group, SIGTERM) }
            DispatchQueue.main.asyncAfter(deadline: .now() + 4) { [weak self, weak process] in
                guard let self = self, let process = process,
                      self.activeProcess === process, process.isRunning else { return }
                for group in self.activeGroups { kill(-group, SIGKILL) }
                kill(process.processIdentifier, SIGKILL)
            }
        }
    }

    @objc private func refreshStatus() {
        if let activity = activity {
            setVisual(symbol: stopping ? IconState.stopped.symbol : IconState.busy.symbol,
                      title: stopping ? "Stopping… · queue retained" : activity)
        } else if pendingAction != nil {
            showActionVisual()
        } else if pendingRun != nil {
            showRunVisual()
        } else {
            runStatus()
        }
    }

    @objc private func syncNow() {
        runInteractive(command: ["sync"], activity: "Busy/Syncing")
    }

    private func decodeAction(from data: Data) -> PendingAction? {
        guard let text = String(data: data, encoding: .utf8),
              let range = text.range(of: actionMarker, options: .backwards) else { return nil }
        let suffix = text[range.upperBound...]
        guard let line = suffix.split(whereSeparator: { $0 == "\n" || $0 == "\r" }).first,
              let payload = String(line).data(using: .utf8) else { return nil }
        return try? JSONDecoder().decode(PendingAction.self, from: payload)
    }

    private func setPendingAction(_ action: PendingAction) {
        pendingAction = action
        showActionVisual()
        if let data = try? JSONEncoder().encode(action) {
            try? FileManager.default.createDirectory(at: actionURL.deletingLastPathComponent(),
                                                     withIntermediateDirectories: true)
            try? data.write(to: actionURL, options: .atomic)
        }
        let notificationKey = "notified-action-\(action.id)"
        if !UserDefaults.standard.bool(forKey: notificationKey) {
            let notification = UNMutableNotificationContent()
            notification.title = "Homebrew Pool — Action Required"
            notification.body = action.reason
            notification.sound = .default
            let request = UNNotificationRequest(identifier: "homebrew-pool-\(action.id)",
                                                content: notification, trigger: nil)
            UNUserNotificationCenter.current().add(request)
            UserDefaults.standard.set(true, forKey: notificationKey)
        }
    }

    private func restorePendingAction() {
        guard let data = try? Data(contentsOf: actionURL),
              let action = try? JSONDecoder().decode(PendingAction.self, from: data) else { return }
        pendingAction = action
        showActionVisual()
    }

    private func clearPendingAction() {
        pendingAction = nil
        reviewItem.isHidden = true
        try? FileManager.default.removeItem(at: actionURL)
        refreshStatus()
    }

    @objc private func reviewAction() {
        guard let action = pendingAction else { return }
        let alert = NSAlert()
        alert.messageText = "Homebrew Pool needs your decision"
        var message = action.reason
        if !action.subject.isEmpty { message += "\n\nItem: \(action.subject)" }
        if !action.detail.isEmpty { message += "\n\nDetails:\n\(String(action.detail.suffix(1200)))" }
        alert.informativeText = message
        alert.alertStyle = .critical
        for choice in action.choices.prefix(3) { alert.addButton(withTitle: choice.label) }
        NSApp.activate(ignoringOtherApps: true)
        let response = alert.runModal().rawValue - NSApplication.ModalResponse.alertFirstButtonReturn.rawValue
        guard response >= 0, response < action.choices.count else { return }
        handleActionChoice(action.choices[response].id, action: action)
    }

    private func handleActionChoice(_ choice: String, action: PendingAction) {
        guard var command = action.command else { clearPendingAction(); return }
        if choice == "cancel" {
            clearPendingActionWithoutRefresh()
            runInteractive(command: ["job", "cancel"], activity: "Busy/Cancelling")
            return
        }
        command = command.filter { $0 != "--resume" && $0 != "--retry-failed" }
        if command.first == "upgrade" || command.first == "install" { command.append("--resume") }
        if choice == "skip" {
            if command.first == "install" {
                clearPendingActionWithoutRefresh()
                runInteractive(command: ["job", "cancel"], activity: "Busy/Skipping installation")
                return
            }
            guard command.first == "upgrade", !action.subject.isEmpty else { clearPendingAction(); return }
            command += ["--skip", pendingRun?.state.current.isEmpty == false ? pendingRun!.state.current : action.subject]
        } else if choice == "formula" || choice == "cask" {
            if let index = command.firstIndex(of: "--type"), index + 1 < command.count {
                command[index + 1] = choice
            } else {
                command += ["--type", choice]
            }
        } else if choice == "continue" && action.category == "authentication" {
            guard requestNativeAuthorization() else { return }
        }
        let title = action.activity ?? "Busy/Continuing"
        clearPendingActionWithoutRefresh()
        runInteractive(command: command, activity: title)
    }

    private func clearPendingActionWithoutRefresh() {
        pendingAction = nil
        reviewItem.isHidden = true
        try? FileManager.default.removeItem(at: actionURL)
    }

    private func requestNativeAuthorization() -> Bool {
        // SecurityAgent owns the credential UI. The application never receives,
        // stores, or forwards an administrator password.
        let source = "do shell script \"/usr/bin/true\" with administrator privileges"
        var error: NSDictionary?
        let result = NSAppleScript(source: source)?.executeAndReturnError(&error)
        if result == nil {
            showAlert(title: "Authorization was not granted",
                      message: error?[NSAppleScript.errorMessage] as? String ?? "The system authorization dialog was cancelled.")
            return false
        }
        return true
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
            func require(_ value: Bool, _ message: String) throws {
                if !value { throw NSError(domain: "HomebrewPoolUISmoke", code: 1, userInfo: [NSLocalizedDescriptionKey: message]) }
            }
            var icons = [[String: Any]]()
            for state in IconState.allCases {
                let image = state.image()
                try require(image?.isTemplate == true, "Every status icon must be a template")
                setVisual(symbol: state.symbol, title: state.rawValue)
                try require(statusItem.button?.contentTintColor == nil, "Native contrast must not be overridden")
                icons.append(["state": state.rawValue, "symbol": state.symbol, "template": image!.isTemplate, "native_contrast": true])
            }
            try require(Set(icons.compactMap { $0["symbol"] as? String }).count == 5, "State symbols must differ")
            pendingRun = PendingRun(state: RunState(status: "paused_error", failed_count: 2, remaining_count: 3,
                failures: [FailedItem(name: "fixture", kind: "formula", error: "fixture error")], current: "fixture", command: "upgrade"),
                command: ["upgrade"], activity: "Busy/Building")
            refreshStatus()
            try require(statusLine.title.contains("2 failed"), "Errors must remain visible on refresh")
            try require(!errorsItem.isHidden && retryItem.isEnabled && resumeItem.isEnabled, "Paused error menu")
            activeProcess = Process()
            updateRunMenu()
            try require(stopItem.isEnabled && !stopItem.isHidden, "Stop must be enabled while busy")
            try require(menu.items.first(where: { $0.title == "Quit" })?.isEnabled == true, "Quit must remain enabled")
            try require(!retryItem.isEnabled && !resumeItem.isEnabled, "Do not launch a second worker")
            activeProcess = nil
            pendingRun = nil
            let data = try JSONSerialization.data(withJSONObject: ["menu": titles, "config_written": false,
                "icons": icons, "paused_error_persists": true, "stop_and_quit_while_busy": true,
                "retry_resume_menu": true], options: .prettyPrinted)
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

    private func startWorkflowSmoke(_ directory: String) {
        let root = URL(fileURLWithPath: directory).resolvingSymlinksInPath()
        // This test mode must never reach the user's configuration or Homebrew.
        guard FileManager.default.fileExists(atPath: root.appendingPathComponent("test-fixture").path),
              configURL.resolvingSymlinksInPath().path.hasPrefix(root.path + "/"),
              let data = try? Data(contentsOf: configURL),
              let config = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let brew = config["brew"] as? String,
              URL(fileURLWithPath: brew).resolvingSymlinksInPath().path.hasPrefix(root.path + "/") else {
            fputs("Workflow smoke requires an isolated fixture configuration\n", stderr)
            exit(1)
        }
        workflowDeadline = Date().addingTimeInterval(120)
        runInteractive(command: ["upgrade"], activity: "Busy/Fixture upgrade")
        workflowTimer = Timer.scheduledTimer(withTimeInterval: 0.2, repeats: true) { [weak self] _ in
            self?.advanceWorkflowSmoke(root)
        }
    }

    private func advanceWorkflowSmoke(_ root: URL) {
        do {
            func require(_ value: Bool, _ message: String) throws {
                if !value { throw NSError(domain: "HomebrewPoolWorkflowSmoke", code: 1, userInfo: [NSLocalizedDescriptionKey: message]) }
            }
            try require(Date() < workflowDeadline, "Workflow timed out at phase \(workflowPhase)")
            switch workflowPhase {
            case 0:
                guard activeProcess == nil else { return }
                try require(pendingRun?.state.failed_count == 1, "First technical error must pause")
                refreshStatus()
                try require(statusLine.title.contains("1 failed"), "Periodic refresh must preserve error count")
                try require(retryItem.isEnabled && resumeItem.isEnabled, "Retry/Resume menu must be available")
                try require(!FileManager.default.fileExists(atPath: root.appendingPathComponent("beta-visited").path), "Second package started after error")
                try FileManager.default.removeItem(at: root.appendingPathComponent("fail"))
                workflowPhase = 1
                retryFailed()
            case 1:
                guard activeProcess == nil else { return }
                try require(pendingRun?.state.failed_count == 0 && (pendingRun?.state.remaining_count ?? 0) > 0, "Retry must stop before remaining queue")
                try require(!FileManager.default.fileExists(atPath: root.appendingPathComponent("beta-visited").path), "Retry started another package")
                workflowPhase = 2
                resumeRun()
            case 2:
                guard activeProcess == nil else { return }
                try require(pendingRun == nil, "Resume must finish the saved queue")
                try require(FileManager.default.fileExists(atPath: root.appendingPathComponent("beta-visited").path), "Remaining package was not visited")
                _ = FileManager.default.createFile(atPath: root.appendingPathComponent("block").path, contents: Data())
                workflowPhase = 3
                runInteractive(command: ["upgrade"], activity: "Busy/Fixture stop test")
            case 3:
                guard FileManager.default.fileExists(atPath: root.appendingPathComponent("child-pid").path) else { return }
                try require(activeProcess != nil && stopItem.isEnabled, "Stop unavailable while worker is running")
                try require(menu.items.first(where: { $0.title == "Quit" })?.isEnabled == true, "Quit unavailable while worker is running")
                workflowPhase = 4
                stopRun()
            case 4:
                guard activeProcess == nil else { return }
                try require(pendingRun?.state.status == "stopped", "Stopped worker must retain queue")
                try require(FileManager.default.fileExists(atPath: root.appendingPathComponent("stop-clean").path), "Child did not receive graceful stop")
                try FileManager.default.removeItem(at: root.appendingPathComponent("block"))
                workflowPhase = 5
                resumeRun()
            default:
                guard activeProcess == nil else { return }
                try require(pendingRun == nil, "Stop/Resume must finish")
                let report: [String: Any] = ["pause_on_first_error": true, "sticky_failed_count": true,
                    "retry_only_failed": true, "resume_remaining": true, "stop_child_cleanup": true,
                    "stop_resume": true, "quit_while_busy": true, "isolated_configuration": true]
                let data = try JSONSerialization.data(withJSONObject: report, options: .prettyPrinted)
                try data.write(to: root.appendingPathComponent("workflow-smoke.json"))
                workflowTimer?.invalidate()
                NSApp.terminate(nil)
            }
        } catch {
            fputs("Workflow smoke failed: \(error)\n", stderr)
            if activeProcess != nil { quitAfterStop = true; stopRun() }
            else { exit(1) }
        }
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
        process.environment = normalizedEnvironment()
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
        process.environment = normalizedEnvironment()
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
        if activeProcess != nil {
            let alert = NSAlert()
            alert.messageText = "Stop the current operation and quit?"
            alert.informativeText = "The process will stop in a controlled way. The saved queue remains available for Retry or Resume after reopening."
            alert.addButton(withTitle: "Stop & Quit")
            alert.addButton(withTitle: "Cancel")
            NSApp.activate(ignoringOtherApps: true)
            if alert.runModal() == .alertFirstButtonReturn {
                quitAfterStop = true
                stopRun()
            }
            return
        }
        settingsProcess?.terminate()
        statusProcess?.terminate()
        NSApp.terminate(nil)
    }

    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        if activeProcess != nil {
            quitApp()
            return .terminateCancel
        }
        settingsProcess?.terminate()
        statusProcess?.terminate()
        return .terminateNow
    }
}

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.run()
