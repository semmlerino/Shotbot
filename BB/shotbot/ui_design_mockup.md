# ShotBot Custom Launcher Integration Design

## Design Overview

The custom launchers have been integrated directly into the main launcher panel, creating a unified interface for all application launching functionality.

### Visual Design

```
┌─────────────────────────────────────┐
│ Launch Applications                 │
├─────────────────────────────────────┤
│ Select a shot to enable app launch  │
│                                     │
│ [3DE]          (Blue-gray buttons)  │
│ [NUKE]                              │
│ [MAYA]                              │
│ [RV]                                │
│ [PUBLISH]                           │
│                                     │
│ ☐ Include undistortion nodes (Nuke) │
│ ☐ Include raw plate (Nuke)          │
│                                     │
│ ─────────────────────────────────── │
│ Custom Launchers                    │
│                                     │
│ [🚀 Script Runner]  (Green buttons) │
│ [🚀 Render Farm]                    │
│ [🚀 Custom Tool]                    │
└─────────────────────────────────────┘
```

### Color Scheme

**Built-in Launchers (Blue-gray theme):**
- Normal: `#2b3e50` (dark blue-gray)
- Hover: `#34495e` (lighter blue-gray)
- Pressed: `#1a252f` (darker blue-gray)
- Disabled: `#1e2a35` (muted blue-gray)

**Custom Launchers (Green theme):**
- Normal: `#1a4d2e` (dark green)
- Hover: `#245938` (lighter green)
- Pressed: `#0f3620` (darker green)
- Disabled: `#1a2e20` (muted green)

### Key Features

1. **Unified Interface**: All launchers in one place, no need to navigate to separate menus
2. **Visual Distinction**: Different color schemes make it immediately clear which are built-in vs custom
3. **Consistent Behavior**: Both types of launchers follow the same enable/disable pattern based on shot selection
4. **Dynamic Updates**: Custom launcher section updates automatically when launchers are added/edited/removed
5. **Category Support**: If multiple categories exist, they are displayed with subtle headers
6. **Emoji Icons**: Custom launchers use a rocket emoji (🚀) to further distinguish them
7. **Tooltips**: Full descriptions available on hover

### Implementation Details

- Custom launchers section added directly to the launcher panel layout
- Horizontal separator line visually divides the two sections
- Minimum height increased from 250px to 350px to accommodate custom launchers
- Button states synchronized with shot selection
- Menu system retained for backward compatibility but primary access is through the integrated UI

### Benefits

1. **Improved Discoverability**: Users immediately see all available launchers
2. **Faster Access**: No need to navigate through menus
3. **Better Visual Hierarchy**: Clear distinction between launcher types
4. **Consistent UX**: All launchers behave the same way
5. **Space Efficient**: Vertical stacking makes good use of available space