// CC level panel: your cclevel creature in the macOS menu bar. Click it for a small black panel with the creature and its
// stats; right-click (or control-click) for Refresh and Quit.
//
// It runs the offline card (`cclevel.py --json --no-save`, which writes nothing) when its last result is more than an hour
// old or older than the scanner copy beside it (so a rebuild after a plugin update scores again at once), keeps that result
// in card.json beside itself, and makes no network call. `cclevel.py --panel on --yes` builds it on
// this Mac with Apple's swiftc and starts it at login; `cclevel.py --panel off` removes it.
//
// An overview of rounded cards: the creature, Level and Today, the six stats and a 14-day Trend, then Friends (with a group
// link saved, Copy invite link beside it, which copies the link at once), then two buttons that open Fix next (the card's
// top Needs, how to fix each, and its docs page) and Learn (the training path, each stat's next lesson, and the tip of the
// day), each with a way back. Links open Claude Code's docs pages only.
//
// The Creature card plays the creature's rendered loop while the panel is open (creatures/<stage>_<class>.mp4 beside the
// panel for its class look, else creatures/<stage>.mp4), a still of its first frame otherwise or with Reduce Motion on, and
// the card's own text art when there is no clip.
//
// Poke the pet: over the creature the cursor becomes a pointing hand and the creature lifts a little; a click (or
// VoiceOver's Poke action) makes it squash and hop and go boing like a cartoon spring, lower as it grows, a sound made here
// in memory, quiet, and silent when macOS user interface sound effects are off. With Reduce Motion on it boings without
// moving. It sends and saves nothing.
//
// Free roam: the lock in the corner of the creature's square lets it out. It hops along the top of the screen, just under
// the menu bar, in a small see-through window of its own (creatures/roam/<stage>_<class>.mov, else the stage's), rests
// most of the time, and a poke makes it jump aside. The lock again, or a right-click on it, calls it back. While it is
// out the panel keeps one empty file, roam, beside itself. It sends nothing. `--roam-test` (further down) runs it for tests.
//
// `--snapshot OUT.png --card CARD.json [--clips DIR] [--page home|fix|learn] [--height PT] [--full | --scrolled]` draws
// what the panel shows on that page (with --height, as on a screen with that much room; with --full, the whole page; with
// --scrolled, the page scrolled to its end, under the header that stays put) into a picture,
// prints the VoiceOver label of each thing on it, one per line, top to bottom, and exits (for tests and previews).
// With `--poke-at X,Y [--times N] [--gap MS]` it instead clicks the Creature card N times at that point (from the card's
// top left; 88,88 is the creature's middle), --gap ms apart (300 if not given), through a window off screen, and prints
// what each click did ("poke hop" = it was poked, whatever it did; "anim=blink" = the text creature's blink), read back
// from the creature's layer and its sound player. `--reduce-motion` runs it as if Reduce Motion were on, and
// `--ui-sounds on|off` as if user interface sound effects were on or off (without it, the Mac's own setting counts).
import AppKit
import AVFoundation

let statOrder = ["grind", "appetite", "arsenal", "brains", "autonomy", "craft"]
let staleAfter: TimeInterval = 60 * 60
let scanTimeout: TimeInterval = 120
/// The menu bar item's saved name: macOS keeps its position under it.
let statusItemName = "com.cclevel.panel"

/// Whether the saved card needs a new score: none saved, saved over an hour ago, or saved before the scanner beside the
/// panel (--panel on just put in a newer one, after a plugin update, so the card may lack what the new panel shows) or
/// before identity.json last changed (a check-in, or a session start that read the group and found a friend new or gone).
/// A card is dated from the start of its scan, so a change made while it was scored counts too. A time in the future (the
/// clock set back) is not counted, or every new card would look stale until it caught up.
func cardStale(saved: Date?, scanner: Date?, identity: Date? = nil, now: Date = Date()) -> Bool {
    guard let saved else { return true }
    for newer in [scanner, identity] {
        if let newer, newer > saved, newer <= now { return true }
    }
    return now.timeIntervalSince(saved) > staleAfter
}

/// When a file was last written, or nil when it is not there.
func modified(_ url: URL) -> Date? {
    (try? FileManager.default.attributesOfItem(atPath: url.path))?[.modificationDate] as? Date
}

/// The scanner's identity.json in a Claude Code folder: where check-ins and group reads save what the board said.
func identityFile(_ claudeDir: String) -> URL {
    URL(fileURLWithPath: claudeDir).appendingPathComponent("cclevel").appendingPathComponent("identity.json")
}
let orange = NSColor(srgbRed: 0xd9 / 255, green: 0x77 / 255, blue: 0x57 / 255, alpha: 1)
let dim = NSColor(white: 0.55, alpha: 1)
let track = NSColor(white: 0.22, alpha: 1)
let cardFill = NSColor(white: 0.1, alpha: 1)
let panelWidth: CGFloat = 360
let panelHeight: CGFloat = 754
/// The scanner's DAY_CAP: the most XP one day can bank (a test keeps the two the same).
let dayCap = 550
let trendDays = 14
/// The scanner's and the board's GROUP_MAX: the most creatures one private group holds (a test keeps them the same).
let groupMax = 25
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

/// The poke's boing for each stage: its voice (Hz; the spring sounds at half of it), lower as the creature grows.
let boingVoices: [String: Double] = ["Egg": 1500, "Hatchling": 1220, "Lil Guy": 980, "Big Guy": 790, "Gigachad": 640,
                                     "GOAT": 520]
let boingSeconds = 0.38
let boingRate = 22050
/// The loudest sample as a share of full scale: 0.1 is -20 dBFS, quiet even in headphones at full volume.
let boingLevel = 0.1
/// Pokes closer together than this still hop, but boing only once.
let boingGap: TimeInterval = 0.15

/// A boing as WAV bytes (16-bit mono PCM), made here rather than shipped as a file: a cartoon spring, a note at half the
/// voice that wobbles fast (13 times a second) and settles as it fades, with a little of its octave and twelfth.
func boingWAV(hz: Double) -> Data {
    let count = Int(boingSeconds * Double(boingRate))
    let fadeOut = 0.02 * Double(boingRate)   // the last 20 ms, so it ends without a click
    var phase = 0.0
    var wave = [Double](repeating: 0, count: count)
    for i in 0..<count {
        let t = Double(i) / Double(boingRate)
        let wobble = 1 + 0.45 * exp(-t * 7) * sin(2 * Double.pi * 13 * t)
        phase += 2 * Double.pi * hz * 0.5 * wobble * (1 + 0.15 * exp(-t * 20)) / Double(boingRate)
        let level = min(1, t / 0.005) * exp(-t * 6) * min(1, Double(count - i) / fadeOut)
        wave[i] = (sin(phase) + 0.45 * sin(2 * phase) + 0.2 * sin(3 * phase)) * level
    }
    let top = wave.map(abs).max() ?? 0
    let scale = top > 0 ? boingLevel * 32767 / top : 0
    var data = Data()
    func add<T: FixedWidthInteger>(_ value: T) { withUnsafeBytes(of: value.littleEndian) { data.append(contentsOf: $0) } }
    let bytes = UInt32(count * 2)
    data.append(contentsOf: Array("RIFF".utf8))
    add(36 + bytes)
    data.append(contentsOf: Array("WAVEfmt ".utf8))
    add(UInt32(16)); add(UInt16(1)); add(UInt16(1)); add(UInt32(boingRate)); add(UInt32(boingRate * 2))
    add(UInt16(2)); add(UInt16(16))
    data.append(contentsOf: Array("data".utf8))
    add(bytes)
    for sample in wave { add(Int16((sample * scale).rounded())) }
    return data
}

/// The loudest sample of boingWAV's bytes, in dBFS: read back from the very bytes the player gets (for --poke-at).
func peakDBFS(_ wav: Data) -> Double {
    let samples = [UInt8](wav.dropFirst(44))
    var top = 0
    for i in stride(from: 0, to: samples.count - 1, by: 2) {
        top = max(top, abs(Int(Int16(bitPattern: UInt16(samples[i]) | UInt16(samples[i + 1]) << 8))))
    }
    return top == 0 ? -.infinity : 20 * log10(Double(top) / 32767)
}

/// Set by --reduce-motion and --ui-sounds on|off in a --snapshot run, as if this Mac were set so (for tests).
var testReduceMotion = false
var testUISounds: Bool?

/// Whether Reduce Motion is on: the loop shows its still, and a poke boings without moving.
func reduceMotion() -> Bool { testReduceMotion || NSWorkspace.shared.accessibilityDisplayShouldReduceMotion }

/// Whether macOS plays user interface sound effects (System Settings → Sound): when not, a poke hops without a boing.
/// Read only. A Mac where it was never switched off has no value saved, which means on.
func uiSoundsOn() -> Bool {
    if let testUISounds { return testUISounds }
    let value = UserDefaults(suiteName: "com.apple.systemsound")?.object(forKey: "com.apple.sound.uiaudio.enabled")
    return (value as? NSNumber)?.boolValue ?? true
}

/// The poke's boing, in a stage's voice: the player is made once per stage and kept. The creature in the panel and the
/// one out for a walk follow the same rules: silent when user interface sound effects are off, and once per boingGap.
final class Boinger {
    private var made: (stage: String, player: AVAudioPlayer, wav: Data)?
    private var last: TimeInterval = -.infinity

