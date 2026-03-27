import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import path from 'path';
import {defineConfig, loadEnv} from 'vite';

export default defineConfig(({mode}) => {
  const env = loadEnv(mode, '.', '');
  const publicBase = env.SHOWCASE_PUBLIC_BASE || '/';
  const outDir = env.SHOWCASE_OUT_DIR
    ? path.resolve(__dirname, env.SHOWCASE_OUT_DIR)
    : path.resolve(__dirname, 'dist');

  return {
    base: publicBase,
    plugins: [react(), tailwindcss()],
    define: {
      'process.env.AI_PROVIDER': JSON.stringify(env.AI_PROVIDER),
      'process.env.AI_API_KEY': JSON.stringify(env.AI_API_KEY),
      'process.env.AI_BASE_URL': JSON.stringify(env.AI_BASE_URL),
      'process.env.AI_MODEL': JSON.stringify(env.AI_MODEL),
      'process.env.AI_REVIEW_MODEL': JSON.stringify(env.AI_REVIEW_MODEL),
      'process.env.DEEPSEEK_API_KEY': JSON.stringify(env.DEEPSEEK_API_KEY),
      'process.env.DEEPSEEK_BASE_URL': JSON.stringify(env.DEEPSEEK_BASE_URL),
      'process.env.DEEPSEEK_MODEL': JSON.stringify(env.DEEPSEEK_MODEL),
      'process.env.DEEPSEEK_REVIEW_MODEL': JSON.stringify(env.DEEPSEEK_REVIEW_MODEL),
      'process.env.OPENAI_API_KEY': JSON.stringify(env.OPENAI_API_KEY),
      'process.env.OPENAI_BASE_URL': JSON.stringify(env.OPENAI_BASE_URL),
      'process.env.OPENAI_MODEL': JSON.stringify(env.OPENAI_MODEL),
      'process.env.OPENAI_REVIEW_MODEL': JSON.stringify(env.OPENAI_REVIEW_MODEL),
      'process.env.OPENAI_REASONING_EFFORT': JSON.stringify(env.OPENAI_REASONING_EFFORT),
      'process.env.OPENAI_DISABLE_RESPONSE_STORAGE': JSON.stringify(env.OPENAI_DISABLE_RESPONSE_STORAGE),
      'process.env.ANTHROPIC_API_KEY': JSON.stringify(env.ANTHROPIC_API_KEY),
      'process.env.ANTHROPIC_BASE_URL': JSON.stringify(env.ANTHROPIC_BASE_URL),
      'process.env.ANTHROPIC_MODEL': JSON.stringify(env.ANTHROPIC_MODEL),
      'process.env.ANTHROPIC_REVIEW_MODEL': JSON.stringify(env.ANTHROPIC_REVIEW_MODEL),
      'process.env.GEMINI_API_KEY': JSON.stringify(env.GEMINI_API_KEY),
      'process.env.GEMINI_BASE_URL': JSON.stringify(env.GEMINI_BASE_URL),
      'process.env.GEMINI_MODEL': JSON.stringify(env.GEMINI_MODEL),
      'process.env.GEMINI_REVIEW_MODEL': JSON.stringify(env.GEMINI_REVIEW_MODEL),
      'process.env.GOOGLE_API_KEY': JSON.stringify(env.GOOGLE_API_KEY),
      'process.env.OPENROUTER_API_KEY': JSON.stringify(env.OPENROUTER_API_KEY),
      'process.env.OPENROUTER_BASE_URL': JSON.stringify(env.OPENROUTER_BASE_URL),
      'process.env.OPENROUTER_MODEL': JSON.stringify(env.OPENROUTER_MODEL),
      'process.env.OPENROUTER_REVIEW_MODEL': JSON.stringify(env.OPENROUTER_REVIEW_MODEL),
      'process.env.OLLAMA_BASE_URL': JSON.stringify(env.OLLAMA_BASE_URL),
      'process.env.OLLAMA_MODEL': JSON.stringify(env.OLLAMA_MODEL),
      'process.env.FUNCTION_ANALYSIS_MAX_DEPTH': JSON.stringify(env.FUNCTION_ANALYSIS_MAX_DEPTH),
      'process.env.KEY_SUB_FUNCTION_LIMIT': JSON.stringify(env.KEY_SUB_FUNCTION_LIMIT),
      'process.env.GITHUB_TOKEN': JSON.stringify(env.GITHUB_TOKEN),
      'process.env.TAB3_DEFAULT_GITHUB_TOKEN': JSON.stringify(env.TAB3_DEFAULT_GITHUB_TOKEN),
      'process.env.TAB3_EMBEDDED': JSON.stringify(env.TAB3_EMBEDDED),
      'process.env.TAB3_DISABLE_LOCAL_PROJECT': JSON.stringify(env.TAB3_DISABLE_LOCAL_PROJECT),
    },
    resolve: {
      alias: {
        '@': path.resolve(__dirname, '.'),
      },
    },
    server: {
      // HMR is disabled in AI Studio via DISABLE_HMR env var.
      // File watching stays disabled there to avoid flicker during agent edits.
      hmr: process.env.DISABLE_HMR !== 'true',
      proxy: {
        // Proxy API calls to backend during development
        '/api': {
          target: 'http://localhost:8000',
          changeOrigin: true,
          secure: false,
        },
      },
    },
    build: {
      outDir,
      emptyOutDir: true,
    },
  };
});
