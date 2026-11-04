// CC level panel: your cclevel creature in the macOS menu bar. Click it for a small black panel with the creature and its
// stats; right-click (or control-click) for Refresh and Quit.
//
// It runs the offline card (`cclevel.py --json --no-save`, which writes nothing) when its last result is more than an hour
// old, keeps that result in card.json beside itself, and makes no network call. `cclevel.py --panel on --yes` builds it on
// this Mac with Apple's swiftc and starts it at login; `cclevel.py --panel off` removes it.
//
// `--snapshot OUT.png --card CARD.json` draws the panel for a card into a picture and exits (for tests and previews).
import AppKit

let statOrder = ["grind", "appetite", "arsenal", "brains", "autonomy", "craft"]
let staleAfter: TimeInterval = 60 * 60
let scanTimeout: TimeInterval = 120
let orange = NSColor(srgbRed: 0xd9 / 255, green: 0x77 / 255, blue: 0x57 / 255, alpha: 1)
let dim = NSColor(white: 0.55, alpha: 1)
let track = NSColor(white: 0.16, alpha: 1)
let panelWidth: CGFloat = 360

/// The numbers behind the card, from data this program does not control: every field is checked.
struct Card {
    let stage: String, cls: String, brain: String, mood: String
    let level: Int, xp: Int, xpStart: Int, xpNext: Int, today: Int, health: Int, power: Int
    let stats: [String: Int]
    let art: [String]

    init?(json: Any) {
        guard let o = json as? [String: Any] else { return nil }
        func text(_ k: String, _ max: Int = 40) -> String? {
            guard let s = o[k] as? String, s.count <= max else { return nil }
            return s
        }
        func count(_ k: String) -> Int? {
            guard let n = o[k] as? NSNumber, CFGetTypeID(n) != CFBooleanGetTypeID() else { return nil }
            let v = n.intValue
            return v >= 0 && v < 1_000_000_000 ? v : nil
        }
        guard let stage = text("stage", 20), !stage.isEmpty, let cls = text("class"), let brain = text("brain"),
              let mood = text("mood"), let level = count("level"), level >= 1, let xp = count("xp"),
              let xpNext = count("xp_next_level"), let today = count("xp_today_pending"), let health = count("health"),
              let power = count("power"), let rawStats = o["stats"] as? [String: Any],
              let art = o["art"] as? [String], art.count == 4, art.allSatisfy({ $0.count <= 20 })
        else { return nil }
        var stats: [String: Int] = [:]
        for name in statOrder {
            guard let n = rawStats[name] as? NSNumber, (0...100).contains(n.intValue) else { return nil }
            stats[name] = n.intValue
        }
        self.stage = stage; self.cls = cls; self.brain = brain; self.mood = mood
        self.level = level; self.xp = xp; self.xpNext = xpNext; self.today = today
        self.xpStart = count("xp_level_start") ?? 0
        self.health = health; self.power = power; self.stats = stats; self.art = art
    }

    /// How far through its level the creature is, 0 to 1.
    var progress: CGFloat {
        let span = xpNext - xpStart
        return level >= 99 ? 1 : span > 0 ? min(1, max(0, CGFloat(xp - xpStart) / CGFloat(span))) : 0
    }

    /// A one-line face for the menu bar, from the art's eye row.
    var face: String {
        stage == "Egg" ? "( . )" : (art[1].trimmingCharacters(in: .whitespaces))
    }

    var summary: String {
        "\(stage), level \(level), \(Int(progress * 100)) percent of the way to level \(level + 1), \(today) XP today, mood \(mood)"
    }
}

func readCard(_ data: Data) -> Card? {
    (try? JSONSerialization.jsonObject(with: data)).flatMap(Card.init(json:))
}

func mono(_ size: CGFloat, _ weight: NSFont.Weight = .regular) -> NSFont {
    NSFont.monospacedSystemFont(ofSize: size, weight: weight)
}

