import AppKit

func loadFonts() {
    let fontPaths = [
        "tracker-app/Fonts/SpaceGrotesk-Regular.ttf",
        "tracker-app/Fonts/SpaceGrotesk-Medium.ttf",
        "tracker-app/Fonts/SpaceGrotesk-SemiBold.ttf",
        "tracker-app/Fonts/SpaceGrotesk-Bold.ttf",
        "tracker-app/Fonts/JetBrainsMono-Regular.ttf",
        "tracker-app/Fonts/JetBrainsMono-Medium.ttf",
        "tracker-app/Fonts/JetBrainsMono-SemiBold.ttf",
        "tracker-app/Fonts/JetBrainsMono-Bold.ttf"
    ]
    
    for path in fontPaths {
        guard let data = try? Data(contentsOf: URL(fileURLWithPath: path)),
              let provider = CGDataProvider(data: data as CFData),
              let font = CGFont(provider) else {
            print("Failed to load \(path)")
            continue
        }
        print("\(path) -> PSName: \(font.postScriptName as String?)")
    }
}
loadFonts()
