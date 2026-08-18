import AppKit
import SwiftUI

/// Design tokens ported from the web frontend's `index.css` OKLCH values
public enum Tokens {
    public enum Colors {
        // Main colors
        public static let bg = NSColor(red: 0.964, green: 0.956, blue: 0.924, alpha: 1.000)
        public static let surface = NSColor(red: 0.994, green: 0.991, blue: 0.970, alpha: 1.000)
        public static let surface2 = NSColor(red: 0.932, green: 0.923, blue: 0.882, alpha: 1.000)
        
        // Borders
        public static let border = NSColor(red: 0.847, green: 0.840, blue: 0.794, alpha: 1.000)
        public static let border2 = NSColor(red: 0.723, green: 0.724, blue: 0.662, alpha: 1.000)
        
        // Text
        public static let text = NSColor(red: 0.083, green: 0.132, blue: 0.092, alpha: 1.000)
        public static let muted = NSColor(red: 0.280, green: 0.342, blue: 0.294, alpha: 1.000)
        public static let faint = NSColor(red: 0.441, green: 0.497, blue: 0.446, alpha: 1.000)
        
        // Accents
        public static let accent = NSColor(red: 0.101, green: 0.447, blue: 0.273, alpha: 1.000)
        public static let accentInk = NSColor(red: 0.968, green: 0.965, blue: 0.906, alpha: 1.000)
        public static let accentDim = NSColor(red: 0.101, green: 0.447, blue: 0.273, alpha: 1.000)
        public static let accentSoft = NSColor(red: 0.101, green: 0.447, blue: 0.273, alpha: 0.130)
        
        // Danger
        public static let danger = NSColor(red: 0.693, green: 0.241, blue: 0.024, alpha: 1.000)
        public static let dangerSoft = NSColor(red: 0.693, green: 0.241, blue: 0.024, alpha: 0.120)
        
        // Sidebar
        public static let sidebarBg = NSColor(red: 0.065, green: 0.112, blue: 0.084, alpha: 1.000)
        public static let sidebarSurface = NSColor(red: 0.127, green: 0.186, blue: 0.151, alpha: 1.000)
        public static let sidebarText = NSColor(red: 0.924, green: 0.934, blue: 0.899, alpha: 1.000)
        public static let sidebarMuted = NSColor(red: 0.565, green: 0.612, blue: 0.572, alpha: 1.000)
        public static let sidebarBorder = NSColor(red: 0.164, green: 0.220, blue: 0.186, alpha: 1.000)
        
        // SwiftUI equivalents for convenience if using NSHostingView later
        public struct SwiftUI {
            public static let bg = Color(nsColor: Colors.bg)
            public static let surface = Color(nsColor: Colors.surface)
            public static let surface2 = Color(nsColor: Colors.surface2)
            public static let border = Color(nsColor: Colors.border)
            public static let border2 = Color(nsColor: Colors.border2)
            public static let text = Color(nsColor: Colors.text)
            public static let muted = Color(nsColor: Colors.muted)
            public static let faint = Color(nsColor: Colors.faint)
            public static let accent = Color(nsColor: Colors.accent)
            public static let accentInk = Color(nsColor: Colors.accentInk)
            public static let accentDim = Color(nsColor: Colors.accentDim)
            public static let accentSoft = Color(nsColor: Colors.accentSoft)
            public static let danger = Color(nsColor: Colors.danger)
            public static let dangerSoft = Color(nsColor: Colors.dangerSoft)
        }
    }
    
    public enum Radius {
        public static let xs: CGFloat = 4
        public static let sm: CGFloat = 7
        public static let md: CGFloat = 9
        public static let lg: CGFloat = 12
        public static let xl: CGFloat = 14
        public static let xxl: CGFloat = 16
        public static let xxxl: CGFloat = 18
        public static let pill: CGFloat = 999
    }
}