func grouped(_ n: Int) -> String {
    let f = NumberFormatter()
    f.numberStyle = .decimal
    f.locale = Locale(identifier: "en_US")
    return f.string(from: NSNumber(value: n)) ?? String(n)
}

/// The panel: pure black, the creature in the card's own art, and the stats the card shows.
final class PanelView: NSView {
    var card: Card? { didSet { updateAccessibility(); needsDisplay = true } }
    var status = "" { didSet { needsDisplay = true } }
    var updated: Date? { didSet { needsDisplay = true } }
    var isBlinking = false { didSet { needsDisplay = true } }

    override var isFlipped: Bool { true }

    init() {
        super.init(frame: NSRect(x: 0, y: 0, width: panelWidth, height: 336))
        setAccessibilityElement(true)
        setAccessibilityRole(.group)
        updateAccessibility()
    }

    required init?(coder: NSCoder) { nil }

    func updateAccessibility() {
        setAccessibilityLabel(card.map { "CC level: \($0.summary)" } ?? "CC level: no creature yet")
    }

    func put(_ s: String, _ font: NSFont, _ color: NSColor, at p: NSPoint) {
        (s as NSString).draw(at: p, withAttributes: [.font: font, .foregroundColor: color])
    }

    func bar(_ rect: NSRect, _ fraction: CGFloat) {
        track.setFill()
        NSBezierPath(roundedRect: rect, xRadius: rect.height / 2, yRadius: rect.height / 2).fill()
        guard fraction > 0 else { return }
        orange.setFill()
        var filled = rect
        filled.size.width = max(rect.height, rect.width * fraction)
        NSBezierPath(roundedRect: filled, xRadius: rect.height / 2, yRadius: rect.height / 2).fill()
    }

    override func draw(_ dirtyRect: NSRect) {
        NSColor.black.setFill()
        bounds.fill()
        let left: CGFloat = 20
        guard let c = card else {
            put("( ? )", mono(18, .medium), orange, at: NSPoint(x: left, y: 24))
            put(status.isEmpty ? "No creature yet." : status, mono(12), dim, at: NSPoint(x: left, y: 60))
            put("Run /pet in Claude Code to hatch it.", mono(12), dim, at: NSPoint(x: left, y: 80))
            return
        }
        // The creature, in the card's own art; it blinks now and then while the panel is open.
        var y: CGFloat = 20
        for line in c.art {
            let shown = isBlinking ? line.replacingOccurrences(of: "o", with: "-").replacingOccurrences(of: "@", with: "-") : line
            put(shown, mono(16, .semibold), orange, at: NSPoint(x: left, y: y))
            y += 20
        }
        let side: CGFloat = left + 118
        let who = c.cls == "Unhatched" ? c.stage : "\(c.stage) \(c.cls)"
        put(who, NSFont.systemFont(ofSize: 15, weight: .semibold), .white, at: NSPoint(x: side, y: 20))
        put("Lv \(c.level)", NSFont.systemFont(ofSize: 22, weight: .bold), .white, at: NSPoint(x: side, y: 40))
        put("\(c.mood) · Health \(c.health)", NSFont.systemFont(ofSize: 12), dim, at: NSPoint(x: side, y: 70))

        // The level bar: from where this level began to the next one.
        y = 112
        bar(NSRect(x: left, y: y, width: bounds.width - 2 * left, height: 8), c.progress)
        let toNext = c.level >= 99 ? "Top level" : "\(grouped(max(0, c.xpNext - c.xp))) XP to Lv \(c.level + 1)"
        put(toNext, mono(11), dim, at: NSPoint(x: left, y: y + 14))
        let today = "+\(c.today) today"
        let todayWidth = (today as NSString).size(withAttributes: [.font: mono(11, .medium)]).width
        put(today, mono(11, .medium), orange, at: NSPoint(x: bounds.width - left - todayWidth, y: y + 14))

        // The six stats, as the card shows them.
        y = 160
        for name in statOrder {
            let v = c.stats[name] ?? 0
            put(name.capitalized, mono(12), .white, at: NSPoint(x: left, y: y))
            bar(NSRect(x: left + 84, y: y + 5, width: 170, height: 6), CGFloat(v) / 100)
            put(String(format: "%3d", v), mono(12), .white, at: NSPoint(x: left + 262, y: y))
            y += 22
        }
        if !c.brain.isEmpty {
            put("Brains: \(c.brain)", mono(11), dim, at: NSPoint(x: left, y: y + 2))
        }
        let when = updated.map { "Updated " + DateFormatter.localizedString(from: $0, dateStyle: .none, timeStyle: .short) } ?? ""
        let footer = status.isEmpty ? "\(when) · offline · Aura \(c.power)" : status
        put(footer, mono(10), dim, at: NSPoint(x: left, y: bounds.height - 22))
    }
}

