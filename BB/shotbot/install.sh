#!/bin/bash
#
# ShotBot Installation Script
#

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Default installation directory
DEFAULT_INSTALL_DIR="/opt/shotbot"
DEFAULT_BIN_DIR="/usr/local/bin"

# Function to print colored messages
print_message() {
    local color=$1
    local message=$2
    echo -e "${color}${message}${NC}"
}

# Check if running as root for system-wide installation
if [ "$EUID" -eq 0 ]; then 
    print_message "$GREEN" "Running as root - will perform system-wide installation"
    INSTALL_DIR="$DEFAULT_INSTALL_DIR"
    BIN_DIR="$DEFAULT_BIN_DIR"
else
    print_message "$YELLOW" "Not running as root - will install to user directory"
    INSTALL_DIR="$HOME/.local/share/shotbot"
    BIN_DIR="$HOME/.local/bin"
    
    # Create user bin directory if it doesn't exist
    mkdir -p "$BIN_DIR"
    
    # Check if user bin is in PATH
    if [[ ":$PATH:" != *":$BIN_DIR:"* ]]; then
        print_message "$YELLOW" "Warning: $BIN_DIR is not in your PATH"
        print_message "$YELLOW" "Add this line to your ~/.bashrc or ~/.profile:"
        print_message "$BLUE" "export PATH=\"\$PATH:$BIN_DIR\""
    fi
fi

# Script directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"

print_message "$GREEN" "Installing ShotBot..."

# Create installation directory
print_message "$BLUE" "Creating installation directory: $INSTALL_DIR"
mkdir -p "$INSTALL_DIR"

# Copy all Python files
print_message "$BLUE" "Copying application files..."
cp -r "$SCRIPT_DIR"/*.py "$INSTALL_DIR/"

# Create wrapper script
print_message "$BLUE" "Creating launcher script..."
cat > "$BIN_DIR/shotbot" << 'EOF'
#!/bin/bash
#
# ShotBot Launcher
#

# Installation directory
INSTALL_DIR="__INSTALL_DIR__"
SHOTBOT_SCRIPT="${INSTALL_DIR}/shotbot.py"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Function to print colored messages
print_message() {
    local color=$1
    local message=$2
    echo -e "${color}${message}${NC}"
}

# Error handling
set -e
trap 'echo -e "${RED}Error: Command failed${NC}"' ERR

# Check if rez is available
if ! command -v rez &> /dev/null; then
    print_message "$RED" "Error: 'rez' command not found."
    print_message "$YELLOW" "Please ensure Rez is installed and available in your environment."
    exit 1
fi

# Check if we're in a VFX environment (look for SHOW or SHOT env vars)
if [ -z "$SHOW" ] && [ -z "$SHOT" ]; then
    print_message "$YELLOW" "Note: No SHOW/SHOT environment variables detected."
    print_message "$YELLOW" "You may need to source your studio environment first."
fi

# Required packages
REZ_PACKAGES="PySide6_Essentials pillow Jinja2"

# Launch ShotBot
print_message "$GREEN" "Starting ShotBot..."

# Execute with rez environment
exec rez env $REZ_PACKAGES -- python3 "$SHOTBOT_SCRIPT" "$@"
EOF

# Replace the installation directory placeholder
sed -i "s|__INSTALL_DIR__|$INSTALL_DIR|g" "$BIN_DIR/shotbot"

# Make executable
chmod +x "$BIN_DIR/shotbot"

print_message "$GREEN" "Installation complete!"
print_message "$BLUE" "ShotBot installed to: $INSTALL_DIR"
print_message "$BLUE" "Launcher installed to: $BIN_DIR/shotbot"
print_message "$GREEN" "\nYou can now run ShotBot by typing: shotbot"

# Create desktop entry for GUI menu (optional)
if [ "$EUID" -eq 0 ]; then
    DESKTOP_DIR="/usr/share/applications"
else
    DESKTOP_DIR="$HOME/.local/share/applications"
    mkdir -p "$DESKTOP_DIR"
fi

print_message "$BLUE" "\nCreating desktop entry..."
cat > "$DESKTOP_DIR/shotbot.desktop" << EOF
[Desktop Entry]
Name=ShotBot
Comment=VFX Shot Browser and Launcher
Exec=$BIN_DIR/shotbot
Icon=applications-multimedia
Terminal=false
Type=Application
Categories=Graphics;AudioVideo;
EOF

print_message "$GREEN" "Desktop entry created. ShotBot should appear in your applications menu."
print_message "$YELLOW" "\nNote: Make sure you're in a proper VFX environment with 'ws' command available before running ShotBot."