    func boing(stage: String, at time: TimeInterval) -> (sound: String, hz: Double, seconds: Double, peak: Double) {
        guard let voice = boingVoices[stage] else { return ("none", 0, 0, -.infinity) }
        if made?.stage != stage {
            let wav = boingWAV(hz: voice)
            made = (try? AVAudioPlayer(data: wav, fileTypeHint: AVFileType.wav.rawValue)).map { (stage: stage, player: $0, wav: wav) }
            made?.player.prepareToPlay()
        }
        guard let made else { return ("failed", voice, 0, -.infinity) }
        var sound = "off"
        if uiSoundsOn() {
            if time - last < boingGap {
                sound = "throttled"
            } else {
                last = time
                made.player.currentTime = 0
                sound = made.player.play() ? "played" : "failed"
            }
        }
        return (sound, voice, made.player.duration, peakDBFS(made.wav))
    }
}

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

/// Small stills of friends' creatures (their stage and class look), each look decoded once, misses included.
var faceCache: [String: NSImage?] = [:]

func faceImage(stage: String, cls: String, dir: URL?) -> NSImage? {
    guard let dir, let name = clipNames[stage] else { return nil }
    let key = "\(dir.path)|\(stage)|\(cls)"
    if let hit = faceCache[key] { return hit }
    var found: NSImage?
    for url in ((classNames[cls].map { ["\(name)_\($0)"] } ?? []) + [name]).map({ dir.appendingPathComponent("\($0).mp4") })
    where FileManager.default.isReadableFile(atPath: url.path) {
        if let frame = firstFrame(url) {
            found = frame
            break
        }
    }
    faceCache[key] = found
    return found
}

