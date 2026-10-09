import Foundation

enum GUICommand {
    private static let repositoryCommands: Set<String> = [
        "upgrade", "install", "repair", "maintenance", "capture", "compatibility", "imports"
    ]

    static func arguments(entry: String, config: String, command: [String], userInitiated: Bool) -> [String] {
        var arguments = ["-B", entry, "--config", config]
        // A current UI action authorizes only this child invocation. Never put
        // this flag in the saved queue, configuration, or automatic status poll.
        if userInitiated, let operation = command.first, repositoryCommands.contains(operation) {
            arguments.append("--authorize-repository-access")
        }
        return arguments + command
    }
}

struct GUIFailure {
    let title: String
    let message: String

    init(command: [String], output: String, exitCode: Int32, remaining: Int? = nil, failed: Int? = nil) {
        let operation = command.first == "upgrade" ? "Update & Upgrade" : (command.first?.capitalized ?? "Operation")
        title = (remaining ?? 0) > 0 || (failed ?? 0) > 0 ? "Paused — Error" : operation + " failed"
        let diagnostic = output.components(separatedBy: .newlines).filter {
            !$0.hasPrefix("HOMEBREW_POOL_PROCESS_GROUP") && !$0.hasPrefix("HOMEBREW_POOL_RUN_STATE=")
        }.joined(separator: "\n").trimmingCharacters(in: .whitespacesAndNewlines)
        var detail = diagnostic.isEmpty ? "The command exited with code \(exitCode)." : String(diagnostic.suffix(8000))
        if let count = remaining, count > 0 {
            detail += "\n\n\(count) remaining item(s) are saved in the queue."
        }
        message = detail
    }
}
