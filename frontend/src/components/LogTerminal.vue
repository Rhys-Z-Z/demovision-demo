<template>
  <div class="log-terminal" ref="container">
    <pre ref="preBox" class="log-pre">{{ joined }}</pre>
  </div>
</template>

<script setup>
import { computed, nextTick, ref, watch } from 'vue'

const props = defineProps({
  lines: {
    type: Array,
    default: () => [],
  },
  height: {
    type: String,
    default: '320px',
  },
  dark: {
    type: Boolean,
    default: true,
  },
})

const container = ref(null)
const preBox = ref(null)
const stickToBottom = ref(true)

const joined = computed(() => props.lines.join('\n'))

// 保持自动滚动到底部（除非用户手动向上滚动）
function onScroll() {
  const el = container.value
  if (!el) return
  const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 30
  stickToBottom.value = atBottom
}

watch(
  () => props.lines.length,
  async () => {
    if (stickToBottom.value && container.value) {
      await nextTick()
      container.value.scrollTop = container.value.scrollHeight
    }
  }
)
</script>

<style scoped>
.log-terminal {
  width: 100%;
  height: v-bind(height);
  overflow-y: auto;
  background: var(--xv-bg);
  border-radius: 6px;
  padding: 10px 12px;
  box-sizing: border-box;
  font-family: 'JetBrains Mono', 'Consolas', 'Courier New', monospace;
}
.log-pre {
  margin: 0;
  font-size: 12px;
  line-height: 1.55;
  color: var(--xv-text-2);
  white-space: pre-wrap;
  word-break: break-all;
}
</style>