/// A friend's face in a small rounded square: the still, or the stage's first letter when there is none.
func drawFace(_ image: NSImage?, in rect: NSRect, stage: String) {
    NSGraphicsContext.saveGraphicsState()
    NSBezierPath(roundedRect: rect, xRadius: rect.width * 0.22, yRadius: rect.width * 0.22).addClip()
    NSColor.black.setFill()
    rect.fill()
    if let image {
        image.draw(in: rect)
    } else {
        let font = NSFont.systemFont(ofSize: rect.width * 0.45, weight: .semibold)
        let letter = String(stage.prefix(1))
        put(letter, font, orange, at: NSPoint(x: rect.midX - textWidth(letter, font) / 2, y: rect.midY - font.pointSize * 0.62))
    }
    NSGraphicsContext.restoreGraphicsState()
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

/// True or false from data this program does not control (JSON booleans arrive as NSNumber).
func flag(_ value: Any?) -> Bool? {
    guard let n = value as? NSNumber, CFGetTypeID(n) == CFBooleanGetTypeID() else { return nil }
    return n.boolValue
}

/// A whole number from data this program does not control, from 0 up to (not including) `limit`.
func whole(_ value: Any?, limit: Double = 1_000_000_000) -> Int? {
    guard let n = value as? NSNumber, CFGetTypeID(n) != CFBooleanGetTypeID(), n.doubleValue.rounded() == n.doubleValue,
          n.doubleValue >= 0, n.doubleValue < limit else { return nil }
    return n.intValue
}

/// One creature in the private group, as the scanner worked it out from its saved copy of the board's reply.
struct Friend {
    let name: String, stage: String, cls: String
    let place: Int, level: Int, xp: Int
    var weekXP: Int
    let you: Bool, sus: Bool
    var crown: Bool

    init?(_ value: Any?) {
        guard let o = value as? [String: Any], let place = whole(o["place"]), (1...groupMax).contains(place),
              let name = shortText(o["name"], 40), let stage = shortText(o["stage"], 20),
              clipNames[stage] != nil, let cls = shortText(o["class"], 30), let level = whole(o["level"]), (1...99).contains(level),
              let xp = whole(o["xp"]), let weekXP = whole(o["week_xp"]), let you = flag(o["you"]), let sus = flag(o["sus"]),
              let crown = flag(o["crown"]) else { return nil }
        self.name = name; self.stage = stage; self.cls = cls
        self.place = place; self.level = level; self.xp = xp; self.weekXP = weekXP
        self.you = you; self.sus = sus; self.crown = crown
    }
}

/// The Friends page's data. The panel never asks the board for it: the daily check-in, a later Claude Code start (at most
/// every 15 minutes, while in a group) or /pet group saves the group, and the scanner hides a copy older than a day and a
/// half, and everything in Privacy mode.
struct Friends {
    enum State: String { case ok, none, stale, privacy }
    let state: State, auto: Bool, fetched: Date?, members: [Friend]

    init?(_ value: Any?) {
        guard let o = value as? [String: Any], let raw = shortText(o["state"], 10), let state = State(rawValue: raw) else { return nil }
        self.state = state
        self.auto = flag(o["auto"]) ?? false
        guard state == .ok else {
            self.fetched = nil
            self.members = []
            return
        }
        guard let fetched = whole(o["fetched"], limit: 10_000_000_000), let list = o["members"] as? [Any],
              (1...groupMax).contains(list.count) else { return nil }
        let members = list.compactMap(Friend.init)
        guard members.count == list.count else { return nil }
        self.fetched = Date(timeIntervalSince1970: TimeInterval(fetched))
        self.members = members
    }

    /// What to show now. The scanner already hides an old copy, but a card can sit unrescored (a sleeping Mac, a failed
    /// score), so the panel checks again when it draws: a copy older than 36 hours is stale, one from the future is ignored.
    func shown(now: Date = Date()) -> State {
        guard state == .ok, let fetched else { return state }
        let age = now.timeIntervalSince(fetched)
        return age < -300 ? .none : age > friendsFresh ? .stale : .ok
    }

    /// The members as they may be shown now: a copy read in an earlier ISO week (Monday 00:00 UTC on, as the board counts
    /// them) shows nobody's XP this week, and nobody wears the crown. The scanner does the same when it writes the card.
    func members(now: Date = Date()) -> [Friend] {
        guard let fetched, isoWeek(fetched) != isoWeek(now) else { return members }
        return members.map { m in
            var last = m
            last.weekXP = 0
            last.crown = false
            return last
        }
    }
}

func isoWeek(_ date: Date) -> String {
    var calendar = Calendar(identifier: .iso8601)
    calendar.timeZone = TimeZone(identifier: "UTC")!
    let c = calendar.dateComponents([.yearForWeekOfYear, .weekOfYear], from: date)
    return "\(c.yearForWeekOfYear ?? 0)-W\(c.weekOfYear ?? 0)"
}

/// The scanner's FRIENDS_FRESH: no saved copy of the group older than this is shown (a test keeps them the same).
let friendsFresh: TimeInterval = 36 * 3600

/// The group's invite link: only one of cclevel's own join links (https, or http on this machine for a test board).
func inviteLinkOK(_ s: String) -> Bool {
    guard let url = URL(string: s), url.path == "/join" || url.path.hasSuffix("/join"), url.query == nil, url.user == nil,
          url.password == nil,
          let code = url.fragment, code.count == 32, code.allSatisfy({ "0123456789abcdef".contains($0) }),
          let host = url.host, !host.isEmpty else { return false }
    return url.scheme == "https" || (url.scheme == "http" && (host == "localhost" || host == "127.0.0.1"))
}

/// The invite card's data: the group's generated name and its link, which anyone can open to join.
struct Invite {
    let name: String, link: String, max: Int

    init?(_ value: Any?) {
        guard let o = value as? [String: Any], let name = shortText(o["name"], 60), let link = shortText(o["link"], 200),
              inviteLinkOK(link), let max = whole(o["max"]), (1...100).contains(max) else { return nil }
        self.name = name; self.link = link; self.max = max
    }
}

/// Whether this machine is in Privacy mode now: the scanner's opted-out note. Anything at that path counts, as it does for
/// the scanner, and a link is not followed.
func privacyCheck(_ claudeDir: String) -> () -> Bool {
    let note = URL(fileURLWithPath: claudeDir).appendingPathComponent("cclevel").appendingPathComponent("opted-out").path
    return { (try? FileManager.default.attributesOfItem(atPath: note)) != nil }
}

/// Puts text on the clipboard.
func copyToClipboard(_ text: String) -> Bool {
    let board = NSPasteboard.general
    board.clearContents()
    return board.setString(text, forType: .string)
}

/// What the invite card's Copy button does, and --copy-invite too: copies the card's invite link, unless the card or this
/// machine is in Privacy mode or the link is not one of cclevel's join links. Returns whether it copied.
func copyInviteLink(_ card: Card, privacyOn: (() -> Bool)?) -> Bool {
    guard card.friends?.state != .privacy, privacyOn?() != true, let invite = card.invite, inviteLinkOK(invite.link) else {
        return false
    }
    return copyToClipboard(invite.link)
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
    /// The Friends page: nil on a card from before 0.16.0 (it fills in at the next score). The invite only with a group.
    let friends: Friends?
    let invite: Invite?

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
        let friends = Friends(o["friends"])
        self.friends = friends
        self.invite = friends?.state == .privacy ? nil : Invite(o["invite"])
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

/// A card's title row: a small orange symbol, the title, and an optional note on the right. Returns where the title ends.
@discardableResult
func heading(_ title: String, _ symbol: String, right: String? = nil, width: CGFloat, top: CGFloat = inset) -> CGFloat {
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
    return x + textWidth(title, font)
}

/// The Creature card: the creature (its rendered loop, or the card's own art), who it is, and how it feels.
final class PanelView: NSView {
    var card: Card? { didSet { updateAccessibility(); loadClip(); roamChanged(); needsDisplay = true } }
    var isBlinking = false { didSet { needsDisplay = true } }
    /// Where the stage loops are; nil, or a stage without its file, draws the card's art instead.
    var clipsDir: URL? { didSet { clipStage = nil; loadClip() } }

    private var clipStage: String?
    private var still: NSImage?
    private let video = NSView(frame: creatureBox)
    /// The loop's layer sits in hopper, which only a poke moves, inside body, which only a hover lifts: two layers, so a
    /// hover that starts or ends mid-hop never cuts the hop short. Both move inside the video's black, clipped square,
    /// which keeps covering the still drawn under it, so a second creature never shows behind the moving one.
    private let body = CALayer()
    private let hopper = CALayer()
    private let playerLayer = AVPlayerLayer()
    private var player: AVQueuePlayer?
    private var looper: AVPlayerLooper?
    private var wantsPlay = false
    private var hovering = false
    private var pressed = false
    private let boinger = Boinger()
    /// Free roam: whether the creature is out for a walk (its square then says so and plays nothing), whether this look
    /// has a see-through loop to walk with, and what the lock in the square's corner does.
    var roamOut = false { didSet { roamChanged() } }
    var roamAvailable = false { didSet { roamChanged() } }
    var onRoam: (() -> Void)?
    let lock = NSButton(frame: NSRect(x: creatureBox.maxX - 30, y: creatureBox.maxY - 30, width: 26, height: 26))

    /// What one poke did, read back from the layer and the player: --poke-at prints it.
    struct Poke {
        let anim: [String], sound: String, hz: Double, seconds: Double, peak: Double
    }
    private var lastPoke: Poke?

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
        CATransaction.begin()
        CATransaction.setDisableActions(true)
        body.frame = video.bounds
        hopper.frame = body.bounds
        playerLayer.frame = hopper.bounds
        CATransaction.commit()
        playerLayer.videoGravity = .resizeAspect
        playerLayer.backgroundColor = NSColor.black.cgColor
        hopper.addSublayer(playerLayer)
        body.addSublayer(hopper)
        video.layer?.addSublayer(body)
        video.isHidden = true
        video.setAccessibilityElement(false)   // decorative: the card's label says who the creature is
        addSubview(video)
        lock.wantsLayer = true   // layer-backed like the loop under it, or the playing loop would cover it
        lock.isBordered = false
        lock.imagePosition = .imageOnly
        lock.contentTintColor = NSColor(white: 1, alpha: 0.75)
        lock.target = self
        lock.action = #selector(lockClicked)
        addSubview(lock)
        roamChanged()
        // Hover and the pointing hand: the panel is an accessory app, so the cursor is set on enter and exit as well.
        addTrackingArea(NSTrackingArea(rect: creatureBox, options: [.mouseEnteredAndExited, .cursorUpdate, .activeAlways],
                                       owner: self))
        // Reduce Motion switched on (or off) while the panel is open takes effect at once.
        NSWorkspace.shared.notificationCenter.addObserver(
            self, selector: #selector(motionSettingChanged),
            name: NSWorkspace.accessibilityDisplayOptionsDidChangeNotification, object: nil)
    }

    @objc private func motionSettingChanged() {
        setPlaying(wantsPlay)
        lift()   // a hover lift goes (or comes back) with the setting
    }

    @objc private func lockClicked() { onRoam?() }

    /// The lock in the creature square's corner: closed while the creature is home, open while it is out for a walk,
    /// and switched off for a look with no see-through loop.
    private func roamChanged() {
        let name = roamOut ? "lock.open.fill" : "lock.fill"
        let label = roamOut ? "Call your creature back" : "Let your creature out on your screen"
        lock.image = NSImage(systemSymbolName: name, accessibilityDescription: label)
        lock.setAccessibilityLabel(label)
        lock.isEnabled = roamAvailable || roamOut
        lock.isHidden = card == nil
        lock.toolTip = roamOut ? "Call it back home."
            : roamAvailable ? "Let it out: your creature hops along the top of your screen. Click again to call it back."
            : "Not available for this creature yet."
        setPlaying(wantsPlay)
        needsDisplay = true
    }

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
        if !on {   // closed, or another page: the next open starts with the creature at rest
            hovering = false
            pressed = false
            CATransaction.begin()
            CATransaction.setDisableActions(true)
            hopper.removeAllAnimations()
            body.removeAllAnimations()
            body.transform = CATransform3DIdentity
            CATransaction.commit()
        }
        guard let player else { return }
        if on && !reduceMotion() && !roamOut {
            video.isHidden = false
            player.play()
        } else {
            player.pause()
            if reduceMotion() || roamOut {
                video.isHidden = true   // the first-frame still drawn underneath shows instead
            }
        }
    }

    required init?(coder: NSCoder) { nil }

    func updateAccessibility() {
        guard let c = card else {
            setAccessibilityCustomActions([])
            return setAccessibilityLabel("Creature: no creature yet")
        }
        let brains = c.brain.isEmpty ? "" : ", Brains: \(c.brain)"
        setAccessibilityLabel("Creature: \(c.who), mood \(c.mood), Health \(c.health)\(brains)")
        setAccessibilityCustomActions([NSAccessibilityCustomAction(name: "Poke") { [weak self] in
            self?.poke(at: ProcessInfo.processInfo.systemUptime) != nil
        }])
    }

    // Poke the pet. Only a click that starts and ends on the creature counts: dragging off it cancels.
    override func acceptsFirstMouse(for event: NSEvent?) -> Bool { true }

    // Clicks on the playing loop come here, not to the video view, which would drop a first click on a panel not in front.
    override func hitTest(_ point: NSPoint) -> NSView? {
        let hit = super.hitTest(point)
        return hit === video ? self : hit
    }

    private func onCreature(_ event: NSEvent) -> Bool {   // not while it is out for a walk: its square is empty
        card != nil && !roamOut && creatureBox.contains(convert(event.locationInWindow, from: nil))
    }

    override func mouseEntered(with event: NSEvent) {
        guard card != nil, !roamOut else { return }
        hovering = true
        NSCursor.pointingHand.set()
        lift()
    }

    override func mouseExited(with event: NSEvent) {
        NSCursor.arrow.set()
        guard hovering else { return }
        hovering = false
        lift()
    }

    override func cursorUpdate(with event: NSEvent) {
        (onCreature(event) ? NSCursor.pointingHand : NSCursor.arrow).set()
    }

    override func mouseDown(with event: NSEvent) { pressed = onCreature(event) }

    override func mouseUp(with event: NSEvent) {
        defer { pressed = false }
        if pressed && onCreature(event) { poke(at: event.timestamp) }
    }

    /// A hover lifts the creature a little; it settles when the mouse leaves. Not with Reduce Motion on.
    private func lift() {
        CATransaction.begin()
        CATransaction.setAnimationDuration(0.15)
        body.transform = hovering && !reduceMotion() ? CATransform3DMakeScale(1.04, 1.04, 1) : CATransform3DIdentity
        CATransaction.commit()
    }

    /// The squash and the hop, about 0.4 s, on hopper alone (a hover lift on body stays as it is). A poke during one starts
    /// it again.
    private func hop() {
        // Up on screen, whichever way the layers above count y.
        let up: CGFloat = hopper.superlayer?.contentsAreFlipped() == true ? -8 : 8
        func keyframes(_ path: String, _ values: [CGFloat]) -> CAKeyframeAnimation {
            let animation = CAKeyframeAnimation(keyPath: path)
            animation.values = values
            animation.keyTimes = [0, 0.18, 0.5, 0.78, 1]
            animation.timingFunctions = [CAMediaTimingFunction(name: .easeOut), CAMediaTimingFunction(name: .easeOut),
                                         CAMediaTimingFunction(name: .easeIn), CAMediaTimingFunction(name: .easeOut)]
            return animation
        }
        let group = CAAnimationGroup()
        group.animations = [keyframes("transform.scale.x", [1, 1.1, 0.95, 1.02, 1]),
                            keyframes("transform.scale.y", [1, 0.86, 1.08, 0.97, 1]),
                            keyframes("transform.translation.y", [0, 0, up, 0, 0])]
        group.duration = 0.4
        hopper.removeAnimation(forKey: "poke")
        hopper.add(group, forKey: "poke")
    }

    /// A poke: the creature squashes and hops (the text creature blinks), not with Reduce Motion on, and boings in its
    /// stage's voice, unless user interface sound effects are off or it boinged less than boingGap ago.
    @discardableResult
    func poke(at time: TimeInterval) -> Poke? {
        guard let card, !roamOut else { return nil }   // out for a walk: nobody in the square to poke
        if !reduceMotion() {
            if !video.isHidden {
                hop()
            } else if still == nil {
                isBlinking = true
                DispatchQueue.main.asyncAfter(deadline: .now() + 0.18) { [weak self] in self?.isBlinking = false }
            }
        }
        let (sound, hz, seconds, peak) = boinger.boing(stage: card.stage, at: time)
        let done = Poke(anim: (hopper.animationKeys() ?? []) + (isBlinking ? ["blink"] : []), sound: sound, hz: hz,
                        seconds: seconds, peak: peak)
        lastPoke = done
        return done
    }

    /// One line for --poke-at: what the last click did ("poke none" when it was no poke), then forgotten.
    func takePokeLine() -> String {
        defer { lastPoke = nil }
        guard let p = lastPoke else {
            let keys = hopper.animationKeys() ?? []
            return "poke none anim=\(keys.isEmpty ? "-" : keys.joined(separator: ",")) sound=none"
        }
        return String(format: "poke hop anim=%@ sound=%@ hz=%.0f dur=%.3f peak_dbfs=%.1f",
                      p.anim.isEmpty ? "-" : p.anim.joined(separator: ","), p.sound, p.hz, p.seconds, p.peak)
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
        if roamOut {   // its square, dimmed, says where it went
            NSColor(white: 0, alpha: 0.6).setFill()
            NSBezierPath(roundedRect: creatureBox, xRadius: creatureCorner, yRadius: creatureCorner).fill()
            let note = "Out for a walk"
            let font = NSFont.systemFont(ofSize: 12, weight: .medium)
            let w = (note as NSString).size(withAttributes: [.font: font]).width
            put(note, font, .white, at: NSPoint(x: creatureBox.midX - w / 2, y: creatureBox.midY - 8))
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

/// A card at the bottom of the overview that opens one of its lists (Friends, Fix next or Learn, each with a "›"), or
/// does one thing at once without it (Copy invite link).
final class TileButton: NSButton {
    var name: String { didSet { needsDisplay = true } }
    var symbol: String { didSet { needsDisplay = true } }
    private let note: String
    /// The "›" on the right: on for a card that opens a list, off for one that acts at once.
    var opensList = true { didSet { needsDisplay = true } }
    /// Small creature faces drawn left of the note (the Friends button): each a still or nil, with its stage.
    var faces: [(NSImage?, String)] = [] { didSet { needsDisplay = true } }
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
        let right = opensList ? (note.isEmpty ? "›" : "\(note)  ›") : note
        let titleEnd = heading(name, symbol, right: right.isEmpty ? nil : right, width: bounds.width, top: (bounds.height - 17) / 2)
        guard !faces.isEmpty else { return }
        // As many faces as fit between the title and the note: all five full width, fewer on a half-width card.
        let side: CGFloat = 24, step: CGFloat = 28
        let end = bounds.width - inset - textWidth(right, .systemFont(ofSize: 11.5)) - 10
        let shown = min(faces.count, max(0, Int((end - titleEnd - 8 + (step - side)) / step)))
        var x = end - CGFloat(shown) * step + (step - side)
        for (image, stage) in faces.prefix(shown) {
            drawFace(image, in: NSRect(x: x, y: (bounds.height - side) / 2, width: side, height: side), stage: stage)
            x += step
        }
    }

    // The keyboard focus ring follows the card's rounded corners.
    override func drawFocusRingMask() {
        NSBezierPath(roundedRect: bounds, xRadius: corner, yRadius: corner).fill()
    }

    override var focusRingMaskBounds: NSRect { bounds }
}

/// What the panel shows: the overview of cards, or one of the three lists it opens.
enum Page: String {
    case home, fix, learn, friends
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
    /// True while this machine is in Privacy mode, read from its own files each time the page is drawn (the panel sets it),
    /// so turning Privacy mode on hides friends at once, before the next score rewrites the card.
    var privacyOn: (() -> Bool)?
    /// The time the Friends page is drawn at: the clock, or a fixed time a snapshot is given (--now, for tests).
    var clock: () -> Date = { Date() }

    /// The Friends data as it may be shown now: in Privacy mode nothing, and the saved copy's age checked again.
    private func friendsNow(_ c: Card) -> (state: Friends.State, friends: Friends, invite: Invite?)? {
        guard let f = c.friends else { return nil }
        if f.state == .privacy || privacyOn?() == true { return (.privacy, f, nil) }
        return (f.shown(now: clock()), f, c.invite)
    }
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
    @objc private func openFriends() { show(.friends) }
    @objc private func goBack() { show(.home) }

    @objc private func copyInvite(_ sender: NSButton) {
        guard let c = card, copyInviteLink(c, privacyOn: privacyOn) else { return }
        sender.title = "Copied"
        sender.setAccessibilityLabel("Invite link copied")
        DispatchQueue.main.asyncAfter(deadline: .now() + 2) { [weak sender] in
            sender?.title = "Copy invite link"
            sender?.setAccessibilityLabel("Copy the invite link")
        }
    }

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
                // With a group link saved here, Copy invite link sits beside Friends, one click from the overview.
                if let invite = friendsNow(c)?.invite {
                    place(friendsButton(c), x: edge, y: y, width: half, height: buttonHeight)
                    place(inviteButton(invite), x: edge + half + gap, y: y, width: half, height: buttonHeight)
                } else {
                    place(friendsButton(c), x: edge, y: y, width: cardWidth, height: buttonHeight)
                }
                y += buttonHeight + gap
                place(fixButton(c), x: edge, y: y, width: half, height: buttonHeight)
                place(learnButton(c), x: edge + half + gap, y: y, width: half, height: buttonHeight)
                y += buttonHeight + gap
            }
        } else if let c = card {
            cards.append(back)
            let parts = page == .fix ? [fixCard(c)] : page == .learn ? [learnCard(c)] : friendsCards(c)
            for (view, height) in parts {
                place(view, x: edge, y: y, width: cardWidth, height: height)
                y += height + gap
            }
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

    private func friendsButton(_ c: Card) -> TileButton {
        let now = friendsNow(c)
        let members = now?.state == .ok ? now?.friends.members ?? [] : []
        let label: String
        switch now?.state {
        case .ok?: label = "Friends: \(members.count) \(members.count == 1 ? "creature" : "creatures") in your group. Opens the list"
        case .privacy?: label = "Friends: off in Privacy mode. Opens the page"
        case .stale?: label = "Friends: need a fresh check-in. Opens the page"
        case .none?: label = now?.invite == nil ? "Friends: no group yet. Opens the page" : "Friends: your invite link. Opens the page"
        case nil: label = "Friends: fills in at the next score. Opens the page"
        }
        let button = TileButton("Friends", "person.2.fill", note: members.isEmpty ? "" : String(members.count), label: label,
                                target: self, action: #selector(openFriends))
        button.faces = members.prefix(5).map { (faceImage(stage: $0.stage, cls: $0.cls, dir: creature.clipsDir), $0.stage) }
        return button
    }

    /// The overview's Copy invite link card, beside Friends: copies the link at once, as the invite card's button does.
    private func inviteButton(_ invite: Invite) -> TileButton {
        let button = TileButton("Copy invite link", "link", note: "", label: inviteTileLabel(invite),
                                target: self, action: #selector(copyInviteTile(_:)))
        button.opensList = false
        return button
    }

    private func inviteTileLabel(_ invite: Invite) -> String {
        "Copy invite link: \(invite.name). Anyone with the link can join, up to \(invite.max)"
    }

    @objc private func copyInviteTile(_ sender: TileButton) {
        guard let c = card, let invite = c.invite, copyInviteLink(c, privacyOn: privacyOn) else { return }
        let label = inviteTileLabel(invite)
        sender.tag += 1   // only the last click's timer puts the tile back, 2 s after that click
        let click = sender.tag
        sender.name = "Copied"
        sender.symbol = "checkmark"
        sender.setAccessibilityLabel("Invite link copied")
        DispatchQueue.main.asyncAfter(deadline: .now() + 2) { [weak sender] in
            guard let sender, sender.tag == click else { return }
            sender.name = "Copy invite link"
            sender.symbol = "link"
            sender.setAccessibilityLabel(label)
        }
    }

    /// The Friends page: the invite card (when a group code is saved here), then the group's creatures.
    private func friendsCards(_ c: Card) -> [(NSView, CGFloat)] {
        guard let now = friendsNow(c) else { return [waiting("Friends", "person.2.fill")] }
        if now.state == .privacy {
            return [message("Friends: off in Privacy mode", "Friends are off in Privacy mode.")]
        }
        var parts: [(NSView, CGFloat)] = []
        if let invite = now.invite { parts.append(inviteCard(invite)) }
        switch now.state {
        case .ok: parts.append(membersCard(now.friends))
        case .stale: parts.append(message("Friends: need a fresh check-in", "Friends need a fresh check-in: run /pet group."))
        default:
            if now.invite == nil {
                parts.append(message("Friends: no group yet",
                                     "No group yet. In Claude Code, /pet group create starts one, or open a friend's invite link to join."))
            } else if now.friends.auto {
                parts.append(message("Friends: they show here after the next Claude Code start",
                                     "Your friends show here after the next Claude Code start, or run /pet group."))
            } else {
                parts.append(message("Friends: run /pet group to see them", "Run /pet group in Claude Code to see them."))
            }
        }
        return parts
    }

    private func inviteCard(_ invite: Invite) -> (NSView, CGFloat) {
        let card = CardView("Invite friends: \(invite.name). Anyone with the link can join, up to \(invite.max)") { w in
            heading("Invite friends", "link", width: w)
        }
        var y: CGFloat = 40
        label(invite.name, .systemFont(ofSize: 13, weight: .semibold), .white, in: card, y: &y, gap: 2)
        label("Anyone with this link can join, up to \(invite.max).", .systemFont(ofSize: 11), dim, in: card, y: &y, gap: 10)
        let copy = NSButton(title: "Copy invite link", target: self, action: #selector(copyInvite(_:)))
        copy.bezelStyle = .rounded
        copy.controlSize = .regular
        copy.setAccessibilityLabel("Copy the invite link")
        copy.sizeToFit()
        copy.frame.origin = NSPoint(x: inset - 6, y: y)
        card.addSubview(copy)
        y += copy.frame.height + 12
        return (card, y)
    }

    /// The group's creatures, best first by XP since joining, as of the saved copy's time.
    private func membersCard(_ f: Friends) -> (NSView, CGFloat) {
        let members = f.members(now: clock())   // last week's copy shows nobody's XP this week
        let top: CGFloat = 40, row: CGFloat = 44, faceSide: CGFloat = 32
        let faces = members.map { faceImage(stage: $0.stage, cls: $0.cls, dir: creature.clipsDir) }
        let spoken = members.enumerated().map { i, m in
            "\(m.place), \(m.name), Lv \(m.level) \(m.stage), \(grouped(m.weekXP)) XP this week" +
                (m.crown ? ", most XP this week" : "") + (m.you ? ", you" : "") + (m.sus ? ", sus" : "")
        }
        var when = ""
        if let fetched = f.fetched {
            when = DateFormatter.localizedString(from: fetched, dateStyle: Calendar.current.isDateInToday(fetched) ? .none : .short,
                                                 timeStyle: .short)
        }
        // The time the list was last saved: a later read that finds the same group checks it without saving it again.
        let foot = "Saved \(when). " + (f.auto ? "Checked when Claude Code starts." : "Run /pet group to update.")
        let card = CardView("Friends: \(members.count) in your group. " + spoken.joined(separator: "; ") + ". " + foot) { w in
            heading("Friends", "person.2.fill", right: "\(members.count) in your group", width: w)
            for (i, m) in members.enumerated() {
                let y = top + CGFloat(i) * row
                put("\(m.place)", mono(11, .medium), dim, at: NSPoint(x: inset, y: y + 13))
                drawFace(faces[i], in: NSRect(x: inset + 18, y: y + 4, width: faceSide, height: faceSide), stage: m.stage)
                let x = inset + 18 + faceSide + 10
                let tags = [m.crown ? "♛" : "", m.you ? "(you)" : "", m.sus ? "sus" : ""].filter { !$0.isEmpty }.joined(separator: " ")
                let tagFont = NSFont.systemFont(ofSize: 11.5, weight: .medium)
                let tagWidth = tags.isEmpty ? 0 : textWidth(tags, tagFont)
                let textWidth = w - x - inset - (tagWidth > 0 ? tagWidth + 8 : 0)
                put(m.name, .systemFont(ofSize: 12.5, weight: .medium), .white, at: NSPoint(x: x, y: y + 4), width: textWidth)
                put("Lv \(m.level) \(m.stage) · +\(grouped(m.weekXP)) XP this week", .systemFont(ofSize: 11), dim,
                    at: NSPoint(x: x, y: y + 21), width: textWidth)
                if !tags.isEmpty {
                    put(tags, tagFont, m.crown ? orange : dim, at: NSPoint(x: w - inset - tagWidth, y: y + 13))
                }
            }
            put(foot, .systemFont(ofSize: 10.5), dim, at: NSPoint(x: inset, y: top + CGFloat(members.count) * row + 4),
                width: w - 2 * inset)
        }
        return (card, top + CGFloat(members.count) * row + 28)
    }

    /// A Friends page card with one message under its title.
    private func message(_ spoken: String, _ text: String) -> (NSView, CGFloat) {
        let card = CardView(spoken) { w in heading("Friends", "person.2.fill", width: w) }
        var y: CGFloat = 40
        label(text, .systemFont(ofSize: 12), dim, in: card, y: &y)
        return (card, y + 10)
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
// Free roam: with the lock on the Creature card open, the creature leaves the panel and hops along the top of the screen,
// just under the menu bar, in a small see-through window of its own that moves with it. The window is the size of one
// frame of its loop, so the only clicks it can take are clicks on the creature (a poke); everything beside it belongs to
// whatever is underneath. It rests most of the time on a paused frame; the loop plays while it travels and for a moment
// when the pointer touches it. It makes no network call and saves one empty file, panel/roam, while it is out.

/// The walker's window, a square this many points wide: one frame of the loop (the body is about 40 of them).
let roamSize: CGFloat = 64
/// A poke sends it at least this far from where it was, so what it sat on can be clicked.
let roamAway: CGFloat = 120
/// With no keyboard or mouse input for this long, it stops travelling until someone is back.
let roamIdleAfter: TimeInterval = 5 * 60
let roamRest = 5.0...20.0
let roamFirstRest = 2.0...4.0
/// How far one trip goes, in points.
let roamTrip: ClosedRange<CGFloat> = 80...420
/// How long the loop plays when the pointer touches it.
let roamNotice: TimeInterval = 3
/// How each stage travels: a hop's height and length in points, and its seconds.
let roamStyles: [String: (hop: CGFloat, step: CGFloat, beat: TimeInterval)] = [
    "Egg": (4, 14, 0.45), "Hatchling": (10, 26, 0.32), "Lil Guy": (12, 32, 0.34), "Big Guy": (8, 30, 0.5),
    "Gigachad": (14, 44, 0.42), "GOAT": (18, 56, 0.6)]
/// Set by --idle in a --roam-test run, as if nobody had touched this Mac for that many seconds (for tests).
var testIdle: TimeInterval?

/// The empty file that says the creature is out: there while it is, gone when it is home. --panel off removes it.
func roamMarker(_ panelDir: URL) -> URL { panelDir.appendingPathComponent("roam") }

/// The see-through loop for a look, creatures/roam/<stage>_<class>.mov or the stage's own: the first that is there and
/// decodes, or nil, and then this creature cannot be let out.
func roamClip(stage: String, cls: String, dir: URL?) -> URL? {
    guard let dir, let name = clipNames[stage] else { return nil }
    let roam = dir.appendingPathComponent("roam")
    for url in ((classNames[cls].map { ["\(name)_\($0)"] } ?? []) + [name]).map({ roam.appendingPathComponent("\($0).mov") })
    where FileManager.default.isReadableFile(atPath: url.path) && firstFrame(url) != nil {
        return url
    }
    return nil
}

/// Seconds since the last keyboard or mouse input on this Mac: one number from macOS, not what was typed or clicked.
func idleSeconds() -> TimeInterval {
    testIdle ?? CGEventSource.secondsSinceLastEventType(.combinedSessionState, eventType: CGEventType(rawValue: ~0)!)
}

/// How see-through one pixel of a picture is, 0 (clear) to 255 (solid), counted from the top left (for --roam-test).
func alphaAt(_ image: CGImage, x: Int, y: Int) -> Int {
    var pixels = [UInt8](repeating: 0, count: image.width * image.height * 4)
    guard let context = CGContext(data: &pixels, width: image.width, height: image.height, bitsPerComponent: 8,
                                  bytesPerRow: image.width * 4, space: CGColorSpaceCreateDeviceRGB(),
                                  bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue) else { return -1 }
    context.draw(image, in: CGRect(x: 0, y: 0, width: image.width, height: image.height))
    return Int(pixels[(y * image.width + x) * 4 + 3])
}

/// The walker's choices (where next, how long a rest): random, or the same every run from --seed (for tests).
struct Dice: RandomNumberGenerator {
    var state: UInt64

    mutating func next() -> UInt64 {
        state &+= 0x9E3779B97F4A7C15
        var z = state
        z = (z ^ (z >> 30)) &* 0xBF58476D1CE4E5B9
        z = (z ^ (z >> 27)) &* 0x94D049BB133111EB
        return z ^ (z >> 31)
    }
}

/// The walker's window: never the key window, and free to hop up past the top of the screen.
final class RoamWindow: NSPanel {
    override var canBecomeKey: Bool { false }
    override func constrainFrameRect(_ frameRect: NSRect, to screen: NSScreen?) -> NSRect { frameRect }
}

/// What is in the walker's window: the loop, and the mouse. A click is a poke, a right-click offers the way home.
final class RoamView: NSView {
    weak var roamer: Roamer?
    let playerLayer = AVPlayerLayer()

    override init(frame: NSRect) {
        super.init(frame: frame)
        wantsLayer = true
        // Squashes from its feet. The loop's clear pixels stay clear: the layer asks for frames that keep their alpha.
        playerLayer.anchorPoint = CGPoint(x: 0.5, y: 0)
        playerLayer.frame = bounds
        playerLayer.videoGravity = .resizeAspect
        playerLayer.pixelBufferAttributes = [kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32BGRA]
        layer?.addSublayer(playerLayer)
        addTrackingArea(NSTrackingArea(rect: bounds, options: [.mouseEnteredAndExited, .activeAlways], owner: self))
        setAccessibilityElement(true)
        setAccessibilityRole(.image)
        setAccessibilityLabel("Your creature, out for a walk")
        setAccessibilityCustomActions([NSAccessibilityCustomAction(name: "Poke") { [weak self] in
            self?.roamer?.poke(at: ProcessInfo.processInfo.systemUptime) ?? false
        }])
    }

    required init?(coder: NSCoder) { nil }

    override func acceptsFirstMouse(for event: NSEvent?) -> Bool { true }

    override func mouseEntered(with event: NSEvent) {
        NSCursor.pointingHand.set()
        roamer?.notice()
    }

    override func mouseExited(with event: NSEvent) { NSCursor.arrow.set() }

    override func mouseUp(with event: NSEvent) {
        // Where the click was, from the click itself: the walker never asks macOS where the pointer is.
        if bounds.contains(convert(event.locationInWindow, from: nil)), let window {
            roamer?.poke(at: event.timestamp, clickX: window.convertPoint(toScreen: event.locationInWindow).x)
        }
    }

    override func rightMouseDown(with event: NSEvent) {
        let menu = NSMenu()
        menu.addItem(withTitle: "Call it back", action: #selector(Roamer.callBack), keyEquivalent: "").target = roamer
        menu.addItem(.separator())
        menu.addItem(withTitle: "Quit CC level panel", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "").target = NSApp
        NSMenu.popUpContextMenu(menu, with: event, for: self)
    }
}

/// The creature out for a walk: its window, where it goes and when it stops.
final class Roamer: NSObject {
    let window = RoamWindow(contentRect: NSRect(x: 0, y: 0, width: roamSize, height: roamSize),
                            styleMask: [.borderless, .nonactivatingPanel], backing: .buffered, defer: false)
    private let view = RoamView(frame: NSRect(x: 0, y: 0, width: roamSize, height: roamSize))
    private var player: AVQueuePlayer?
    private var looper: AVPlayerLooper?
    private var stage = ""
    private let boinger = Boinger()
    private var dice: Dice
    /// The next thing to do (a trip after a rest, the loop's pause after a notice), and the 60-a-second clock that runs
    /// only while it moves.
    private var next: Timer?
    private var stopLoop: Timer?
    private var ticker: Timer?
    private var move: (from: NSPoint, to: NSPoint, height: CGFloat, start: TimeInterval, seconds: TimeInterval,
                       fade: (from: CGFloat, to: CGFloat), then: () -> Void)?
    private(set) var isOut = false
    private var settled = false   // on the line and free to travel: not on its way out or home
    private var asleep = false
    /// "Call it back" in its right-click menu.
    var onCallBack: (() -> Void)?
    /// --roam-test: every event, with where the window is.
    var log: ((String, [String: Any]) -> Void)?

    init(seed: UInt64?) {
        dice = Dice(state: seed ?? UInt64.random(in: 0...UInt64.max))
        super.init()
        view.roamer = self
        window.contentView = view
        window.isOpaque = false
        window.backgroundColor = .clear
        window.hasShadow = false
        window.hidesOnDeactivate = false
        window.ignoresMouseEvents = false   // said outright: a click anywhere in its small square is a poke
        // Above app windows and the menu bar's items, below any open menu. On every desktop, not in full-screen spaces.
        window.level = NSWindow.Level(rawValue: NSWindow.Level.statusBar.rawValue + 1)
        window.collectionBehavior = [.canJoinAllSpaces, .stationary, .ignoresCycle]
        let center = NotificationCenter.default, work = NSWorkspace.shared.notificationCenter
        center.addObserver(self, selector: #selector(seen), name: NSWindow.didChangeOcclusionStateNotification, object: window)
        center.addObserver(self, selector: #selector(screenChanged), name: NSApplication.didChangeScreenParametersNotification, object: nil)
        for name in [NSWorkspace.screensDidSleepNotification, NSWorkspace.sessionDidResignActiveNotification] {
            work.addObserver(self, selector: #selector(sleep), name: name, object: nil)
        }
        for name in [NSWorkspace.screensDidWakeNotification, NSWorkspace.sessionDidBecomeActiveNotification] {
            work.addObserver(self, selector: #selector(seen), name: name, object: nil)
        }
    }

    /// The display with the main menu bar, and the line under it: where the window's bottom left corner may be.
    private var screen: NSScreen? { NSScreen.screens.first }
    private var lineY: CGFloat { (screen?.visibleFrame.maxY ?? roamSize) - roamSize }
    private var lineX: ClosedRange<CGFloat> {
        let frame = screen?.visibleFrame ?? .zero
        return frame.minX...max(frame.minX, frame.maxX - roamSize)
    }
    private func onLine(_ x: CGFloat) -> CGFloat { min(max(x, lineX.lowerBound), lineX.upperBound) }
    var hasClip: Bool { player != nil }

    /// The look's see-through loop, paused on its first frame until the creature moves.
    func load(_ url: URL, stage: String) {
        self.stage = stage
        let wasPlaying = (player?.rate ?? 0) != 0   // a new look while it travels (it evolved): the new loop plays on
        player?.pause()
        let queue = AVQueuePlayer()
        queue.isMuted = true
        queue.preventsDisplaySleepDuringVideoPlayback = false
        looper = AVPlayerLooper(player: queue, templateItem: AVPlayerItem(url: url))
        player = queue
        view.playerLayer.player = queue
        if wasPlaying { queue.play() }
    }

    private func report(_ event: String, _ more: [String: Any] = [:]) {
        guard let log else { return }
        let f = window.frame
        var info: [String: Any] = [
            "x": Double(f.minX), "y": Double(f.minY), "w": Double(f.width), "h": Double(f.height),
            "top": Double(f.maxY), "line": Double(screen?.visibleFrame.maxY ?? 0), "level": window.level.rawValue,
            "playing": (player?.rate ?? 0) != 0, "all_spaces": window.collectionBehavior.contains(.canJoinAllSpaces),
            "full_screen": window.collectionBehavior.contains(.fullScreenAuxiliary), "shown": window.isVisible]
        more.forEach { info[$0] = $1 }
        log(event, info)
    }

    /// Plays the loop, for a while or until the next rest. Never with Reduce Motion on.
    private func playLoop(for seconds: TimeInterval? = nil) {
        guard !reduceMotion() else { return }
        stopLoop?.invalidate()
        player?.play()
        if let seconds {
            stopLoop = Timer.scheduledTimer(withTimeInterval: seconds, repeats: false) { [weak self] _ in
                if self?.move == nil { self?.player?.pause() }
            }
        }
    }

    /// Out of its menu bar icon (or, with the icon hidden, at the right end) and down onto the line.
    func letOut(from icon: NSRect?) {
        guard hasClip, !isOut else { return }
        isOut = true
        settled = false
        asleep = false
        let x = onLine((icon?.midX ?? lineX.upperBound + roamSize / 2 - 12) - roamSize / 2)
        if reduceMotion() {
            window.setFrameOrigin(NSPoint(x: x, y: lineY))
            window.alphaValue = 1
            window.orderFrontRegardless()
            arrived()
            return
        }
        window.setFrameOrigin(NSPoint(x: x, y: lineY + roamSize))
        window.alphaValue = 0
        window.orderFrontRegardless()
        playLoop()
        animate(to: NSPoint(x: x, y: lineY), height: 0, seconds: 0.4, fade: (0, 1)) { [weak self] in self?.arrived() }
    }

    private func arrived() {
        settled = true
        report("out")
        // Let out where it cannot be seen (a full-screen app in front, the screen asleep): it waits there, stopped.
        if !window.occlusionState.contains(.visible) { return sleep() }
        rest(roamFirstRest)
    }

    /// No loop for this look: nothing to walk with until another is loaded.
    func unload() {
        player?.pause()
        looper = nil
        player = nil
        view.playerLayer.player = nil
    }

    /// Back up into its icon, and gone.
    func goHome(to icon: NSRect?, now: Bool = false) {
        guard isOut else { return }
        settled = false
        next?.invalidate()
        let gone = { [weak self] in
            guard let self else { return }
            self.isOut = false
            self.player?.pause()
            self.window.orderOut(nil)
            self.report("home")
        }
        if now || reduceMotion() || asleep {
            stopMoving()
            return gone()
        }
        let x = icon.map { $0.midX - roamSize / 2 } ?? window.frame.minX
        playLoop()
        animate(to: NSPoint(x: x, y: lineY + roamSize), height: 24, seconds: 0.45, fade: (1, 0), then: gone)
    }

    @objc func callBack() { onCallBack?() }

    /// A rest on a paused frame, then a trip.
    private func rest(_ range: ClosedRange<Double>) {
        guard isOut, settled, !asleep else { return }
        stopLoop?.invalidate()
        player?.pause()
        // On the line as it is now: the display may have changed while it was on its way.
        window.setFrameOrigin(NSPoint(x: onLine(window.frame.minX), y: lineY))
        report("rest")
        next?.invalidate()
        next = Timer.scheduledTimer(withTimeInterval: Double.random(in: range, using: &dice), repeats: false) { [weak self] _ in
            self?.trip()
        }
    }

    /// Hops to another spot on the line, now and then with a jump at the end. Not with Reduce Motion on, and not while
    /// nobody is at the Mac: then it looks again after the next rest.
    private func trip() {
        guard isOut, settled, !asleep else { return }
        if reduceMotion() || idleSeconds() >= roamIdleAfter { return rest(roamRest) }
        let style = roamStyles[stage] ?? (10, 28, 0.4)
        let from = window.frame.minX
        // A short trip, to either side: back the other way where the line ends.
        let far = CGFloat.random(in: roamTrip, using: &dice)
        var side: CGFloat = Bool.random(using: &dice) ? 1 : -1
        if !lineX.contains(from + side * far) { side = -side }
        let to = onLine(from + side * far)
        let hops = max(1, Int((abs(to - from) / style.step).rounded(.up)))
        let jumps = Int.random(in: 0..<4, using: &dice) == 0
        playLoop()
        report("trip", ["to": Double(to), "hops": hops])
        func hop(_ i: Int) {
            guard i <= hops else {
                guard jumps else { return rest(roamRest) }
                report("jump")
                return animate(to: NSPoint(x: to, y: lineY), height: 36, seconds: 0.55) { [weak self] in self?.rest(roamRest) }
            }
            let x = from + (to - from) * CGFloat(i) / CGFloat(hops)
            animate(to: NSPoint(x: x, y: lineY), height: style.hop, seconds: style.beat) { hop(i + 1) }
        }
        hop(1)
    }

    /// The pointer touched it: the loop plays for a moment.
    func notice() {
        guard isOut, settled, !asleep, move == nil else { return }
        playLoop(for: roamNotice)
        report("notice")
    }

    /// A poke: the boing, a squash, and a jump of roamAway or more to the side away from the click (either side for a
    /// poke that was not a click, such as VoiceOver's), so what it sat on is free. With Reduce Motion on, the boing alone.
    @discardableResult
    func poke(at time: TimeInterval, clickX: CGFloat? = nil) -> Bool {
        guard isOut, settled else { return false }
        let sound = boinger.boing(stage: stage, at: time).sound
        let from = window.frame.minX
        guard !reduceMotion(), !asleep else {
            report("poke", ["sound": sound, "anim": "none", "from": Double(from)])
            return true
        }
        let squash = CAAnimationGroup()
        squash.animations = [("transform.scale.x", [1, 1.12, 0.96, 1]), ("transform.scale.y", [1, 0.82, 1.06, 1])].map {
            let animation = CAKeyframeAnimation(keyPath: $0.0)
            animation.values = $0.1
            return animation
        }
        squash.duration = 0.3
        view.playerLayer.add(squash, forKey: "poke")
        let far = CGFloat.random(in: roamAway...(roamAway + 100), using: &dice)
        let either = Bool.random(using: &dice)
        var side: CGFloat = (clickX.map { from + roamSize / 2 >= $0 } ?? either) ? 1 : -1
        if !lineX.contains(from + side * far) { side = -side }
        next?.invalidate()
        playLoop()
        report("poke", ["sound": sound, "anim": "squash,jump", "from": Double(from)])
        animate(to: NSPoint(x: onLine(from + side * far), y: lineY), height: 40, seconds: 0.55) { [weak self] in
            self?.rest(roamRest)
        }
        return true
    }

    /// Moves the window from where it is to a point along an arc this high, fading if asked, then goes on.
    private func animate(to: NSPoint, height: CGFloat, seconds: TimeInterval, fade: (from: CGFloat, to: CGFloat) = (1, 1),
                         then: @escaping () -> Void) {
        move = (window.frame.origin, to, height, ProcessInfo.processInfo.systemUptime, seconds, fade, then)
        guard ticker == nil else { return }
        let clock = Timer(timeInterval: 1.0 / 60, repeats: true) { [weak self] _ in self?.tick() }
        RunLoop.main.add(clock, forMode: .common)   // keeps hopping while a menu is open
        ticker = clock
    }

    private func tick() {
        guard let m = move else { return stopMoving() }
        let t = CGFloat(min(1, (ProcessInfo.processInfo.systemUptime - m.start) / m.seconds))
        window.setFrameOrigin(NSPoint(x: m.from.x + (m.to.x - m.from.x) * t,
                                      y: m.from.y + (m.to.y - m.from.y) * t + m.height * 4 * t * (1 - t)))
        window.alphaValue = m.fade.from + (m.fade.to - m.fade.from) * t
        if t >= 1 {
            move = nil
            m.then()
            if move == nil { stopMoving() }
        }
    }

    private func stopMoving() {
        ticker?.invalidate()
        ticker = nil
        move = nil
    }

    /// The screen went to sleep, the session was switched away, or the window is not visible (a full-screen app, the
    /// screensaver): everything stops, on the line.
    @objc private func sleep() {
        guard isOut, settled, !asleep else { return }
        asleep = true
        next?.invalidate()
        stopLoop?.invalidate()
        stopMoving()
        player?.pause()
        window.setFrameOrigin(NSPoint(x: onLine(window.frame.minX), y: lineY))
        window.alphaValue = 1
        report("sleep")
    }

    /// Visible again: back to a short rest, then on with its walk.
    @objc private func seen() {
        guard isOut, settled else { return }
        if !window.occlusionState.contains(.visible) { return sleep() }
        guard asleep else { return }
        asleep = false
        report("wake")
        rest(roamFirstRest)
    }

    /// The display changed (resolution, a lid, the menu bar hidden or shown): back onto the line.
    @objc private func screenChanged() {
        guard isOut, settled, move == nil else { return }
        window.setFrameOrigin(NSPoint(x: onLine(window.frame.minX), y: lineY))
    }
}

/// Free roam's switch: the lock on the Creature card, the marker file, and the walker.
final class RoamControl {
    let roamer: Roamer
    private let marker: URL
    private let clipsDir: URL?
    private weak var creature: PanelView?
    private var look = ""
    /// Where the menu bar icon is, when it is on screen: the creature leaves and comes home through it.
    var icon: () -> NSRect? = { nil }
    /// After the lock was clicked (the panel closes, so the creature is seen leaving).
    var didToggle: (() -> Void)?

    init(panelDir: URL, creature: PanelView, clipsDir: URL?, seed: UInt64? = nil) {
        roamer = Roamer(seed: seed)
        marker = roamMarker(panelDir)
        self.clipsDir = clipsDir
        self.creature = creature
        creature.onRoam = { [weak self] in self?.toggle() }
        roamer.onCallBack = { [weak self] in self?.toggle() }
    }

    private var wantsOut: Bool { FileManager.default.fileExists(atPath: marker.path) }

    /// A new card: the look's see-through loop, if it has one, and out again if it was out when the panel last ran.
    func update(_ card: Card?) {
        guard let card else { return }
        let key = "\(card.stage)|\(card.cls)"
        guard key != look else { return }
        look = key
        if let clip = roamClip(stage: card.stage, cls: card.cls, dir: clipsDir) {
            roamer.load(clip, stage: card.stage)
            creature?.roamAvailable = true
            if wantsOut && !roamer.isOut { roamer.letOut(from: icon()) }
            creature?.roamOut = wantsOut && roamer.isOut   // the marker is gone while it is still on its way home
        } else {   // home at once: its going is animated, so the panel is told here, not from isOut
            creature?.roamAvailable = false
            roamer.goHome(to: nil, now: true)
            roamer.unload()
            creature?.roamOut = false
        }
    }

    /// The lock: out when it is home (and this look can walk), home when it is out.
    func toggle() {
        if roamer.isOut {
            try? FileManager.default.removeItem(at: marker)
            roamer.goHome(to: icon())
            creature?.roamOut = false
        } else if roamer.hasClip {
            try? FileManager.default.createDirectory(at: marker.deletingLastPathComponent(), withIntermediateDirectories: true)
            guard FileManager.default.createFile(atPath: marker.path, contents: nil, attributes: [.posixPermissions: 0o600]) else { return }
            roamer.letOut(from: icon())
            creature?.roamOut = true
        }
        didToggle?()
    }
}

final class PanelApp: NSObject, NSApplicationDelegate, NSPopoverDelegate {
    let python: String, scanner: String, claudeDir: String, cache: URL
    /// The creature's menu bar item. A fixed name lets macOS keep where the user ⌘-drags it, across restarts and
    /// updates (in this program's own preferences, cclevel-panel; --panel off removes them). The first time, with no
    /// position saved, it is put at the right end of the menu bar items, next to the system ones, instead of macOS's
    /// default for a new item: the far left, beside the notch, where a notch app or a crowded menu bar hides it. That
    /// first position is saved like a drag (a registered default would pin it there and override every later drag).
    lazy var item: NSStatusItem = {
        let key = "NSStatusItem Preferred Position \(statusItemName)"
        if UserDefaults.standard.object(forKey: key) == nil {
            UserDefaults.standard.set(1.0, forKey: key)
        }
        let item = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        item.autosaveName = statusItemName
        return item
    }()
    let popover = NSPopover()
    let root = PageView()
    var isScanning = false
    var blinkTimer: Timer?
    /// Free roam: the lock on the Creature card, and the creature out for a walk.
    lazy var roam = RoamControl(panelDir: cache.deletingLastPathComponent(), creature: root.creature,
                                clipsDir: cache.deletingLastPathComponent().appendingPathComponent("creatures"))

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
        root.privacyOn = privacyCheck(claudeDir)
        // The creature leaves and comes home through its menu bar icon, when the icon is on screen (a menu bar tidier
        // or a crowded notch bar can hide it). The panel closes on the lock's click, so the creature is seen going.
        roam.icon = { [weak self] in
            guard let window = self?.item.button?.window, window.isVisible, let screen = NSScreen.screens.first,
                  screen.frame.intersects(window.frame) else { return nil }
            return window.frame
        }
        roam.didToggle = { [weak self] in self?.popover.performClose(nil) }
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
        roam.update(card)
    }

    func refreshIfStale() {
        if root.card == nil || cardStale(saved: modified(cache), scanner: modified(URL(fileURLWithPath: scanner)),
                                         identity: modified(identityFile(claudeDir))) { refresh() }
    }

    @objc func refresh() {
        guard !isScanning else { return }
        isScanning = true
        root.status = "Scoring your setup, offline…"
        let started = Date()
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
            DispatchQueue.main.async { self?.finish(ok ? data : nil, started: started) }
        }
    }

    func finish(_ data: Data?, started: Date) {
        isScanning = false
        guard let data, let card = readCard(data) else {
            root.status = "Could not score this time. Right-click to try again."
            return
        }
        try? FileManager.default.createDirectory(at: cache.deletingLastPathComponent(), withIntermediateDirectories: true)
        if (try? data.write(to: cache, options: .atomic)) != nil {
            // Dated from when the scan started: a change to identity.json while it ran is newer, so it scores again.
            try? FileManager.default.setAttributes([.posixPermissions: 0o600, .modificationDate: started], ofItemAtPath: cache.path)
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

// What the invite card's Copy button does (the same function, Privacy mode check included, with --claude-dir for the
// folder to check), without the panel: for tests. Prints nothing; the link is on the clipboard.
if CommandLine.arguments.contains("--copy-invite") {
    guard let path = option("--card"), let data = FileManager.default.contents(atPath: path), let card = readCard(data) else {
        FileHandle.standardError.write("cclevel-panel: --copy-invite needs --card with a card from `cclevel.py --json`\n".data(using: .utf8)!)
        exit(1)
    }
    guard copyInviteLink(card, privacyOn: option("--claude-dir").map(privacyCheck)) else {
        FileHandle.standardError.write("cclevel-panel: no invite link to copy (no group, or Privacy mode)\n".data(using: .utf8)!)
        exit(1)
    }
    exit(0)
}

// Whether the running panel would score again now, from the same files and the same rule: exit 0 when the card is stale
// (none, over an hour old, or older than the scanner beside it or than --identity), 1 when it is current. For tests;
// prints nothing.
if CommandLine.arguments.contains("--card-stale") {
    guard let cache = option("--cache"), let scanner = option("--scanner") else {
        FileHandle.standardError.write("cclevel-panel: --card-stale needs --cache CARD.json and --scanner cclevel.py\n".data(using: .utf8)!)
        exit(2)
    }
    let identity = option("--identity").flatMap { modified(URL(fileURLWithPath: $0)) }
    exit(cardStale(saved: modified(URL(fileURLWithPath: cache)), scanner: modified(URL(fileURLWithPath: scanner)),
                   identity: identity) ? 0 : 1)
}

if let out = option("--snapshot") {
    guard let path = option("--card"), let data = FileManager.default.contents(atPath: path), let card = readCard(data) else {
        FileHandle.standardError.write("cclevel-panel: --snapshot needs --card with a card from `cclevel.py --json`\n".data(using: .utf8)!)
        exit(1)
    }
    if CommandLine.arguments.contains("--tab") {
        FileHandle.standardError.write("cclevel-panel: --tab is gone (the tabs became pages): use --page home, fix or learn\n".data(using: .utf8)!)
        exit(1)
    }
    testReduceMotion = CommandLine.arguments.contains("--reduce-motion")
    testUISounds = ["on": true, "off": false][option("--ui-sounds") ?? ""]
    let view = PageView()
    if let text = option("--height"), let height = Double(text) {
        view.fit(height: CGFloat(height))   // as on a screen with less room
    }
    if let clips = option("--clips") {
        view.creature.clipsDir = URL(fileURLWithPath: clips, isDirectory: true)
    }
    if let dir = option("--claude-dir") {
        view.privacyOn = privacyCheck(dir)   // as the running panel checks it
    }
    if let text = option("--now"), let seconds = Double(text) {
        view.clock = { Date(timeIntervalSince1970: seconds) }   // the Friends page drawn as at that moment
    }
    view.card = card
    view.updated = Date(timeIntervalSince1970: 0)
    // Free roam's lock as the running panel would show it: on when this look has a see-through loop in --clips, and
    // with --roam-out, as while the creature is out for a walk.
    view.creature.roamAvailable = roamClip(stage: card.stage, cls: card.cls, dir: view.creature.clipsDir) != nil
    view.creature.roamOut = CommandLine.arguments.contains("--roam-out")
    if CommandLine.arguments.contains("--page") {
        guard let name = option("--page"), let page = Page(rawValue: name) else {
            FileHandle.standardError.write("cclevel-panel: --page is home, fix, learn or friends\n".data(using: .utf8)!)
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
    // Clicks on the Creature card: the panel as when it opens, in a window off screen, gets each click through that
    // window (so the real hit test and mouse handlers run), and prints what it did, read back from the layer and player.
    if let at = option("--poke-at") {
        let xy = at.split(separator: ",").compactMap { Double($0) }
        guard xy.count == 2 else {
            FileHandle.standardError.write("cclevel-panel: --poke-at takes X,Y in the Creature card, such as 88,88\n".data(using: .utf8)!)
            exit(1)
        }
        let window = NSWindow(contentRect: NSRect(x: -10000, y: -10000, width: size.width, height: size.height),
                              styleMask: [.borderless], backing: .buffered, defer: false)
        window.contentView = view
        window.orderFrontRegardless()   // a window that is not ordered in drops mouse events; this one stays off screen
        view.setOpen(true)
        view.layoutSubtreeIfNeeded()
        let point = view.creature.convert(NSPoint(x: xy[0], y: xy[1]), to: nil)
        let times = max(Int(option("--times") ?? "") ?? 1, 1)
        let gap = (Double(option("--gap") ?? "") ?? 300) / 1000
        let start = ProcessInfo.processInfo.systemUptime
        print("ui_sounds=\(uiSoundsOn() ? "on" : "off")")
        for i in 0..<times {
            let down = start + Double(i) * gap
            for (type, when) in [(NSEvent.EventType.leftMouseDown, down), (.leftMouseUp, down + 0.02)] {
                if let event = NSEvent.mouseEvent(with: type, location: point, modifierFlags: [], timestamp: when,
                                                  windowNumber: window.windowNumber, context: nil, eventNumber: i,
                                                  clickCount: 1, pressure: type == .leftMouseDown ? 1 : 0) {
                    window.sendEvent(event)
                }
            }
            print(view.creature.takePokeLine())
        }
        exit(0)
    }
    for card in view.cards { print(card.accessibilityLabel() ?? "") }
    if CommandLine.arguments.contains("--roam-out") || CommandLine.arguments.contains("--lock") {
        let lock = view.creature.lock
        print("Lock: \(lock.accessibilityLabel() ?? "")\(lock.isEnabled ? "" : " (off: \(lock.toolTip ?? ""))")")
    }
    exit(0)
}

// How see-through each of free roam's loops is, for tests: `--clip-alpha DIR` prints, for every .mov in DIR by name, its
// first frame's alpha at a corner and at the centre ("egg.mov 0 255"; "egg.mov none" for one that does not decode).
if let dir = option("--clip-alpha") {
    let names = ((try? FileManager.default.contentsOfDirectory(atPath: dir)) ?? []).filter { $0.hasSuffix(".mov") }.sorted()
    for name in names {
        let url = URL(fileURLWithPath: dir, isDirectory: true).appendingPathComponent(name)
        if let frame = firstFrame(url)?.cgImage(forProposedRect: nil, context: nil, hints: nil) {
            print("\(name) \(alphaAt(frame, x: 1, y: 1)) \(alphaAt(frame, x: frame.width / 2, y: frame.height / 2))")
        } else {
            print("\(name) none")
        }
    }
    exit(0)
}

// Free roam without the menu bar item, for tests: `--roam-test SECONDS --card CARD.json --clips DIR --panel-dir DIR` runs
// the walker as the panel would (out if DIR/roam is there) and prints one JSON line per event with where its window is.
// `--seed N` makes its choices the same every run, `--idle S` runs it as if nobody had touched the Mac for S seconds,
// `--poke-after S` pokes it S seconds in (with `--click-side left|right`, as a click on that half of it), `--toggle-after S` clicks the Creature card's lock S seconds in, and
// --reduce-motion and --ui-sounds work as with --snapshot.
if let text = option("--roam-test") {
    guard let seconds = Double(text), let path = option("--card"), let data = FileManager.default.contents(atPath: path),
          let card = readCard(data), let clips = option("--clips"), let panelDir = option("--panel-dir") else {
        FileHandle.standardError.write("cclevel-panel: --roam-test SECONDS needs --card, --clips and --panel-dir\n".data(using: .utf8)!)
        exit(1)
    }
    setvbuf(stdout, nil, _IONBF, 0)
    testReduceMotion = CommandLine.arguments.contains("--reduce-motion")
    testUISounds = ["on": true, "off": false][option("--ui-sounds") ?? ""]
    testIdle = option("--idle").flatMap { Double($0) }
    app.setActivationPolicy(.accessory)
    let clipsDir = URL(fileURLWithPath: clips, isDirectory: true)
    let creature = PanelView()
    creature.clipsDir = clipsDir
    creature.card = card
    let control = RoamControl(panelDir: URL(fileURLWithPath: panelDir, isDirectory: true), creature: creature,
                              clipsDir: clipsDir, seed: option("--seed").flatMap { UInt64($0) })
    let start = ProcessInfo.processInfo.systemUptime
    func line(_ event: String, _ info: [String: Any]) {
        var all = info
        all["event"] = event
        all["t"] = ((ProcessInfo.processInfo.systemUptime - start) * 100).rounded() / 100
        if let json = try? JSONSerialization.data(withJSONObject: all, options: [.sortedKeys]) {
            print(String(data: json, encoding: .utf8) ?? "")
        }
    }
    control.roamer.log = line
    if let clip = roamClip(stage: card.stage, cls: card.cls, dir: clipsDir),
       let frame = firstFrame(clip)?.cgImage(forProposedRect: nil, context: nil, hints: nil) {
        line("clip", ["file": clip.lastPathComponent, "alpha_corner": alphaAt(frame, x: 1, y: 1),
                      "alpha_centre": alphaAt(frame, x: frame.width / 2, y: frame.height / 2)])
    } else {
        line("clip", ["file": ""])
    }
    control.update(card)
    line(control.roamer.isOut ? "walker" : "no-walker", ["lock_enabled": creature.lock.isEnabled])
    if let after = option("--poke-after").flatMap({ Double($0) }) {
        // With --click-side left|right, a poke as from a click on that half of the creature: it jumps to the other side.
        let side: CGFloat? = ["left": 8, "right": roamSize - 8][option("--click-side") ?? ""]
        DispatchQueue.main.asyncAfter(deadline: .now() + after) {
            control.roamer.poke(at: ProcessInfo.processInfo.systemUptime,
                                clickX: side.map { control.roamer.window.frame.minX + $0 })
        }
    }
    if let after = option("--toggle-after").flatMap({ Double($0) }) {
        DispatchQueue.main.asyncAfter(deadline: .now() + after) {
            creature.lock.performClick(nil)
            line("lock", ["out": creature.roamOut, "label": creature.lock.accessibilityLabel() ?? ""])
        }
    }
    DispatchQueue.main.asyncAfter(deadline: .now() + seconds) { exit(0) }
    app.run()
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
