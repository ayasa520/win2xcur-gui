# Win2xcur Flatpak Repository

This repository hosts the Flatpak packages for Win2xcur, a tool to convert Windows cursors to Xcursor format.

## Installation

### Method 1: Using flatpakref (Recommended)

```bash
flatpak install --user https://ayasa520.github.io/win2xcur-gui/io.github.ayasa520.Win2xcur.flatpakref
```

### Method 2: Manual remote configuration

```bash
# Download GPG key
wget https://ayasa520.github.io/win2xcur-gui/repo/win2xcur.gpg

# Add remote
flatpak remote-add --user --gpg-import=win2xcur.gpg win2xcur https://ayasa520.github.io/win2xcur-gui/repo

# Install application
flatpak install --user win2xcur io.github.ayasa520.Win2xcur
```

## Source Code

The source code is available on the [main branch](https://github.com/ayasa520/win2xcur-gui/tree/main).
