#!/bin/bash

# Simple setup script for k8s-ansible-manager

set -e # Exit immediately if a command exits with a non-zero status.

# --- Helper Functions ---

echo_info() {
    echo -e "\033[1;34m[INFO]\033[0m $1"
}

echo_warn() {
    echo -e "\033[1;33m[WARN]\033[0m $1"
}

echo_error() {
    echo -e "\033[1;31m[ERROR]\033[0m $1"
}

command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# --- Check OS ---
echo_info "Checking Operating System..."
if [[ "$(uname)" == "Linux" ]]; then
    # Further check for Debian/Ubuntu derivatives for apt
    if ! command_exists apt-get; then
        echo_warn "This script primarily supports Debian/Ubuntu based Linux distributions for automatic package installation."
        echo_warn "For other distributions, please install Python 3.8+, pip, and Ansible manually."
        # exit 1 # Or continue without apt support?
    fi
elif [[ "$(uname)" == "Darwin" ]]; then
     echo_warn "Detected macOS. Please ensure Python 3.8+, pip, and Ansible are installed (e.g., using Homebrew)."
     # Add brew install commands here? Or just check?
else
    echo_warn "Unsupported OS detected. Please ensure Python 3.8+, pip, and Ansible are installed manually."
    exit 1
fi

# --- Check Python & Pip ---
echo_info "Checking for Python 3.8+ and pip..."
REQUIRED_PYTHON_VERSION="3.8"

python_version_ok=false
if command_exists python3; then
    # Get version (handle different output formats)
    py_version=$(python3 -V 2>&1 | sed 's/.* \([0-9]\.[0-9]\+\).*/\1/')
    if [[ "$(printf '%s\n' "$REQUIRED_PYTHON_VERSION" "$py_version" | sort -V | head -n1)" == "$REQUIRED_PYTHON_VERSION" ]]; then
        python_version_ok=true
    fi
fi

if ! $python_version_ok; then
    echo_error "Python 3.8 or higher is required. Please install it."
    echo_info "(Ubuntu/Debian: sudo apt update && sudo apt install python3 python3-pip python3-venv)"
    exit 1
fi

if ! command_exists pip3; then
     echo_error "pip3 is required but not found. Please install python3-pip."
     echo_info "(Ubuntu/Debian: sudo apt install python3-pip)"
     exit 1
fi
echo_info "Python and pip check passed."

# --- Check/Install Ansible ---
echo_info "Checking for Ansible..."
if command_exists ansible; then
    echo_info "Ansible found: $(ansible --version | head -n 1)"
else
    echo_warn "Ansible is not installed."
    read -p "Install Ansible using pip (recommended) or apt (if available)? (pip/apt/skip): " install_choice

    case $install_choice in
        pip|PIP)
            echo_info "Installing ansible-core using pip..."
            pip3 install ansible-core>=2.14 # Or just ansible
            if ! command_exists ansible; then echo_error "Ansible installation via pip failed."; exit 1; fi
            ;;
        apt|APT)
            if command_exists apt-get; then
                echo_info "Updating package list..."
                sudo apt-get update
                echo_info "Installing ansible using apt..."
                sudo apt-get install -y ansible
                if ! command_exists ansible; then echo_error "Ansible installation via apt failed."; exit 1; fi
            else
                echo_error "apt not found. Cannot install Ansible via apt."
                exit 1
            fi
            ;;
        skip|SKIP)
            echo_warn "Skipping Ansible installation. Please install it manually."
            ;;
        *)
            echo_warn "Invalid choice. Skipping Ansible installation."
            ;;
    esac
fi

# --- Setup Virtual Environment (Optional but Recommended) ---
if [ ! -d "venv" ]; then
    read -p "Create Python virtual environment 'venv'? (y/N): " create_venv
    if [[ "$create_venv" =~ ^[Yy]$ ]]; then
        # Check if python3-venv package is needed and installed (Debian/Ubuntu)
        if command_exists apt-get && ! dpkg -s python3-venv > /dev/null 2>&1; then
             # Try installing the generic python3-venv first
             echo_warn "Python 'venv' module requires the 'python3-venv' system package."
             read -p "Attempt to install 'python3-venv' using apt? (Requires sudo) (y/N): " install_venv_pkg
             if [[ "$install_venv_pkg" =~ ^[Yy]$ ]]; then
                 echo_info "Installing python3-venv..."
                 sudo apt-get update
                 # Try python3-venv first, then python3.X-venv if needed?
                 # Usually python3-venv is sufficient as a meta-package or for the default python3
                 sudo apt-get install -y python3-venv 
                 if ! dpkg -s python3-venv > /dev/null 2>&1; then
                     echo_error "Failed to install python3-venv package. Please install it manually and re-run the script."
                     exit 1
                 fi
                 echo_info "'python3-venv' package installed successfully."
             else
                 echo_error "Cannot create virtual environment without 'python3-venv' package. Please install it manually."
                 exit 1
             fi
        fi
        
        echo_info "Creating Python virtual environment 'venv'..."
        # Now attempt to create the venv
        if ! python3 -m venv venv; then
             echo_error "Failed to create virtual environment even after attempting package installation."
             echo_error "Please check your Python installation and ensure the 'venv' module is available."
             exit 1
        fi
        echo_info "Virtual environment created."
    else
        echo_warn "Skipping virtual environment creation."
    fi
fi

if [ -d "venv" ]; then
     echo_info "To activate the virtual environment, run: source venv/bin/activate"
     # Optionally activate here? Might complicate things if script is sourced vs run.
fi

# --- Install Python Dependencies ---
echo_info "Installing Python dependencies..."

if [ -f "backend/requirements.txt" ]; then
    pip3 install -r backend/requirements.txt
else
    echo_warn "backend/requirements.txt not found. Skipping backend dependencies."
fi

if [ -f "client/requirements.txt" ]; then
    pip3 install -r client/requirements.txt
else
    echo_warn "client/requirements.txt not found. Skipping client dependencies."
fi

echo_info "Python dependency installation complete (or skipped)."

# --- Final Instructions ---
echo_info "-----------------------------------------------------"
echo_info "Setup steps completed."
echo_info "Next Steps:"
echo_info "1. If you created a virtual environment, activate it: source venv/bin/activate"
echo_info "2. Ensure SSH keys are set up for passwordless access to target nodes (see README.md)."
echo_info "3. Review configuration variables (e.g., client/.env, Ansible defaults)."
echo_info "4. Start the backend server: cd backend && uvicorn app.main:app --host 0.0.0.0 --port 8000"
echo_info "5. Run the CLI client: python client/cli.py"
echo_info "-----------------------------------------------------"

exit 0 