/// The menu bar item, the panel it opens, and the hourly offline refresh.
final class PanelApp: NSObject, NSApplicationDelegate, NSPopoverDelegate {
    let python: String, scanner: String, claudeDir: String, cache: URL
    let item = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
    let popover = NSPopover()
    let view = PanelView()
    var isScanning = false
    var blinkTimer: Timer?

    init(python: String, scanner: String, claudeDir: String, cache: String) {
        self.python = python; self.scanner = scanner; self.claudeDir = claudeDir
        self.cache = URL(fileURLWithPath: cache)
    }

    func applicationDidFinishLaunching(_ note: Notification) {
        let vc = NSViewController()
        vc.view = view
        popover.contentViewController = vc
        popover.contentSize = view.frame.size
        popover.behavior = .transient
        popover.appearance = NSAppearance(named: .darkAqua)
        popover.delegate = self
        if let button = item.button {
            button.target = self
            button.action = #selector(clicked(_:))
            button.sendAction(on: [.leftMouseUp, .rightMouseUp])
        }
        if let data = try? Data(contentsOf: cache), let card = readCard(data) {
            show(card, at: modified(cache))
        } else {
            showTitle(nil)
        }
        refreshIfStale()
        Timer.scheduledTimer(withTimeInterval: 10 * 60, repeats: true) { [weak self] _ in self?.refreshIfStale() }
    }

    func modified(_ url: URL) -> Date? {
        (try? FileManager.default.attributesOfItem(atPath: url.path))?[.modificationDate] as? Date
    }

    func showTitle(_ card: Card?) {
        guard let button = item.button else { return }
        let title = card.map { "\($0.face) \($0.level)" } ?? "( ? )"
        button.attributedTitle = NSAttributedString(string: title, attributes: [.font: mono(12, .semibold)])
        button.setAccessibilityLabel(card.map { "CC level: \($0.stage), level \($0.level)" } ?? "CC level")
        button.toolTip = card.map { "\($0.stage) · Lv \($0.level) · \($0.mood)" } ?? "CC level"
    }

    func show(_ card: Card, at date: Date?) {
        view.card = card
        view.updated = date
        showTitle(card)
    }

    func refreshIfStale() {
        // No creature to show (no card yet, or one that could not be read) counts as stale too.
        let age = modified(cache).map { Date().timeIntervalSince($0) } ?? .infinity
        if age > staleAfter || view.card == nil { refresh() }
    }

