#!/bin/bash
set -e

echo "🔧 Starting Chat UI setup..."

if [ ! -f "package.json" ]; then
  echo "❌ Error: This script must be run from the chat-ui directory"
  echo "Please run: cd chat-ui && bash fetch_run_huggingchat.sh"
  exit 1
fi

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

# echo "📦 Setting up npm..."
# if ! command -v npm &> /dev/null; then
#     echo "npm not found, attempting to use npx directly from Node.js"
#     mkdir -p ~/.npm-global
#     export PATH=~/.npm-global/bin:$PATH
#     echo 'export PATH=~/.npm-global/bin:$PATH' >> ~/.bashrc
    
#     if command -v npx &> /dev/null; then
#         echo "Using npx from Node.js"
#     else
#         echo "Installing npm using Node.js mechanism"
#         NODE_PATH=$(which node)
#         NODE_DIR=$(dirname "$NODE_PATH")
#         if [ -f "$NODE_DIR/npm" ]; then
#             ln -sf "$NODE_DIR/npm" /usr/local/bin/npm
#         else
#             curl -L https://www.npmjs.com/install.sh | sh
#         fi
#     fi
# fi

echo "📚 Installing npm dependencies..."
if command -v npm &> /dev/null; then
    npm install
else
    echo "Attempting to use npx directly..."
    npx --yes npm install
fi

# export NODE_OPTIONS="--max-old-space-size=4096"

echo "🏗️ Building the application..."
if command -v npm &> /dev/null; then
    npm run build
    echo "🚀 Starting Chat UI on http://localhost:7860"
    echo "Press Ctrl+C to stop the server"
    npm run preview -- --host 0.0.0.0 --port 7860
else
    npx --yes npm run build
    echo "🚀 Starting Chat UI on http://localhost:7860"
    echo "Press Ctrl+C to stop the server"
    npx --yes npm run preview -- --host 0.0.0.0 --port 7860
fi
