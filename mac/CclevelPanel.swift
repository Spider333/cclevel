// CC level panel: your cclevel creature in the macOS menu bar. Click it for a small black panel with the creature and its
// stats; right-click (or control-click) for Refresh and Quit.
//
// It runs the offline card (`cclevel.py --json --no-save`, which writes nothing) when its last result is more than an hour
// old, keeps that result in card.json beside itself, and makes no network call. `cclevel.py --panel on --yes` builds it on
// this Mac with Apple's swiftc and starts it at login; `cclevel.py --panel off` removes it.
//
// An overview of rounded cards: the creature, Level and Today, the six stats and a 14-day Trend, then two buttons that
// open Fix next (the card's top Needs, how to fix each, and its docs page) and Learn (the training path, each stat's next
// lesson, and the tip of the day), each with a way back. Links open Claude Code's docs pages only.
//
// The Creature card plays the creature's rendered loop while the panel is open (creatures/<stage>_<class>.mp4 beside the
// panel for its class look, else creatures/<stage>.mp4), a still of its first frame otherwise or with Reduce Motion on, and
// the card's own text art when there is no clip.
//
// `--snapshot OUT.png --card CARD.json [--clips DIR] [--page home|fix|learn] [--height PT] [--full | --scrolled]` draws
// what the panel shows on that page (with --height, as on a screen with that much room; with --full, the whole page; with
// --scrolled, the page scrolled to its end, under the header that stays put) into a picture,
// prints the VoiceOver label of each thing on it, one per line, top to bottom, and exits (for tests and previews).
import AppKit
import AVFoundation

let statOrder = ["grind", "appetite", "arsenal", "brains", "autonomy", "craft"]
let staleAfter: TimeInterval = 60 * 60
let scanTimeout: TimeInterval = 120
let orange = NSColor(srgbRed: 0xd9 / 255, green: 0x77 / 255, blue: 0x57 / 255, alpha: 1)
let dim = NSColor(white: 0.55, alpha: 1)
let track = NSColor(white: 0.22, alpha: 1)
let cardFill = NSColor(white: 0.1, alpha: 1)
let panelWidth: CGFloat = 360
let panelHeight: CGFloat = 696
/// The scanner's DAY_CAP: the most XP one day can bank (a test keeps the two the same).
let dayCap = 550
let trendDays = 14
let edge: CGFloat = 12      // page edge to a card
let inset: CGFloat = 14     // card edge to what is in it
let gap: CGFloat = 10       // between cards
let corner: CGFloat = 16
let headerHeight: CGFloat = 40
let creatureHeight: CGFloat = 176
let tileHeight: CGFloat = 104
let buttonHeight: CGFloat = 48
let creatureBox = NSRect(x: 12, y: 12, width: 152, height: 152)
let creatureCorner: CGFloat = 12
/// The rendered loop for each stage, beside the panel in creatures/<name>.mp4 (copied there by --panel on).
let clipNames = ["Egg": "egg", "Hatchling": "hatchling", "Lil Guy": "lil_guy", "Big Guy": "big_guy",
                 "Gigachad": "gigachad", "GOAT": "goat"]
/// The class look's file suffix: creatures/<stage>_<class>.mp4, when that stage has one for the class.
let classNames = ["Shipper": "shipper", "AFK Farmer": "afk_farmer", "Loot Goblin": "loot_goblin",
                  "Tokenmaxxer": "tokenmaxxer", "Perfectly Balanced": "balanced", "Noob": "noob"]

/// Holds the first frame while it is decoded on another queue.
final class FrameBox: @unchecked Sendable {
    var image: CGImage?
}

/// The first frame of a clip, to show before it plays, in pictures, and when Reduce Motion is on.
func firstFrame(_ url: URL) -> NSImage? {
    let generator = AVAssetImageGenerator(asset: AVURLAsset(url: url))
    generator.appliesPreferredTrackTransform = true
    let box = FrameBox()
    let done = DispatchSemaphore(value: 0)
    generator.generateCGImageAsynchronously(for: .zero) { image, _, _ in
        box.image = image
        done.signal()
    }
    guard done.wait(timeout: .now() + 5) == .success, let image = box.image else { return nil }
    return NSImage(cgImage: image, size: creatureBox.size)
}
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

/// The Trend card's numbers: exactly 14 whole numbers from 0 to the day cap, or none at all.
func trendNumbers(_ value: Any?) -> [Int]? {
    guard let list = value as? [Any], list.count == trendDays else { return nil }
    var out: [Int] = []
    for item in list {
        guard let n = item as? NSNumber, CFGetTypeID(n) != CFBooleanGetTypeID(), n.doubleValue.rounded() == n.doubleValue,
              n.doubleValue >= 0, n.doubleValue <= Double(dayCap) else { return nil }
        out.append(n.intValue)
    }
    return out
}

/// The scanner's days are UTC days, written yyyy-mm-dd.
func utcFormatter(_ format: String) -> DateFormatter {
    let f = DateFormatter()
    f.locale = Locale(identifier: "en_US_POSIX")
    f.timeZone = TimeZone(identifier: "UTC")
    f.dateFormat = format
    return f
}