    @objc func refresh() {
        guard !isScanning else { return }
        isScanning = true
        view.status = "Scoring your setup, offline…"
        let (python, scanner, claudeDir) = (self.python, self.scanner, self.claudeDir)
        DispatchQueue.global(qos: .utility).async { [weak self] in
            let p = Process()
            p.executableURL = URL(fileURLWithPath: python)
            p.arguments = [scanner, "--claude-dir", claudeDir, "--json", "--no-save"]
            let out = Pipe()
            p.standardOutput = out
            p.standardError = FileHandle.nullDevice
            var data = Data()
            var ok = false
            do {
                try p.run()
                DispatchQueue.global().asyncAfter(deadline: .now() + scanTimeout) { if p.isRunning { p.terminate() } }
                data = out.fileHandleForReading.readDataToEndOfFile()
                p.waitUntilExit()
                ok = p.terminationStatus == 0
            } catch {}
            DispatchQueue.main.async { self?.finish(ok ? data : nil) }
        }
    }

    func finish(_ data: Data?) {
        isScanning = false
        guard let data, let card = readCard(data) else {
            view.status = "Could not score this time. Right-click to try again."
            return
        }
        try? FileManager.default.createDirectory(at: cache.deletingLastPathComponent(), withIntermediateDirectories: true)
        if (try? data.write(to: cache, options: .atomic)) != nil {
            try? FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: cache.path)
        }
        view.status = ""
        show(card, at: Date())
    }

    @objc func clicked(_ sender: NSStatusBarButton) {
        let event = NSApp.currentEvent
        if event?.type == .rightMouseUp || event?.modifierFlags.contains(.control) == true {
            let menu = NSMenu()
            menu.addItem(withTitle: "Refresh", action: #selector(refresh), keyEquivalent: "r").target = self
            menu.addItem(.separator())
            menu.addItem(withTitle: "Quit CC level panel", action: #selector(quit), keyEquivalent: "q").target = self
            item.menu = menu
            sender.performClick(nil)
            item.menu = nil
        } else if popover.isShown {
            popover.performClose(nil)
        } else {
            refreshIfStale()
            popover.show(relativeTo: sender.bounds, of: sender, preferredEdge: .minY)
            popover.contentViewController?.view.window?.makeKey()
        }
    }

    @objc func quit() { NSApp.terminate(nil) }

    // A blink every few seconds, only while the panel is open.
    func popoverDidShow(_ note: Notification) {
        blinkTimer = Timer.scheduledTimer(withTimeInterval: 3.5, repeats: true) { [weak self] _ in
            self?.view.isBlinking = true
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.18) { self?.view.isBlinking = false }
        }
    }

    func popoverDidClose(_ note: Notification) {
        blinkTimer?.invalidate()
        blinkTimer = nil
    }
}

func option(_ name: String) -> String? {
    let args = CommandLine.arguments
    guard let i = args.firstIndex(of: name), i + 1 < args.count else { return nil }
    return args[i + 1]
}

let app = NSApplication.shared

if let out = option("--snapshot") {
    guard let path = option("--card"), let data = FileManager.default.contents(atPath: path), let card = readCard(data) else {
        FileHandle.standardError.write("cclevel-panel: --snapshot needs --card with a card from `cclevel.py --json`\n".data(using: .utf8)!)
        exit(1)
    }
    let view = PanelView()
    view.card = card
    view.updated = Date(timeIntervalSince1970: 0)
    let size = view.bounds.size
    guard let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: Int(size.width * 2), pixelsHigh: Int(size.height * 2),
                                     bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
                                     colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0) else { exit(1) }
    rep.size = size
    view.cacheDisplay(in: view.bounds, to: rep)
    guard let png = rep.representation(using: .png, properties: [:]), (try? png.write(to: URL(fileURLWithPath: out))) != nil else {
        exit(1)
    }
    exit(0)
}

guard let python = option("--python"), let scanner = option("--scanner"), let claudeDir = option("--claude-dir"),
      let cache = option("--cache") else {
    FileHandle.standardError.write("cclevel-panel: started by `cclevel.py --panel on`; run that instead\n".data(using: .utf8)!)
    exit(1)
}
let delegate = PanelApp(python: python, scanner: scanner, claudeDir: claudeDir, cache: cache)
app.setActivationPolicy(.accessory)
app.delegate = delegate
app.run()
