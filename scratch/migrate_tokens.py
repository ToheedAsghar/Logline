import os

files_to_check = ["tracker-app/UI/MainView.swift", "tracker-app/UI/LiveEventsView.swift"]
for filepath in files_to_check:
    with open(filepath, 'r') as f:
        content = f.read()
    
    # Migrate Colors
    content = content.replace("Tokens.Colors.SwiftUI.bg", "Tokens.Colors.windowBg")
    content = content.replace("Tokens.Colors.SwiftUI.surface", "Tokens.Colors.cardBg")
    content = content.replace("Tokens.Colors.SwiftUI.border", "Tokens.Colors.border")
    content = content.replace("Tokens.Colors.SwiftUI.text", "Tokens.Colors.ink")
    content = content.replace("Tokens.Colors.SwiftUI.muted", "Tokens.Colors.muted")
    content = content.replace("Tokens.Colors.SwiftUI.accent", "Tokens.Colors.brandGreen")
    content = content.replace("Tokens.Colors.SwiftUI.accentSoft", "Tokens.Colors.statusNotConnected")
    content = content.replace("Tokens.Colors.SwiftUI.danger", "Tokens.Colors.statusFailed")
    content = content.replace("Tokens.Colors.SwiftUI.", "Tokens.Colors.")
    
    # Migrate Radius
    content = content.replace("Tokens.Radius.md", "Tokens.Radius.card")
    content = content.replace("Tokens.Radius.lg", "Tokens.Radius.window")
    
    with open(filepath, 'w') as f:
        f.write(content)
