// CC level panel: your cclevel creature in the macOS menu bar. Click it for a small black panel with the creature and its
// stats; right-click (or control-click) for Refresh and Quit.
//
// It runs the offline card (`cclevel.py --json --no-save`, which writes nothing) when its last result is more than an hour
// old, keeps that result in card.json beside itself, and makes no network call. `cclevel.py --panel on --yes` builds it on
// this Mac with Apple's swiftc and starts it at login; `cclevel.py --panel off` removes it.
//
// Three tabs: Creature (the art and the stats), Fix next (the card's top Needs, how to fix each, and its docs page) and Learn
// (the training path, each stat's next lesson, and the tip of the day). Links open Claude Code's docs pages only.
//
// `--snapshot OUT.png --card CARD.json [--tab creature|fix|learn]` draws the panel into a picture and exits (for tests and
// previews).
import AppKit

let statOrder = ["grind", "appetite", "arsenal", "brains", "autonomy", "craft"]
let staleAfter: TimeInterval = 60 * 60
let scanTimeout: TimeInterval = 120
let orange = NSColor(srgbRed: 0xd9 / 255, green: 0x77 / 255, blue: 0x57 / 255, alpha: 1)
let dim = NSColor(white: 0.55, alpha: 1)
let track = NSColor(white: 0.16, alpha: 1)
let panelWidth: CGFloat = 360
let tabBarHeight: CGFloat = 44
let contentHeight: CGFloat = 356
let docsPrefix = "https://code.claude.com/docs/"

/// A docs page from data this program does not control: only Claude Code's own docs, over https.
func docsURL(_ value: Any?) -> URL? {
    guard let s = value as? String, s.hasPrefix(docsPrefix), s.count <= 200, let url = URL(string: s),
          url.scheme == "https", url.host == "code.claude.com" else { return nil }
    return url
}

/// Text from data this program does not control: present, not empty, not too long.
func shortText(_ value: Any?, _ max: Int = 300) -> String? {
    guard let s = value as? String, !s.isEmpty, s.count <= max else { return nil }
    return s
}

func small(_ value: Any?) -> Int? {
    guard let n = value as? NSNumber, CFGetTypeID(n) != CFBooleanGetTypeID(), (0...1000).contains(n.intValue) else { return nil }
    return n.intValue
}

/// Something to do: what it is, how to do it, and the docs page that explains it.
struct Advice {
    let title: String, how: String, docs: URL?

    init?(_ value: Any?, titleKey: String) {
        guard let o = value as? [String: Any], let title = shortText(o[titleKey]) else { return nil }
        self.title = title
        self.how = shortText(o["how"]) ?? ""
        self.docs = docsURL(o["docs"])
    }
}

/// The training path: lessons done per stat, and each stat's next lesson.
struct Training {
    struct Stat { let name: String, done: Int, total: Int, next: Advice? }
    let done: Int, total: Int, checked: String
    let stats: [Stat]

    init?(_ value: Any?) {
        guard let o = value as? [String: Any], let done = small(o["done"]), let total = small(o["total"]),
              let raw = o["stats"] as? [[String: Any]] else { return nil }
        self.done = done
        self.total = total
        self.checked = shortText(o["checked"], 20) ?? ""
        self.stats = raw.prefix(statOrder.count).compactMap { s in
            guard let name = shortText(s["stat"], 20), statOrder.contains(name), let d = small(s["done"]),
                  let t = small(s["total"]) else { return nil }
            return Stat(name: name, done: d, total: t, next: Advice(s["next"], titleKey: "title"))
        }
    }
}

/// The numbers behind the card, from data this program does not control: every field is checked.
struct Card {
    let stage: String, cls: String, brain: String, mood: String
    let level: Int, xp: Int, xpStart: Int, xpNext: Int, today: Int, health: Int, power: Int
    let stats: [String: Int]
    let art: [String]
    /// The Fix next and Learn tabs' data: nil on a card from before they existed (it fills in at the next score).
    let fix: [Advice]?
    let training: Training?
    let tip: (stat: String, advice: Advice)?

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
        self.fix = (o["fix"] as? [Any]).map { $0.prefix(5).compactMap { Advice($0, titleKey: "text") } }
        self.training = Training(o["learn"])
        if let t = o["tip"] as? [String: Any], let stat = shortText(t["stat"], 20), let advice = Advice(t, titleKey: "text") {
            self.tip = (stat, advice)
        } else {
            self.tip = nil
        }
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
        super.init(frame: NSRect(x: 0, y: 0, width: panelWidth, height: contentHeight))
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

final class FlippedView: NSView {
    override var isFlipped: Bool { true }
}

/// A docs link: opens the page in the browser, and only Claude Code's docs (checked when the card was read).
final class DocsButton: NSButton {
    var url: URL?
}

/// The whole panel: a tab switch on top, then the Creature tab or one of the two text tabs.
final class TabsView: NSView {
    static let names = ["Creature", "Fix next", "Learn"]
    let tabs = NSSegmentedControl(labels: TabsView.names, trackingMode: .selectOne, target: nil, action: nil)
    let creature = PanelView()
    let scroll = NSScrollView()
    let list = FlippedView()
    var onLink: ((URL) -> Void)?
    var card: Card? { didSet { creature.card = card; rebuild() } }

