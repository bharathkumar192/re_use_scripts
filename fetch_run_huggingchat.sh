#!/bin/bash

# ChatUI Setup Script
# This script sets up and runs the HuggingFace Chat UI on port 7860
# Created by Claude

# Exit immediately if a command exits with a non-zero status
set -e

echo "🔧 Starting Chat UI setup..."

# Check if the script is running from within the chat-ui directory
if [ ! -f "package.json" ]; then
  echo "❌ Error: This script must be run from the chat-ui directory"
  echo "Please run: cd chat-ui && bash setup-chatui.sh"
  exit 1
fi

# Install required dependencies
echo "📦 Installing system dependencies..."
apt-get update
apt-get install -y nodejs npm curl

# Check Node.js and npm versions
echo "ℹ️ Node.js version: $(node --version)"
echo "ℹ️ npm version: $(npm --version)"

# Create .env.local configuration file
echo "⚙️ Creating configuration..."
cat > .env.local << EOL
PORT=7860
HOST=0.0.0.0
# Use in-memory database instead of MongoDB
MONGODB_URL=
# App configuration
PUBLIC_APP_NAME="My Chat UI"
PUBLIC_APP_DESCRIPTION="My personal AI chat assistant interface"
PUBLIC_APP_COLOR=blue
# Model configuration
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

# Install npm dependencies
echo "📚 Installing npm dependencies..."
npm install

# Increase Node.js memory limit for build process
export NODE_OPTIONS="--max-old-space-size=4096"

# Build the application
echo "🏗️ Building the application..."
npm run build

# Start the application
echo "🚀 Starting Chat UI on http://localhost:7860"
echo "Press Ctrl+C to stop the server"
npm run preview -- --host 0.0.0.0 --port 7860
