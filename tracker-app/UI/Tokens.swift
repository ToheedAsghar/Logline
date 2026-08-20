import AppKit
import SwiftUI

public enum Tokens {
    public enum Colors {
        // Core Layout
        public static let windowBg = Color(hex: "#F6F2E9")
        public static let cardBg = Color(hex: "#FEFDF8")
        public static let border = Color(hex: "#E3DFD5")
        
        // Text
        public static let ink = Color(hex: "#1A1712") // Primary text
        public static let body = Color(hex: "#4A4640") // Secondary text
        public static let muted = Color(hex: "#8B8474") // Muted detail text
        
        // Brand & Accents
        public static let primaryButton = Color(hex: "#8DAA94")
        public static let primaryButtonHover = Color(hex: "#7D9C85")
        public static let brandLime = Color(hex: "#9BD648")
        public static let brandGreen = Color(hex: "#12623D")
        
        // Status Indicators
        public static let statusNotConnected = Color(hex: "#A39C8C")
        public static let statusConnected = Color(hex: "#5F8A71")
        public static let statusSyncing = Color(hex: "#9BD648")
        public static let statusFailed = Color(hex: "#B8442F")
        
        // Idle pill
        public static let idlePillText = Color(hex: "#8A6C22")
        public static let idlePillDot = Color(hex: "#B08B2F")
        public static let idlePillBg = Color(red: 184/255.0, green: 141/255.0, blue: 47/255.0, opacity: 0.13)
        
        // Tables
        public static let tableHeaderBg = Color(hex: "#F4F0E5")
        public static let tableRowHover = Color(hex: "#F5F1E6")
        public static let tableRowBorder = Color(hex: "#F2EEE3")
    }
    
    public enum Radius {
        public static let control: CGFloat = 7
        public static let card: CGFloat = 10
        public static let window: CGFloat = 14
    }
    
    public enum Fonts {
        public static func ui(size: CGFloat, weight: Font.Weight = .regular) -> Font {
            let weightName: String
            switch weight {
            case .medium: weightName = "SpaceGrotesk-Medium"
            case .semibold: weightName = "SpaceGrotesk-SemiBold"
            case .bold: weightName = "SpaceGrotesk-Bold"
            default: weightName = "SpaceGrotesk-Regular"
            }
            return Font.custom(weightName, size: size)
        }
        
        public static func mono(size: CGFloat, weight: Font.Weight = .regular) -> Font {
            let weightName: String
            switch weight {
            case .medium: weightName = "JetBrainsMono-Medium"
            case .semibold: weightName = "JetBrainsMono-SemiBold"
            case .bold: weightName = "JetBrainsMono-Bold"
            default: weightName = "JetBrainsMono-Regular"
            }
            return Font.custom(weightName, size: size)
        }
    }
}

// Helper for hex colors
extension Color {
    init(hex: String) {
        let hex = hex.trimmingCharacters(in: CharacterSet.alphanumerics.inverted)
        var int: UInt64 = 0
        Scanner(string: hex).scanHexInt64(&int)
        let a, r, g, b: UInt64
        switch hex.count {
        case 3: // RGB (12-bit)
            (a, r, g, b) = (255, (int >> 8) * 17, (int >> 4 & 0xF) * 17, (int & 0xF) * 17)
        case 6: // RGB (24-bit)
            (a, r, g, b) = (255, int >> 16, int >> 8 & 0xFF, int & 0xFF)
        case 8: // ARGB (32-bit)
            (a, r, g, b) = (int >> 24, int >> 16 & 0xFF, int >> 8 & 0xFF, int & 0xFF)
        default:
            (a, r, g, b) = (1, 1, 1, 0)
        }
        self.init(
            .sRGB,
            red: Double(r) / 255,
            green: Double(g) / 255,
            blue:  Double(b) / 255,
            opacity: Double(a) / 255
        )
    }
}