    override var isFlipped: Bool { true }

    init() {
        super.init(frame: NSRect(x: 0, y: 0, width: panelWidth, height: tabBarHeight + contentHeight))
        appearance = NSAppearance(named: .darkAqua)
        tabs.selectedSegment = 0
        tabs.target = self
        tabs.action = #selector(switched)
        tabs.sizeToFit()
        tabs.frame.origin = NSPoint(x: (panelWidth - tabs.frame.width) / 2, y: 12)
        tabs.setAccessibilityLabel("CC level panel tabs")
        creature.frame.origin = NSPoint(x: 0, y: tabBarHeight)
        scroll.frame = NSRect(x: 0, y: tabBarHeight, width: panelWidth, height: contentHeight)
        scroll.drawsBackground = false
        scroll.hasVerticalScroller = true
        // A scroller that shows whenever a tab is taller than the panel, so it is clear there is more below.
        scroll.scrollerStyle = .legacy
        scroll.autohidesScrollers = true
        scroll.documentView = list
        addSubview(tabs)
        addSubview(creature)
        addSubview(scroll)
        show(0)
    }

    required init?(coder: NSCoder) { nil }

    override func draw(_ dirtyRect: NSRect) {
        NSColor.black.setFill()
        bounds.fill()
    }

    @objc func switched() { show(tabs.selectedSegment) }

    func show(_ tab: Int) {
        tabs.selectedSegment = tab
        creature.isHidden = tab != 0
        scroll.isHidden = tab == 0
        rebuild()
    }

    // The text tabs, laid out top to bottom.
    private var y: CGFloat = 0
    private let left: CGFloat = 20
    private var width: CGFloat { panelWidth - 2 * left }

    private func label(_ text: String, _ font: NSFont, _ color: NSColor, gap: CGFloat = 4) {
        let field = NSTextField(wrappingLabelWithString: text)
        field.font = font
        field.textColor = color
        field.isSelectable = false
        field.preferredMaxLayoutWidth = width
        let height = field.cell?.cellSize(forBounds: NSRect(x: 0, y: 0, width: width, height: 10_000)).height ?? 16
        field.frame = NSRect(x: left, y: y, width: width, height: ceil(height))
        list.addSubview(field)
        y += ceil(height) + gap
    }

