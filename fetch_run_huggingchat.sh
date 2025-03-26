#!/bin/bash

# ChatUI Setup Script with llama.cpp support
# This script sets up and runs the HuggingFace Chat UI on port 7860
# Created by Claude

# Exit immediately if a command exits with a non-zero status
set -e

echo "🔧 Starting Chat UI setup..."

# Check if the script is running from within the chat-ui directory
if [ ! -f "package.json" ]; then
  echo "❌ Error: This script must be run from the chat-ui directory"
  echo "Please run: cd chat-ui && bash fetch_run_huggingchat.sh"
  exit 1
fi

# Check for llama.cpp and offer to install it
echo "🔍 Checking for llama.cpp..."
LLAMACPP_AVAILABLE=false

if command -v llama-server &> /dev/null; then
  LLAMACPP_AVAILABLE=true
  echo "✅ llama.cpp is installed."
else
  echo "llama.cpp is not installed."
  echo "Would you like to attempt to install llama.cpp? (y/n)"
  read -r install_llamacpp
  
  if [[ "$install_llamacpp" == "y" ]]; then
    echo "📦 Installing llama.cpp dependencies..."
    apt-get update
    apt-get install -y build-essential cmake git
    
    echo "🔄 Cloning and building llama.cpp with CMake..."
    cd /tmp
    git clone https://github.com/ggerganov/llama.cpp.git
    cd llama.cpp
    
    # Use CMake to build as per the new requirements
    mkdir -p build
    cd build
    cmake ..
    cmake --build . --config Release
    
    # Copy the binaries to a location in PATH
    cp -f bin/llama-server /usr/local/bin/
    cp -f bin/main /usr/local/bin/llama
    
    cd - # Return to llama.cpp directory
    cd - # Return to original directory
    LLAMACPP_AVAILABLE=true
    echo "✅ llama.cpp has been installed."
  fi
fi

# Function to download a model for llama.cpp
download_model() {
  if [ "$LLAMACPP_AVAILABLE" = true ]; then
    echo "Do you want to download a GGUF model for local inference? (y/n)"
    read -r download_model
    
    if [[ "$download_model" == "y" ]]; then
      echo "📥 Downloading Phi-3-mini-4k-instruct-q4.gguf..."
      mkdir -p models
      cd models
      
      # Download a small model (Phi-3-mini) - adjust URL as needed
      if [ ! -f "Phi-3-mini-4k-instruct-q4.gguf" ]; then
        curl -L -O "https://huggingface.co/microsoft/Phi-3-mini-4k-instruct-gguf/resolve/main/Phi-3-mini-4k-instruct-q4.gguf"
      fi
      
      cd ..
      echo "✅ Model downloaded."
      return 0
    fi
  fi
  return 1
}

# Create .env.local configuration file
echo "⚙️ Creating configuration..."

# Ask if user wants to use a local model with llama.cpp
USE_LOCAL_MODEL=false
if [ "$LLAMACPP_AVAILABLE" = true ]; then
  echo "Would you like to use a local model with llama.cpp? (y/n)"
  read -r use_local
  
  if [[ "$use_local" == "y" ]]; then
    USE_LOCAL_MODEL=true
    download_model
  fi
fi

# Create base configuration
cat > .env.local << EOL
PORT=7860
HOST=0.0.0.0
# Use in-memory database instead of MongoDB
MONGODB_URL=
# App configuration
PUBLIC_APP_NAME="My Chat UI"
PUBLIC_APP_DESCRIPTION="My personal AI chat assistant interface"
PUBLIC_APP_COLOR=blue
EOL

# Add model configuration based on user choice
if [ "$USE_LOCAL_MODEL" = true ]; then
  # Start llama.cpp server in the background
  echo "🚀 Starting llama.cpp server..."
  if [ -f "models/Phi-3-mini-4k-instruct-q4.gguf" ]; then
    llama-server --model models/Phi-3-mini-4k-instruct-q4.gguf -c 2048 --port 8080 &
    LLAMA_SERVER_PID=$!
    
    # Add local model configuration
    cat >> .env.local << EOL
# Local model configuration with llama.cpp
MODELS=\`[
  {
    "name": "Phi-3-mini-local",
    "displayName": "Phi-3 Mini (Local)",
    "description": "Microsoft's Phi-3 Mini model running locally via llama.cpp",
    "chatPromptTemplate": "{{#each messages}}{{#ifUser}}<|user|>\n{{content}}</s>\n<|assistant|>\n{{/ifUser}}{{#ifAssistant}}{{content}}</s>\n{{/ifAssistant}}{{/each}}",
    "parameters": {
      "temperature": 0.7,
      "top_p": 0.95,
      "repetition_penalty": 1.2,
      "top_k": 50,
      "max_new_tokens": 1024,
      "stop": ["</s>"]
    },
    "endpoints": [{
      "type": "llamacpp",
      "baseURL": "http://localhost:8080"
    }]
  }
]\`
EOL
    echo "✅ Added local model configuration with llama.cpp"
  else
    echo "⚠️ Model file not found. Falling back to remote models."
    USE_LOCAL_MODEL=false
  fi
fi

# If not using local model, use remote models
if [ "$USE_LOCAL_MODEL" = false ]; then
  cat >> .env.local << EOL
# Remote model configuration
MODELS=\`[
  {
    "name": "HuggingFaceH4/zephyr-7b-beta",
    "displayName": "Zephyr 7B",
    "description": "An efficient open-source chat model",
    "chatPromptTemplate": "{{#each messages}}{{#ifUser}}<|user|>\n{{content}}</s>\n<|assistant|>\n{{/ifUser}}{{#ifAssistant}}{{content}}</s>\n{{/ifAssistant}}{{/each}}",
    "parameters": {
      "temperature": 0.7,
      "top_p": 0.95,
      "repetition_penalty": 1.2,
      "top_k": 50,
      "truncate": 1000,
      "max_new_tokens": 1024,
      "stop": ["</s>"]
    }
  },
  {
    "name": "meta-llama/Llama-2-7b-chat-hf",
    "displayName": "Llama 2 (7B)",
    "description": "Meta's open-source chat model",
    "chatPromptTemplate": "<s>{{#each messages}}{{#ifUser}}[INST] {{#if @first}}{{#if @root.preprompt}}{{@root.preprompt}}\n{{/if}}{{/if}}{{content}} [/INST]{{/ifUser}}{{#ifAssistant}}{{content}}</s>{{/ifAssistant}}{{/each}}",
    "parameters": {
      "temperature": 0.6,
      "top_p": 0.95,
      "repetition_penalty": 1.2,
      "top_k": 50,
      "truncate": 3072,
      "max_new_tokens": 1024,
      "stop": ["</s>"]
    }
  }
]\`
EOL
  echo "✅ Added remote model configuration"
fi

# Build the application
echo "🏗️ Building the application..."
npm run build

# Start the application
echo "🚀 Starting Chat UI on http://localhost:7860"
echo "Press Ctrl+C to stop the server"
npm run preview -- --host 0.0.0.0 --port 7860

# Cleanup when the script exits
cleanup() {
    if [ "$USE_LOCAL_MODEL" = true ] && [ -n "$LLAMA_SERVER_PID" ]; then
        echo "Stopping llama.cpp server..."
        kill $LLAMA_SERVER_PID
    fi
    echo "Cleanup complete."
}

# Set the trap to call cleanup when the script exits
trap cleanup EXIT
