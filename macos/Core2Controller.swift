import AppKit
import Foundation

final class Core2Controller: NSObject {
    private var window: NSWindow?
    private let summary = NSTextField(wrappingLabelWithString: "Core2 Legacy is disabled. Auto-import remains OFF.")
    private let details = NSTextView()
    private var process: Process?
    private var buttons: [NSButton] = []

    private var root: URL {
        if let value = ProcessInfo.processInfo.environment["HOMEBREW_POOL_APP_ROOT"] {
            return URL(fileURLWithPath: value)
        }
        return FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library/Application Support/Homebrew Pool Core2 Legacy")
    }

    @objc func open() {
        if window == nil {
            let stack = NSStackView()
            stack.orientation = .vertical
            stack.alignment = .leading
            stack.spacing = 14
            stack.edgeInsets = NSEdgeInsets(top: 22, left: 24, bottom: 22, right: 24)
            let title = NSTextField(labelWithString: "Core2 Legacy · Private channel")
            title.font = .boldSystemFont(ofSize: 20)
            stack.addArrangedSubview(title)
            summary.font = .systemFont(ofSize: 14)
            stack.addArrangedSubview(summary)
            let explanation = NSTextField(wrappingLabelWithString: "Only enrolled Intel Core 2 machines and approved bottles can use this channel. Penryn and Conroe/Merom are checked separately. The global Pool is kept separate. Python, XZ and the deferred Tcl/Tk installations are protected.")
            stack.addArrangedSubview(explanation)
            for row in [
                [("Review status", #selector(review)), ("Create disabled setup", #selector(initialize)), ("Load approved setup…", #selector(configure))],
                [("Review hardware", #selector(hardware)), ("Verify bottle…", #selector(verify)), ("Publish bottle…", #selector(publish)), ("Download approved bottle…", #selector(fetch))],
                [("Review source build plan…", #selector(buildPlan))]
            ] {
                let group = NSStackView()
                group.orientation = .horizontal
                group.spacing = 10
                for (label, action) in row {
                    let button = NSButton(title: label, target: self, action: action)
                    button.bezelStyle = .rounded
                    buttons.append(button); group.addArrangedSubview(button)
                }
                stack.addArrangedSubview(group)
            }
            let note = NSTextField(wrappingLabelWithString: "Auto-import: OFF. Downloads are prepared for review. Installation and source builds need separate authorization for the specific Homebrew operation.")
            note.textColor = .secondaryLabelColor
            stack.addArrangedSubview(note)
            details.isEditable = false
            details.isSelectable = true
            details.font = .monospacedSystemFont(ofSize: 12, weight: .regular)
            details.textContainerInset = NSSize(width: 10, height: 10)
            let scroll = NSScrollView()
            scroll.hasVerticalScroller = true
            scroll.borderType = .bezelBorder
            scroll.documentView = details
            stack.addArrangedSubview(scroll)
            scroll.heightAnchor.constraint(greaterThanOrEqualToConstant: 230).isActive = true
            scroll.widthAnchor.constraint(equalToConstant: 780).isActive = true
            window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 830, height: 500),
                              styleMask: [.titled, .closable, .miniaturizable, .resizable], backing: .buffered, defer: false)
            window?.title = "Homebrew Pool — Core2 Legacy"
            window?.appearance = NSAppearance(named: .aqua)
            window?.backgroundColor = NSColor(calibratedWhite: 0.96, alpha: 1)
            window?.contentView = stack
            stack.wantsLayer = true
            stack.layer?.backgroundColor = NSColor(calibratedWhite: 0.96, alpha: 1).cgColor
            window?.isReleasedWhenClosed = false
            window?.center()
        }
        window?.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        review()
    }

    private func choose(_ message: String) -> String? {
        let panel = NSOpenPanel()
        panel.message = message
        panel.canChooseDirectories = false
        panel.allowsMultipleSelection = false
        return panel.runModal() == .OK ? panel.url?.path : nil
    }

    private func run(_ arguments: [String]) {
        guard process == nil, let entry = Bundle.main.resourceURL?.appendingPathComponent("client/entry.py") else { return }
        let override = ProcessInfo.processInfo.environment["POOL_PYTHON"]
        let candidates = [override, "/usr/bin/python3", "/usr/local/bin/python3", "/opt/homebrew/bin/python3"].compactMap { $0 }
        guard let python = candidates.first(where: { FileManager.default.isExecutableFile(atPath: $0) }) else {
            summary.stringValue = "Python 3.9 or later is required. No Python installation was changed."
            return
        }
        let task = Process()
        task.executableURL = URL(fileURLWithPath: python)
        task.arguments = ["-B", entry.path, "legacy"] + arguments
        var environment = ProcessInfo.processInfo.environment
        environment["HOMEBREW_POOL_APP_ROOT"] = root.path
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        task.environment = environment
        let output = Pipe()
        task.standardOutput = output
        task.standardError = output
        process = task
        buttons.forEach { $0.isEnabled = false }
        summary.stringValue = "Checking private channel…"
        DispatchQueue.global(qos: .userInitiated).async {
            do {
                try task.run()
                let data = output.fileHandleForReading.readDataToEndOfFile()
                task.waitUntilExit()
                let text = String(data: data, encoding: .utf8) ?? "Unreadable response"
                let object = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any]
                DispatchQueue.main.async {
                    self.process = nil
                    self.buttons.forEach { $0.isEnabled = true }
                    self.details.string = text
                    self.summary.stringValue = (object?["error"] as? String) ?? (object?["message"] as? String)
                        ?? ((task.terminationStatus == 0) ? "Completed. Auto-import remains OFF." : "Blocked. Review the details below.")
                }
            } catch {
                DispatchQueue.main.async {
                    self.process = nil
                    self.buttons.forEach { $0.isEnabled = true }
                    self.summary.stringValue = "Could not start the private channel check."
                    self.details.string = error.localizedDescription
                }
            }
        }
    }

    @objc private func review() { run(["status"]) }
    @objc private func initialize() { run(["init"]) }
    @objc private func hardware() { run(["hardware"]) }
    @objc private func buildPlan() {
        guard let request = choose("Choose the build request approved for a dedicated Core 2 builder. This review does not run a build.") else { return }
        run(["build-plan", "--request", request])
    }
    @objc private func configure() {
        guard let file = choose("Choose the private configuration supplied by your Pool administrator.") else { return }
        run(["configure", "--file", file])
    }
    private func artifact(_ action: String, bottle: Bool) {
        guard let manifest = choose("Choose the approved Core2 Legacy manifest."),
              let plan = choose("Choose the independently reviewed dependency and recipe plan.") else { return }
        var args = [action, "--manifest", manifest, "--plan", plan]
        if bottle {
            guard let file = choose("Choose the matching rebuilt bottle archive.") else { return }
            args += ["--bottle", file]
        }
        run(args)
    }
    @objc private func verify() { artifact("verify", bottle: true) }
    @objc private func publish() { artifact("publish", bottle: true) }
    @objc private func fetch() { artifact("fetch", bottle: false) }

    func capturePreview(to path: String) throws {
        guard let view = window?.contentView,
              let bitmap = view.bitmapImageRepForCachingDisplay(in: view.bounds) else { return }
        view.cacheDisplay(in: view.bounds, to: bitmap)
        if let png = bitmap.representation(using: .png, properties: [:]) {
            try png.write(to: URL(fileURLWithPath: path))
        }
    }
}
