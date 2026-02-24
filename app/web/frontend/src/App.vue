<template>
  <div class="app">
    <header>
      <h1>🍊 orange-translator</h1>
      <p>EPUB 双语翻译工具</p>
    </header>
    <main>
      <TranslatorPanel />
    </main>
  </div>
</template>

<script setup lang="ts">
import TranslatorPanel from './components/TranslatorPanel.vue'
</script>

<style>
* { box-sizing: border-box; margin: 0; padding: 0; }

body {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  background: #f8fafc;
  color: #1e293b;
  min-height: 100vh;
}

.app {
  max-width: 760px;
  margin: 0 auto;
  padding: 2rem 1rem;
}

header {
  text-align: center;
  margin-bottom: 2.5rem;
}

header h1 {
  font-size: 2rem;
  font-weight: 700;
  color: #ea580c;
}

header p {
  margin-top: 0.4rem;
  color: #64748b;
}
</style>
