// macOS text editor window for long prompts (decision 13; the Linux side is zenity --text-info
// --editable), built by oslayer.py (at Install, else on first use).
//
//   cpo_editor <file> <title>
//
// Shows the file's text in a resizable window. OK writes the edited text back to the file and
// exits 0; Cancel or closing the window exits 1 and leaves the file alone. Unlike the progress
// window it takes the keyboard focus, so typing goes to the editor while Flame waits.
import AppKit

let args = CommandLine.arguments
guard args.count > 1 else { exit(2) }
let path = args[1]
let title = args.count > 2 ? args[2] : "Edit"
let original = (try? String(contentsOfFile: path, encoding: .utf8)) ?? ""

final class FirstClickButton: NSButton {
    override func acceptsFirstMouse(for event: NSEvent?) -> Bool { true }
}

final class Handler: NSObject, NSWindowDelegate {
    var textView: NSTextView!
    @objc func ok(_ sender: Any?) {
        do {
            try textView.string.write(toFile: path, atomically: true, encoding: .utf8)
            exit(0)
        } catch {
            exit(2)
        }
    }
    @objc func cancel(_ sender: Any?) { exit(1) }
    func windowWillClose(_ notification: Notification) { exit(1) }
}

let app = NSApplication.shared
app.setActivationPolicy(.accessory)
let handler = Handler()
let w: CGFloat = 760, h: CGFloat = 440

let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: w, height: h),
                      styleMask: [.titled, .closable, .resizable], backing: .buffered, defer: false)
window.title = title
window.level = .floating
window.isReleasedWhenClosed = false
window.delegate = handler
window.minSize = NSSize(width: 360, height: 200)

let scroll = NSTextView.scrollableTextView()
scroll.frame = NSRect(x: 12, y: 56, width: w - 24, height: h - 68)
scroll.autoresizingMask = [.width, .height]
let textView = scroll.documentView as! NSTextView
textView.string = original
textView.font = NSFont.systemFont(ofSize: 14)
textView.isRichText = false
textView.allowsUndo = true
handler.textView = textView

let ok = FirstClickButton(title: "OK", target: handler, action: #selector(Handler.ok(_:)))
ok.frame = NSRect(x: w - 112, y: 12, width: 100, height: 32)
ok.autoresizingMask = [.minXMargin, .maxYMargin]
ok.keyEquivalent = "\r"
ok.keyEquivalentModifierMask = [.command]  // Cmd-Return: plain Return types a new line
let cancel = FirstClickButton(title: "Cancel", target: handler, action: #selector(Handler.cancel(_:)))
cancel.frame = NSRect(x: w - 220, y: 12, width: 100, height: 32)
cancel.autoresizingMask = [.minXMargin, .maxYMargin]
cancel.keyEquivalent = "\u{1b}"  // Escape

for view in [scroll, ok, cancel] as [NSView] {
    window.contentView?.addSubview(view)
}
window.center()
window.makeKeyAndOrderFront(nil)
window.makeFirstResponder(textView)
app.activate(ignoringOtherApps: true)
app.run()
