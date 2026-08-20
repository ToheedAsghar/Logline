import AppKit

let fontManager = NSFontManager.shared
let availableFamilies = fontManager.availableFontFamilies

let targets = ["Space Grotesk", "JetBrains Mono"]
for target in targets {
    if availableFamilies.contains(target) {
        print("\(target): FOUND")
    } else {
        print("\(target): MISSING")
    }
}