    private func link(_ url: URL?, gap: CGFloat = 14) {
        guard let url else { y += gap - 4; return }
        let page = url.path.split(separator: "/").last.map(String.init) ?? "docs"
        let button = DocsButton(title: "", target: self, action: #selector(open(_:)))
        button.url = url
        button.isBordered = false
        button.attributedTitle = NSAttributedString(string: "Docs: \(page) ↗", attributes: [
            .font: mono(11, .medium), .foregroundColor: orange, .underlineStyle: NSUnderlineStyle.single.rawValue])
        button.setAccessibilityLabel("Open the Claude Code docs page \(page)")
        button.sizeToFit()
        button.frame.origin = NSPoint(x: left - 2, y: y)
        list.addSubview(button)
        y += button.frame.height + gap
    }

    @objc func open(_ sender: DocsButton) {
        guard let url = sender.url, url.absoluteString.hasPrefix(docsPrefix) else { return }
        onLink?(url)
    }

    private func capitalized(_ s: String) -> String { s.prefix(1).uppercased() + s.dropFirst() }

    func rebuild() {
        list.subviews.forEach { $0.removeFromSuperview() }
        y = 8
        switch tabs.selectedSegment {
        case 1: buildFix()
        case 2: buildLearn()
        default: return
        }
        list.frame = NSRect(x: 0, y: 0, width: panelWidth, height: max(contentHeight, y + 8))
    }

    private func waiting() {
        label(card == nil ? "No creature yet." : "This tab fills in at the next score.", .systemFont(ofSize: 13), dim)
        label("Right-click the creature in the menu bar and choose Refresh.", .systemFont(ofSize: 12), dim)
    }

    private func buildFix() {
        guard let fix = card?.fix else { return waiting() }
        label("Fix next", .systemFont(ofSize: 15, weight: .semibold), .white, gap: 2)
        label("What would raise Health or Brains most, from your last score.", .systemFont(ofSize: 11.5), dim, gap: 14)
        if fix.isEmpty {
            label("Nothing to fix right now. Touch grass.", .systemFont(ofSize: 13), .white)
            return
        }
        for (i, item) in fix.enumerated() {
            label("\(i + 1). \(capitalized(item.title))", .systemFont(ofSize: 12.5, weight: .medium), .white, gap: 3)
            if !item.how.isEmpty { label("How: \(item.how)", .systemFont(ofSize: 11.5), dim, gap: 3) }
            link(item.docs)
        }
    }

    private func buildLearn() {
        guard let training = card?.training else { return waiting() }
        label("Learn · \(training.done) of \(training.total) lessons done", .systemFont(ofSize: 15, weight: .semibold), .white, gap: 12)
        if let tip = card?.tip {
            label("Tip of the day (\(capitalized(tip.stat)))", mono(11, .medium), orange, gap: 3)
            label(capitalized(tip.advice.title), .systemFont(ofSize: 12.5), .white, gap: 3)
            link(tip.advice.docs, gap: 16)
        }
        for stat in training.stats {
            let state = stat.done >= stat.total ? " · trained" : ""
            label("\(capitalized(stat.name))  \(stat.done)/\(stat.total)\(state)", mono(12, .medium), .white, gap: 3)
            if let next = stat.next {
                label("Next: \(next.title)", .systemFont(ofSize: 12), .white, gap: 2)
                if !next.how.isEmpty { label("How: \(next.how)", .systemFont(ofSize: 11.5), dim, gap: 3) }
                link(next.docs, gap: 12)
            } else {
                y += 8
            }
        }
        let checked = training.checked.isEmpty ? "" : " Checked against the docs on \(training.checked)."
        label("Lessons tick themselves when your Claude Code logs show them done. They never change your level.\(checked)",
              .systemFont(ofSize: 10.5), dim)
    }
}

/// The menu bar item, the panel it opens, and the hourly offline refresh.
final class PanelApp: NSObject, NSApplicationDelegate, NSPopoverDelegate {
    let python: String, scanner: String, claudeDir: String, cache: URL
    let item = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
    let popover = NSPopover()
    let root = TabsView()
    var isScanning = false
    var blinkTimer: Timer?

    init(python: String, scanner: String, claudeDir: String, cache: String) {
        self.python = python; self.scanner = scanner; self.claudeDir = claudeDir
        self.cache = URL(fileURLWithPath: cache)
    }

    func applicationDidFinishLaunching(_ note: Notification) {
        let vc = NSViewController()
        vc.view = root
        popover.contentViewController = vc
        popover.contentSize = root.frame.size
        root.onLink = { [weak self] url in
            NSWorkspace.shared.open(url)
            self?.popover.performClose(nil)
        }
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
        root.card = card
        root.creature.updated = date
        showTitle(card)
    }

    func refreshIfStale() {
        // No creature to show (no card yet, or one that could not be read) counts as stale too.
        let age = modified(cache).map { Date().timeIntervalSince($0) } ?? .infinity
        if age > staleAfter || root.card == nil { refresh() }
    }

    @objc func refresh() {
        guard !isScanning else { return }
        isScanning = true
        root.creature.status = "Scoring your setup, offline…"
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
            root.creature.status = "Could not score this time. Right-click to try again."
            return
        }
        try? FileManager.default.createDirectory(at: cache.deletingLastPathComponent(), withIntermediateDirectories: true)
        if (try? data.write(to: cache, options: .atomic)) != nil {
            try? FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: cache.path)
        }
        root.creature.status = ""
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
            self?.root.creature.isBlinking = true
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.18) { self?.root.creature.isBlinking = false }
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
    let view = TabsView()
    view.card = card
    view.creature.updated = Date(timeIntervalSince1970: 0)
    if let tab = option("--tab") {
        guard let i = ["creature", "fix", "learn"].firstIndex(of: tab) else {
            FileHandle.standardError.write("cclevel-panel: --tab is creature, fix or learn\n".data(using: .utf8)!)
            exit(1)
        }
        view.show(i)
    }
    view.layoutSubtreeIfNeeded()
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