func utcDay(_ s: String) -> Date? {
    let f = utcFormatter("yyyy-MM-dd")
    guard let d = f.date(from: s), f.string(from: d) == s else { return nil }
    return d
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
    /// The Fix next and Learn cards' data: nil on a card from before they existed (it fills in at the next score).
    let fix: [Advice]?
    let training: Training?
    let tip: (stat: String, advice: Advice)?
    /// The Trend card's data: nil on a card from before 0.14.0, or one that does not add up.
    let xpByDay: [Int]?
    /// The UTC day the card was scored, yyyy-mm-dd: where the Trend ends, and what the Today tile is about.
    let generated: String?

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
        let day = text("generated", 10).flatMap { utcDay($0) != nil ? $0 : nil }
        let trend = trendNumbers((o["raw"] as? [String: Any])?["xp_by_day"])
        // The day stands on its own (the Today tile needs it on any card); the Trend needs both.
        self.generated = day
        self.xpByDay = day == nil ? nil : trend
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

    /// The day this card was scored, when that is not today (UTC): a sleeping Mac or failed scans leave an older card.
    var olderDay: String? {
        guard let generated, let day = utcDay(generated),
              generated != utcFormatter("yyyy-MM-dd").string(from: Date()) else { return nil }
        return utcFormatter("MMM d").string(from: day)
    }

    var who: String { cls == "Unhatched" ? stage : "\(stage) \(cls)" }
    var todayShown: Int { min(today, dayCap) }
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

func capitalized(_ s: String) -> String { s.prefix(1).uppercased() + s.dropFirst() }

// Drawing, inside a card's own (flipped) coordinates.

let bigFont = NSFont.monospacedDigitSystemFont(ofSize: 26, weight: .bold)

func textWidth(_ s: String, _ font: NSFont) -> CGFloat {
    ceil((s as NSString).size(withAttributes: [.font: font]).width)
}

/// One line of text; with a width, a line too long for it ends in "…".
func put(_ s: String, _ font: NSFont, _ color: NSColor, at p: NSPoint, width: CGFloat? = nil) {
    guard let width else {
        (s as NSString).draw(at: p, withAttributes: [.font: font, .foregroundColor: color])
        return
    }
    let style = NSMutableParagraphStyle()
    style.lineBreakMode = .byTruncatingTail
    let rect = NSRect(x: p.x, y: p.y, width: width, height: ceil(font.ascender - font.descender + font.leading) + 2)
    (s as NSString).draw(with: rect, options: [.usesLineFragmentOrigin, .truncatesLastVisibleLine],
                         attributes: [.font: font, .foregroundColor: color, .paragraphStyle: style])
}

func bar(_ rect: NSRect, _ fraction: CGFloat) {
    track.setFill()
    NSBezierPath(roundedRect: rect, xRadius: rect.height / 2, yRadius: rect.height / 2).fill()
    guard fraction > 0 else { return }
    orange.setFill()
    var filled = rect
    filled.size.width = max(rect.height, rect.width * min(1, fraction))
    NSBezierPath(roundedRect: filled, xRadius: rect.height / 2, yRadius: rect.height / 2).fill()
}

func fillCard(_ rect: NSRect) {
    cardFill.setFill()
    NSBezierPath(roundedRect: rect, xRadius: corner, yRadius: corner).fill()
}

/// A card's title row: a small orange symbol, the title, and an optional note on the right.
func heading(_ title: String, _ symbol: String, right: String? = nil, width: CGFloat, top: CGFloat = inset) {
    var x = inset
    let config = NSImage.SymbolConfiguration(pointSize: 11, weight: .semibold)
        .applying(NSImage.SymbolConfiguration(paletteColors: [orange]))
    if let icon = NSImage(systemSymbolName: symbol, accessibilityDescription: nil)?.withSymbolConfiguration(config) {
        let size = icon.size
        icon.draw(in: NSRect(x: x, y: top + 8 - size.height / 2, width: size.width, height: size.height))
        x += size.width + 6
    }
    let font = NSFont.systemFont(ofSize: 13, weight: .semibold)
    put(title, font, .white, at: NSPoint(x: x, y: top))
    if let right {
        let note = NSFont.systemFont(ofSize: 11.5)
        let w = min(textWidth(right, note), width - x - textWidth(title, font) - 2 * inset)
        put(right, note, dim, at: NSPoint(x: width - inset - w, y: top + 1.5), width: w)
    }
}

/// The Creature card: the creature (its rendered loop, or the card's own art), who it is, and how it feels.
final class PanelView: NSView {
    var card: Card? { didSet { updateAccessibility(); loadClip(); needsDisplay = true } }
    var isBlinking = false { didSet { needsDisplay = true } }
    /// Where the stage loops are; nil, or a stage without its file, draws the card's art instead.
    var clipsDir: URL? { didSet { clipStage = nil; loadClip() } }

    private var clipStage: String?
    private var still: NSImage?
    private let video = NSView(frame: creatureBox)
    private let playerLayer = AVPlayerLayer()
    private var player: AVQueuePlayer?
    private var looper: AVPlayerLooper?
    private var wantsPlay = false

    override var isFlipped: Bool { true }

    init() {
        super.init(frame: NSRect(x: 0, y: 0, width: 300, height: creatureHeight))
        setAccessibilityElement(true)
        setAccessibilityRole(.group)
        updateAccessibility()
        // The loops are rendered on black: their square gets the same rounded corners as the still under it.
        video.wantsLayer = true
        video.layer?.backgroundColor = NSColor.black.cgColor
        video.layer?.cornerRadius = creatureCorner
        video.layer?.masksToBounds = true
        playerLayer.frame = video.bounds
        playerLayer.videoGravity = .resizeAspect
        playerLayer.backgroundColor = NSColor.black.cgColor
        video.layer?.addSublayer(playerLayer)
        video.isHidden = true
        video.setAccessibilityElement(false)   // decorative: the card's label says who the creature is
        addSubview(video)
        // Reduce Motion switched on (or off) while the panel is open takes effect at once.
        NSWorkspace.shared.notificationCenter.addObserver(
            self, selector: #selector(motionSettingChanged),
            name: NSWorkspace.accessibilityDisplayOptionsDidChangeNotification, object: nil)
    }

    @objc private func motionSettingChanged() { setPlaying(wantsPlay) }

    /// Loads the loop for the card's stage and class, once per look: its first frame now, the player for later.
    /// The class look (<stage>_<class>.mp4) comes first; a stage without one plays the stage's own loop.
    private func loadClip() {
        let key = card.map { "\($0.stage)|\($0.cls)" }
        guard key != clipStage else { return }
        clipStage = key
        player?.pause()
        looper = nil
        player = nil
        playerLayer.player = nil
        still = nil
        video.isHidden = true
        guard let card, let name = clipNames[card.stage], let dir = clipsDir else { return }
        let names = (classNames[card.cls].map { ["\(name)_\($0)"] } ?? []) + [name]
        // The first one that is there AND decodes: a damaged class look falls back to the stage's own loop.
        var found: (url: URL, frame: NSImage)?
        for url in names.map({ dir.appendingPathComponent("\($0).mp4") })
        where FileManager.default.isReadableFile(atPath: url.path) {
            if let frame = firstFrame(url) {
                found = (url, frame)
                break
            }
        }
        guard let found else { return }
        let (url, frame) = found
        still = frame
        let queue = AVQueuePlayer()
        queue.isMuted = true
        queue.preventsDisplaySleepDuringVideoPlayback = false
        looper = AVPlayerLooper(player: queue, templateItem: AVPlayerItem(url: url))
        player = queue
        playerLayer.player = queue
        setPlaying(wantsPlay)
    }

    /// Plays the loop while the panel is open, unless Reduce Motion is on: then the still stays.
    func setPlaying(_ on: Bool) {
        wantsPlay = on
        guard let player else { return }
        if on && !NSWorkspace.shared.accessibilityDisplayShouldReduceMotion {
            video.isHidden = false
            player.play()
        } else {
            player.pause()
            if NSWorkspace.shared.accessibilityDisplayShouldReduceMotion {
                video.isHidden = true   // the first-frame still drawn underneath shows instead
            }
        }
    }

    required init?(coder: NSCoder) { nil }

    func updateAccessibility() {
        guard let c = card else { return setAccessibilityLabel("Creature: no creature yet") }
        let brains = c.brain.isEmpty ? "" : ", Brains: \(c.brain)"
        setAccessibilityLabel("Creature: \(c.who), mood \(c.mood), Health \(c.health)\(brains)")
    }

    override func draw(_ dirtyRect: NSRect) {
        fillCard(bounds)
        let side = creatureBox.maxX + 14
        let width = bounds.width - side - inset
        guard let c = card else {
            let unknown = mono(26, .medium)
            let w = ("( ? )" as NSString).size(withAttributes: [.font: unknown]).width
            put("( ? )", unknown, orange, at: NSPoint(x: creatureBox.midX - w / 2, y: creatureBox.midY - 16))
            put("No creature yet.", .systemFont(ofSize: 14, weight: .semibold), .white, at: NSPoint(x: side, y: 60), width: width)
            // Two lines: the hint is wider than the column beside the bigger creature box.
            put("Run /pet in Claude Code", .systemFont(ofSize: 11), dim, at: NSPoint(x: side, y: 84), width: width)
            put("to hatch it.", .systemFont(ofSize: 11), dim, at: NSPoint(x: side, y: 98), width: width)
            return
        }
        // The creature: its rendered loop's first frame (the loop plays over it while the panel is open), or
        // the card's own art, which blinks now and then, centred in the creature's box.
        if let still {
            NSGraphicsContext.saveGraphicsState()
            NSBezierPath(roundedRect: creatureBox, xRadius: creatureCorner, yRadius: creatureCorner).addClip()
            still.draw(in: creatureBox)
            NSGraphicsContext.restoreGraphicsState()
        } else {
            let art = mono(19, .semibold)
            let step: CGFloat = 26
            let w = c.art.map { ($0 as NSString).size(withAttributes: [.font: art]).width }.max() ?? 0
            var y = creatureBox.midY - CGFloat(c.art.count) * step / 2
            for line in c.art {
                let shown = isBlinking ? line.replacingOccurrences(of: "o", with: "-").replacingOccurrences(of: "@", with: "-") : line
                put(shown, art, orange, at: NSPoint(x: creatureBox.midX - w / 2, y: y))
                y += step
            }
        }
        // One short fact a line, so every mood, class and Brains title fits the column beside the creature,
        // even when the overview scrolls.
        put(c.stage, .systemFont(ofSize: 16, weight: .semibold), .white, at: NSPoint(x: side, y: 43), width: width)
        if c.cls != "Unhatched" {
            put(c.cls, .systemFont(ofSize: 12, weight: .medium), orange, at: NSPoint(x: side, y: 65), width: width)
        }
        put(c.mood, .systemFont(ofSize: 11), dim, at: NSPoint(x: side, y: 87), width: width)
        put("Health \(c.health)", .systemFont(ofSize: 11), dim, at: NSPoint(x: side, y: 103), width: width)
        if !c.brain.isEmpty {
            put("Brains: \(c.brain)", .systemFont(ofSize: 11), dim, at: NSPoint(x: side, y: 119), width: width)
        }
    }
}

/// The page that scrolls: black behind the cards, like the panel around it.
final class PageList: NSView {
    override var isFlipped: Bool { true }

    override func draw(_ dirtyRect: NSRect) {
        NSColor.black.setFill()
        dirtyRect.fill()
    }
}

/// One rounded card on the page: `paint` draws its numbers and bars, text views inside it hold its wrapped text.
final class CardView: NSView {
    let paint: ((CGFloat) -> Void)?

    override var isFlipped: Bool { true }

    init(_ label: String, paint: ((CGFloat) -> Void)? = nil) {
        self.paint = paint
        super.init(frame: .zero)
        setAccessibilityElement(true)
        setAccessibilityRole(.group)
        setAccessibilityLabel(label)
    }

    required init?(coder: NSCoder) { nil }

    override func draw(_ dirtyRect: NSRect) {
        fillCard(bounds)
        paint?(bounds.width)
    }
}

/// A docs link: opens the page in the browser, and only Claude Code's docs (checked when the card was read).
final class DocsButton: NSButton {
    var url: URL?
}

/// A half-width card at the bottom of the overview that opens one of the two lists, Fix next or Learn.
final class TileButton: NSButton {
    private let name: String, symbol: String, note: String
    private var hovering = false { didSet { needsDisplay = true } }
    private var hover: NSTrackingArea?

    override var isFlipped: Bool { true }

    init(_ name: String, _ symbol: String, note: String, label: String, target: AnyObject, action: Selector) {
        self.name = name
        self.symbol = symbol
        self.note = note
        super.init(frame: .zero)
        self.target = target
        self.action = action
        isBordered = false
        title = ""
        setAccessibilityLabel(label)
    }

    required init?(coder: NSCoder) { nil }

    override func updateTrackingAreas() {
        super.updateTrackingAreas()
        if let hover { removeTrackingArea(hover) }
        let area = NSTrackingArea(rect: .zero, options: [.mouseEnteredAndExited, .activeAlways, .inVisibleRect], owner: self)
        addTrackingArea(area)
        hover = area
    }

    override func mouseEntered(with event: NSEvent) { hovering = true }
    override func mouseExited(with event: NSEvent) { hovering = false }

    override func draw(_ dirtyRect: NSRect) {
        // A little lighter while the pointer is on it, lighter still while it is pressed.
        NSColor(white: isHighlighted ? 0.18 : hovering ? 0.14 : 0.1, alpha: 1).setFill()
        NSBezierPath(roundedRect: bounds, xRadius: corner, yRadius: corner).fill()
        heading(name, symbol, right: note.isEmpty ? "›" : "\(note)  ›", width: bounds.width, top: (bounds.height - 17) / 2)
    }

    // The keyboard focus ring follows the card's rounded corners.
    override func drawFocusRingMask() {
        NSBezierPath(roundedRect: bounds, xRadius: corner, yRadius: corner).fill()
    }

    override var focusRingMaskBounds: NSRect { bounds }
}

/// What the panel shows: the overview of cards, or one of the two lists it opens.
enum Page: String {
    case home, fix, learn
}

/// The whole panel, in a popover of a fixed size: the overview of cards, or the Fix next or Learn list with a way back.
final class PageView: NSView {
    let scroll = NSScrollView()
    let list = PageList()
    let creature = PanelView()
    var onLink: ((URL) -> Void)?
    var card: Card? { didSet { creature.card = card; rebuild() } }
    var status = "" { didSet { updateHeader() } }
    var updated: Date? { didSet { updateHeader() } }
    private(set) var page = Page.home
    /// What VoiceOver finds on the page, top to bottom: --snapshot prints their labels.
    private(set) var cards: [NSView] = []

    private let title = NSTextField(labelWithString: "CC level")
    private let back = NSButton(title: "", target: nil, action: nil)
    private let note = NSTextField(wrappingLabelWithString: "")
    private let footer = NSTextField(labelWithString: "")
    /// What stays in the scrolling page between rebuilds (the header sits above it, pinned).
    private var kept: [NSView] { [footer, creature] }
    private var isOpen = false
    /// How tall the page's content came out at the last layout.
    private var contentHeight: CGFloat = 0
    /// The scrolling part: everything below the header.
    private var scrollHeight: CGFloat { bounds.height - headerHeight }
    /// The page's width: the panel's, less the scroller when the page is taller than the panel.
    private var pageWidth = panelWidth
    private var cardWidth: CGFloat { pageWidth - 2 * edge }
    private var innerWidth: CGFloat { cardWidth - 2 * inset }

    override var isFlipped: Bool { true }

    init() {
        super.init(frame: NSRect(x: 0, y: 0, width: panelWidth, height: panelHeight))
        appearance = NSAppearance(named: .darkAqua)
        placeScroll()
        scroll.drawsBackground = false
        scroll.hasVerticalScroller = true
        // A scroller that shows whenever a list is taller than the panel, so it is clear there is more below.
        scroll.scrollerStyle = .legacy
        scroll.autohidesScrollers = true
        scroll.documentView = list
        addSubview(scroll)
        // A mouse plugged in or out can switch scroll views to overlay scrollers, which hide: keep this one showing.
        NotificationCenter.default.addObserver(self, selector: #selector(keepScroller),
                                               name: NSScroller.preferredScrollerStyleDidChangeNotification, object: nil)
        title.font = .systemFont(ofSize: 15, weight: .semibold)
        title.textColor = .white
        title.sizeToFit()
        title.frame.origin = NSPoint(x: edge + 2, y: (headerHeight - title.frame.height) / 2 + 2)
        back.isBordered = false
        back.attributedTitle = NSAttributedString(string: "‹ Back", attributes: [
            .font: NSFont.systemFont(ofSize: 14, weight: .semibold), .foregroundColor: orange])
        back.setAccessibilityLabel("Back to the overview")
        back.target = self
        back.action = #selector(goBack)
        back.sizeToFit()
        back.frame.origin = NSPoint(x: edge, y: (headerHeight - back.frame.height) / 2 + 2)
        note.font = .systemFont(ofSize: 11)
        note.textColor = dim
        note.alignment = .right
        note.isSelectable = false
        note.maximumNumberOfLines = 2
        footer.font = .systemFont(ofSize: 10.5)
        footer.textColor = dim
        // The header (the title, or Back on a list, and when it was updated) stays put above the page as it scrolls.
        let header: [NSView] = [title, back, note]
        for view in header { addSubview(view, positioned: .below, relativeTo: scroll) }   // first, so VoiceOver reads Back first
        for view in kept { list.addSubview(view) }
        rebuild()
    }

    private func placeScroll() {
        scroll.frame = NSRect(x: 0, y: headerHeight, width: panelWidth, height: scrollHeight)
    }

    required init?(coder: NSCoder) { nil }

    @objc private func keepScroller() {
        DispatchQueue.main.async { [weak self] in self?.scroll.scrollerStyle = .legacy }   // after AppKit's own switch
    }

    override func draw(_ dirtyRect: NSRect) {
        NSColor.black.setFill()
        bounds.fill()
    }

    /// Whether the panel is on screen: it always opens at the overview, and the creature's loop plays only then.
    func setOpen(_ open: Bool) {
        isOpen = open
        if open {
            show(.home)   // rebuilt, so "Today" is worked out again: UTC midnight may have passed since the last score
        } else {
            creature.setPlaying(false)
        }
    }

    /// Shows the overview or one of its two lists, from the top.
    func show(_ next: Page) {
        page = next
        rebuild()
        scroll.contentView.scroll(to: .zero)
        scroll.reflectScrolledClipView(scroll.contentView)
        creature.setPlaying(isOpen && page == .home)
        NSAccessibility.post(element: self, notification: .layoutChanged)
    }

    @objc private func openFix() { show(.fix) }
    @objc private func openLearn() { show(.learn) }
    @objc private func goBack() { show(.home) }

    private func updateHeader() {
        let when = updated.map { "Updated " + DateFormatter.localizedString(from: $0, dateStyle: .none, timeStyle: .short) + " · offline" }
        note.stringValue = status.isEmpty ? (when ?? "offline") : status
        let noteX = (back.isHidden ? title.frame.maxX : back.frame.maxX) + 12
        note.frame = NSRect(x: noteX, y: 0, width: panelWidth - edge - noteX, height: 30)
        // One line sits level with the title; two start a little higher.
        let lines = note.cell?.cellSize(forBounds: NSRect(x: 0, y: 0, width: note.frame.width, height: 1_000)).height ?? 14
        note.frame.origin.y = max(5, (headerHeight - min(30, lines)) / 2 + 2)
    }

    // Text inside a card, top to bottom from its running y.
    private func label(_ text: String, _ font: NSFont, _ color: NSColor, in card: NSView, y: inout CGFloat, gap: CGFloat = 4) {
        let field = NSTextField(wrappingLabelWithString: text)
        field.font = font
        field.textColor = color
        field.isSelectable = false
        field.preferredMaxLayoutWidth = innerWidth
        let height = field.cell?.cellSize(forBounds: NSRect(x: 0, y: 0, width: innerWidth, height: 10_000)).height ?? 16
        field.frame = NSRect(x: inset, y: y, width: innerWidth, height: ceil(height))
        card.addSubview(field)
        y += ceil(height) + gap
    }

    private func link(_ url: URL?, in card: NSView, y: inout CGFloat, gap: CGFloat = 12) {
        guard let url else { y += gap - 4; return }
        let page = url.path.split(separator: "/").last.map(String.init) ?? "docs"
        let button = DocsButton(title: "", target: self, action: #selector(open(_:)))
        button.url = url
        button.isBordered = false
        button.attributedTitle = NSAttributedString(string: "Docs: \(page) ↗", attributes: [
            .font: mono(11, .medium), .foregroundColor: orange, .underlineStyle: NSUnderlineStyle.single.rawValue])
        button.setAccessibilityLabel("Open the Claude Code docs page \(page)")
        button.sizeToFit()
        button.frame.origin = NSPoint(x: inset - 2, y: y)
        card.addSubview(button)
        y += button.frame.height + gap
    }

    @objc func open(_ sender: DocsButton) {
        guard let url = sender.url, url.absoluteString.hasPrefix(docsPrefix) else { return }
        onLink?(url)
    }

    private func place(_ view: NSView, x: CGFloat, y: CGFloat, width: CGFloat, height: CGFloat) {
        view.frame = NSRect(x: x, y: y, width: width, height: height)
        if view.superview == nil { list.addSubview(view) }
        cards.append(view)
    }

    func rebuild() {
        pageWidth = panelWidth
        arrange()
        if list.frame.height > scrollHeight + 0.5 {
            // Taller than the panel: the scroller shows, so the page makes room for it.
            pageWidth = panelWidth - NSScroller.scrollerWidth(for: .regular, scrollerStyle: .legacy)
            arrange()
        }
    }

    /// Lays out the page that is showing, top to bottom, at the page's current width.
    private func arrange() {
        list.subviews.filter { !kept.contains($0) }.forEach { $0.removeFromSuperview() }
        cards = []
        let home = page == .home || card == nil   // with no creature yet there are no lists to open
        title.isHidden = !home
        back.isHidden = home
        creature.isHidden = !home
        updateHeader()
        var y: CGFloat = 0
        if home {
            place(creature, x: edge, y: y, width: cardWidth, height: creatureHeight)
            y += creatureHeight + gap
            if let c = card {
                let half = (cardWidth - gap) / 2
                place(levelCard(c), x: edge, y: y, width: half, height: tileHeight)
                place(todayCard(c), x: edge + half + gap, y: y, width: half, height: tileHeight)
                y += tileHeight + gap
                for (view, height) in [statsCard(c), trendCard(c)] {
                    place(view, x: edge, y: y, width: cardWidth, height: height)
                    y += height + gap
                }
                place(fixButton(c), x: edge, y: y, width: half, height: buttonHeight)
                place(learnButton(c), x: edge + half + gap, y: y, width: half, height: buttonHeight)
                y += buttonHeight + gap
            }
        } else if let c = card {
            cards.append(back)
            let (view, height) = page == .fix ? fixCard(c) : learnCard(c)
            place(view, x: edge, y: y, width: cardWidth, height: height)
            y += height + gap
        }
        footer.stringValue = card.map { "Aura \(grouped($0.power)) · right-click for Refresh or Quit" }
            ?? "Right-click the creature in the menu bar for Refresh or Quit"
        footer.sizeToFit()
        footer.frame.origin = NSPoint(x: edge + 2, y: y)
        y += footer.frame.height + 6   // a few points to spare, so a slightly larger system font still fits the overview
        contentHeight = y
        list.frame = NSRect(x: 0, y: 0, width: pageWidth, height: max(scrollHeight, y))
    }

    /// The panel's height: its full height, or less on a screen with less room (then the overview scrolls too).
    func fit(height: CGFloat) {
        let height = min(panelHeight, max(240, height))
        guard height != bounds.height else { return }
        setFrameSize(NSSize(width: panelWidth, height: height))
        placeScroll()
        rebuild()
    }

    /// For --full pictures: the panel as tall as its whole page, header and all, so nothing is a scroll away.
    func growToWholePage() {
        let start = bounds.height
        guard headerHeight + contentHeight > start else { return }
        // Twice: grown, the page needs no scroller, so it is laid out wider and its text may take fewer lines.
        for _ in 0..<2 {
            setFrameSize(NSSize(width: panelWidth, height: max(start, headerHeight + contentHeight)))
            placeScroll()
            rebuild()
        }
    }

    /// For pictures: the page scrolled to its end, as after scrolling down a long list.
    func scrollToEnd() {
        scroll.contentView.scroll(to: NSPoint(x: 0, y: max(0, list.frame.height - scroll.contentSize.height)))
        scroll.reflectScrolledClipView(scroll.contentView)
    }

    private func levelCard(_ c: Card) -> CardView {
        let top = c.level >= 99
        let toNext = top ? "Top level" : "\(grouped(max(0, c.xpNext - c.xp))) XP to Lv \(c.level + 1)"
        let label = top ? "Level \(c.level), top level"
            : "Level \(c.level), \(Int(c.progress * 100)) percent of the way to level \(c.level + 1), \(toNext)"
        return CardView(label) { w in
            heading("Level", "chart.line.uptrend.xyaxis", width: w)
            put("Lv \(c.level)", bigFont, .white, at: NSPoint(x: inset, y: 32), width: w - 2 * inset)
            bar(NSRect(x: inset, y: 72, width: w - 2 * inset, height: 6), c.progress)
            put(toNext, .systemFont(ofSize: 11), dim, at: NSPoint(x: inset, y: 84), width: w - 2 * inset)
        }
    }

    private func todayCard(_ c: Card) -> CardView {
        let today = c.todayShown
        let day = c.olderDay   // a card scored on an earlier day says which day its number is from
        return CardView("\(day ?? "Today"): \(today) XP of \(dayCap) a day") { w in
            heading(day ?? "Today", "bolt.fill", width: w)
            let big = "+\(grouped(today))"
            put(big, bigFont, .white, at: NSPoint(x: inset, y: 32))
            let x = inset + textWidth(big, bigFont) + 6
            put(day == nil ? "XP today" : "XP", .systemFont(ofSize: 12), dim, at: NSPoint(x: x, y: 45),
                width: max(0, w - inset - x))
            bar(NSRect(x: inset, y: 72, width: w - 2 * inset, height: 6), CGFloat(today) / CGFloat(dayCap))
            put("of \(dayCap) a day", .systemFont(ofSize: 11), dim, at: NSPoint(x: inset, y: 84), width: w - 2 * inset)
        }
    }

    private func statsCard(_ c: Card) -> (NSView, CGFloat) {
        let label = "Stats: " + statOrder.map { "\(capitalized($0)) \(c.stats[$0] ?? 0)" }.joined(separator: ", ")
        let card = CardView(label) { w in
            heading("Stats", "slider.horizontal.3", width: w)
            let column = (w - 2 * inset - 20) / 2
            for (i, name) in statOrder.enumerated() {
                let x = inset + CGFloat(i / 3) * (column + 20)
                let y = 40 + CGFloat(i % 3) * 28
                let value = String(c.stats[name] ?? 0)
                let font = NSFont.monospacedDigitSystemFont(ofSize: 12, weight: .medium)
                put(capitalized(name), .systemFont(ofSize: 12), .white, at: NSPoint(x: x, y: y))
                put(value, font, .white, at: NSPoint(x: x + column - textWidth(value, font), y: y))
                bar(NSRect(x: x, y: y + 18, width: column, height: 4), CGFloat(c.stats[name] ?? 0) / 100)
            }
        }
        return (card, 128)
    }

    private func trendCard(_ c: Card) -> (NSView, CGFloat) {
        guard let days = c.xpByDay, let generated = c.generated, let end = utcDay(generated) else {
            let card = CardView("Trend: fills in at the next score") { w in
                heading("Trend", "chart.bar.fill", width: w)
                put("Fills in at the next score.", .systemFont(ofSize: 12), dim, at: NSPoint(x: inset, y: 40), width: w - 2 * inset)
            }
            return (card, 68)
        }
        let first = utcFormatter("MMM d").string(from: end.addingTimeInterval(-Double(trendDays - 1) * 86_400))
        let last = c.olderDay ?? "Today"
        let total = days.reduce(0, +)
        let spoken = days.dropLast().map(String.init).joined(separator: ", ") + ", \(last): \(days[days.count - 1])"
        let card = CardView("Trend: XP per day, last \(trendDays) days: \(spoken)") { w in
            heading("Trend", "chart.bar.fill", right: "\(trendDays) days · \(grouped(total)) XP", width: w)
            let chart = NSRect(x: inset, y: 40, width: w - 2 * inset, height: 56)
            let slot = chart.width / CGFloat(trendDays)
            let barWidth = floor(slot * 0.62)
            for (i, xp) in days.enumerated() {
                let height = xp > 0 ? max(3, chart.height * CGFloat(xp) / CGFloat(dayCap)) : 2
                let rect = NSRect(x: chart.minX + slot * CGFloat(i) + (slot - barWidth) / 2, y: chart.maxY - height,
                                  width: barWidth, height: height)
                (xp == 0 ? track : i == days.count - 1 ? orange : orange.withAlphaComponent(0.42)).setFill()
                NSBezierPath(roundedRect: rect, xRadius: 2.5, yRadius: 2.5).fill()
            }
            let font = NSFont.systemFont(ofSize: 10.5)
            put(first, font, dim, at: NSPoint(x: inset, y: chart.maxY + 6))
            put(last, font, dim, at: NSPoint(x: w - inset - textWidth(last, font), y: chart.maxY + 6))
        }
        return (card, 122)
    }

    private func fixButton(_ c: Card) -> TileButton {
        let note: String, label: String
        if let fix = c.fix {
            note = fix.isEmpty ? "none" : String(fix.count)
            label = fix.isEmpty ? "Fix next: nothing to fix right now. Opens the list"
                : "Fix next: \(fix.count) \(fix.count == 1 ? "thing" : "things") to fix. Opens the list"
        } else {
            note = ""
            label = "Fix next: fills in at the next score. Opens the list"
        }
        return TileButton("Fix next", "wrench.and.screwdriver", note: note, label: label, target: self, action: #selector(openFix))
    }

    private func learnButton(_ c: Card) -> TileButton {
        let note = c.training.map { "\($0.done)/\($0.total)" } ?? ""
        let label = c.training.map { "Learn: \($0.done) of \($0.total) lessons done. Opens the lessons" }
            ?? "Learn: fills in at the next score. Opens the lessons"
        return TileButton("Learn", "book.fill", note: note, label: label, target: self, action: #selector(openLearn))
    }

    private func fixCard(_ c: Card) -> (NSView, CGFloat) {
        guard let fix = c.fix else { return waiting("Fix next", "wrench.and.screwdriver") }
        let card = CardView(fix.isEmpty ? "Fix next: nothing to fix right now"
                            : fix.count == 1 ? "Fix next: the one thing that would raise Health or Brains most"
                            : "Fix next: the top \(fix.count) of what would raise Health or Brains most") { w in
            heading("Fix next", "wrench.and.screwdriver", width: w)
        }
        var y: CGFloat = 40
        if fix.isEmpty {
            label("Nothing to fix right now. Touch grass.", .systemFont(ofSize: 13), .white, in: card, y: &y)
        } else {
            label("What would raise Health or Brains most, from your last score.", .systemFont(ofSize: 11), dim, in: card, y: &y, gap: 10)
            for (i, item) in fix.enumerated() {
                label("\(i + 1). \(capitalized(item.title))", .systemFont(ofSize: 12.5, weight: .medium), .white, in: card, y: &y, gap: 3)
                if !item.how.isEmpty { label("How: \(item.how)", .systemFont(ofSize: 11.5), dim, in: card, y: &y, gap: 3) }
                link(item.docs, in: card, y: &y)
            }
        }
        return (card, y + 8)
    }

    private func learnCard(_ c: Card) -> (NSView, CGFloat) {
        guard let training = c.training else { return waiting("Learn", "book.fill") }
        let fraction = training.total > 0 ? CGFloat(training.done) / CGFloat(training.total) : 0
        let card = CardView("Learn: \(training.done) of \(training.total) lessons done") { w in
            heading("Learn", "book.fill", right: "\(training.done) of \(training.total) lessons", width: w)
            bar(NSRect(x: inset, y: 40, width: w - 2 * inset, height: 6), fraction)
        }
        var y: CGFloat = 58
        if let tip = c.tip {
            label("Tip of the day (\(capitalized(tip.stat)))", mono(11, .medium), orange, in: card, y: &y, gap: 3)
            label(capitalized(tip.advice.title), .systemFont(ofSize: 12.5), .white, in: card, y: &y, gap: 3)
            link(tip.advice.docs, in: card, y: &y, gap: 16)
        }
        for stat in training.stats {
            let trained = stat.done >= stat.total
            label("\(capitalized(stat.name))  \(stat.done)/\(stat.total)\(trained ? " · trained" : "")", mono(12, .medium), .white,
                  in: card, y: &y, gap: 3)
            if !trained, let next = stat.next {
                label("Next: \(next.title)", .systemFont(ofSize: 12), .white, in: card, y: &y, gap: 2)
                if !next.how.isEmpty { label("How: \(next.how)", .systemFont(ofSize: 11.5), dim, in: card, y: &y, gap: 3) }
                link(next.docs, in: card, y: &y)
            } else {
                y += 8
            }
        }
        let checked = training.checked.isEmpty ? "" : " Checked against the docs on \(training.checked)."
        label("Lessons tick themselves when your Claude Code logs show them done. They never change your level.\(checked)",
              .systemFont(ofSize: 10.5), dim, in: card, y: &y)
        return (card, y + 8)
    }

    /// A card whose data comes with the next score (the card on disk is older than the panel).
    private func waiting(_ name: String, _ symbol: String) -> (NSView, CGFloat) {
        let card = CardView("\(name): fills in at the next score") { w in
            heading(name, symbol, width: w)
            put("Fills in at the next score.", .systemFont(ofSize: 12), dim, at: NSPoint(x: inset, y: 40), width: w - 2 * inset)
        }
        return (card, 68)
    }
}

/// The menu bar item, the panel it opens, and the hourly offline refresh.
final class PanelApp: NSObject, NSApplicationDelegate, NSPopoverDelegate {
    let python: String, scanner: String, claudeDir: String, cache: URL
    let item = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
    let popover = NSPopover()
    let root = PageView()
    var isScanning = false
    var blinkTimer: Timer?

    init(python: String, scanner: String, claudeDir: String, cache: String) {
        self.python = python; self.scanner = scanner; self.claudeDir = claudeDir
        self.cache = URL(fileURLWithPath: cache)
    }

    func applicationDidFinishLaunching(_ note: Notification) {
        root.creature.clipsDir = cache.deletingLastPathComponent().appendingPathComponent("creatures")
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
        root.updated = date
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
        root.status = "Scoring your setup, offline…"
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
            root.status = "Could not score this time. Right-click to try again."
            return
        }
        try? FileManager.default.createDirectory(at: cache.deletingLastPathComponent(), withIntermediateDirectories: true)
        if (try? data.write(to: cache, options: .atomic)) != nil {
            try? FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: cache.path)
        }
        root.status = ""
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
            // No taller than the screen it opens on leaves room for (a small display, or one set to larger text).
            let room = (sender.window?.screen ?? NSScreen.main)?.visibleFrame.height ?? panelHeight
            root.fit(height: room - 16)
            popover.contentSize = root.frame.size
            popover.show(relativeTo: sender.bounds, of: sender, preferredEdge: .minY)
            popover.contentViewController?.view.window?.makeKey()
        }
    }

    @objc func quit() { NSApp.terminate(nil) }

    // Back at the overview before the panel appears, so it never opens on a list left open last time.
    func popoverWillShow(_ note: Notification) {
        root.setOpen(true)
    }

    // The loop plays, or the text creature blinks every few seconds, only while the panel is open.
    func popoverDidShow(_ note: Notification) {
        blinkTimer = Timer.scheduledTimer(withTimeInterval: 3.5, repeats: true) { [weak self] _ in
            self?.root.creature.isBlinking = true
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.18) { self?.root.creature.isBlinking = false }
        }
    }

    func popoverDidClose(_ note: Notification) {
        root.setOpen(false)
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
    if CommandLine.arguments.contains("--tab") {
        FileHandle.standardError.write("cclevel-panel: --tab is gone (the tabs became pages): use --page home, fix or learn\n".data(using: .utf8)!)
        exit(1)
    }
    let view = PageView()
    if let text = option("--height"), let height = Double(text) {
        view.fit(height: CGFloat(height))   // as on a screen with less room
    }
    if let clips = option("--clips") {
        view.creature.clipsDir = URL(fileURLWithPath: clips, isDirectory: true)
    }
    view.card = card
    view.updated = Date(timeIntervalSince1970: 0)
    if CommandLine.arguments.contains("--page") {
        guard let name = option("--page"), let page = Page(rawValue: name) else {
            FileHandle.standardError.write("cclevel-panel: --page is home, fix or learn\n".data(using: .utf8)!)
            exit(1)
        }
        view.show(page)
    }
    // What the panel shows when it opens, scroller and all; with --full, the whole page under its header; with
    // --scrolled, the page scrolled to its end.
    if CommandLine.arguments.contains("--full") { view.growToWholePage() }
    view.layoutSubtreeIfNeeded()
    if CommandLine.arguments.contains("--scrolled") { view.scrollToEnd() }
    let size = view.bounds.size
    guard let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: Int(size.width * 2), pixelsHigh: Int(size.height * 2),
                                     bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
                                     colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0) else { exit(1) }
    rep.size = size
    view.cacheDisplay(in: view.bounds, to: rep)
    guard let png = rep.representation(using: .png, properties: [:]), (try? png.write(to: URL(fileURLWithPath: out))) != nil else {
        exit(1)
    }
    for card in view.cards { print(card.accessibilityLabel() ?? "") }
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
